"""Batch scheduling and reporting with synthetic stores, media, and costs only."""

import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from io import StringIO
from threading import Barrier, Event, Lock
from time import sleep
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from beautyads.domain import (
    AnalysisRepository,
    Category,
    ContentType,
    Creative,
    CreativeRepository,
    HookType,
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
from beautyads.obs.ledger import LedgerEntry, append_entry
from beautyads.pipeline import analyze as runner
from beautyads.pipeline.media_flow import (
    RETRYABLE_ERROR_CODES,
    AnalysisRun,
    AxisRecord,
    CreativeOutcome,
    MediaDeps,
    UrlPlan,
)

NOW = datetime(2026, 11, 12, tzinfo=UTC)
MEDIA_SENTINEL = "https://example.invalid/PRIVATE_VIDEO_SENTINEL"
FILE_SENTINEL = "https://example.invalid/PRIVATE_FILE_SENTINEL"


def creative(index, **kwargs):
    return Creative(
        source=Source.youtube,
        source_id=str(index),
        url="https://example.invalid/public-video",
        collected_at=NOW,
        analyzable=True,
        brand="synthetic-brand",
        account="synthetic-account",
        **kwargs,
    )


class Store:
    def __init__(self, creatives):
        self.creatives = {item.key: item for item in creatives}
        self.jobs = {}
        self.requeues = []
        self.records = []

    def upsert_creatives(self, creatives):
        self.creatives.update((item.key, item) for item in creatives)
        return len(creatives)

    def get_creative(self, key):
        return self.creatives.get(key)

    def collection_stats(self):
        return []

    def list_creatives(
        self, *, brands=None, sources=None, analyzable_only=False, limit=None
    ):
        return [
            item
            for item in self.creatives.values()
            if (not analyzable_only or item.analyzable is True)
            and (brands is None or item.brand in brands)
            and (sources is None or item.source in sources)
        ][:limit]

    def enqueue_analysis(self, kind, creatives):
        added = 0
        for item in creatives:
            if item.analyzable is True and (kind, item.key) not in self.jobs:
                self.jobs[kind, item.key] = JobResult(
                    key=item.key,
                    kind=kind,
                    status=JobStatus.pending,
                    labels=None,
                    error_code=None,
                    model=None,
                    thinking_level=None,
                    prompt_version=None,
                    raw_output=None,
                    attempts=0,
                    updated_at=None,
                )
                added += 1
        return added

    def next_pending(self, kind, limit):
        return [
            self.creatives[key]
            for (job_kind, key), job in self.jobs.items()
            if job_kind == kind and job.status == JobStatus.pending
        ][:limit]

    def requeue_jobs(self, kind, error_codes):
        self.requeues.append((kind, error_codes))
        count = 0
        for (job_kind, _), job in self.jobs.items():
            if (
                job_kind == kind
                and job.status == JobStatus.failed
                and job.error_code in error_codes
            ):
                job.status = JobStatus.pending
                count += 1
        return count

    def job_counts(self, kind):
        counts = dict.fromkeys((status.value for status in JobStatus), 0)
        for (job_kind, _), job in self.jobs.items():
            if job_kind == kind:
                counts[job.status.value] += 1
        return counts

    def get_job_results(self, kind, keys):
        return [
            job
            for (job_kind, key), job in self.jobs.items()
            if job_kind == kind and key in keys
        ]

    def record_analysis(self, kind, key, **kwargs):
        job = self.jobs[kind, key]
        self.jobs[kind, key] = job.model_copy(
            update={**kwargs, "attempts": job.attempts + 1}
        )
        self.records.append((kind, key, kwargs))


def outcome(item, run, status=JobStatus.done, code=None, *, cleanup="none", mark=False):
    return CreativeOutcome(
        key=item.key,
        records=[
            AxisRecord(
                kind=f"content_type@{run.run_tag}",
                status=status,
                labels=None,
                model=None,
                thinking_level=run.thinking_level,
                prompt_version=None,
                raw_output=None,
                error_code=code,
            )
        ],
        cleanup=cleanup,
        mark_not_analyzable=mark,
    )


@pytest.fixture
def rig(tmp_path, monkeypatch):
    items = [creative(index) for index in range(8)]
    store = Store(items)
    runner.enqueue_targets(store, "test", brands=None, sources=None, limit=None)
    run = AnalysisRun(
        "minimal",
        "test",
        "test-batch",
        tmp_path / "costs.jsonl",
        {"gemini": 12},
        12,
        60,
        3,
        Mock(),
    )
    fake = Mock(side_effect=lambda item, **kw: outcome(item, run))
    monkeypatch.setattr(runner, "analyze_creative", fake)
    plans = Mock(
        side_effect=lambda items: {
            item.key: UrlPlan(MEDIA_SENTINEL, "ok") for item in items
        }
    )
    deps = runner.AnalysisDeps(
        store,
        MediaDeps(*(Mock() for _ in range(4))),
        plans,
        Mock(return_value=None),
        Mock(),
        Mock(side_effect=[NOW, NOW + timedelta(seconds=9)]),
    )
    return SimpleNamespace(
        items=items, store=store, run=run, fake=fake, deps=deps, out=StringIO()
    )


def execute(rig, **kwargs):
    return runner.run_analysis(
        rig.deps, run=rig.run, limit=kwargs.pop("limit", 8), out=rig.out, **kwargs
    )


def set_job(
    rig,
    item,
    axis="content_type",
    status=JobStatus.failed,
    code="LLM_RETRYABLE",
    labels=None,
):
    kind = f"{axis}@test"
    rig.store.enqueue_analysis(kind, [item])
    job = rig.store.jobs[kind, item.key]
    job.status, job.error_code, job.labels = status, code, labels
    return job


@pytest.mark.parametrize("retry", [False, True])
def test_requeue_only_selected_failures_and_never_held(rig, retry):
    set_job(rig, rig.items[0])
    set_job(rig, rig.items[1], status=JobStatus.held)
    set_job(rig, rig.items[2], code="PERMANENT")
    report = execute(rig, retry_failed=retry)
    assert rig.store.requeues == (
        [(f"{axis}@test", RETRYABLE_ERROR_CODES) for axis in runner.AXES]
        if retry
        else []
    )
    keys = {call.args[0].key for call in rig.fake.call_args_list}
    assert (rig.items[0].key in keys) == retry
    assert rig.items[1].key not in keys and rig.items[2].key not in keys
    assert report.processed == 5 + int(retry)
    assert (
        rig.store.jobs["content_type@test", rig.items[1].key].status == JobStatus.held
    )


def test_failures_are_isolated_and_unexpected_is_sanitized(rig):
    def analyze(item, **kwargs):
        if item.key == rig.items[0].key:
            return outcome(item, rig.run, JobStatus.failed, "LLM_RETRYABLE")
        if item.key == rig.items[1].key:
            return outcome(item, rig.run, JobStatus.held, "INVALID_OUTPUT")
        if item.key == rig.items[2].key:
            raise RuntimeError(MEDIA_SENTINEL + FILE_SENTINEL)
        return outcome(item, rig.run, cleanup="delete_failed", mark=True)

    rig.fake.side_effect = analyze
    report = execute(rig)
    assert report.processed == 8 and report.stopped is None
    assert report.error_codes == {
        "LLM_RETRYABLE": 1,
        "INVALID_OUTPUT": 1,
        "UNEXPECTED": 1,
    }
    assert report.cleanup_failed == 5 and report.not_analyzable_marked == 5
    assert all(not rig.store.creatives[item.key].analyzable for item in rig.items[3:])
    assert (
        rig.store.jobs["content_type@test", rig.items[2].key].error_code == "UNEXPECTED"
    )
    assert (
        MEDIA_SENTINEL not in rig.out.getvalue()
        and FILE_SENTINEL not in rig.out.getvalue()
    )


def daily():
    return DailyLimitReached(kind=ErrorKind.DAILY_LIMIT, code="DAILY_LIMIT")


def credits():
    return DailyLimitReached(kind=ErrorKind.CREDITS_DEPLETED, code="CREDITS_DEPLETED")


def rate(wait=None):
    return LlmCallError(
        kind=ErrorKind.RATE_LIMIT, code="RATE_LIMIT", retry_after_s=wait
    )


@pytest.mark.parametrize(
    ("error", "stop"),
    [
        (daily(), "DAILY_LIMIT"),
        (credits(), "CREDITS_DEPLETED"),
        (CostCapExceeded("gemini", 12, 12), "COST_CAP:gemini"),
        (rate(), "RATE_LIMITED"),
    ],
)
def test_limits_stop_without_recording_or_starting_more(rig, error, stop):
    rig.fake.side_effect = error
    report = execute(rig)
    assert report.stopped == stop and report.processed == 0
    assert rig.fake.call_count == (2 if stop == "RATE_LIMITED" else 1)
    assert rig.store.records == []
    assert rig.store.job_counts("content_type@test")["pending"] == 8
    if stop != "RATE_LIMITED":
        rig.deps.sleep.assert_not_called()


@pytest.mark.parametrize(
    ("retry_after", "wait"),
    [(None, 30), (0, 0), (7, 7), (999, runner.RATE_LIMIT_WAIT_MAX_S)],
)
def test_rate_limit_waits_once_then_continues_same_creative(rig, retry_after, wait):
    counts = Counter()

    def analyze(item, **kwargs):
        counts[item.key] += 1
        if item.key == rig.items[0].key and counts[item.key] == 1:
            raise rate(retry_after)
        return outcome(item, rig.run)

    rig.fake.side_effect = analyze
    report = execute(rig)
    rig.deps.sleep.assert_called_once_with(wait)
    assert report.processed == 8 and report.stopped is None
    assert counts == Counter(
        {item.key: 2 if item == rig.items[0] else 1 for item in rig.items}
    )


@pytest.mark.parametrize("concurrency", [0, runner.MAX_CONCURRENCY + 1])
def test_invalid_concurrency(rig, concurrency):
    with pytest.raises(ValueError):
        execute(rig, concurrency=concurrency)
    rig.fake.assert_not_called()
    rig.deps.plans.assert_not_called()


@pytest.mark.parametrize("concurrency", [1, 2, runner.MAX_CONCURRENCY])
def test_bounded_concurrency_and_record_set(rig, concurrency):
    barrier = Barrier(concurrency)
    lock = Lock()
    active = maximum = 0

    def analyze(item, **kwargs):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(active, maximum)
        barrier.wait(timeout=5)
        sleep(0.005)
        with lock:
            active -= 1
        return outcome(item, rig.run)

    rig.fake.side_effect = analyze
    report = execute(rig, concurrency=concurrency)
    assert maximum == concurrency
    assert report.processed == len(rig.items)
    assert {key for _, key, _ in rig.store.records} == {item.key for item in rig.items}
    assert len(rig.store.records) == 8


def test_all_repository_methods_share_one_lock():
    names = {
        name
        for protocol in (CreativeRepository, AnalysisRepository)
        for name, method in vars(protocol).items()
        if not name.startswith("_") and callable(method)
    }
    lock = Lock()
    active = maximum = 0
    calls = Counter()

    class Probe:
        def __getattr__(self, name):
            def call(*args, **kwargs):
                nonlocal active, maximum
                with lock:
                    active += 1
                    maximum = max(maximum, active)
                    calls[name] += 1
                sleep(0.002)
                with lock:
                    active -= 1
                return name, args, kwargs

            return call

    store = runner.SerializedStore(Probe())
    barrier = Barrier(4)

    def exercise(_):
        barrier.wait(timeout=5)
        return [getattr(store, name)("argument", option=True) for name in names]

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(exercise, range(4)))
    assert maximum == 1 and calls == Counter({name: 4 for name in names})
    assert all({name for name, _, _ in result} == names for result in results)
    assert all(
        args == ("argument",) and kwargs == {"option": True}
        for result in results
        for _, args, kwargs in result
    )


