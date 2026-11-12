"""YouTube metadata → hook analysis → PostgreSQL, with a small live limit."""

import argparse
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from contextlib import ExitStack
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import NamedTuple, Protocol, TextIO

from pydantic import BaseModel

from beautyads.analysis import analyze_pending, select_for_analysis
from beautyads.domain import (
    AnalysisRepository,
    Creative,
    CreativeKey,
    CreativeRepository,
    JobStatus,
)
from beautyads.llm import (
    CostCapExceeded,
    DailyLimitReached,
    InteractionResult,
    gemini_interact,
)
from beautyads.obs import provider_total
from beautyads.settings import (
    DEFAULT_ENV_FILE,
    SettingError,
    ThinkingLevel,
    load_settings,
    require_setting,
)
from beautyads.sources.config import ConfigError, YouTubeChannel, load_youtube_channels
from beautyads.sources.youtube import HttpGet, collect_youtube, httpx_get
from beautyads.store import (
    PostgresCreativeStore,
    StoreConnectError,
    apply_migrations,
    connect,
    postgres_dsn,
)

from .preflight import docker_running, preflight, tcp_reachable


class SliceStore(CreativeRepository, AnalysisRepository, Protocol):
    """The slice needs both creative metadata and analysis jobs."""


class SliceDeps(NamedTuple):
    http_get: HttpGet
    store: SliceStore
    interact: Callable[..., InteractionResult]
    channels: list[YouTubeChannel]
    now: Callable[[], datetime]


class SliceReport(BaseModel):
    collected: int
    analyzed: dict[str, int]
    stopped: str | None
    items: list[dict]
    gemini_total_usd: float


class _AnalysisEvents:
    """Observe repository writes without changing the analysis contract."""

    def __init__(self, store: SliceStore, emit: Callable[..., None]):
        self.store = store
        self.emit = emit
        self.pending: dict[CreativeKey, Creative] = {}

    def next_pending(self, kind: str, limit: int) -> list[Creative]:
        creatives = self.store.next_pending(kind, limit)
        self.pending = {creative.key: creative for creative in creatives}
        return creatives

    def record_analysis(self, kind: str, key: CreativeKey, **kwargs) -> None:
        self.store.record_analysis(kind, key, **kwargs)
        creative = self.pending.pop(key)
        self.emit(
            "analysis",
            creative,
            status=kwargs["status"].value,
            hook_type=(kwargs["labels"] or {}).get("hook_type"),
            error_code=kwargs["error_code"],
        )


def run_slice(
    deps: SliceDeps,
    *,
    count: int,
    youtube_api_key: str,
    thinking_level: ThinkingLevel,
    window_max_s: float,
    length_cut_s: float,
    ledger_path: Path,
    caps: Mapping[str, float],
    out: TextIO,
) -> SliceReport:
    if not 1 <= count <= 5:
        raise ValueError("count must be between 1 and 5")
    items = []

    def emit(
        event, creative=None, *, source_id=None, status, hook_type=None, error_code=None
    ):
        item = {
            "event": event,
            "source": "youtube",
            "source_id": creative.source_id if creative is not None else source_id,
            # Only the canonical public video URL made by the source adapter.
            "url": creative.url if creative is not None else None,
            "status": status,
            "hook_type": hook_type,
            "error_code": error_code,
        }
        items.append(item)
        print(json.dumps(item, ensure_ascii=False), file=out)

    creatives: dict[CreativeKey, Creative] = {}
    stopped = None
    for channel in deps.channels:
        if len(creatives) >= count:
            break
        collected = collect_youtube(
            deps.http_get,
            youtube_api_key,
            [channel],
            max_items_per_channel=count - len(creatives),
            collected_at=deps.now(),
            video_length_cut_s=length_cut_s,
        )
        for error_code in collected.errors.values():
            emit(
                "collection",
                source_id=channel.channel_id,
                status="failed",
                error_code=error_code,
            )
        for creative in collected.creatives:
            if len(creatives) >= count:
                break
            creatives.setdefault(creative.key, creative)
        if collected.stopped:
            stopped = collected.stopped
            break

    selected = list(creatives.values())
    deps.store.upsert_creatives(selected)
    for creative in selected:
        emit("collection", creative, status="collected")
    selection = select_for_analysis(selected, video_length_cut_s=length_cut_s)
    for skip in selection.skipped:
        emit("selection", creatives[skip.key], status="skipped", error_code=skip.reason)
    deps.store.enqueue_analysis("hook", selection.eligible)
    events = _AnalysisEvents(deps.store, emit)
    counts = {status.value: 0 for status in JobStatus}
    if stopped is None:
        summary = analyze_pending(
            events,
            limit=count,
            interact=deps.interact,
            thinking_level=thinking_level,
            purpose="live-slice-hook",
            ledger_path=ledger_path,
            caps=caps,
            window_max_s=window_max_s,
        )
        counts.update(summary.counts)
        stopped = summary.stopped
    else:
        events.next_pending("hook", count)
    counts["pending"] = len(events.pending)
    for creative in events.pending.values():
        emit("analysis", creative, status="pending", error_code=stopped)
    report = SliceReport(
        collected=len(selected),
        analyzed=counts,
        stopped=stopped,
        items=items,
        gemini_total_usd=provider_total(ledger_path, "gemini"),
    )
    print(
        json.dumps({"event": "summary", **report.model_dump(exclude={"items"})}),
        file=out,
    )
    return report


