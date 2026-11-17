"""Separate product-id batches: bounded samples, transient media, quota stops."""

import argparse
import json
import random
import re
import sys
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from contextlib import ExitStack
from datetime import UTC, datetime
from functools import partial
from math import fsum
from pathlib import Path
from typing import NamedTuple, TextIO

from beautyads.analysis.models import ANALYSIS_MODEL_ID, VideoInput, models_match
from beautyads.analysis.product_identify import ProductIdOutcome, identify_product
from beautyads.analysis.prompts import PRODUCT_ID_PROMPT_VERSION
from beautyads.domain import Creative, JobStatus, Source
from beautyads.domain.links import DEFAULT_SEED, LinkCreative, plan_links
from beautyads.domain.product_id import (
    PRODUCT_ID_KIND,
    candidates_for_brand,
    select_targets,
)
from beautyads.domain.products import Product
from beautyads.domain.sync import SyncCreative, SyncLabel
from beautyads.llm import (
    CostCapExceeded,
    DailyLimitReached,
    FileError,
    InteractionResult,
    LlmCallError,
    delete_file,
    gemini_interact,
    upload_video,
    wait_processed,
)
from beautyads.obs.ledger import check_cap, provider_total, read_entries
from beautyads.pipeline.analyze import AnalysisDeps
from beautyads.pipeline.analyze_target import _integer, _window
from beautyads.pipeline.collect import DEFAULT_INSTAGRAM_BASE_URL, with_retries
from beautyads.pipeline.media_flow import (
    _HELD_CODES,
    MediaDeps,
    UrlPlan,
    _download,
    _redact,
    prepare_instagram_plans,
)
from beautyads.pipeline.preflight import Problem, docker_running, tcp_reachable
from beautyads.settings import (
    DEFAULT_ENV_FILE,
    SettingError,
    get_setting,
    load_settings,
    require_setting,
)
from beautyads.sources.config import ConfigError, load_instagram_accounts
from beautyads.sources.instagram import (
    RefreshResult,
    instagram_httpx_get,
    needs_refresh,
    parse_oe_expiry,
    refresh_media_urls,
)
from beautyads.sources.media import MediaError, download_media, httpx_media_get
from beautyads.store import (
    PostgresCreativeStore,
    StoreConnectError,
    connect,
    postgres_dsn,
)
from beautyads.store.product_repository import PostgresProductStore


class IdentifyDeps(NamedTuple):
    analysis: AnalysisDeps
    products: Sequence[Product]
    interact: Callable[..., InteractionResult]


class BatchStop(Exception):
    pass


def _account_stop(exc: Exception) -> str | None:
    """The wrapper preserves measured error text, including 400 bad-key errors.

    A missing uploaded file is a creative failure, not account authentication.
    No provider diagnostic is printed or stored here.
    """
    if getattr(exc, "code", None) in {"FILE_NOT_FOUND", "FILE_NOT_ACTIVE"}:
        return None
    text = str(exc).lower()
    if re.search(r"\b(?:401|403)\b", text) or any(
        phrase in text
        for phrase in (
            "api key not valid",
            "api_key_invalid",
            "unauthenticated",
            "authentication",
            "invalid api key",
        )
    ):
        return "AUTH_FAILED"
    if "prepayment credits" in text or "resource_exhausted" in text and "402" in text:
        return "CREDITS_DEPLETED"
    return None


def _entry(creative: Creative, jobs=()) -> LinkCreative:
    return LinkCreative(
        SyncCreative(creative.model_dump(), creative.collected_at),
        tuple(SyncLabel(job.kind, job.status, job.labels) for job in jobs),
    )


def _targets(deps: IdentifyDeps) -> tuple[list[Creative], dict]:
    store = deps.analysis.store
    creatives = store.list_creatives(
        analyzable_only=False,
        brands=None,
        sources={Source.youtube, Source.instagram},
        limit=None,
    )
    keys = [c.key for c in creatives]
    jobs = (
        [
            job
            for kind in ("content_type@v1", PRODUCT_ID_KIND)
            for job in store.get_job_results(kind, keys)
        ]
        if keys
        else []
    )
    grouped = {}
    for job in jobs:
        grouped.setdefault(job.key, []).append(job)
    entries = {c.key: _entry(c, grouped.get(c.key, ())) for c in creatives}
    selected = {
        e.creative.key for e in select_targets(list(entries.values()), deps.products)
    }
    return sorted(
        (c for c in creatives if c.key in selected),
        key=lambda c: (c.source.value, c.source_id),
    ), entries


