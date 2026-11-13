"""Create the ordered, blind first-stage E1 sheet from test creatives only."""

import argparse
import csv
import json
import random
import sys
from collections import Counter, defaultdict, deque
from collections.abc import Mapping, Sequence
from contextlib import ExitStack
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import Any, Literal, NamedTuple, TextIO

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from beautyads.domain import Creative, Source, is_analyzable
from beautyads.eval.sheets import codebook_rows, sha256_of
from beautyads.pipeline.preflight import docker_running, tcp_reachable
from beautyads.settings import DEFAULT_ENV_FILE, get_setting
from beautyads.sources.split import (
    BrandSplit,
    SplitError,
    brand_group,
    load_brand_split,
)
from beautyads.store import (
    PostgresCreativeStore,
    StoreConnectError,
    connect,
    postgres_dsn,
)

CONFIG_PATH = Path("config/e1_sampling.yaml")
PREREGISTRATION_PATH = Path("docs/results/e1_preregistration.md")
SPLIT_PATH = Path("config/brand_split.yaml")
TAXONOMY_PATH = Path("docs/TAXONOMY.md")
DEFAULT_OUT_DIR = Path("data/interim/e1")
STAGE1_COLUMNS = ["item_id", "link", "text", "content_type", "category"]


class E1Error(Exception):
    """Stable public reason; never expose connection or raw input diagnostics."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class Stage1Config(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    min_labeled: int = Field(gt=0)
    max_labeled: int = Field(gt=0)
    target_product: int = Field(gt=0)

    @model_validator(mode="after")
    def ordered_limits(self):
        if (
            self.min_labeled > self.max_labeled
            or self.target_product > self.max_labeled
        ):
            raise ValueError("inconsistent labeling limits")
        return self


class Stage2Config(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    size: int = Field(gt=0)


class DedupeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    youtube: list[Literal["source", "account", "title", "caption"]]
    instagram: list[Literal["source", "account", "caption"]]

    @model_validator(mode="after")
    def registered_keys(self):
        # These are constraints on the registered definition, never fallback keys.
        if self.youtube != [
            "source",
            "account",
            "title",
            "caption",
        ] or self.instagram != ["source", "account", "caption"]:
            raise ValueError("dedupe keys differ from registration")
        return self


class E1Config(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    seed: int
    stage1: Stage1Config
    stage2: Stage2Config
    sources: list[Literal["youtube", "instagram"]]
    dedupe: DedupeConfig

    @model_validator(mode="after")
    def registered_sources(self):
        if len(self.sources) != 2 or set(self.sources) != {"youtube", "instagram"}:
            raise ValueError("sources differ from registration")
        return self


def load_e1_config(path: Path) -> E1Config:
    try:
        return E1Config.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeError, yaml.YAMLError, ValidationError):
        raise E1Error("E1_CONFIG_INVALID") from None


def provenance_files() -> tuple[E1Config, dict[str, str]]:
    """Read registration first, then config; both stages record exact file bytes."""
    try:
        preregistration_hash = sha256_of(PREREGISTRATION_PATH)
    except OSError:
        raise E1Error("PREREGISTRATION_MISSING") from None
    config = load_e1_config(CONFIG_PATH)
    try:
        config_hash = sha256_of(CONFIG_PATH)
    except OSError:
        raise E1Error("E1_CONFIG_INVALID") from None
    return config, {
        "preregistration_sha256": preregistration_hash,
        "config_sha256": config_hash,
    }


class FrameReport(NamedTuple):
    items: list[Creative]
    dropped_duplicates: dict[str, int]
    frame_size_before: int
    frame_size_after: int


def dedupe_key(creative: Creative, config: E1Config) -> tuple | None:
    if creative.source.value not in config.sources:
        return None
    values = tuple(
        getattr(creative, field)
        for field in getattr(config.dedupe, creative.source.value)
    )
    if any(value is None or not value.strip() for value in values):
        return None
    return values


def build_frame(creatives, split: BrandSplit, config: E1Config) -> FrameReport:
    grouped = defaultdict(list)
    ungrouped = []
    before = 0
    for creative in creatives:
        if not is_analyzable(creative) or creative.source.value not in config.sources:
            continue
        try:
            if brand_group(split, creative.brand) != "test":
                continue
        except SplitError:
            continue
        before += 1
        key = dedupe_key(creative, config)
        if key is None:
            ungrouped.append(creative)
        else:
            grouped[key].append(creative)
    rng = random.Random(config.seed)
    items = list(ungrouped)
    dropped = dict.fromkeys(config.sources, 0)
    for key in sorted(grouped):
        group = sorted(grouped[key], key=lambda item: item.source_id)
        items.append(rng.choice(group))
        dropped[group[0].source.value] += len(group) - 1
    items.sort(key=lambda item: (item.source, item.source_id))
    return FrameReport(items, dropped, before, len(items))


def round_robin(
    groups: Mapping[tuple, Sequence], *, size: int, seed: int, identity
) -> list:
    """Pilot's sorted strata, sorted input, seeded shuffle and round-robin rule."""
    rng = random.Random(seed)
    queues = []
    for key in sorted(groups):
        items = sorted(groups[key], key=identity)
        rng.shuffle(items)
        if items:
            queues.append(deque(items))
    selected = []
    while queues and len(selected) < size:
        for queue in queues:
            selected.append(queue.popleft())
            if len(selected) == size:
                break
        queues = [queue for queue in queues if queue]
    return selected