def _live_deps(*, environ, env_file, stack: ExitStack) -> SliceDeps:
    channels = load_youtube_channels(Path("config/sources.yaml"))
    connection = connect(postgres_dsn(environ=environ, env_file=env_file))
    stack.callback(connection.close)
    apply_migrations(connection)
    return SliceDeps(
        http_get=httpx_get,
        store=PostgresCreativeStore(connection),
        interact=partial(
            gemini_interact,
            api_key=require_setting(
                "GEMINI_API_KEY", environ=environ, env_file=env_file
            ),
        ),
        channels=channels,
        now=lambda: datetime.now(UTC),
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    out: TextIO | None = None,
    docker_check: Callable[[], bool] = docker_running,
    tcp_check: Callable[[str, int, float], bool] = tcp_reachable,
    deps_factory: Callable[[], SliceDeps] | None = None,
) -> int:
    out = sys.stdout if out is None else out
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=1, choices=range(1, 6))
    parser.add_argument("--preflight-only", action="store_true")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    # An injected environment is self-contained; never consult a developer's .env.
    env_file = DEFAULT_ENV_FILE if environ is None else None
    try:
        settings = load_settings(environ=environ, env_file=env_file)
    except SettingError as exc:
        print(f"PREFLIGHT_FAILED {exc.code}:{exc.name}", file=out)
        return 2
    problems = preflight(
        environ=environ,
        env_file=env_file,
        ledger_path=settings.ledger_path,
        caps=settings.provider_caps_usd,
        docker_check=docker_check,
        tcp_check=tcp_check,
    )
    if problems:
        for problem in problems:
            print(f"PREFLIGHT_FAILED {problem.code}", file=out)
        return 2
    if args.preflight_only:
        return 0
    try:
        with ExitStack() as stack:
            deps = (
                deps_factory()
                if deps_factory is not None
                else _live_deps(environ=environ, env_file=env_file, stack=stack)
            )
            report = run_slice(
                deps,
                count=args.count,
                youtube_api_key=require_setting(
                    "YOUTUBE_API_KEY", environ=environ, env_file=env_file
                ),
                thinking_level=settings.thinking_level,
                window_max_s=settings.analysis_window_max_s,
                length_cut_s=settings.video_length_cut_s,
                ledger_path=settings.ledger_path,
                caps=settings.provider_caps_usd,
                out=out,
            )
    except StoreConnectError as exc:
        print(f"PREFLIGHT_FAILED {exc.code}", file=out)
        return 2
    except ConfigError as exc:
        print(f"PREFLIGHT_FAILED {exc}", file=out)
        return 2
    except DailyLimitReached:
        print("STOPPED DAILY_LIMIT", file=out)
        return 3
    except CostCapExceeded as exc:
        print(f"STOPPED COST_CAP:{exc.provider}", file=out)
        return 3
    if report.stopped:
        print(f"STOPPED {report.stopped}", file=out)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
