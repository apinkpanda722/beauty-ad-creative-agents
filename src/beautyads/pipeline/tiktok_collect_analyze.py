"""Collect TikTok ads and analyze a seeded sample in the same run.

TikTok's search result set differs between runs, so an ad cannot be found again
later to renew its video URL. Each brand is collected, its sample is chosen, and
those ads are analyzed immediately with the signed URLs from that very response.
The URLs live only in memory; nothing signed is stored or printed.
"""

import argparse
import json
import sys
import time
from collections import Counter
from collections.abc import Callable, Collection, Mapping, Sequence
from contextlib import ExitStack
from datetime import UTC, datetime
from functools import partial
from io import StringIO
from pathlib import Path
from typing import (
    NamedTuple,
    TextIO,
    get_args,
)

from beautyads.analysis.models import FINAL_RUN_TAG
from beautyads.domain import CreativeKey, JobStatus, Source
from beautyads.llm import (
    InteractionResult,
    delete_file,
    gemini_interact,
    upload_video,
    wait_processed,
)
from beautyads.obs.ledger import read_entries
from beautyads.pipeline.analyze import AnalysisDeps, run_analysis
from beautyads.pipeline.analyze_target import (
    PER_BRAND_SAMPLE_RULE,
    PER_BRAND_SAMPLE_SEED,
    PREREGISTRATION_PATH,
    TIKTOK_MAX_PAGES,
    _integer,
    _window,
    cost_by_axis,
    preflight_target,
    select_per_brand,
)
from beautyads.pipeline.media_flow import AnalysisRun, MediaDeps, UrlPlan
from beautyads.pipeline.preflight import docker_running, tcp_reachable
from beautyads.settings import (
    DEFAULT_ENV_FILE,
    SettingError,
    ThinkingLevel,
    load_settings,
    require_setting,
)
from beautyads.sources.config import (
    ConfigError,
    load_retailers,
    load_tiktok_config,
)
from beautyads.sources.media import download_media, httpx_media_get
from beautyads.sources.tiktok import (
    STOP_ERROR_CODES,
    BrandCollection,
    TokenProvider,
    collect_tiktok_brand,
    tiktok_httpx_post,
)
from beautyads.store import (
    PostgresCreativeStore,
    StoreConnectError,
    apply_migrations,
    connect,
    postgres_dsn,
)

KIND = f"content_type@{FINAL_RUN_TAG}"


class TiktokRunDeps(NamedTuple):
    analysis: AnalysisDeps
    interact: Callable[..., InteractionResult]
    collect_brand: Callable[..., BrandCollection]
    brands: list


def _select(pool, need: int):
    # Same seeded rule as `--per-brand-limit`, so earlier and larger samples agree.
    return select_per_brand(pool, need, PER_BRAND_SAMPLE_SEED) if need > 0 else []


def run_collect_analyze(
    deps: TiktokRunDeps,
    *,
    run: AnalysisRun,
    brands: Collection[str] | None,
    per_brand_limit: int,
    ledger_start: int,
    out: TextIO,
) -> int:
    store = deps.analysis.store
    started = deps.analysis.now()
    cost = 0.0
    errors: Counter = Counter()
    model_errors: Counter = Counter()
    collected_total = selected_total = processed_total = 0
    stopped = None
    for brand in deps.brands:
        if brands is not None and brand.brand not in brands:
            continue
        result = deps.collect_brand(brand)
        if result.error is not None:
            errors[result.error] += 1
            print(
                json.dumps(
                    {"event": "brand", "brand": brand.brand, "error": result.error}
                ),
                file=out,
                flush=True,
            )
            if result.error in STOP_ERROR_CODES:
                stopped = result.error
                break
            continue
        store.upsert_creatives(result.creatives)
        collected_total += len(result.creatives)
        stored = store.list_creatives(brands=[brand.brand], sources=[Source.tiktok])
        jobs = store.get_job_results(KIND, [item.key for item in stored])
        done = sum(job.status == JobStatus.done for job in jobs)
        taken = {job.key for job in jobs}
        pool = [
            item
            for item in result.creatives
            if item.analyzable is True and item.key not in taken
        ]
        selected = _select(pool, per_brand_limit - done)
        selected_total += len(selected)
        urls = result.urls
        analysis = deps.analysis._replace(
            plans=lambda creatives, urls=urls: {
                item.key: (
                    UrlPlan(urls[item.source_id], "ok")
                    if item.source_id in urls
                    else UrlPlan(None, "missing")
                )
                for item in creatives
            },
            rerefresh=lambda creative: None,
        )
        keys: list[CreativeKey] = [item.key for item in selected]
        processed = 0
        if keys:
            store.enqueue_analysis(KIND, selected)
            report = run_analysis(
                analysis,
                run=run,
                limit=len(keys),
                concurrency=1,
                retry_failed=False,
                only_keys=keys,
                out=StringIO(),
            )
            processed = report.processed
            processed_total += processed
            cost += report.gemini_cost_usd
            model_errors.update(report.error_codes)
            stopped = report.stopped
        print(
            json.dumps(
                {
                    "event": "brand",
                    "brand": brand.brand,
                    "collected": len(result.creatives),
                    "selected": len(keys),
                    "processed": processed,
                    "error": None,
                    "stopped": stopped,
                }
            ),
            file=out,
            flush=True,
        )
        if stopped:
            break
    if stopped:
        print(f"STOPPED {stopped}", file=out)
    print(
        json.dumps(
            {
                "event": "summary",
                "collected": collected_total,
                "selected": selected_total,
                "processed": processed_total,
                "errors": dict(errors),
                "error_codes": dict(model_errors),
                "stopped": stopped,
                "cumulative_cost_usd": cost,
                "elapsed_s": (deps.analysis.now() - started).total_seconds(),
                "cost_by_axis": cost_by_axis(run.ledger_path, ledger_start),
                "sampling": {
                    "seed": PER_BRAND_SAMPLE_SEED,
                    "per_brand_limit": per_brand_limit,
                    "rule": PER_BRAND_SAMPLE_RULE
                    + "; 이번 실행의 수집 응답 안에서 고르고 이미 분석한 소재는 목표에 포함",
                },
            },
            ensure_ascii=False,
        ),
        file=out,
        flush=True,
    )
    return 3 if stopped else 0


