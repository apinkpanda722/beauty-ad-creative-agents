"""Assemble one creative's analysis while owning transient media cleanup."""

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, NamedTuple, Protocol

from pydantic import BaseModel

from beautyads.analysis.axes import (
    analyze_content_type,
    analyze_full,
    is_product_target,
)
from beautyads.analysis.hook import analyze_hook
from beautyads.analysis.models import AxisOutcome, VideoInput, video_input_for
from beautyads.domain import (
    AnalysisRepository,
    ContentTypeResult,
    Creative,
    CreativeKey,
    CreativeRepository,
    JobStatus,
    Source,
)
from beautyads.llm import FileError, InteractionResult, ThinkingLevel, UploadedFile
from beautyads.sources.config import InstagramAccount
from beautyads.sources.instagram import RefreshResult
from beautyads.sources.media import DownloadedMedia, MediaError

RETRYABLE_ERROR_CODES = frozenset(
    {
        "MEDIA_REQUEST_FAILED",
        "MEDIA_TRUNCATED",
        "FILE_UPLOAD_FAILED",
        "FILE_PROCESS_TIMEOUT",
        "FILE_RETRIEVE_FAILED",
        "LLM_RETRYABLE",
        # 분류되지 않은 호출 실패. 2026-11-14 YouTube 실행 끝에서 118건이 몰려 실패했고
        # 다시 호출하자 성공했다(시간 의존 일시 오류). 영구 사유면 재시도해도 같은 코드로 다시 실패한다.
        "LLM_FATAL",
        # 사용량 등으로 재조회가 중간에 멈춰 못 찾은 것이라 소재 문제가 아니다.
        "MEDIA_REFRESH_STOPPED",
    }
)
# 재시도 뒤에도 같은 LLM_FATAL로 다시 실패한 작업의 제외 사유. RETRYABLE_ERROR_CODES에 없으므로
# --retry-failed가 다시 집지 않는다.
LLM_FATAL_REPEATED = "LLM_FATAL_REPEATED"
_HELD_CODES = frozenset(
    {
        "MEDIA_NOT_VIDEO",
        "MEDIA_EMPTY",
        "MEDIA_UNAVAILABLE",
        "MEDIA_URL_GONE",
        "FILE_STATUS_ERROR",
        "EMPTY_FILE",
        "INVALID_OUTPUT",
    }
)


class UrlPlan(NamedTuple):
    url: str | None
    state: str


class AnalysisRun(NamedTuple):
    thinking_level: ThinkingLevel
    run_tag: str
    purpose: str
    ledger_path: Path
    caps: Mapping[str, float]
    content_type_window_s: float
    full_window_s: float
    hook_window_max_s: float
    interact: Callable[..., InteractionResult]
    purpose_by_axis: bool = False


class MediaDeps(NamedTuple):
    download: Callable[[str], DownloadedMedia]
    upload: Callable[[bytes, str], UploadedFile]
    wait: Callable[[str], None]
    delete: Callable[[str], bool]


class AxisRecord(BaseModel):
    kind: str
    status: JobStatus
    labels: dict[str, Any] | None
    model: str | None
    thinking_level: str
    prompt_version: str | None
    raw_output: str | None
    error_code: str | None


class CreativeOutcome(BaseModel):
    key: CreativeKey
    records: list[AxisRecord]
    cleanup: str
    mark_not_analyzable: bool


class MediaStore(CreativeRepository, AnalysisRepository, Protocol):
    """Persist creative metadata and the tagged analysis jobs together."""


def prepare_instagram_plans(
    creatives: Sequence[Creative],
    accounts: Mapping[str, InstagramAccount],
    *,
    refresh: Callable[[InstagramAccount, set[str]], RefreshResult],
) -> dict[CreativeKey, UrlPlan]:
    plans = {}
    grouped: dict[str, list[Creative]] = defaultdict(list)
    for creative in creatives:
        if creative.source != Source.instagram:
            continue
        plans[creative.key] = UrlPlan(None, "missing")
        if creative.account in accounts:
            grouped[creative.account].append(creative)
    for username, items in grouped.items():
        result = refresh(accounts[username], {item.source_id for item in items})
        for item in items:
            url = result.urls.get(item.source_id)
            if url:
                plans[item.key] = UrlPlan(url, "ok")
            elif item.source_id in result.gone:
                plans[item.key] = UrlPlan(None, "gone")
            elif result.stopped is not None:
                # 스캔이 끝까지 돌지 못했으므로 "없다"가 아니라 "못 찾았다"다.
                plans[item.key] = UrlPlan(None, "refresh_stopped")
    return plans


def _error_record(run: AnalysisRun, code: str) -> AxisRecord:
    return AxisRecord(
        kind=f"content_type@{run.run_tag}",
        status=JobStatus.held if code in _HELD_CODES else JobStatus.failed,
        labels=None,
        model=None,
        thinking_level=run.thinking_level,
        prompt_version=None,
        raw_output=None,
        error_code=code,
    )


def _axis_record(result: AxisOutcome, run: AnalysisRun) -> AxisRecord:
    return AxisRecord(
        kind=f"{result.axis}@{run.run_tag}",
        status=result.status,
        labels=result.labels,
        model=result.model,
        thinking_level=run.thinking_level,
        prompt_version=result.prompt_version,
        raw_output=result.raw_output,
        error_code=result.error_code,
    )