def estimate_cost(
    creatives: Sequence[Creative], ledger_path: Path, window_max_s: float
) -> dict:
    rows = [
        e
        for e in read_entries(ledger_path).entries
        if e.provider == "gemini"
        and e.cost_source == "response_cost"
        and e.input_tokens > 0
        and models_match(ANALYSIS_MODEL_ID, e.requested_model or e.model)
    ]
    rate = (
        fsum(e.cost_usd for e in rows) / sum(e.input_tokens for e in rows)
        if rows
        else 0.75 / 1_000_000
    )
    tokens = (
        fsum(
            min(window_max_s, max(c.duration_s, 0))
            if c.duration_s is not None
            else window_max_s
            for c in creatives
        )
        * 91
    )
    return {
        "label": "가정(미실측)",
        "video_tokens": tokens,
        "tokens_per_second": 91,
        "unknown_duration_assumed_window": sum(c.duration_s is None for c in creatives),
        "effective_usd_per_input_token": rate,
        "rate_source": "원장 실측 총비용/입력 토큰(출력·추론 포함 유효 단가)"
        if rows
        else "가정(미실측): 입력 $0.75/M, 출력·추론 제외",
        "cost_usd": tokens * rate,
        "limitations": "후보 글자·출력·추론·재요청에 따라 달라짐. 판정 기준으로 사용하지 않음",
    }


def _process(creative, candidates, deps, *, plan, persist, kwargs):
    media = deps.analysis.media
    if creative.source == Source.youtube:
        return identify_product(
            creative, candidates=candidates, on_attempt=persist, **kwargs
        ), "none"
    if plan.state == "refresh_stopped":
        raise BatchStop("MEDIA_REFRESH_STOPPED")
    if plan.state != "ok" or not plan.url:
        return ProductIdOutcome(
            key=creative.key,
            status=JobStatus.held,
            error_code="MEDIA_URL_GONE"
            if plan.state == "gone"
            else "MEDIA_URL_MISSING",
        ), "none"
    transient = [plan.url]
    url = plan.url
    rerefresh = deps.analysis.rerefresh(creative)
    if parse_oe_expiry(url) is not None and needs_refresh(url, deps.analysis.now()):
        refreshed = rerefresh() if rerefresh is not None else None
        if not refreshed:
            return ProductIdOutcome(
                key=creative.key, status=JobStatus.held, error_code="MEDIA_URL_MISSING"
            ), "none"
        url = refreshed
        transient.append(url)
    file_id = None
    cleanup = "none"
    try:
        downloaded = _download(url, media, rerefresh, transient)
        try:
            file_id = media.upload(downloaded.data, filename="video.mp4").id
        finally:
            del downloaded
        transient.append(file_id)
        media.wait(file_id)

        def safe_persist(result):
            persist(
                ProductIdOutcome.model_validate(_redact(result.model_dump(), transient))
            )

        outcome = identify_product(
            creative,
            candidates=candidates,
            video=VideoInput(file_id, "video/mp4"),
            on_attempt=safe_persist,
            **kwargs,
        )
        outcome = ProductIdOutcome.model_validate(
            _redact(outcome.model_dump(), transient)
        )
    finally:
        if file_id is not None:
            cleanup = "deleted" if media.delete(file_id) else "delete_failed"
    return outcome, cleanup