def _live_deps(*, environ, env_file, stack: ExitStack, max_pages: int) -> TiktokRunDeps:
    config = load_tiktok_config(Path("config/sources.yaml"))
    retailers = load_retailers(Path("config/retailers.yaml"))
    token = TokenProvider(
        tiktok_httpx_post,
        client_key=require_setting(
            "TIKTOK_CLIENT_KEY", environ=environ, env_file=env_file
        ),
        client_secret=require_setting(
            "TIKTOK_CLIENT_SECRET", environ=environ, env_file=env_file
        ),
        now=lambda: datetime.now(UTC),
    )
    gemini_key = require_setting("GEMINI_API_KEY", environ=environ, env_file=env_file)
    connection = connect(postgres_dsn(environ=environ, env_file=env_file))
    stack.callback(connection.close)
    apply_migrations(connection)

    def collect_brand(brand):
        return collect_tiktok_brand(
            tiktok_httpx_post,
            token,
            config,
            retailers,
            brand,
            max_pages=max_pages,
            collected_at=datetime.now(UTC),
        )

    analysis = AnalysisDeps(
        PostgresCreativeStore(connection),
        MediaDeps(
            partial(download_media, httpx_media_get),
            partial(upload_video, api_key=gemini_key),
            partial(wait_processed, api_key=gemini_key),
            partial(delete_file, api_key=gemini_key),
        ),
        lambda creatives: {},
        lambda creative: None,
        time.sleep,
        lambda: datetime.now(UTC),
    )
    return TiktokRunDeps(
        analysis,
        partial(gemini_interact, api_key=gemini_key),
        collect_brand,
        list(config.brands),
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    out: TextIO | None = None,
    docker_check=docker_running,
    tcp_check=tcp_reachable,
    deps_factory: Callable[[], TiktokRunDeps] | None = None,
    preregistration_path: Path = PREREGISTRATION_PATH,
) -> int:
    out = sys.stdout if out is None else out
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brands")
    parser.add_argument("--per-brand-limit", type=_integer, required=True)
    parser.add_argument("--max-pages", type=_integer, default=TIKTOK_MAX_PAGES)
    parser.add_argument(
        "--thinking-level", choices=get_args(ThinkingLevel), default="minimal"
    )
    parser.add_argument("--content-type-window-s", type=_window, default=60.0)
    parser.add_argument("--full-window-s", type=_window, default=60.0)
    parser.add_argument("--dry-run", action="store_true")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    if args.dry_run:
        print(
            "ESTIMATE "
            + json.dumps(
                {
                    "seed": PER_BRAND_SAMPLE_SEED,
                    "per_brand_limit": args.per_brand_limit,
                    "max_pages": args.max_pages,
                    "rule": PER_BRAND_SAMPLE_RULE,
                    "assumptions": "광고 조회는 브랜드당 최대 max_pages회, 분석 비용은 원장 기록을 따른다",
                },
                ensure_ascii=False,
            ),
            file=out,
        )
        return 0
    try:
        env_file = DEFAULT_ENV_FILE if environ is None else None
        settings = load_settings(environ=environ, env_file=env_file)
        problems = preflight_target(
            sources={Source.tiktok},
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
                    environ=environ,
                    env_file=env_file,
                    stack=stack,
                    max_pages=args.max_pages,
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
            return run_collect_analyze(
                deps,
                run=run,
                brands={part.strip() for part in args.brands.split(",")}
                if args.brands is not None
                else None,
                per_brand_limit=args.per_brand_limit,
                ledger_start=ledger_start,
                out=out,
            )
    except SettingError as exc:
        print(f"PREFLIGHT_FAILED {exc.code}:{exc.name}", file=out)
    except StoreConnectError as exc:
        print(f"PREFLIGHT_FAILED {exc.code}", file=out)
    except ConfigError as exc:
        print(f"PREFLIGHT_FAILED {exc}", file=out)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
