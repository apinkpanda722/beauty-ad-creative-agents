"""Synchronize the public graph skeleton from PostgreSQL change timestamps."""

import argparse
import json
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import ExitStack
from pathlib import Path
from typing import NamedTuple, TextIO
from urllib.parse import urlsplit

from beautyads.analysis.models import FINAL_RUN_TAG
from beautyads.domain.claims import ClaimRule
from beautyads.domain.feedback_sync import FeedbackSyncSource
from beautyads.domain.layer1 import Layer1SyncSource, Layer1Tables
from beautyads.domain.links import DEFAULT_SAMPLE_PAIRS, DEFAULT_SEED, LinksSource
from beautyads.domain.sync import SYNC_OVERLAP, GraphSyncSource
from beautyads.graph.connection import GraphConnection, GraphError, connect_graph
from beautyads.graph.feedback import load_feedback, read_feedback_state
from beautyads.graph.layer1 import load_layer1, load_layer1_tables
from beautyads.graph.layer2 import load_layer2, read_link_state
from beautyads.graph.load import (
    count_axis_relationships,
    load_creatives,
    verify_counts,
)
from beautyads.graph.schema import (
    FEEDBACK_CONSTRAINTS,
    LAYER1_CONSTRAINTS,
    apply_schema,
)
from beautyads.settings import (
    DEFAULT_ENV_FILE,
    SettingError,
    get_setting,
    neo4j_password,
    neo4j_uri,
)
from beautyads.sources.claim_rules import load_claim_rules
from beautyads.sources.split import load_brand_split
from beautyads.store.connection import StoreConnectError, connect, postgres_dsn
from beautyads.store.feedback_source import PostgresFeedbackSource
from beautyads.store.layer1_source import PostgresLayer1Source
from beautyads.store.links_source import PostgresLinksSource
from beautyads.store.sync_source import PostgresGraphSyncSource

from .preflight import docker_running, tcp_reachable


class SyncDeps(NamedTuple):
    source: GraphSyncSource | Layer1SyncSource | LinksSource | FeedbackSyncSource
    graph: GraphConnection


def sync_preflight(
    *,
    environ: Mapping[str, str] | None,
    env_file: Path | None,
    docker_check: Callable[[], bool],
    tcp_check: Callable[[str, int, float], bool],
) -> list[str]:
    problems = [
        f"ENV_MISSING:{name}"
        for name in ("NEO4J_PASSWORD", "POSTGRES_PASSWORD")
        if get_setting(name, environ=environ, env_file=env_file) is None
    ]
    if not problems:
        try:
            neo4j_password(environ=environ, env_file=env_file)
        except SettingError as error:
            problems.append(f"INVALID_SETTING:{error.name}")
    if not docker_check():
        problems.append("DOCKER_DOWN")
    try:
        port = int(
            get_setting(
                "BEAUTYADS_POSTGRES_PORT", "5433", environ=environ, env_file=env_file
            )
        )
        reachable = 1 <= port <= 65535 and tcp_check("127.0.0.1", port, 1.0)
    except (TypeError, ValueError, OSError):
        reachable = False
    if not reachable:
        problems.append("POSTGRES_UNREACHABLE")
    try:
        uri = urlsplit(neo4j_uri(environ=environ, env_file=env_file))
        port = uri.port or 7687
        reachable = (
            uri.scheme
            in {"bolt", "bolt+s", "bolt+ssc", "neo4j", "neo4j+s", "neo4j+ssc"}
            and uri.hostname is not None
            and 1 <= port <= 65535
            and tcp_check(uri.hostname, port, 1.0)
        )
    except (TypeError, ValueError, OSError):
        reachable = False
    if not reachable:
        problems.append("NEO4J_UNREACHABLE")
    return problems


