"""Resume final v1 analysis in bounded batches, after local prerequisite checks."""

import argparse
import json
import random
import re
import sys
import tempfile
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Collection, Mapping, Sequence
from contextlib import ExitStack
from datetime import UTC, date, datetime
from functools import partial
from io import StringIO
from math import fsum, isfinite
from pathlib import Path
from threading import Lock
from typing import Any, NamedTuple, TextIO, get_args

from beautyads.analysis.models import ANALYSIS_MODEL_ID, FINAL_RUN_TAG, PROMPT_VERSIONS
from beautyads.domain import Creative, CreativeKey, FullResult, JobStatus, Source
from beautyads.llm import (
    CostCapExceeded,
    InteractionResult,
    delete_file,
    gemini_interact,
    upload_video,
    wait_processed,
)
from beautyads.obs.ledger import check_cap, read_entries
from beautyads.pipeline.analyze import (
    AXES,
    MAX_CONCURRENCY,
    AnalysisDeps,
    enqueue_targets,
    run_analysis,
)
from beautyads.pipeline.collect import DEFAULT_INSTAGRAM_BASE_URL, with_retries
from beautyads.pipeline.media_flow import (
    AnalysisRun,
    MediaDeps,
    MediaStore,
    prepare_instagram_plans,
    prepare_tiktok_plans,
)
from beautyads.pipeline.preflight import Problem, docker_running, tcp_reachable
from beautyads.settings import (
    DEFAULT_ENV_FILE,
    SettingError,
    ThinkingLevel,
    get_setting,
    load_settings,
    require_setting,
)
from beautyads.sources.config import (
    ConfigError,
    load_instagram_accounts,
    load_tiktok_config,
)
from beautyads.sources.instagram import (
    RefreshResult,
    instagram_httpx_get,
    refresh_media_urls,
)
from beautyads.sources.media import download_media, httpx_media_get
from beautyads.sources.tiktok import (
    TokenProvider,
    refresh_tiktok_video_urls,
    tiktok_httpx_post,
)
from beautyads.store import (
    PostgresCreativeStore,
    StoreConnectError,
    apply_migrations,
    connect,
    postgres_dsn,
)

PREREGISTRATION_PATH = Path("docs/results/e1_preregistration.md")
TOKEN_FIELDS = ("input_tokens", "output_tokens", "thought_tokens", "cached_tokens")
TIKTOK_MAX_PAGES = 20
PER_BRAND_SAMPLE_SEED = 20261114
PER_BRAND_SAMPLE_RULE = (
    "분석 가능 소재를 브랜드별로 source_id 정렬 후 섞어 앞에서 N건(최신순 아님)"
)


class TargetDeps(NamedTuple):
    analysis: AnalysisDeps
    interact: Callable[..., InteractionResult]
    scan_log: list[dict[str, Any]]


class TargetError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def select_per_brand(
    creatives: Sequence[Creative], per_brand_limit: int, seed: int
) -> list[Creative]:
    """Use an independent seeded shuffle for each brand, including no brand."""
    grouped: dict[str | None, list[Creative]] = defaultdict(list)
    for creative in creatives:
        if creative.analyzable is True:
            grouped[creative.brand].append(creative)
    selected = []
    for brand in sorted(grouped, key=lambda value: (value is not None, value or "")):
        # Source breaks ties when different platforms share a source_id.
        items = sorted(grouped[brand], key=lambda item: (item.source_id, item.source))
        random.Random(f"{seed}:{brand}").shuffle(items)
        selected.extend(items[:per_brand_limit])
    return selected


def _sampling(per_brand_limit: int, selected_total: int | None) -> dict:
    return {
        "seed": PER_BRAND_SAMPLE_SEED,
        "per_brand_limit": per_brand_limit,
        "selected_total": selected_total,
        "rule": PER_BRAND_SAMPLE_RULE,
    }