def run_identification(
    deps: IdentifyDeps,
    *,
    ledger_path: Path,
    caps: Mapping[str, float],
    out: TextIO,
    sample: int | None = None,
    seed: int = DEFAULT_SEED,
    sample_pairs: int = 20,
    max_videos: int | None = None,
    thinking_level="minimal",
    window_max_s: float = 60,
    dry_run: bool = False,
) -> dict:
    if (
        sample is not None
        and sample < 1
        or max_videos is not None
        and max_videos < 1
        or sample_pairs < 0
    ):
        raise ValueError("invalid sample or limit")
    _window(str(window_max_s))
    targets, entries = _targets(deps)
    target_count = len(targets)
    if sample is not None:
        targets = random.Random(seed).sample(targets, min(sample, len(targets)))
    if max_videos is not None:
        targets = targets[:max_videos]
    report = {
        "target_count": target_count,
        "selected": len(targets),
        "processed": 0,
        "done": 0,
        "held": 0,
        "failed": 0,
        "pending": len(targets),
        "newly_linked": 0,
        "video_multi_product": 0,
        "video_links": 0,
        "by_basis": {"title": 0, "caption": 0, "video": 0},
        "cost_usd": 0.0,
        "stopped": None,
        "sample_pairs": [],
        "seed": seed,
    }
    report["estimate"] = estimate_cost(targets, ledger_path, window_max_s)
    if dry_run:
        print(json.dumps(report, ensure_ascii=False), file=out)
        return report
    store = deps.analysis.store
    # Existing enqueue guards require a positive media decision. This copy only
    # creates the separate job; collected metadata and v1 labels stay unchanged.
    store.enqueue_analysis(
        PRODUCT_ID_KIND, [c.model_copy(update={"analyzable": True}) for c in targets]
    )
    initial_cost = provider_total(ledger_path, "gemini")
    pairs = []
    errors = Counter()
    plans = None

    def interact(**kwargs):
        try:
            return deps.interact(**kwargs)
        except LlmCallError as exc:
            stop = _account_stop(exc)
            if stop:
                raise BatchStop(stop) from None
            raise

    for creative in targets:
        saved = 0
        last_status = None

        def persist(outcome, key=creative.key):
            nonlocal saved, last_status
            store.record_analysis(
                PRODUCT_ID_KIND,
                key,
                status=outcome.status,
                labels=outcome.labels,
                model=outcome.model,
                thinking_level=thinking_level,
                prompt_version=outcome.prompt_version,
                raw_output=outcome.raw_output,
                error_code=outcome.error_code,
            )
            saved += 1
            last_status = outcome.status

        try:
            check_cap(ledger_path, "gemini", caps)
            # The existing media planner groups a bounded selection by account.
            # Expiry during a long batch is rechecked immediately before download.
            if creative.source == Source.instagram and plans is None:
                plans = deps.analysis.plans(
                    [c for c in targets if c.source == Source.instagram]
                )
            outcome, cleanup = _process(
                creative,
                candidates_for_brand(creative.brand, deps.products),
                deps,
                plan=(plans or {}).get(creative.key, UrlPlan(None, "missing")),
                persist=persist,
                kwargs={
                    "thinking_level": thinking_level,
                    "ledger_path": ledger_path,
                    "caps": caps,
                    "window_max_s": window_max_s,
                    "interact": interact,
                },
            )
            if cleanup == "delete_failed":
                errors["FILE_DELETE_FAILED"] += 1
        except CostCapExceeded:
            report["stopped"] = "COST_CAP:gemini"
            break
        except DailyLimitReached as exc:
            report["stopped"] = exc.kind.value
            break
        except BatchStop as exc:
            report["stopped"] = str(exc)
            break
        except SettingError as exc:
            report["stopped"] = f"{exc.code}:{exc.name}"
            break
        except (MediaError, FileError, LlmCallError) as exc:
            stop = _account_stop(exc)
            if stop:
                report["stopped"] = stop
                break
            outcome = ProductIdOutcome(
                key=creative.key,
                status=JobStatus.held if exc.code in _HELD_CODES else JobStatus.failed,
                error_code=exc.code,
            )
        except Exception:  # noqa: BLE001 -- a creative cannot abort other creatives
            outcome = ProductIdOutcome(
                key=creative.key, status=JobStatus.failed, error_code="UNEXPECTED"
            )
        # Validation attempts already persisted through the existing repository;
        # media errors and exceptions still need their own terminal job record.
        if not saved or last_status == JobStatus.pending:
            persist(outcome)
        report["processed"] += 1
        report[outcome.status.value] += 1
        if outcome.error_code:
            errors[outcome.error_code] += 1
        if outcome.status == JobStatus.done:
            prior = entries[creative.key]
            entry = LinkCreative(
                prior.creative,
                (*prior.labels, SyncLabel(PRODUCT_ID_KIND, "done", outcome.labels)),
            )
            plan = plan_links(entry, deps.products)
            report["newly_linked"] += bool(plan.links)
            report["video_multi_product"] += plan.multi_product
            report["video_links"] += len(plan.links)
            report["by_basis"]["video"] += len(plan.links)
            pairs.extend(
                {
                    "source": creative.source.value,
                    "source_id": creative.source_id,
                    "title": (creative.title or "")[:120],
                    "caption": (creative.caption or "")[:120],
                    "url": creative.url,
                    "product_name": match.product.name_ko,
                    "product_source_url": match.product.source_url,
                    "basis": "video",
                    "confidence": "model",
                    "multi_product": plan.multi_product,
                }
                for match in plan.links
            )
    if report["stopped"]:
        # Enqueue preserves existing rows. On a stopped resume, transition only
        # unprocessed selected held/failed jobs back to pending, using the same
        # per-job repository boundary as other resumable analysis pipelines.
        # raw_output=None preserves all historical model_outputs rows.
        for creative in targets[report["processed"] :]:
            prior = store.get_job_results(PRODUCT_ID_KIND, [creative.key])
            if prior and prior[0].status in {JobStatus.held, JobStatus.failed}:
                store.record_analysis(
                    PRODUCT_ID_KIND,
                    creative.key,
                    status=JobStatus.pending,
                    labels=None,
                    model=None,
                    thinking_level=thinking_level,
                    prompt_version=PRODUCT_ID_PROMPT_VERSION,
                    raw_output=None,
                    error_code=None,
                )
    report["pending"] -= report["processed"]
    report["cost_usd"] = provider_total(ledger_path, "gemini") - initial_cost
    pairs.sort(key=lambda p: (p["source"], p["source_id"], p["product_source_url"]))
    report["sample_pairs"] = random.Random(seed).sample(
        pairs, min(sample_pairs, len(pairs))
    )
    report["error_codes"] = dict(errors)
    print(json.dumps(report, ensure_ascii=False), file=out)
    return report