def _analyze(
    creative: Creative, video: VideoInput, run: AnalysisRun, outcome: CreativeOutcome
) -> None:
    kwargs = {
        "thinking_level": run.thinking_level,
        "purpose": run.purpose,
        "ledger_path": run.ledger_path,
        "caps": run.caps,
        "interact": run.interact,
    }
    if run.purpose_by_axis:
        kwargs["purpose"] = f"{run.purpose}-content_type"
    content = analyze_content_type(
        creative, video, window_max_s=run.content_type_window_s, **kwargs
    )
    outcome.records.append(_axis_record(content, run))
    if content.status != JobStatus.done:
        return
    if not is_product_target(ContentTypeResult.model_validate(content.labels)):
        return

    if run.purpose_by_axis:
        kwargs["purpose"] = f"{run.purpose}-hook"
    hook = analyze_hook(
        creative, video=video, window_max_s=run.hook_window_max_s, **kwargs
    )
    outcome.records.append(
        AxisRecord(
            kind=f"hook@{run.run_tag}",
            status=hook.status,
            labels=hook.hook.model_dump(mode="json") if hook.hook is not None else None,
            model=hook.model,
            thinking_level=run.thinking_level,
            prompt_version=hook.prompt_version,
            raw_output=hook.raw_output,
            error_code=hook.error_code,
        )
    )
    if hook.status != JobStatus.done:
        return
    if run.purpose_by_axis:
        kwargs["purpose"] = f"{run.purpose}-full"
    full = analyze_full(creative, video, window_max_s=run.full_window_s, **kwargs)
    outcome.records.append(_axis_record(full, run))


def _download(
    url: str,
    media: MediaDeps,
    rerefresh: Callable[[], str | None] | None,
    transient: list[str],
) -> DownloadedMedia:
    try:
        return media.download(url)
    except MediaError as exc:
        if exc.code != "MEDIA_URL_UNAVAILABLE":
            raise
    new_url = rerefresh() if rerefresh is not None else None
    if new_url:
        transient.append(new_url)
        try:
            return media.download(new_url)
        except MediaError:
            pass
    raise MediaError("MEDIA_UNAVAILABLE") from None


def _redact(value: Any, transient: Sequence[str]) -> Any:
    """Do not persist an input URI even if a model echoes it in its output."""
    if isinstance(value, str):
        for identifier in transient:
            value = value.replace(identifier, "[redacted]")
        return value
    if isinstance(value, dict):
        return {key: _redact(child, transient) for key, child in value.items()}
    if isinstance(value, list):
        return [_redact(child, transient) for child in value]
    return value


def analyze_creative(
    creative: Creative,
    *,
    plan: UrlPlan,
    run: AnalysisRun,
    media: MediaDeps,
    rerefresh: Callable[[], str | None] | None = None,
) -> CreativeOutcome:
    outcome = CreativeOutcome(
        key=creative.key, records=[], cleanup="none", mark_not_analyzable=False
    )
    if plan.state == "none":
        _analyze(creative, video_input_for(creative), run, outcome)
        return outcome
    if plan.state == "gone":
        outcome.mark_not_analyzable = True
        outcome.records.append(_error_record(run, "MEDIA_URL_GONE"))
        return outcome
    if plan.state == "refresh_stopped":
        outcome.records.append(_error_record(run, "MEDIA_REFRESH_STOPPED"))
        return outcome
    if plan.state != "ok" or not plan.url:
        outcome.records.append(_error_record(run, "MEDIA_URL_MISSING"))
        return outcome

    transient = [plan.url]
    try:
        downloaded = _download(plan.url, media, rerefresh, transient)
    except MediaError as exc:
        outcome.records.append(_error_record(run, exc.code))
        return outcome

    file_id = None
    try:
        try:
            try:
                file_id = media.upload(downloaded.data, filename="video.mp4").id
            finally:
                # The upload is the last consumer of the video bytes.
                del downloaded
            media.wait(file_id)
        except FileError as exc:
            outcome.records.append(_error_record(run, exc.code))
            return outcome
        transient.append(file_id)
        _analyze(creative, VideoInput(file_id, "video/mp4"), run, outcome)
    finally:
        if file_id is not None:
            outcome.cleanup = "deleted" if media.delete(file_id) else "delete_failed"

    outcome.records = [
        AxisRecord.model_validate(_redact(record.model_dump(), transient))
        for record in outcome.records
    ]
    return outcome


def apply_outcome(
    store: MediaStore, creative: Creative, outcome: CreativeOutcome
) -> None:
    for record in outcome.records:
        if not store.get_job_results(record.kind, [outcome.key]):
            store.enqueue_analysis(record.kind, [creative])
        store.record_analysis(
            record.kind,
            outcome.key,
            status=record.status,
            model=record.model,
            thinking_level=record.thinking_level,
            prompt_version=record.prompt_version,
            raw_output=record.raw_output,
            labels=record.labels,
            error_code=record.error_code,
        )
    if outcome.mark_not_analyzable:
        store.upsert_creatives([creative.model_copy(update={"analyzable": False})])