def read_only_keys(paths: Sequence[Path]) -> set[CreativeKey] | None:
    """Access only source/source_id inside each item; never emit its other fields."""
    if not paths:
        return None
    keys = set()
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise TargetError("ONLY_KEYS_FILE_MISSING") from None
        except (OSError, ValueError, UnicodeError):
            raise TargetError("ONLY_KEYS_FILE_INVALID") from None
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, dict):
            raise TargetError("ONLY_KEYS_FILE_INVALID")
        for item in items.values():
            if not isinstance(item, dict):
                raise TargetError("ONLY_KEYS_FILE_INVALID")
            source, source_id = item.get("source"), item.get("source_id")
            if (
                not isinstance(source, str)
                or source not in {member.value for member in Source}
                or not isinstance(source_id, str)
                or not source_id.strip()
            ):
                raise TargetError("ONLY_KEYS_FILE_INVALID")
            keys.add(CreativeKey(source=Source(source), source_id=source_id))
    return keys


def _preregistered(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    if not all(
        value in text for value in (ANALYSIS_MODEL_ID, *PROMPT_VERSIONS.values())
    ):
        return False
    for value in re.findall(
        r"^\s*(?:-\s*)?전체 v1 동결:\s*(\d{4}-\d{2}-\d{2})\s*$", text, re.MULTILINE
    ):
        try:
            date.fromisoformat(value)
            return True
        except ValueError:
            pass
    return False


def preflight_target(
    *,
    sources: Collection[Source],
    environ: Mapping[str, str] | None,
    env_file: Path | None,
    ledger_path: Path,
    caps: Mapping[str, float],
    preregistration_path: Path,
    docker_check: Callable[[], bool],
    tcp_check: Callable[[str, int, float], bool],
) -> list[Problem]:
    """Local checks precede bounded infrastructure probes and dependency creation."""
    names = ["GEMINI_API_KEY", "POSTGRES_PASSWORD"]
    if Source.instagram in sources:
        names.extend(("INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_USER_ID"))
    if Source.tiktok in sources:
        names.extend(("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET"))
    problems = [
        Problem(f"ENV_MISSING:{name}")
        for name in names
        if get_setting(name, environ=environ, env_file=env_file) is None
    ]
    if not _preregistered(preregistration_path):
        problems.append(Problem("PREREGISTRATION_NOT_UPDATED"))
    writable = True
    try:
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=ledger_path.parent) as probe:
            probe.write(b"probe")
            probe.flush()
        if ledger_path.exists():
            with ledger_path.open("a", encoding="utf-8"):
                pass
        check_cap(ledger_path, "gemini", caps)
    except CostCapExceeded:
        problems.append(Problem("COST_CAP:gemini"))
    except (OSError, UnicodeError):
        writable = False
    if not writable:
        problems.append(Problem("LEDGER_NOT_WRITABLE"))
    if problems:
        return problems
    if not docker_check():
        return [Problem("DOCKER_DOWN")]
    try:
        port = int(
            get_setting(
                "BEAUTYADS_POSTGRES_PORT", "5433", environ=environ, env_file=env_file
            )
        )
        reachable = 1 <= port <= 65535 and tcp_check("127.0.0.1", port, 1.0)
    except (TypeError, ValueError, OSError):
        reachable = False
    return [] if reachable else [Problem("POSTGRES_UNREACHABLE")]


