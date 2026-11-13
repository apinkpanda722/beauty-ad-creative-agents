"""Resumable YouTube and Instagram metadata collection, without model calls."""

import argparse
import json
import sys
import time
from collections.abc import Callable, Collection, Mapping, Sequence
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from functools import wraps
from math import ceil, isfinite
from pathlib import Path
from typing import Any, NamedTuple, TextIO

from pydantic import BaseModel

from beautyads.domain import CollectionStat, CreativeRepository
from beautyads.settings import DEFAULT_ENV_FILE, get_setting
from beautyads.sources.config import (
    ConfigError,
    InstagramAccount,
    YouTubeChannel,
    load_instagram_accounts,
    load_youtube_channels,
)
from beautyads.sources.instagram import collect_instagram, instagram_httpx_get
from beautyads.sources.split import (
    BrandSplit,
    SplitError,
    brand_group,
    load_brand_split,
    volume_violations,
)
from beautyads.sources.youtube import collect_youtube, httpx_get
from beautyads.store import (
    PostgresCreativeStore,
    StoreConnectError,
    apply_migrations,
    connect,
    postgres_dsn,
)

from .preflight import collect_preflight, docker_running, tcp_reachable

DEFAULT_INSTAGRAM_BASE_URL = "https://graph.facebook.com/v21.0"
RETRY_STATUSES = frozenset({500, 502, 503, 504})
RETRY_ERROR_CODES = frozenset({"YOUTUBE_REQUEST_FAILED", "INSTAGRAM_REQUEST_FAILED"})


def with_retries(
    get: Callable[..., Any],
    *,
    attempts: int = 3,
    backoff_s: Sequence[float] = (2.0, 5.0, 15.0),
    sleep: Callable[[float], None] = time.sleep,
) -> Callable[..., Any]:
    """Wrap adapter GETs only; preserve the final response or exception."""
    if attempts < 1 or (attempts > 1 and not backoff_s):
        raise ValueError("attempts and backoff must permit at least one attempt")

    @wraps(get)
    def wrapped(*args, **kwargs):
        for index in range(attempts):
            try:
                response = get(*args, **kwargs)
            except Exception as exc:
                if getattr(exc, "code", None) not in RETRY_ERROR_CODES:
                    raise
                if index == attempts - 1:
                    raise
            else:
                if response.status not in RETRY_STATUSES or index == attempts - 1:
                    return response
            sleep(backoff_s[min(index, len(backoff_s) - 1)])

    return wrapped


class CollectDeps(NamedTuple):
    youtube_get: Callable[..., Any]
    instagram_get: Callable[..., Any]
    store: CreativeRepository
    now: Callable[[], datetime]
    sleep: Callable[[float], None]


class AccountReport(BaseModel):
    source: str
    brand: str | None
    account: str
    fetched: int
    analyzable_true: int
    analyzable_false: int
    analyzable_null: int
    error: str | None
    skipped: bool
    # 불완전(오류·중단)으로 끝난 계정은 저장하지 않으므로 skip-recent 대상이 되지 않는다.
    stored: bool = True
    # Instagram 앱 사용량 지표(call_count·total_cputime·total_time). 없으면 None.
    usage: dict[str, float] | None = None


class CollectReport(BaseModel):
    accounts: list[AccountReport]
    stopped: dict[str, str]
    volume_violations: list[str]
    elapsed_s: float


def estimate(
    *,
    youtube_accounts: int,
    instagram_accounts: int,
    max_per_account: int,
    youtube_s_per_call: float = 1.0,
    instagram_s_per_call: float = 2.0,
) -> dict:
    youtube_calls = youtube_accounts * (1 + 2 * ceil(max_per_account / 50))
    instagram_calls = instagram_accounts * ceil(max_per_account / 100)
    return {
        "youtube_calls": youtube_calls,
        "instagram_calls": instagram_calls,
        "total_calls": youtube_calls + instagram_calls,
        "estimated_minutes": (
            youtube_calls * youtube_s_per_call + instagram_calls * instagram_s_per_call
        )
        / 60,
        "instagram_app_usage_pct": instagram_calls * 0.5,
    }


def _summary(stats: Sequence[CollectionStat], split: BrandSplit) -> dict:
    counts: dict[tuple[str, str | None], dict] = {}
    by_source_brand: dict[tuple[str, str], int] = {}
    totals = {"dev": 0, "test": 0, "unassigned": 0}
    for stat in stats:
        source = stat.source.value
        row = counts.setdefault(
            (source, stat.brand),
            {
                "source": source,
                "brand": stat.brand,
                "analyzable_true": 0,
                "analyzable_false": 0,
                "analyzable_null": 0,
            },
        )
        for field in ("analyzable_true", "analyzable_false", "analyzable_null"):
            row[field] += getattr(stat, field)
        try:
            group = (
                brand_group(split, stat.brand)
                if stat.brand is not None
                else "unassigned"
            )
        except SplitError:
            group = "unassigned"
        totals[group] += stat.analyzable_true
        if group != "unassigned":
            key = (source, stat.brand)
            by_source_brand[key] = by_source_brand.get(key, 0) + stat.analyzable_true
    return {
        "by_source_brand": list(counts.values()),
        "split_analyzable_true": totals,
        "volume_violations": volume_violations(split, by_source_brand),
    }