def run_sync(
    deps: SyncDeps,
    *,
    limit: int | None = None,
    full: bool = False,
    verify: bool = False,
    sample: int | None = None,
) -> dict:
    if sample is not None and (limit is not None or full):
        raise ValueError("sample excludes limit and full")
    started = time.monotonic()
    apply_schema(deps.graph)
    watermark = deps.source.get_watermark()
    if sample is not None:
        # A live-check sample is ordered by analysis state, not by change time, so
        # it must never move the watermark (older changes would be skipped later).
        creatives = deps.source.read_sample(limit=sample, run_tag=FINAL_RUN_TAG)
    else:
        since = None if full or watermark is None else watermark - SYNC_OVERLAP
        creatives = deps.source.read_changed(
            since=since, limit=limit, run_tag=FINAL_RUN_TAG
        )
    entries = [
        (creative, deps.source.read_labels(creative.key, run_tag=FINAL_RUN_TAG))
        for creative in creatives
    ]
    loaded = load_creatives(deps.graph, entries, run_tag=FINAL_RUN_TAG)
    verification = None
    graph_check = None
    if verify:
        before = verify_counts(deps.graph)
        replay = load_creatives(deps.graph, entries, run_tag=FINAL_RUN_TAG)
        after = verify_counts(deps.graph)
        verification = {
            "nodes_created": replay.nodes_created,
            "relationships_created": replay.relationships_created,
            "creative_count_before": before["creative_count"],
            "creative_count_after": after["creative_count"],
            "invalid_values": after["invalid_values"],
        }
        if (
            replay.nodes_created != 0
            or replay.relationships_created != 0
            or before["creative_count"] != after["creative_count"]
            or before["invalid_values"] != 0
            or after["invalid_values"] != 0
        ):
            raise GraphError("GRAPH_VERIFY_FAILED")
        labeled = sum(
            1
            for _, jobs in entries
            if any(
                job.status == "done" and job.kind.split("@")[0] in {"hook", "full"}
                for job in jobs
            )
        )
        axis_relationships = count_axis_relationships(deps.graph)
        graph_check = {
            "labeled_in_sample": labeled,
            "axis_relationships": axis_relationships,
        }
        if sample is not None and labeled == 0:
            # Checking zero analysed creatives must not look like a pass.
            raise GraphError("GRAPH_VERIFY_NO_LABELED_SAMPLE")
        if labeled > 0 and axis_relationships == 0:
            raise GraphError("GRAPH_VERIFY_NO_RELATIONSHIPS")
    # Graph counters are reporting only. The durable checkpoint comes exclusively
    # from the source rows, and only after every batch (and optional replay).
    if creatives and sample is None:
        latest = max(creative.updated_at for creative in creatives)
        watermark = max(watermark, latest) if watermark is not None else latest
        deps.source.set_watermark(watermark)
    report = {
        "event": "summary",
        "read": len(creatives),
        "nodes_created": loaded.nodes_created,
        "relationships_created": loaded.relationships_created,
        "skipped_invalid": loaded.skipped_invalid,
        "watermark": watermark.isoformat() if watermark is not None else None,
        "elapsed_s": time.monotonic() - started,
    }
    if sample is not None:
        report["sample"] = sample
    if verification is not None:
        report["verification"] = verification
    if graph_check is not None:
        report["graph_check"] = graph_check
    return report


def run_layer1_sync(
    deps: SyncDeps,
    *,
    tables: Layer1Tables,
    rules: Sequence[ClaimRule] = (),
    limit: int | None = None,
    full: bool = False,
    verify: bool = False,
) -> dict:
    """Layer-one branch; the original creative synchronization is unchanged."""
    started = time.monotonic()
    apply_schema(deps.graph)
    for statement in LAYER1_CONSTRAINTS:
        deps.graph.run(statement)
    watermark = deps.source.get_watermark()
    since = None if full or watermark is None else watermark - SYNC_OVERLAP
    entries = deps.source.read_changed(since=since, limit=limit)
    report = load_layer1(deps.graph, entries, tables=tables, rules=rules)
    if verify:
        replay = load_layer1(deps.graph, entries, tables=tables, rules=rules)
        report["verification"] = {
            "nodes_created": replay["nodes_created"],
            "relationships_created": replay["relationships_created"],
        }
        if replay["nodes_created"] or replay["relationships_created"]:
            raise GraphError("GRAPH_VERIFY_FAILED")
    # Counters are reporting/optional replay checks only. Checkpoint exclusively
    # uses PostgreSQL times and is persisted after every graph operation succeeds.
    if entries:
        latest = max(entry.updated_at for entry in entries)
        watermark = max(watermark, latest) if watermark is not None else latest
        deps.source.set_watermark(watermark)
    return {
        **report,
        "event": "summary",
        "layers": "1",
        "read": len(entries),
        "watermark": watermark.isoformat() if watermark is not None else None,
        "elapsed_s": time.monotonic() - started,
    }


