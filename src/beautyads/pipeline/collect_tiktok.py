"""Collect TikTok ad metadata by brand, without persisting signed media URLs."""

import argparse
import json
import sys
import time
from collections import Counter
from collections.abc import Callable, Collection, Mapping, Sequence
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple, TextIO

from pydantic import BaseModel

from beautyads.domain import CreativeKey, CreativeRepository
from beautyads.settings import (
    DEFAULT_ENV_FILE,
    MissingSetting,
    get_setting,
    require_setting,
)
from beautyads.sources.config import (
    ConfigError,
    Retailers,
    TikTokConfig,
    load_retailers,
    load_tiktok_config,
)
from beautyads.sources.tiktok import _STOP_ERRORS as ADAPTER_STOP_ERRORS
from beautyads.sources.tiktok import (
    TikTokError,
    TikTokPost,
    TokenProvider,
    collect_tiktok,
    tiktok_httpx_post,
)
from beautyads.store import (
    PostgresCreativeStore,
    StoreConnectError,
    apply_migrations,
    connect,
    postgres_dsn,
)

from .preflight import docker_running, tcp_reachable

SOURCES_PATH = Path("config/sources.yaml")
RETAILERS_PATH = Path("config/retailers.yaml")
_STOP_ERRORS = frozenset(ADAPTER_STOP_ERRORS) | {"TIKTOK_HTTP_429"}


class TikTokCollectDeps(NamedTuple):
    post: TikTokPost
    store: CreativeRepository
    now: Callable[[], datetime]


class BrandReport(BaseModel):
    brand: str
    fetched: int
    executor: dict[str, int]
    error: str | None
    stored: int


class TikTokCollectReport(BaseModel):
    brands: list[BrandReport]
    stopped: str | None
    elapsed_s: float


def run_collect(
    deps: TikTokCollectDeps,
    token: TokenProvider,
    config: TikTokConfig,
    retailers: Retailers,
    *,
    max_pages: int,
    brands: Collection[str] | None,
    retailers_path: Path,
    out: TextIO,
) -> TikTokCollectReport:
    started = time.monotonic()
    now = deps.now()
    reports = []
    stopped = None
    saved: set[CreativeKey] = set()
    for brand in config.brands:
        if brands is not None and brand.brand not in brands:
            continue
        creatives = []
        error = None
        stored = 0
        try:
            # Issue/cache the token before collecting. An issuance failure stops
            # the batch regardless of its HTTP code; no runner-level retries.
            try:
                token.token()
            except TikTokError as exc:
                error = stopped = exc.code
            if stopped is None:
                result = collect_tiktok(
                    deps.post,
                    token,
                    config,
                    retailers,
                    max_pages=max_pages,
                    collected_at=now,
                    brands={brand.brand},
                )
                creatives = list({item.key: item for item in result.creatives}.values())
                error = result.errors.get(brand.brand)
                stopped = result.stopped
                if error in _STOP_ERRORS:
                    stopped = error
                if stopped is not None and error is None:
                    error = stopped
                # Incomplete brands are discarded in full and recollected from
                # page one on the next run, just like P2's account boundary.
                if error is None:
                    fresh = [item for item in creatives if item.key not in saved]
                    if fresh:
                        deps.store.upsert_creatives(fresh)
                        saved.update(item.key for item in fresh)
                        stored = len(fresh)
        except StoreConnectError:
            raise
        except Exception:  # noqa: BLE001 -- isolate diagnostics at the brand boundary
            # Exception text may contain credentials, provider bodies or media URLs.
            error = "COLLECTION_BRAND_FAILED"
            creatives = []
        report = BrandReport(
            brand=brand.brand,
            fetched=len(creatives),
            executor=dict(
                Counter(item.attributes.get("executor") for item in creatives)
            ),
            error=error,
            stored=stored,
        )
        reports.append(report)
        print(
            json.dumps({"event": "brand", **report.model_dump()}, ensure_ascii=False),
            file=out,
            flush=True,
        )
        if stopped is not None:
            break
    report = TikTokCollectReport(
        brands=reports, stopped=stopped, elapsed_s=time.monotonic() - started
    )
    executors: Counter[str] = Counter()
    for row in reports:
        executors.update(row.executor)
    print(
        json.dumps(
            {
                "event": "summary",
                "by_brand": {row.brand: row.fetched for row in reports},
                "stored_by_brand": {row.brand: row.stored for row in reports},
                "executor": dict(executors),
                "errors": {row.brand: row.error for row in reports if row.error},
                "stopped": stopped,
                "retailers_path": str(retailers_path),
                "retailers_count": len(retailers.names),
                "elapsed_s": report.elapsed_s,
            },
            ensure_ascii=False,
        ),
        file=out,
        flush=True,
    )
    return report