def progress(store: MediaStore, keys: Sequence[CreativeKey]) -> dict:
    """Report selected v1 jobs; failure rate counts failed/held terminal jobs."""
    jobs = {
        axis: store.get_job_results(f"{axis}@{FINAL_RUN_TAG}", keys) for axis in AXES
    }
    statuses = {
        axis: {
            status.value: sum(job.status == status for job in rows)
            for status in JobStatus
        }
        for axis, rows in jobs.items()
    }
    counts = Counter(job.status.value for rows in jobs.values() for job in rows)
    content_done = [job for job in jobs["content_type"] if job.status == JobStatus.done]
    full_done = [job for job in jobs["full"] if job.status == JobStatus.done]
    other = {}
    # Derive enum-valued fields from the domain schema, excluding free text/flags.
    for axis, field in FullResult.model_fields.items():
        annotation = field.annotation
        if get_args(annotation):
            annotation = get_args(annotation)[0]
        if (
            not isinstance(annotation, type)
            or not issubclass(annotation, str)
            or not hasattr(annotation, "__members__")
        ):
            continue
        values = [(job.labels or {}).get(axis) for job in full_done]
        values = [value for value in values if value is not None]
        count = sum(
            "other" in value if isinstance(value, list) else value == "other"
            for value in values
        )
        other[axis] = {
            "n": len(values),
            "other": count,
            "ratio": count / len(values) if values else None,
        }
    terminal = sum(
        counts[s.value] for s in (JobStatus.done, JobStatus.failed, JobStatus.held)
    )
    failed = counts["failed"] + counts["held"]
    return {
        "by_status": statuses,
        "done_by_source": dict(Counter(job.key.source.value for job in content_done)),
        "done_by_category": dict(
            Counter(
                (job.labels or {}).get("category")
                for job in content_done
                if (job.labels or {}).get("category") is not None
            )
        ),
        "failed": counts["failed"],
        "held": counts["held"],
        "failure_rate": failed / terminal if terminal else None,
        "other_by_axis": other,
        "error_codes": dict(
            Counter(
                job.error_code
                for rows in jobs.values()
                for job in rows
                if job.error_code
            )
        ),
        "pending": counts["pending"],
    }


def cost_by_axis(ledger_path: Path, start: int) -> dict:
    entries = read_entries(ledger_path).entries[start:]
    result = {}
    for axis in AXES:
        rows = [
            entry
            for entry in entries
            if entry.provider == "gemini" and entry.purpose == f"analyze-target-{axis}"
        ]
        result[axis] = {
            "calls": len(rows),
            "token_means": {
                field: fsum(getattr(row, field) for row in rows) / len(rows)
                if rows
                else None
                for field in TOKEN_FIELDS
            },
            "cost_usd": fsum(row.cost_usd for row in rows),
            "non_response_cost": sum(
                row.cost_source != "response_cost" for row in rows
            ),
        }
    return result


class _RetryOnce:
    """Keep child-job resumption enabled without reopening failures every batch."""

    def __init__(self, store: MediaStore, keys: Sequence[CreativeKey] | None = None):
        self.store = store
        self.keys = keys
        self.requeued: set[str] = set()

    def __getattr__(self, name):
        return getattr(self.store, name)

    def requeue_jobs(self, kind, error_codes):
        if kind in self.requeued:
            return 0
        self.requeued.add(kind)
        if self.keys is None:
            return self.store.requeue_jobs(kind, error_codes)
        # The repository's bulk requeue has no key filter. Use its per-job write
        # boundary for an E1 selection so failures outside the key stay untouched.
        jobs = [
            job
            for job in self.store.get_job_results(kind, self.keys)
            if job.status == JobStatus.failed and job.error_code in error_codes
        ]
        for job in jobs:
            self.store.record_analysis(
                kind,
                job.key,
                status=JobStatus.pending,
                model=job.model,
                thinking_level=job.thinking_level,
                prompt_version=job.prompt_version,
                raw_output=None,
                labels=job.labels,
                error_code=None,
            )
        return len(jobs)