def run_layer2_sync(
    deps: SyncDeps,
    *,
    dev_brands: Sequence[str],
    test_brands: Sequence[str],
    limit: int | None = None,
    full: bool = False,
    verify: bool = False,
    sample_pairs: int = DEFAULT_SAMPLE_PAIRS,
    seed: int = DEFAULT_SEED,
) -> dict:
    """Extend the creative skeleton with frozen-v1 links, without reanalysis."""
    if sample_pairs < 0:
        raise ValueError("sample_pairs must be nonnegative")
    started = time.monotonic()
    apply_schema(deps.graph)
    for statement in LAYER1_CONSTRAINTS:
        deps.graph.run(statement)
    watermark = deps.source.get_watermark()
    since = None if full or watermark is None else watermark - SYNC_OVERLAP
    snapshot = deps.source.read_snapshot(since=since, limit=limit)
    entries = [(entry.creative, entry.labels) for entry in snapshot.changed]
    skeleton = load_creatives(deps.graph, entries, run_tag=FINAL_RUN_TAG)
    options = {
        "products": snapshot.products,
        "dev_brands": dev_brands,
        "test_brands": test_brands,
        "sample_pairs": sample_pairs,
        "seed": seed,
    }
    report = load_layer2(deps.graph, snapshot.changed, **options)
    report["nodes_created"] += skeleton.nodes_created
    report["relationships_created"] += skeleton.relationships_created
    report["skipped_invalid"] = skeleton.skipped_invalid
    if verify:
        before = read_link_state(deps.graph, snapshot.changed)
        replay_skeleton = load_creatives(deps.graph, entries, run_tag=FINAL_RUN_TAG)
        replay = load_layer2(deps.graph, snapshot.changed, **options)
        after = read_link_state(deps.graph, snapshot.changed)
        same = before == after
        report["verification"] = {
            "same_relationships": same,
            "nodes_created": replay_skeleton.nodes_created + replay["nodes_created"],
            "relationships_created": replay_skeleton.relationships_created
            + replay["relationships_created"],
        }
        # PROMOTES is deleted and rebuilt atomically; compare its semantic set,
        # not the number of replacement relationships allocated on replay.
        if not same or report["verification"]["nodes_created"]:
            raise GraphError("GRAPH_VERIFY_FAILED")
    if snapshot.changed:
        latest = max(entry.creative.updated_at for entry in snapshot.changed)
        watermark = max(watermark, latest) if watermark is not None else latest
        deps.source.set_watermark(watermark)
    recommendation = report.pop("recommendation")
    return {
        **report,
        "event": "summary",
        "layers": "2",
        "read": len(snapshot.changed),
        "coverage_scope": "applied_batch",
        "watermark": watermark.isoformat() if watermark is not None else None,
        "elapsed_s": time.monotonic() - started,
        "recommendation": recommendation,
    }


def run_feedback_sync(
    deps: SyncDeps,
    *,
    limit: int | None = None,
    full: bool = False,
    verify: bool = False,
) -> dict:
    """Project feedback patterns without exporting private PostgreSQL text."""
    started = time.monotonic()
    apply_schema(deps.graph)
    for statement in (*LAYER1_CONSTRAINTS, *FEEDBACK_CONSTRAINTS):
        deps.graph.run(statement)
    watermark = deps.source.get_watermark()
    since = None if full or watermark is None else watermark - SYNC_OVERLAP
    items = deps.source.read_changed(since=since, limit=limit)
    report = load_feedback(deps.graph, items)
    if verify:
        before = read_feedback_state(deps.graph, items)
        replay = load_feedback(deps.graph, items)
        after = read_feedback_state(deps.graph, items)
        same = before == after
        report["verification"] = {
            "same_feedback": same,
            "nodes_created": replay["nodes_created"],
            "relationships_created": replay["relationships_created"],
        }
        # ABOUT replacement allocates edges again. Compare content, not counters.
        if not same or replay["nodes_created"]:
            raise GraphError("GRAPH_VERIFY_FAILED")
    # Rejections are reported and skipped; write/replay failures never checkpoint.
    # PostgreSQL updated_at alone drives this checkpoint, never graph counters.
    if items:
        latest = max(item.updated_at for item in items)
        watermark = max(watermark, latest) if watermark is not None else latest
        deps.source.set_watermark(watermark)
    return {
        **report,
        "event": "summary",
        "layers": "3",
        "read": len(items),
        "watermark": watermark.isoformat() if watermark is not None else None,
        "elapsed_s": time.monotonic() - started,
    }