def test_parallel_stop_drains_inflight_without_starting_new(rig):
    barrier = Barrier(2)
    stopped = Event()

    def analyze(item, **kwargs):
        barrier.wait(timeout=5)
        if item.key == rig.items[0].key:
            stopped.set()
            raise daily()
        assert stopped.wait(timeout=5)
        sleep(0.02)
        return outcome(item, rig.run)

    rig.fake.side_effect = analyze
    report = execute(rig, concurrency=2)
    assert report.stopped == "DAILY_LIMIT" and report.processed == 1
    assert {call.args[0].key for call in rig.fake.call_args_list} == {
        item.key for item in rig.items[:2]
    }
    assert rig.store.job_counts("content_type@test")["pending"] == 7


def test_only_keys_filters_before_limit_and_keeps_other_pending(rig):
    selected = {item.key for item in rig.items[4:]}
    report = execute(rig, only_keys=selected, limit=2)
    keys = {call.args[0].key for call in rig.fake.call_args_list}
    assert keys <= selected and len(keys) == report.processed == 2
    assert all(
        job.status == JobStatus.pending
        for (_, key), job in rig.store.jobs.items()
        if key not in keys
    )


def test_empty_only_keys_never_analyzes(rig):
    assert execute(rig, only_keys=[]).processed == 0
    rig.fake.assert_not_called()