def run_collect(
    deps: CollectDeps,
    *,
    sources: Collection[str],
    youtube_api_key: str,
    instagram_token: str,
    ig_user_id: str,
    instagram_base_url: str,
    youtube_channels: Sequence[YouTubeChannel],
    instagram_accounts: Sequence[InstagramAccount],
    max_per_account: int,
    skip_recent_hours: float,
    only_accounts: Collection[str] | None,
    video_length_cut_s: float,
    split: BrandSplit,
    out: TextIO,
) -> CollectReport:
    started = time.monotonic()
    now = deps.now()
    recent = set()
    if skip_recent_hours > 0:
        cutoff = now - timedelta(hours=skip_recent_hours)
        recent = {
            (stat.source.value, stat.account)
            for stat in deps.store.collection_stats()
            if stat.last_collected_at is not None
            and cutoff <= stat.last_collected_at <= now
        }
    getters = {
        "youtube": with_retries(deps.youtube_get, sleep=deps.sleep),
        "instagram": with_retries(deps.instagram_get, sleep=deps.sleep),
    }
    reports = []
    stopped = {}
    # A stable order also makes set-valued source selections reproducible.
    for source, accounts in (
        ("youtube", youtube_channels),
        ("instagram", instagram_accounts),
    ):
        if source not in sources:
            continue
        for account in accounts:
            name = account.handle if source == "youtube" else account.username
            if only_accounts is not None and name not in only_accounts:
                continue
            skipped = (source, name) in recent
            creatives = []
            error = None
            stop = None
            usage = None
            stored = True
            if not skipped:
                try:
                    if source == "youtube":
                        result = collect_youtube(
                            getters[source],
                            youtube_api_key,
                            [account],
                            max_items_per_channel=max_per_account,
                            collected_at=deps.now(),
                            video_length_cut_s=video_length_cut_s,
                        )
                    else:
                        usage = {}
                        result = collect_instagram(
                            getters[source],
                            instagram_token,
                            ig_user_id,
                            [account],
                            base_url=instagram_base_url,
                            max_posts_per_account=max_per_account,
                            collected_at=deps.now(),
                            usage_sink=usage,
                        )
                    # Report unique stored identities, even if provider pages overlap.
                    creatives = list(
                        {item.key: item for item in result.creatives}.values()
                    )
                    error = result.errors.get(name)
                    stop = result.stopped
                    # 오류·중단으로 끝난 계정의 일부 결과를 저장하면 --skip-recent-hours가
                    # 완료된 계정으로 오인해 건너뛴다. 저장하지 않고 다음 실행이 다시 받게 한다.
                    stored = error is None and stop is None
                    if stored:
                        deps.store.upsert_creatives(creatives)
                except StoreConnectError:
                    raise
                except Exception:  # noqa: BLE001 -- isolate failures at the account boundary
                    # Unexpected diagnostics may contain credentials or signed URLs.
                    error = "COLLECTION_ACCOUNT_FAILED"
                    creatives = []
                    stored = False
            report = AccountReport(
                source=source,
                brand=account.brand,
                account=name,
                fetched=len(creatives),
                analyzable_true=sum(item.analyzable is True for item in creatives),
                analyzable_false=sum(item.analyzable is False for item in creatives),
                analyzable_null=sum(item.analyzable is None for item in creatives),
                error=error,
                skipped=skipped,
                stored=stored,
                usage=usage or None,
            )
            reports.append(report)
            print(
                json.dumps(
                    {"event": "account", **report.model_dump()}, ensure_ascii=False
                ),
                file=out,
                flush=True,
            )
            if stop is not None:
                stopped[source] = stop
                break
    summary = _summary(deps.store.collection_stats(), split)
    report = CollectReport(
        accounts=reports,
        stopped=stopped,
        volume_violations=summary["volume_violations"],
        elapsed_s=time.monotonic() - started,
    )
    print(
        json.dumps(
            {
                "event": "summary",
                **report.model_dump(exclude={"accounts"}),
                **summary,
                "instagram_last_usage": next(
                    (item.usage for item in reversed(reports) if item.usage), None
                ),
                "warning": "SPLIT_VOLUME_INSUFFICIENT"
                if report.volume_violations
                else None,
            },
            ensure_ascii=False,
        ),
        file=out,
        flush=True,
    )
    return report


def _live_deps(*, environ, env_file, stack: ExitStack) -> CollectDeps:
    connection = connect(postgres_dsn(environ=environ, env_file=env_file))
    stack.callback(connection.close)
    apply_migrations(connection)
    return CollectDeps(
        httpx_get,
        instagram_httpx_get,
        PostgresCreativeStore(connection),
        lambda: datetime.now(UTC),
        time.sleep,
    )