def preflight(*, environ, env_file, ledger_path, caps, docker_check, tcp_check):
    problems = [
        Problem(f"ENV_MISSING:{name}")
        for name in ("GEMINI_API_KEY", "POSTGRES_PASSWORD")
        if get_setting(name, environ=environ, env_file=env_file) is None
    ]
    if not docker_check():
        problems.append(Problem("DOCKER_DOWN"))
    try:
        port = int(
            get_setting(
                "BEAUTYADS_POSTGRES_PORT", "5433", environ=environ, env_file=env_file
            )
        )
        reachable = 1 <= port <= 65535 and tcp_check("127.0.0.1", port, 1.0)
    except (ValueError, TypeError, OSError):
        reachable = False
    if not reachable:
        problems.append(Problem("POSTGRES_UNREACHABLE"))
    try:
        check_cap(ledger_path, "gemini", caps)
    except CostCapExceeded:
        problems.append(Problem("COST_CAP:gemini"))
    return problems


def _live_deps(stack, *, environ, env_file):
    conn = connect(postgres_dsn(environ=environ, env_file=env_file))
    stack.callback(conn.close)
    store = PostgresCreativeStore(conn)
    accounts = {
        a.username: a for a in load_instagram_accounts(Path("config/sources.yaml"))
    }
    scan_log = []
    stopped = None

    def now():
        return datetime.now(UTC)

    def refresh(account, wanted):
        nonlocal stopped
        if stopped:
            return RefreshResult({}, set(), set(wanted), stopped)
        result = refresh_media_urls(
            with_retries(instagram_httpx_get),
            require_setting(
                "INSTAGRAM_ACCESS_TOKEN", environ=environ, env_file=env_file
            ),
            require_setting("INSTAGRAM_USER_ID", environ=environ, env_file=env_file),
            account,
            wanted,
            base_url=get_setting(
                "BEAUTYADS_INSTAGRAM_BASE_URL",
                DEFAULT_INSTAGRAM_BASE_URL,
                environ=environ,
                env_file=env_file,
            ),
            now=now(),
            scan_log=scan_log,
        )
        stopped = result.stopped
        return result

    def plans(creatives):
        return prepare_instagram_plans(creatives, accounts, refresh=refresh)

    def rerefresh(creative):
        account = accounts.get(creative.account)

        def refresh_one():
            result = refresh(account, {creative.source_id})
            if result.stopped:
                raise BatchStop("MEDIA_REFRESH_STOPPED")
            return result.urls.get(creative.source_id)

        return refresh_one if account else None

    key = require_setting("GEMINI_API_KEY", environ=environ, env_file=env_file)
    media = MediaDeps(
        partial(download_media, httpx_media_get),
        partial(upload_video, api_key=key),
        partial(wait_processed, api_key=key),
        partial(delete_file, api_key=key),
    )
    return IdentifyDeps(
        AnalysisDeps(store, media, plans, rerefresh, time.sleep, now),
        PostgresProductStore(conn).list_products(),
        partial(gemini_interact, api_key=key),
    )