def test_second_run_skips_done_and_refreshes_only_new_batch(rig):
    execute(rig, limit=2)
    first = {call.args[0].key for call in rig.fake.call_args_list}
    rig.fake.reset_mock()
    rig.deps.now.side_effect = [NOW, NOW]
    report = execute(rig)
    second = {call.args[0].key for call in rig.fake.call_args_list}
    assert first.isdisjoint(second) and len(second) == report.processed == 6
    assert len(rig.deps.plans.call_args_list) == 2
    assert [
        {item.key for item in call.args[0]} for call in rig.deps.plans.call_args_list
    ] == [first, second]


def test_json_report_counts_and_ledger_delta(rig):
    def add_cost(provider, cost):
        append_entry(
            rig.run.ledger_path,
            LedgerEntry(
                ts=NOW,
                provider=provider,
                model="synthetic",
                purpose="test",
                cost_usd=cost,
                cost_source="computed",
            ),
        )

    add_cost("gemini", 1.0)
    add_cost("openai", 5.0)

    def analyze(item, **kwargs):
        add_cost("gemini", 0.125)
        return outcome(item, rig.run)

    rig.fake.side_effect = analyze
    report = execute(rig)
    assert report.gemini_cost_usd == 1.0 and report.elapsed_s == 9
    assert report.by_status == {
        axis: rig.store.job_counts(f"{axis}@test") for axis in runner.AXES
    }
    lines = [json.loads(line) for line in rig.out.getvalue().splitlines()]
    assert lines[-1]["processed"] == report.processed
    assert len(lines) == report.processed + 1
    for line in lines[:-1]:
        assert {
            "event",
            "source",
            "brand",
            "account",
            "kinds",
            "status",
            "error_code",
        } <= line.keys()
    assert (
        MEDIA_SENTINEL not in rig.out.getvalue()
        and FILE_SENTINEL not in rig.out.getvalue()
    )