def run_target(
    deps: TargetDeps,
    *,
    run: AnalysisRun,
    sources: Collection[Source],
    brands: Collection[str] | None,
    limit: int | None,
    batch_size: int,
    concurrency: int,
    retry_failed: bool,
    only_keys: Collection[CreativeKey] | None,
    ledger_start: int,
    out: TextIO,
    per_brand_limit: int | None = None,
) -> int:
    store = deps.analysis.store
    started = deps.analysis.now()
    if per_brand_limit is not None:
        candidates = store.list_creatives(
            analyzable_only=True, sources=sources, brands=brands, limit=None
        )
        only_keys = {
            item.key
            for item in select_per_brand(
                candidates, per_brand_limit, PER_BRAND_SAMPLE_SEED
            )
        }
    if only_keys is None:
        targets = enqueue_targets(
            store, FINAL_RUN_TAG, sources=sources, brands=brands, limit=limit
        )
    else:
        targets = []
        skipped = 0
        for key in sorted(only_keys, key=lambda key: (key.source.value, key.source_id)):
            if key.source not in sources:
                continue
            creative = store.get_creative(key)
            if creative is None or creative.analyzable is not True:
                skipped += 1
            else:
                targets.append(creative)
        store.enqueue_analysis(f"content_type@{FINAL_RUN_TAG}", targets)
        print(f"KEY_NOT_ANALYZABLE {skipped}", file=out)
    keys = [item.key for item in targets]
    analysis = deps.analysis._replace(
        store=_RetryOnce(store, keys if only_keys is not None else None)
    )
    cumulative = 0.0
    stopped = None
    while keys:
        # Suppress per-creative diagnostics: the E1 key file must remain blind.
        report = run_analysis(
            analysis,
            run=run,
            limit=batch_size,
            concurrency=concurrency,
            retry_failed=retry_failed,
            only_keys=keys,
            out=StringIO(),
        )
        cumulative += report.gemini_cost_usd
        state = progress(store, keys)
        stopped = report.stopped or next(
            (scan.get("stopped") for scan in deps.scan_log if scan.get("stopped")), None
        )
        if stopped is None and report.error_codes.get("MEDIA_REFRESH_STOPPED", 0):
            stopped = "MEDIA_REFRESH_STOPPED"
        print(
            json.dumps(
                {
                    "event": "batch",
                    "processed": report.processed,
                    **state,
                    "batch_error_codes": report.error_codes,
                    "batch_cost_usd": report.gemini_cost_usd,
                    "cumulative_cost_usd": cumulative,
                    "elapsed_s": (deps.analysis.now() - started).total_seconds(),
                    "stopped": stopped,
                },
                ensure_ascii=False,
            ),
            file=out,
            flush=True,
        )
        if stopped or report.processed == 0 or state["pending"] == 0:
            break
    summary = {
        "event": "summary",
        **progress(store, keys),
        "stopped": stopped,
        "cumulative_cost_usd": cumulative,
        "elapsed_s": (deps.analysis.now() - started).total_seconds(),
        "cost_by_axis": cost_by_axis(run.ledger_path, ledger_start),
        "refresh_by_account": dict(
            Counter(
                scan.get("account") for scan in deps.scan_log if scan.get("account")
            )
        ),
        "instagram_last_usage": next(
            (
                scan.get("usage")
                for scan in reversed(deps.scan_log)
                if scan.get("usage")
            ),
            None,
        ),
    }
    if per_brand_limit is not None:
        summary["sampling"] = _sampling(per_brand_limit, len(keys))
    if stopped:
        print(f"STOPPED {stopped}", file=out)
    print(json.dumps(summary, ensure_ascii=False), file=out, flush=True)
    return 3 if stopped else 0


def tiktok_stop_is_global(code: str | None) -> bool:
    """Server errors and capped scans only fail that brand; account-level errors stop all."""
    if code is None:
        return False
    return not (code.startswith("TIKTOK_HTTP_5") or code == "TIKTOK_PAGES_INCOMPLETE")