def main(
    argv=None,
    *,
    environ=None,
    out=None,
    deps_factory=None,
    docker_check=docker_running,
    tcp_check=tcp_reachable,
):
    out = sys.stdout if out is None else out
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sample", type=_integer)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--sample-pairs", type=int, default=20)
    parser.add_argument("--max-videos", type=_integer)
    parser.add_argument(
        "--thinking-level",
        choices=("minimal", "low", "medium", "high", "default"),
        default="minimal",
    )
    parser.add_argument("--window-max-s", type=_window, default=60.0)
    parser.add_argument(
        "--approve-cost",
        action="store_true",
        help="전체 실행 비용에 대한 사용자 승인 뒤에만 지정",
    )
    args = parser.parse_args(argv)
    if args.sample_pairs < 0:
        parser.error("sample-pairs must be nonnegative")
    if not args.dry_run and args.sample is None and not args.approve_cost:
        print(
            "COST_APPROVAL_REQUIRED: 전체 실행은 사용자 비용 승인 뒤 --approve-cost",
            file=out,
        )
        return 2
    env_file = DEFAULT_ENV_FILE if environ is None else None
    try:
        settings = load_settings(environ=environ, env_file=env_file)
        # The cap is the setting (default 12, raised only by an explicit
        # BEAUTYADS_CAP_GEMINI_USD), the same as `live-products`.
        caps = dict(settings.provider_caps_usd)
        problems = preflight(
            environ=environ,
            env_file=env_file,
            ledger_path=settings.ledger_path,
            caps=caps,
            docker_check=docker_check,
            tcp_check=tcp_check,
        )
        if problems:
            for problem in problems:
                print(f"PREFLIGHT_FAILED {problem.code}", file=out)
            return 2
        with ExitStack() as stack:
            deps = (
                deps_factory()
                if deps_factory is not None
                else _live_deps(stack, environ=environ, env_file=env_file)
            )
            report = run_identification(
                deps,
                ledger_path=settings.ledger_path,
                caps=caps,
                out=out,
                sample=args.sample,
                seed=args.seed,
                sample_pairs=args.sample_pairs,
                max_videos=args.max_videos,
                thinking_level=args.thinking_level,
                window_max_s=args.window_max_s,
                dry_run=args.dry_run,
            )
        return 3 if report["stopped"] else 0
    except SettingError as exc:
        print(f"PREFLIGHT_FAILED {exc.code}:{exc.name}", file=out)
    except StoreConnectError:
        print("PREFLIGHT_FAILED POSTGRES_UNREACHABLE", file=out)
    except ConfigError:
        print("PREFLIGHT_FAILED SOURCE_CONFIG_INVALID", file=out)
    except (OSError, UnicodeError):
        print("PREFLIGHT_FAILED LEDGER_UNREADABLE", file=out)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