def test_enqueue_eligible_filters_and_idempotency():
    items = [creative(i) for i in range(3)]
    items[1].analyzable = False
    items[2].analyzable = None
    store = Store(items)
    for _ in range(2):
        assert runner.enqueue_targets(
            store, "tag", brands={"synthetic-brand"}, sources={Source.youtube}, limit=2
        ) == [items[0]]
    assert len(store.jobs) == 1
    assert (
        runner.enqueue_targets(store, "tag", brands=[], sources=None, limit=None) == []
    )


def content_labels():
    return {
        "content_type": ContentType.product_creative.value,
        "category": next(
            category for category in Category if category != Category.other
        ).value,
    }


def interaction(payload):
    return InteractionResult(
        json.dumps(payload), UsageInfo("gemini-3.6-flash", 0, 0, 0, 0, 0.0), {}
    )


@pytest.mark.parametrize("axis", ["hook", "full"])
@pytest.mark.parametrize("retry", [False, True])
def test_resume_child_jobs_without_recalling_done_axes(rig, monkeypatch, axis, retry):
    from beautyads.pipeline.media_flow import analyze_creative

    monkeypatch.setattr(runner, "analyze_creative", analyze_creative)
    item = rig.items[0]
    set_job(rig, item, status=JobStatus.done, code=None, labels=content_labels())
    hook_labels = {"hook_type": next(iter(HookType)).value}
    if axis == "full":
        set_job(
            rig, item, axis="hook", status=JobStatus.done, code=None, labels=hook_labels
        )
    set_job(rig, item, axis=axis)
    seen = []

    def interact(**kwargs):
        properties = kwargs["response_format"]["schema"]["properties"]
        assert "content_type" not in properties
        seen.append(set(properties))
        if axis == "hook":
            assert "hook_type" in properties
        else:
            assert "angle" in properties
        # An invalid output is held after schema validation; its wording is immaterial.
        return interaction({})

    run = rig.run._replace(interact=interact)
    deps = rig.deps._replace(plans=Mock(return_value={item.key: UrlPlan(None, "none")}))
    report = runner.run_analysis(
        deps, run=run, limit=1, retry_failed=retry, only_keys=[item.key], out=rig.out
    )
    assert report.processed == int(retry)
    assert len(seen) == (2 if retry else 0)
    assert rig.store.jobs["content_type@test", item.key].attempts == 0
    if axis == "full":
        assert rig.store.jobs["hook@test", item.key].attempts == 0