def _live_deps(
    *,
    sources,
    environ,
    env_file,
    stack: ExitStack,
    tiktok_max_pages: int = TIKTOK_MAX_PAGES,
) -> TargetDeps:
    """Connect runtime layer boundaries after preflight, without eval dependencies."""
    scan_log: list[dict[str, Any]] = []
    accounts = {}
    brands = {}
    lock = Lock()
    stop = None
    tiktok_stop = None
    if Source.instagram in sources:
        accounts = {
            item.username: item
            for item in load_instagram_accounts(Path("config/sources.yaml"))
        }
        get = with_retries(instagram_httpx_get)
        token = require_setting(
            "INSTAGRAM_ACCESS_TOKEN", environ=environ, env_file=env_file
        )
        user_id = require_setting(
            "INSTAGRAM_USER_ID", environ=environ, env_file=env_file
        )
        base_url = get_setting(
            "BEAUTYADS_INSTAGRAM_BASE_URL",
            DEFAULT_INSTAGRAM_BASE_URL,
            environ=environ,
            env_file=env_file,
        )

    def now():
        return datetime.now(UTC)

    if Source.tiktok in sources:
        tiktok_config = load_tiktok_config(Path("config/sources.yaml"))
        brands = {item.brand: item for item in tiktok_config.brands}
        tiktok_token = TokenProvider(
            tiktok_httpx_post,
            client_key=require_setting(
                "TIKTOK_CLIENT_KEY", environ=environ, env_file=env_file
            ),
            client_secret=require_setting(
                "TIKTOK_CLIENT_SECRET", environ=environ, env_file=env_file
            ),
            now=now,
        )

    def refresh_tiktok(brand, wanted_ids):
        nonlocal tiktok_stop
        with lock:
            if tiktok_stop is not None:
                return RefreshResult({}, set(), set(wanted_ids), tiktok_stop)
            result = refresh_tiktok_video_urls(
                tiktok_httpx_post,
                tiktok_token,
                tiktok_config,
                brand,
                wanted_ids,
                today=now().date(),
                max_pages=tiktok_max_pages,
            )
            if tiktok_stop_is_global(result.stopped):
                tiktok_stop = result.stopped
            scan_log.append({"source": "tiktok", "stopped": result.stopped})
            return result

    def plans(creatives):
        return {
            **prepare_instagram_plans(creatives, accounts, refresh=refresh),
            **prepare_tiktok_plans(creatives, brands, refresh=refresh_tiktok),
        }

    def refresh(account, wanted_ids):
        nonlocal stop
        # One refresh may exhaust the shared app quota. Latch the stop for this
        # invocation, including concurrent expired-URL refreshes and later accounts.
        with lock:
            if stop is not None:
                return RefreshResult({}, set(), set(wanted_ids), stop)
            result = refresh_media_urls(
                get,
                token,
                user_id,
                account,
                wanted_ids,
                base_url=base_url,
                now=now(),
                scan_log=scan_log,
            )
            stop = result.stopped
            return result

    def rerefresh(creative):
        if creative.source == Source.tiktok:
            brand = brands.get(creative.brand)
            if brand is None:
                return None
            return lambda: refresh_tiktok(brand, {creative.source_id}).urls.get(
                creative.source_id
            )
        account = (
            accounts.get(creative.account)
            if creative.source == Source.instagram
            else None
        )
        if account is None:
            return None
        return lambda: refresh(account, {creative.source_id}).urls.get(
            creative.source_id
        )

    gemini_key = require_setting("GEMINI_API_KEY", environ=environ, env_file=env_file)
    connection = connect(postgres_dsn(environ=environ, env_file=env_file))
    stack.callback(connection.close)
    apply_migrations(connection)
    return TargetDeps(
        AnalysisDeps(
            PostgresCreativeStore(connection),
            MediaDeps(
                partial(download_media, httpx_media_get),
                partial(upload_video, api_key=gemini_key),
                partial(wait_processed, api_key=gemini_key),
                partial(delete_file, api_key=gemini_key),
            ),
            plans,
            rerefresh,
            time.sleep,
            now,
        ),
        partial(gemini_interact, api_key=gemini_key),
        scan_log,
    )


def _integer(value: str, *, maximum: int | None = None) -> int:
    try:
        number = int(value)
        if number >= 1 and (maximum is None or number <= maximum):
            return number
    except ValueError:
        pass
    raise argparse.ArgumentTypeError(
        "expected a positive integer within the allowed range"
    )


def _window(value: str) -> float:
    try:
        number = float(value)
        if isfinite(number) and number > 0:
            return number
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("window must be finite and positive")