def _live_deps(
    *, environ, env_file, stack: ExitStack, layers: str | None = None
) -> SyncDeps:
    connection = connect(postgres_dsn(environ=environ, env_file=env_file))
    stack.callback(connection.close)
    graph = connect_graph(environ=environ, env_file=env_file)
    stack.callback(graph.close)
    if layers == "1":
        source = PostgresLayer1Source(connection)
    elif layers == "2":
        source = PostgresLinksSource(connection)
    elif layers == "3":
        source = PostgresFeedbackSource(connection)
    else:
        source = PostgresGraphSyncSource(connection)
    return SyncDeps(source, graph)


def _limit(value: str) -> int:
    try:
        limit = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("limit must be positive") from None
    if limit < 1:
        raise argparse.ArgumentTypeError("limit must be positive")
    return limit


def _sample_pairs(value: str) -> int:
    try:
        count = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("sample-pairs must be nonnegative") from None
    if count < 0:
        raise argparse.ArgumentTypeError("sample-pairs must be nonnegative")
    return count


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    out: TextIO | None = None,
    docker_check=docker_running,
    tcp_check=tcp_reachable,
    deps_factory: Callable[[], SyncDeps] | None = None,
) -> int:
    out = sys.stdout if out is None else out
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=_limit)
    parser.add_argument("--sample", type=_limit)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--verify", action="store_true")
    # Omitted --layers retains step-zero/live-graph behavior. Explicit layer 2
    # adds links and its own source checkpoint to the creative/axis skeleton.
    parser.add_argument("--layers", choices=("1", "2", "3"))
    parser.add_argument(
        "--sample-pairs", type=_sample_pairs, default=DEFAULT_SAMPLE_PAIRS
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        return int(error.code)
    if args.sample is not None and (args.limit is not None or args.full):
        print("PREFLIGHT_FAILED SYNC_OPTIONS_CONFLICT", file=out)
        return 2
    if args.layers in {"1", "3"} and args.sample is not None:
        print("PREFLIGHT_FAILED SYNC_OPTIONS_CONFLICT", file=out)
        return 2
    env_file = DEFAULT_ENV_FILE if environ is None else None
    problems = sync_preflight(
        environ=environ,
        env_file=env_file,
        docker_check=docker_check,
        tcp_check=tcp_check,
    )
    if problems:
        for code in problems:
            print(f"PREFLIGHT_FAILED {code}", file=out)
        return 2
    try:
        with ExitStack() as stack:
            if args.layers == "1":
                tables = load_layer1_tables(
                    Path("config/ingredient_efficacy.yaml"),
                    Path("config/efficacy_concerns.yaml"),
                )
                rules = load_claim_rules(Path("config/claim_rules.yaml"))
            elif args.layers == "2" and args.sample is None:
                split = load_brand_split(Path("config/brand_split.yaml"))
            deps = (
                deps_factory()
                if deps_factory is not None
                else _live_deps(
                    environ=environ,
                    env_file=env_file,
                    stack=stack,
                    layers=None if args.sample is not None else args.layers,
                )
            )
            if args.layers == "1":
                report = run_layer1_sync(
                    deps,
                    tables=tables,
                    rules=rules,
                    limit=args.limit,
                    full=args.full,
                    verify=args.verify,
                )
            elif args.layers == "2" and args.sample is None:
                report = run_layer2_sync(
                    deps,
                    dev_brands=split.dev,
                    test_brands=split.test,
                    limit=args.limit,
                    full=args.full,
                    verify=args.verify,
                    sample_pairs=args.sample_pairs,
                    seed=args.seed,
                )
            elif args.layers == "3":
                report = run_feedback_sync(
                    deps,
                    limit=args.limit,
                    full=args.full,
                    verify=args.verify,
                )
            else:
                report = run_sync(
                    deps,
                    limit=args.limit,
                    full=args.full,
                    verify=args.verify,
                    sample=args.sample,
                )
    except GraphError as error:
        print(f"PREFLIGHT_FAILED {error}", file=out)
        return 2
    except StoreConnectError as error:
        print(f"PREFLIGHT_FAILED {error.code}", file=out)
        return 2
    except SettingError as error:
        print(f"PREFLIGHT_FAILED {error.code}:{error.name}", file=out)
        return 2
    except Exception:  # noqa: BLE001 -- CLI must not expose driver credentials
        # Driver diagnostics can contain credentials or an authenticated URI.
        print("PREFLIGHT_FAILED SYNC_FAILED", file=out)
        return 2
    print(json.dumps(report, ensure_ascii=False), file=out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
