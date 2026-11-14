"""Bounded offline analysis batches with serialized persistence and quota stops."""

import json
from collections import Counter
from collections.abc import Callable, Collection, Sequence
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime
from threading import Event, Lock
from typing import Any, NamedTuple, TextIO

from pydantic import BaseModel

from beautyads.analysis.axes import is_product_target
from beautyads.analysis.models import ANALYSIS_MODEL_ID
from beautyads.domain import (
    ContentTypeResult,
    Creative,
    CreativeKey,
    JobResult,
    JobStatus,
    Source,
)
from beautyads.llm import (
    CostCapExceeded,
    DailyLimitReached,
    ErrorKind,
    InteractionResult,
    LlmCallError,
    UsageInfo,
)
from beautyads.obs.ledger import provider_total
from beautyads.pipeline.media_flow import (
    LLM_FATAL_REPEATED,
    RETRYABLE_ERROR_CODES,
    AnalysisRun,
    AxisRecord,
    CreativeOutcome,
    MediaDeps,
    MediaStore,
    UrlPlan,
    analyze_creative,
    apply_outcome,
)

MAX_CONCURRENCY = 4
RATE_LIMIT_WAIT_MAX_S = 120.0
AXES = ("content_type", "hook", "full")


class SerializedStore:
    """One connection-wide lock for every creative and analysis repository call."""

    def __init__(self, store: MediaStore):
        self._store = store
        self._lock = Lock()

    def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            return getattr(self._store, method)(*args, **kwargs)

    def upsert_creatives(self, *args: Any, **kwargs: Any) -> int:
        return self._call("upsert_creatives", *args, **kwargs)

    def get_creative(self, *args: Any, **kwargs: Any) -> Creative | None:
        return self._call("get_creative", *args, **kwargs)

    def collection_stats(self, *args: Any, **kwargs: Any) -> list:
        return self._call("collection_stats", *args, **kwargs)

    def list_creatives(self, *args: Any, **kwargs: Any) -> list[Creative]:
        return self._call("list_creatives", *args, **kwargs)

    def enqueue_analysis(self, *args: Any, **kwargs: Any) -> int:
        return self._call("enqueue_analysis", *args, **kwargs)

    def next_pending(self, *args: Any, **kwargs: Any) -> list[Creative]:
        return self._call("next_pending", *args, **kwargs)

    def requeue_jobs(self, *args: Any, **kwargs: Any) -> int:
        return self._call("requeue_jobs", *args, **kwargs)

    def job_counts(self, *args: Any, **kwargs: Any) -> dict[str, int]:
        return self._call("job_counts", *args, **kwargs)

    def get_job_results(self, *args: Any, **kwargs: Any) -> list[JobResult]:
        return self._call("get_job_results", *args, **kwargs)

    def record_analysis(self, *args: Any, **kwargs: Any) -> None:
        return self._call("record_analysis", *args, **kwargs)


class AnalysisDeps(NamedTuple):
    store: MediaStore
    media: MediaDeps
    plans: Callable[[Sequence[Creative]], dict[CreativeKey, UrlPlan]]
    rerefresh: Callable[[Creative], Callable[[], str | None] | None]
    sleep: Callable[[float], None]
    now: Callable[[], datetime]


class AnalysisReport(BaseModel):
    processed: int
    by_status: dict[str, dict[str, int]]
    error_codes: dict[str, int]
    cleanup_failed: int
    not_analyzable_marked: int
    stopped: str | None
    gemini_cost_usd: float
    elapsed_s: float


def enqueue_targets(
    store: MediaStore,
    run_tag: str,
    *,
    brands: Collection[str] | None,
    sources: Collection[Source] | None,
    limit: int | None,
) -> list[Creative]:
    store = SerializedStore(store)
    targets = store.list_creatives(
        analyzable_only=True, brands=brands, sources=sources, limit=limit
    )
    store.enqueue_analysis(f"content_type@{run_tag}", targets)
    return targets


def _jobs(
    store: MediaStore, run: AnalysisRun, key: CreativeKey
) -> dict[str, JobResult]:
    return {
        axis: job
        for axis in AXES
        for job in store.get_job_results(f"{axis}@{run.run_tag}", [key])
    }