def order_stage1(frame_items, config: E1Config, seed: int) -> list[Creative]:
    groups = defaultdict(list)
    for item in frame_items:
        groups[item.source.value, item.brand].append(item)
    return round_robin(
        groups,
        size=config.stage1.max_labeled,
        seed=seed,
        identity=lambda item: item.source_id,
    )


def stratum_shortfall(
    counts: Mapping[tuple[str, str], int], strata, size: int, selected: int
) -> dict:
    """Show deficits against equal nominal allocation, even if others fill them."""
    strata = sorted(strata)
    base, remainder = divmod(size, len(strata)) if strata else (0, 0)
    deficits = []
    for index, (source, value) in enumerate(strata):
        target = base + (index < remainder)
        missing = max(0, target - counts.get((source, value), 0))
        if missing:
            deficits.append({"source": source, "stratum": value, "missing": missing})
    return {"total": size - selected, "by_stratum": deficits}


class Stage1Sheet(NamedTuple):
    rows: list[dict[str, str]]
    key_rows: list[dict[str, Any]]


def build_stage1_sheet(ordered, *, seed: int, provenance: Mapping) -> Stage1Sheet:
    metadata = {
        **provenance,
        "seed": seed,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    rows, key_rows = [], []
    for index, creative in enumerate(ordered, 1):
        item_id = f"E{index:03}"
        rows.append(
            {
                "item_id": item_id,
                "link": creative.url or "",
                "text": "\n".join(
                    text for text in (creative.title, creative.caption) if text
                ),
                "content_type": "",
                "category": "",
            }
        )
        key_rows.append({**metadata, "item_id": item_id, **creative_identity(creative)})
    return Stage1Sheet(rows, key_rows)


def creative_identity(creative: Creative) -> dict:
    return {
        "source": creative.source.value,
        "source_id": creative.source_id,
        "brand": creative.brand,
        "account": creative.account,
        "url": creative.url,
    }


def output_paths(out_dir: Path, stage: int) -> dict[str, Path]:
    """Check lexical and resolved paths, including existing artifact symlinks."""
    absolute = out_dir.absolute()
    root = next(
        (
            p
            for p in (absolute, *absolute.parents)
            if p.name == "interim" and p.parent.name == "data"
        ),
        None,
    )
    if root is None:
        raise E1Error("OUTPUT_NOT_IGNORED")
    expected_root = root.parent.parent.resolve() / "data" / "interim"
    paths = {
        name: out_dir / f"e1_stage{stage}_{name}.{extension}"
        for name, extension in (
            ("sheet", "csv"),
            ("codebook", "csv"),
            ("instructions", "md"),
            ("key", "json"),
        )
    }
    if (
        root.resolve() != expected_root
        or not out_dir.resolve().is_relative_to(expected_root)
        or any(
            not path.resolve().is_relative_to(expected_root) for path in paths.values()
        )
    ):
        raise E1Error("OUTPUT_NOT_IGNORED")
    return paths


def ensure_new_outputs(paths: Mapping[str, Path]) -> None:
    if any(path.exists() or path.is_symlink() for path in paths.values()):
        raise E1Error("E1_OUTPUT_EXISTS")


def csv_text(fields, rows) -> str:
    stream = StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def e1_codebook(axes, stage: int) -> list[dict[str, str]]:
    # codebook_rows calls parse_taxonomy and enumerates the domain's closed values.
    return [
        {
            **row,
            "note": row["note"].replace("pilot_key.json", f"e1_stage{stage}_key.json"),
        }
        for row in codebook_rows(TAXONOMY_PATH.read_text(encoding="utf-8"))
        if row["axis"] in axes
    ]


def write_artifacts(paths, *, fields, rows, document, instructions, stage: int) -> None:
    ensure_new_outputs(paths)
    payloads = {
        "sheet": csv_text(fields, rows),
        "codebook": csv_text(["axis", "value", "note"], e1_codebook(fields[3:], stage)),
        # Metadata lives with the sheet instructions so the CSV retains its exact columns.
        "instructions": instructions
        + "\n\n시트 메타데이터:\n```json\n"
        + json.dumps(
            {
                k: document[k]
                for k in (
                    "seed",
                    "preregistration_sha256",
                    "config_sha256",
                    "generated_at",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n```\n",
        "key": json.dumps(document, ensure_ascii=False, indent=2) + "\n",
    }
    created = []
    try:
        paths["sheet"].parent.mkdir(parents=True, exist_ok=True)
        for name, path in paths.items():
            with path.open("x", encoding="utf-8", newline="") as stream:
                created.append(path)
                stream.write(payloads[name])
    except OSError as exc:
        for path in created:
            path.unlink(missing_ok=True)
        raise E1Error(
            "E1_OUTPUT_EXISTS"
            if isinstance(exc, FileExistsError)
            else "E1_OUTPUT_WRITE_FAILED"
        ) from None


def _live_deps(*, environ, env_file, stack):
    connection = connect(postgres_dsn(environ=environ, env_file=env_file))
    stack.callback(connection.close)
    return PostgresCreativeStore(connection)


def main(
    argv=None,
    *,
    environ=None,
    out: TextIO | None = None,
    docker_check=docker_running,
    tcp_check=tcp_reachable,
    deps_factory=None,
) -> int:
    out = sys.stdout if out is None else out
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    try:
        config, provenance = provenance_files()
        try:
            split = load_brand_split(SPLIT_PATH)
            provenance["split_sha256"] = sha256_of(SPLIT_PATH)
        except (SplitError, OSError):
            raise E1Error("E1_SPLIT_FILE_INVALID") from None
        paths = output_paths(args.out_dir, 1)
        ensure_new_outputs(paths)
        env_file = DEFAULT_ENV_FILE if environ is None else None
        if get_setting("POSTGRES_PASSWORD", environ=environ, env_file=env_file) is None:
            raise E1Error("ENV_MISSING:POSTGRES_PASSWORD")
        if not docker_check():
            raise E1Error("DOCKER_DOWN")
        try:
            port = int(
                get_setting(
                    "BEAUTYADS_POSTGRES_PORT",
                    "5433",
                    environ=environ,
                    env_file=env_file,
                )
            )
            reachable = 1 <= port <= 65535 and tcp_check("127.0.0.1", port, 1.0)
        except (ValueError, TypeError, OSError):
            reachable = False
        if not reachable:
            raise E1Error("POSTGRES_UNREACHABLE")
        with ExitStack() as stack:
            if deps_factory is None:
                store = _live_deps(environ=environ, env_file=env_file, stack=stack)
            else:
                store = deps_factory().store
            candidates = store.list_creatives(
                brands=split.test,
                sources=tuple(Source(value) for value in config.sources),
                analyzable_only=True,
            )
            frame = build_frame(candidates, split, config)
        if not frame.items:
            raise E1Error("E1_FRAME_EMPTY")
        ordered = order_stage1(frame.items, config, config.seed)
        counts = Counter((item.source.value, item.brand) for item in frame.items)
        strata = [(source, brand) for source in config.sources for brand in split.test]
        shortfall = stratum_shortfall(
            counts, strata, config.stage1.max_labeled, len(ordered)
        )
        metadata = {
            **provenance,
            "frame_size_before": frame.frame_size_before,
            "frame_size_after": frame.frame_size_after,
            "dropped_duplicates": frame.dropped_duplicates,
            "shortfall": shortfall,
        }
        sheet = build_stage1_sheet(ordered, seed=config.seed, provenance=metadata)
        identity_fields = ("item_id", "source", "source_id", "brand", "account", "url")
        document = {
            k: v for k, v in sheet.key_rows[0].items() if k not in identity_fields
        }
        document["items"] = {
            row["item_id"]: {k: row[k] for k in identity_fields[1:]}
            for row in sheet.key_rows
        }
        instructions = (
            "# E1 1단계 라벨링\n\n위에서부터 순서대로 라벨링하고, 사람이 제품 소재로 판정한 건이 "
            f"{config.stage1.target_product}건 이상이면서 라벨링한 건이 "
            f"{config.stage1.min_labeled}건 이상이 되면 멈춘다. "
            f"{config.stage1.max_labeled}건을 넘기지 않는다. 건너뛰지 않는다.\n\n"
            "content_type·category를 코드북에 따라 고른다. 비제품 소재의 category는 other다.\n\n"
            "e1_stage1_sheet_labeled.csv에 저장한다. 키 파일(e1_stage1_key.json)은 라벨링 뒤에만 연다."
        )
        write_artifacts(
            paths,
            fields=STAGE1_COLUMNS,
            rows=sheet.rows,
            document=document,
            instructions=instructions,
            stage=1,
        )
        print(
            json.dumps(
                {
                    "by_source_brand": [
                        {
                            "source": source,
                            "brand": brand,
                            "count": counts.get((source, brand), 0),
                        }
                        for source, brand in strata
                    ],
                    **metadata,
                    "selected": len(ordered),
                    "files": {k: str(v) for k, v in paths.items()},
                },
                ensure_ascii=False,
            ),
            file=out,
        )
        print("키 파일(e1_stage1_key.json)은 라벨링 뒤에만 여세요.", file=out)
    except (E1Error, StoreConnectError) as exc:
        print(f"PREFLIGHT_FAILED {exc.code}", file=out)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