def _sources(value: str) -> set[Source]:
    names = {part.strip() for part in value.split(",")}
    if not names or not names <= {"youtube", "instagram", "tiktok"}:
        raise argparse.ArgumentTypeError("sources must be youtube,instagram,tiktok")
    return {Source(name) for name in names}


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    out: TextIO | None = None,
    docker_check=docker_running,
    tcp_check=tcp_reachable,
    deps_factory: Callable[[], TargetDeps] | None = None,
    preregistration_path: Path = PREREGISTRATION_PATH,
) -> int:
    out = sys.stdout if out is None else out
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=_sources, default="youtube,instagram")
    parser.add_argument("--brands")
    parser.add_argument("--limit", type=_integer)
    parser.add_argument("--per-brand-limit", type=partial(_integer, maximum=500))
    parser.add_argument("--tiktok-max-pages", type=_integer, default=TIKTOK_MAX_PAGES)
    parser.add_argument(
        "--batch-size", type=partial(_integer, maximum=500), default=100
    )
    parser.add_argument(
        "--concurrency", type=partial(_integer, maximum=MAX_CONCURRENCY), default=1
    )
    parser.add_argument(
        "--thinking-level", choices=get_args(ThinkingLevel), default="minimal"
    )
    parser.add_argument("--content-type-window-s", type=_window, default=60.0)
    parser.add_argument("--full-window-s", type=_window, default=60.0)
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--items", type=_integer)
    parser.add_argument("--only-keys-file", type=Path, action="append", default=[])
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    try:
        if args.per_brand_limit is not None and (
            args.only_keys_file or args.limit is not None
        ):
            raise TargetError("PER_BRAND_CONFLICT")
        if args.only_keys_file and (args.brands is not None or args.limit is not None):
            raise TargetError("ONLY_KEYS_CONFLICT")
        keys = read_only_keys(args.only_keys_file)
        if args.dry_run:
            preview = {
                "run_tag": FINAL_RUN_TAG,
                "model": ANALYSIS_MODEL_ID,
                "prompt_versions": PROMPT_VERSIONS,
                "batch_size": args.batch_size,
                "concurrency": args.concurrency,
                "thinking_level": args.thinking_level,
                "content_type_window_s": args.content_type_window_s,
                "full_window_s": args.full_window_s,
                "preregistration_path": str(preregistration_path),
                "assumptions": "비용은 원장에 기록되며 `cost-recalc` 결과를 따른다; 호출 수는 스키마 재요청·전송 재시도 제외",
            }
            if keys is not None:
                preview["key_count"] = sum(key.source in args.sources for key in keys)
            if Source.tiktok in args.sources:
                preview["tiktok_max_pages"] = args.tiktok_max_pages
            if args.per_brand_limit is not None:
                preview["sampling"] = _sampling(args.per_brand_limit, None)
            if args.items is not None:
                preview.update(calls_min=args.items, calls_max=args.items * 3)
            print("ESTIMATE " + json.dumps(preview, ensure_ascii=False), file=out)
            return 0
        env_file = DEFAULT_ENV_FILE if environ is None else None
        settings = load_settings(environ=environ, env_file=env_file)
        problems = preflight_target(
            sources=args.sources,
            environ=environ,
            env_file=env_file,
            ledger_path=settings.ledger_path,
            caps=settings.provider_caps_usd,
            preregistration_path=preregistration_path,
            docker_check=docker_check,
            tcp_check=tcp_check,
        )
        if problems:
            for problem in problems:
                print(f"PREFLIGHT_FAILED {problem.code}", file=out)
            return 2
        ledger_start = len(read_entries(settings.ledger_path).entries)
        with ExitStack() as stack:
            deps = (
                deps_factory()
                if deps_factory is not None
                else _live_deps(
                    sources=args.sources,
                    environ=environ,
                    env_file=env_file,
                    stack=stack,
                    tiktok_max_pages=args.tiktok_max_pages,
                )
            )
            run = AnalysisRun(
                args.thinking_level,
                FINAL_RUN_TAG,
                "analyze-target",
                settings.ledger_path,
                settings.provider_caps_usd,
                args.content_type_window_s,
                args.full_window_s,
                3.0,
                deps.interact,
                purpose_by_axis=True,
            )
            return run_target(
                deps,
                run=run,
                sources=args.sources,
                brands={part.strip() for part in args.brands.split(",")}
                if args.brands is not None
                else None,
                limit=args.limit,
                batch_size=args.batch_size,
                concurrency=args.concurrency,
                retry_failed=args.retry_failed,
                only_keys=keys,
                ledger_start=ledger_start,
                out=out,
                per_brand_limit=args.per_brand_limit,
            )
    except SettingError as exc:
        print(f"PREFLIGHT_FAILED {exc.code}:{exc.name}", file=out)
    except (TargetError, StoreConnectError) as exc:
        print(f"PREFLIGHT_FAILED {exc.code}", file=out)
    except ConfigError as exc:
        print(f"PREFLIGHT_FAILED {exc}", file=out)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