def _targets(
    store: MediaStore,
    run: AnalysisRun,
    limit: int,
    retry_failed: bool,
    only_keys: Collection[CreativeKey] | None,
) -> list[Creative]:
    if limit == 0:
        return []
    keys = set(only_keys) if only_keys is not None else None
    kind = f"content_type@{run.run_tag}"
    # Filter before truncation so a small pilot can select keys late in the queue.
    size = store.job_counts(kind).get("pending", 0) if keys is not None else limit
    candidates = store.next_pending(kind, size)
    if retry_failed:
        # Child jobs can remain after a previous content-type success. Only resume
        # a product with no terminal upstream failure; never reopen held jobs.
        for axis in AXES[1:]:
            kind = f"{axis}@{run.run_tag}"
            pending = store.next_pending(kind, store.job_counts(kind).get("pending", 0))
            for creative in pending:
                jobs = _jobs(store, run, creative.key)
                content = jobs.get("content_type")
                if content is None or content.status != JobStatus.done:
                    continue
                if any(
                    job.status in {JobStatus.held, JobStatus.failed}
                    for job in jobs.values()
                ):
                    continue
                if not is_product_target(
                    ContentTypeResult.model_validate(content.labels)
                ):
                    continue
                candidates.append(creative)
    selected = {}
    for creative in candidates:
        if keys is None or creative.key in keys:
            selected.setdefault(creative.key, creative)
        if len(selected) == limit:
            break
    return list(selected.values())


class _Replay:
    """Reuse completed axes and successful calls preceding a minute quota error.

    The existing media flow always starts at content_type. Replay its already
    validated labels through the injected interaction boundary, without another
    paid call. Per-attempt positions preserve ordinary schema-validation retries.
    """

    def __init__(self, run: AnalysisRun, jobs: dict[str, JobResult]):
        self._interact = run.interact
        self._done = {
            axis: job for axis, job in jobs.items() if job.status == JobStatus.done
        }
        self._responses: dict[str, list[InteractionResult]] = {}
        self._positions: Counter[str] = Counter()

    def reset(self) -> None:
        self._positions.clear()

    def __call__(self, **kwargs: Any) -> InteractionResult:
        properties = kwargs["response_format"]["schema"].get("properties", {})
        axis = (
            "content_type"
            if "content_type" in properties
            else "hook"
            if "hook_type" in properties
            else "full"
        )
        if axis in self._done:
            job = self._done[axis]
            return InteractionResult(
                json.dumps(job.labels),
                UsageInfo(job.model or ANALYSIS_MODEL_ID, 0, 0, 0, 0, 0.0),
                {},
            )
        position = self._positions[axis]
        self._positions[axis] += 1
        responses = self._responses.setdefault(axis, [])
        if position < len(responses):
            return responses[position]
        response = self._interact(**kwargs)
        # A retry may upload a new file. Do not replay an echo of the old URI.
        text = response.text
        for part in kwargs.get("input_parts", ()):
            uri = part.get("uri")
            if uri:
                text = text.replace(uri, "[redacted]")
        responses.append(response._replace(text=text, raw={}))
        return response


def _unexpected(
    creative: Creative, run: AnalysisRun, jobs: dict[str, JobResult]
) -> CreativeOutcome:
    axis = next(
        (
            axis
            for axis in AXES
            if axis not in jobs or jobs[axis].status != JobStatus.done
        ),
        "content_type",
    )
    return CreativeOutcome(
        key=creative.key,
        records=[
            AxisRecord(
                kind=f"{axis}@{run.run_tag}",
                status=JobStatus.failed,
                labels=None,
                model=None,
                thinking_level=run.thinking_level,
                prompt_version=None,
                raw_output=None,
                error_code="UNEXPECTED",
            )
        ],
        cleanup="none",
        mark_not_analyzable=False,
    )


class _Result(NamedTuple):
    creative: Creative
    outcome: CreativeOutcome | None
    stopped: str | None