def _maximum(value: str) -> int:
    try:
        maximum = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("max-per-account must be 1..1000") from None
    if not 1 <= maximum <= 1000:
        raise argparse.ArgumentTypeError("max-per-account must be 1..1000")
    return maximum


def _hours(value: str) -> float:
    try:
        hours = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            "skip-recent-hours must be finite and nonnegative"
        ) from None
    if not isfinite(hours) or hours < 0:
        raise argparse.ArgumentTypeError(
            "skip-recent-hours must be finite and nonnegative"
        )
    return hours


def _sources(value: str) -> set[str]:
    sources = {part.strip() for part in value.split(",")}
    if not sources or not sources <= {"youtube", "instagram"}:
        raise argparse.ArgumentTypeError("sources must be youtube,instagram")
    return sources


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    out: TextIO | None = None,
    docker_check=docker_running,
    tcp_check=tcp_reachable,
    deps_factory: Callable[[], CollectDeps] | None = None,
) -> int:
    out = sys.stdout if out is None else out
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=_sources, default="youtube,instagram")
    parser.add_argument("--max-per-account", type=_maximum, default=150)
    parser.add_argument("--skip-recent-hours", type=_hours, default=0.0)
    parser.add_argument("--accounts")
    parser.add_argument("--dry-run", action="store_true")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    only = (
        {part.strip() for part in args.accounts.split(",")}
        if args.accounts is not None
        else None
    )
    env_file = DEFAULT_ENV_FILE if environ is None else None
    if not args.dry_run:
        problems = collect_preflight(
            sources=args.sources,
            environ=environ,
            env_file=env_file,
            docker_check=docker_check,
            tcp_check=tcp_check,
        )
        if problems:
            for problem in problems:
                print(f"PREFLIGHT_FAILED {problem.code}", file=out)
            return 2
    try:
        channels = (
            load_youtube_channels(Path("config/sources.yaml"))
            if "youtube" in args.sources
            else []
        )
        accounts = (
            load_instagram_accounts(Path("config/sources.yaml"))
            if "instagram" in args.sources
            else []
        )
        if args.dry_run:
            preview = estimate(
                youtube_accounts=sum(
                    only is None or item.handle in only for item in channels
                ),
                instagram_accounts=sum(
                    only is None or item.username in only for item in accounts
                ),
                max_per_account=args.max_per_account,
            )
            preview["assumptions"] = (
                "호출당 시간은 가정(미실측); YouTube 쿼터 사용량은 미확인(Cloud 콘솔에서 확인); "
                "호출당 앱 사용량 0.5%는 과소추정이었다(첫 live에서 13계정·약 26호출에 80% 도달); "
                "instagram_app_usage_pct는 하한 참고값이며 한도에 닿으면 수집기가 멈춘다"
            )
            print("ESTIMATE " + json.dumps(preview, ensure_ascii=False), file=out)
            return 0
        split = load_brand_split(Path("config/brand_split.yaml"))
        value = get_setting(
            "BEAUTYADS_VIDEO_LENGTH_CUT_S", "600", environ=environ, env_file=env_file
        )
        try:
            length_cut = int(value)
            if length_cut <= 0:
                raise ValueError
        except (TypeError, ValueError):
            print(
                "PREFLIGHT_FAILED INVALID_SETTING:BEAUTYADS_VIDEO_LENGTH_CUT_S",
                file=out,
            )
            return 2
        with ExitStack() as stack:
            dependencies = (
                deps_factory()
                if deps_factory is not None
                else _live_deps(environ=environ, env_file=env_file, stack=stack)
            )
            report = run_collect(
                dependencies,
                sources=args.sources,
                youtube_api_key=get_setting(
                    "YOUTUBE_API_KEY", "", environ=environ, env_file=env_file
                ),
                instagram_token=get_setting(
                    "INSTAGRAM_ACCESS_TOKEN", "", environ=environ, env_file=env_file
                ),
                ig_user_id=get_setting(
                    "INSTAGRAM_USER_ID", "", environ=environ, env_file=env_file
                ),
                instagram_base_url=get_setting(
                    "BEAUTYADS_INSTAGRAM_BASE_URL",
                    DEFAULT_INSTAGRAM_BASE_URL,
                    environ=environ,
                    env_file=env_file,
                ),
                youtube_channels=channels,
                instagram_accounts=accounts,
                max_per_account=args.max_per_account,
                skip_recent_hours=args.skip_recent_hours,
                only_accounts=only,
                video_length_cut_s=length_cut,
                split=split,
                out=out,
            )
    except StoreConnectError as exc:
        print(f"PREFLIGHT_FAILED {exc.code}", file=out)
        return 2
    except SplitError as exc:
        print(f"PREFLIGHT_FAILED {exc.code}", file=out)
        return 2
    except ConfigError as exc:
        print(f"PREFLIGHT_FAILED {exc}", file=out)
        return 2
    return 3 if report.stopped else 0


if __name__ == "__main__":
    raise SystemExit(main())