def test_rate_retry_does_not_pay_twice_for_completed_content(rig, monkeypatch):
    from beautyads.pipeline.media_flow import analyze_creative

    monkeypatch.setattr(runner, "analyze_creative", analyze_creative)
    calls = Counter()

    def interact(**kwargs):
        properties = kwargs["response_format"]["schema"]["properties"]
        axis = "content_type" if "content_type" in properties else "hook"
        calls[axis] += 1
        if axis == "content_type":
            return interaction(content_labels())
        if calls[axis] == 1:
            raise rate(2)
        return interaction({})

    deps = rig.deps._replace(
        plans=Mock(return_value={rig.items[0].key: UrlPlan(None, "none")})
    )
    report = runner.run_analysis(
        deps, run=rig.run._replace(interact=interact), limit=1, out=rig.out
    )
    assert calls == {"content_type": 1, "hook": 3}
    assert report.processed == 1 and report.stopped is None
    rig.deps.sleep.assert_called_once_with(2)


def test_empty_or_zero_limit_does_not_plan_media(rig):
    assert execute(rig, limit=0).processed == 0
    rig.deps.plans.assert_not_called()


def test_repeated_llm_fatal_becomes_a_permanent_exclusion_reason(rig):
    # A first LLM_FATAL stays retryable; failing the same way again after a retry is
    # recorded as a permanent exclusion so --retry-failed never requeues it again.
    repeated, first = rig.items[0], rig.items[1]
    job = set_job(rig, repeated, code="LLM_FATAL")
    job.attempts = 1

    def analyze(item, **kwargs):
        return outcome(item, rig.run, JobStatus.failed, "LLM_FATAL")

    rig.fake.side_effect = analyze
    report = execute(rig, retry_failed=True, only_keys={repeated.key, first.key})
    codes = {
        key.source_id: rig.store.jobs["content_type@test", key].error_code
        for key in (repeated.key, first.key)
    }
    assert codes[repeated.source_id] == "LLM_FATAL_REPEATED"
    assert codes[first.source_id] == "LLM_FATAL"
    assert "LLM_FATAL_REPEATED" not in RETRYABLE_ERROR_CODES
    assert report.error_codes["LLM_FATAL_REPEATED"] == 1
    # the permanent one is not requeued by another retry
    rig.store.jobs["content_type@test", first.key].status = JobStatus.done
    assert rig.store.requeue_jobs("content_type@test", RETRYABLE_ERROR_CODES) == 0