def _live_deps(*, environ, env_file, stack: ExitStack) -> TikTokCollectDeps:
    connection = connect(postgres_dsn(environ=environ, env_file=env_file))
    stack.callback(connection.close)
    apply_migrations(connection)
    return TikTokCollectDeps(
        tiktok_httpx_post, PostgresCreativeStore(connection), lambda: datetime.now(UTC)
    )


def _maximum(value: str) -> int:
    try:
        maximum = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("max-pages must be 1..50") from None
    if not 1 <= maximum <= 50:
        raise argparse.ArgumentTypeError("max-pages must be 1..50")
    return maximum


def _preflight(*, environ, env_file, docker_check, tcp_check) -> list[str]:
    problems = []
    for name in ("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "POSTGRES_PASSWORD"):
        try:
            require_setting(name, environ=environ, env_file=env_file)
        except MissingSetting:
            problems.append(f"ENV_MISSING:{name}")
    if problems:
        return problems
    if not docker_check():
        return ["DOCKER_DOWN"]
    value = get_setting(
        "BEAUTYADS_POSTGRES_PORT", "5433", environ=environ, env_file=env_file
    )
    try:
        port = int(value)
        reachable = 1 <= port <= 65535 and tcp_check("127.0.0.1", port, 1.0)
    except (TypeError, ValueError, OSError):
        reachable = False
    return [] if reachable else ["POSTGRES_UNREACHABLE"]


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    out: TextIO | None = None,
    docker_check=docker_running,
    tcp_check=tcp_reachable,
    deps_factory: Callable[[], TikTokCollectDeps] | None = None,
) -> int:
    out = sys.stdout if out is None else out
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brands")
    parser.add_argument("--max-pages", type=_maximum, default=1)
    parser.add_argument("--dry-run", action="store_true")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    brands = (
        {part.strip() for part in args.brands.split(",")}
        if args.brands is not None
        else None
    )
    env_file = DEFAULT_ENV_FILE if environ is None else None
    try:
        config = load_tiktok_config(SOURCES_PATH)
        retailers = load_retailers(RETAILERS_PATH)
        if brands is not None and not brands <= {b.brand for b in config.brands}:
            print("PREFLIGHT_FAILED TIKTOK_BRANDS_INVALID", file=out)
            return 2
        if args.dry_run:
            count = sum(brands is None or b.brand in brands for b in config.brands)
            print(
                "ESTIMATE "
                + json.dumps(
                    {
                        "brands": count,
                        "max_pages": args.max_pages,
                        "min_calls": count,
                        "max_calls": count * args.max_pages,
                        "assumptions": "광고 조회만 계산(토큰 발급 별도); 호출당 시간은 가정(미실측)",
                    },
                    ensure_ascii=False,
                ),
                file=out,
            )
            return 0
        problems = _preflight(
            environ=environ,
            env_file=env_file,
            docker_check=docker_check,
            tcp_check=tcp_check,
        )
        if problems:
            for problem in problems:
                print(f"PREFLIGHT_FAILED {problem}", file=out)
            return 2
        with ExitStack() as stack:
            deps = (
                deps_factory()
                if deps_factory is not None
                else _live_deps(environ=environ, env_file=env_file, stack=stack)
            )
            token = TokenProvider(
                deps.post,
                client_key=require_setting(
                    "TIKTOK_CLIENT_KEY", environ=environ, env_file=env_file
                ),
                client_secret=require_setting(
                    "TIKTOK_CLIENT_SECRET", environ=environ, env_file=env_file
                ),
                now=deps.now,
            )
            report = run_collect(
                deps,
                token,
                config,
                retailers,
                max_pages=args.max_pages,
                brands=brands,
                retailers_path=RETAILERS_PATH,
                out=out,
            )
    except StoreConnectError as exc:
        print(f"PREFLIGHT_FAILED {exc.code}", file=out)
        return 2
    except ConfigError as exc:
        print(f"PREFLIGHT_FAILED {exc}", file=out)
        return 2
    return 3 if report.stopped or any(row.error for row in report.brands) else 0


if __name__ == "__main__":
    raise SystemExit(main())