def _process(
    creative: Creative,
    plan: UrlPlan,
    deps: AnalysisDeps,
    run: AnalysisRun,
    stop: Event,
) -> _Result:
    if stop.is_set():
        return _Result(creative, None, None)
    jobs = _jobs(deps.store, run, creative.key)
    replay = _Replay(run, jobs)
    try:
        rerefresh = deps.rerefresh(creative)
        for attempt in range(2):
            if stop.is_set():
                return _Result(creative, None, None)
            replay.reset()
            try:
                outcome = analyze_creative(
                    creative,
                    plan=plan,
                    run=run._replace(interact=replay),
                    media=deps.media,
                    rerefresh=rerefresh,
                )
                done_kinds = {
                    job.kind for job in jobs.values() if job.status == JobStatus.done
                }
                outcome.records = [
                    record
                    for record in outcome.records
                    if record.kind not in done_kinds
                ]
                # 이미 한 번 실패했던 작업이 재시도에서도 LLM_FATAL이면 영구 제외로 기록한다.
                prior = {job.kind: job.attempts for job in jobs.values()}
                outcome.records = [
                    record.model_copy(update={"error_code": LLM_FATAL_REPEATED})
                    if record.error_code == "LLM_FATAL"
                    and prior.get(record.kind, 0) >= 1
                    else record
                    for record in outcome.records
                ]
                return _Result(creative, outcome, None)
            except DailyLimitReached as exc:
                stop.set()
                reason = (
                    "CREDITS_DEPLETED"
                    if exc.kind == ErrorKind.CREDITS_DEPLETED
                    else "DAILY_LIMIT"
                )
                return _Result(creative, None, reason)
            except CostCapExceeded as exc:
                stop.set()
                return _Result(creative, None, f"COST_CAP:{exc.provider}")
            except LlmCallError as exc:
                if exc.kind != ErrorKind.RATE_LIMIT:
                    raise
                if attempt:
                    stop.set()
                    return _Result(creative, None, "RATE_LIMITED")
                deps.sleep(
                    min(
                        exc.retry_after_s if exc.retry_after_s is not None else 30.0,
                        RATE_LIMIT_WAIT_MAX_S,
                    )
                )
    except Exception:  # noqa: BLE001 -- isolate a creative, without logging unsafe text
        # Exception messages may contain URLs or file identifiers; never emit them.
        return _Result(creative, _unexpected(creative, run, jobs), None)
    raise AssertionError("unreachable")


def run_analysis(
    deps: AnalysisDeps,
    *,
    run: AnalysisRun,
    limit: int,
    concurrency: int = 1,
    retry_failed: bool = False,
    only_keys: Collection[CreativeKey] | None = None,
    out: TextIO,
) -> AnalysisReport:
    if not 1 <= concurrency <= MAX_CONCURRENCY:
        raise ValueError(f"concurrency must be between 1 and {MAX_CONCURRENCY}")
    if limit < 0:
        raise ValueError("limit must be nonnegative")
    deps = deps._replace(store=SerializedStore(deps.store))
    started = deps.now()
    initial_cost = provider_total(run.ledger_path, "gemini")
    if retry_failed:
        for axis in AXES:
            deps.store.requeue_jobs(f"{axis}@{run.run_tag}", RETRYABLE_ERROR_CODES)
    targets = _targets(deps.store, run, limit, retry_failed, only_keys)
    plans = deps.plans(targets) if targets else {}
    stop = Event()
    stopped = None
    processed = cleanup_failed = not_analyzable_marked = 0
    error_codes: Counter[str] = Counter()
    remaining = iter(targets)
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        inflight = set()
        while True:
            while not stop.is_set() and len(inflight) < concurrency:
                creative = next(remaining, None)
                if creative is None:
                    break
                default = UrlPlan(
                    None, "none" if creative.source == Source.youtube else "missing"
                )
                inflight.add(
                    pool.submit(
                        _process,
                        creative,
                        plans.get(creative.key, default),
                        deps,
                        run,
                        stop,
                    )
                )
            if not inflight:
                break
            finished, inflight = wait(inflight, return_when=FIRST_COMPLETED)
            for future in finished:
                result = future.result()
                if result.stopped is not None:
                    stopped = stopped or result.stopped
                outcome = result.outcome
                if outcome is not None:
                    apply_outcome(deps.store, result.creative, outcome)
                    processed += 1
                    cleanup_failed += outcome.cleanup == "delete_failed"
                    not_analyzable_marked += outcome.mark_not_analyzable
                    error_codes.update(
                        record.error_code
                        for record in outcome.records
                        if record.error_code is not None
                    )
                if outcome is not None or result.stopped is not None:
                    records = outcome.records if outcome is not None else []
                    out.write(
                        json.dumps(
                            {
                                "event": "creative_analysis",
                                "source": result.creative.source.value,
                                "brand": result.creative.brand,
                                "account": result.creative.account,
                                "kinds": [record.kind for record in records],
                                "status": {
                                    record.kind: record.status.value
                                    for record in records
                                },
                                "error_code": {
                                    record.kind: record.error_code for record in records
                                },
                            }
                        )
                        + "\n"
                    )
    report = AnalysisReport(
        processed=processed,
        by_status={
            axis: deps.store.job_counts(f"{axis}@{run.run_tag}") for axis in AXES
        },
        error_codes=dict(error_codes),
        cleanup_failed=cleanup_failed,
        not_analyzable_marked=not_analyzable_marked,
        stopped=stopped,
        gemini_cost_usd=provider_total(run.ledger_path, "gemini") - initial_cost,
        elapsed_s=(deps.now() - started).total_seconds(),
    )
    out.write(report.model_dump_json() + "\n")
    return report
