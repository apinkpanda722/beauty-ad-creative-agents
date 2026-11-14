"""Transient media orchestration uses only synthetic data and injected fakes."""

import json
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from beautyads.analysis.models import ANALYSIS_MODEL_ID, PROMPT_VERSIONS
from beautyads.domain import (
    Angle,
    Category,
    Claim,
    ContentType,
    Creative,
    CtaType,
    Format,
    HookType,
    JobStatus,
    PlatformFitFlags,
    Source,
    StructureFlags,
    Talent,
)
from beautyads.llm import (
    CostCapExceeded,
    DailyLimitReached,
    ErrorKind,
    FileError,
    InteractionResult,
    LlmCallError,
    UploadedFile,
    UsageInfo,
)
from beautyads.pipeline.media_flow import (
    RETRYABLE_ERROR_CODES,
    AnalysisRun,
    MediaDeps,
    UrlPlan,
    analyze_creative,
    apply_outcome,
    prepare_instagram_plans,
)
from beautyads.sources.config import InstagramAccount
from beautyads.sources.instagram import RefreshResult
from beautyads.sources.media import DownloadedMedia, MediaError

MEDIA_URL = "https://example.invalid/TRANSIENT_VIDEO_SENTINEL?oe=ffffffff"
FILE_ID = "https://example.invalid/UPLOADED_FILE_SENTINEL"


def creative(source_id="post", **overrides):
    return Creative.model_validate(
        {
            "source": Source.instagram,
            "source_id": source_id,
            "url": "https://example.invalid/public-post",
            "account": "account-a",
            "analyzable": True,
            "duration_s": 45.0,
            "collected_at": datetime(2026, 11, 12, tzinfo=UTC),
            **overrides,
        }
    )


def content_payload(content_type=ContentType.product_creative, category=None):
    return {
        "content_type": content_type.value,
        "category": (category or next(iter(Category))).value,
    }


def full_payload():
    return {
        "angle": next(iter(Angle)).value,
        "format": next(iter(Format)).value,
        "talent": next(iter(Talent)).value,
        "cta_type": next(iter(CtaType)).value,
        "claims": [member.value for member in Claim],
        "ingredients": ["  합성 성분 원문  "],
        "structure": {name: False for name in StructureFlags.model_fields},
        "platform_fit": {name: False for name in PlatformFitFlags.model_fields},
    }


def responses():
    return [
        content_payload(),
        {"hook_type": next(iter(HookType)).value},
        full_payload(),
    ]


class FakeInteract:
    def __init__(self, replies=None, events=None):
        self.replies = iter(responses() if replies is None else replies)
        self.events = events if events is not None else []
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        self.events.append("interact")
        response = next(self.replies)
        if isinstance(response, BaseException):
            raise response
        text = response if isinstance(response, str) else json.dumps(response)
        return InteractionResult(
            text, UsageInfo(ANALYSIS_MODEL_ID, 0, 0, 0, 0, 0.0), {}
        )


class FakeMedia:
    def __init__(
        self,
        *,
        events=None,
        downloads=None,
        upload_error=None,
        wait_error=None,
        deleted=True,
    ):
        self.events = events if events is not None else []
        self.downloads = iter(downloads) if downloads is not None else None
        self.upload_error = upload_error
        self.wait_error = wait_error
        self.deleted = deleted
        self.download_urls = []
        self.delete_ids = []

    def download(self, url):
        self.events.append("download")
        self.download_urls.append(url)
        value = next(self.downloads) if self.downloads is not None else downloaded()
        if isinstance(value, BaseException):
            raise value
        return value

    def upload(self, data, *, filename):
        self.events.append("upload")
        assert data == b"synthetic-video"
        assert filename.endswith(".mp4")
        assert MEDIA_URL not in filename and FILE_ID not in filename
        if self.upload_error is not None:
            raise self.upload_error
        return UploadedFile(FILE_ID, len(data))

    def wait(self, file_id):
        self.events.append("wait")
        assert file_id == FILE_ID
        if self.wait_error is not None:
            raise self.wait_error

    def delete(self, file_id):
        self.events.append("delete")
        self.delete_ids.append(file_id)
        return self.deleted

    def deps(self):
        return MediaDeps(self.download, self.upload, self.wait, self.delete)


def downloaded():
    return DownloadedMedia(b"synthetic-video", "video/mp4", 15)


@pytest.fixture
def run(tmp_path):
    return AnalysisRun(
        thinking_level="minimal",
        run_tag="synthetic-tag",
        purpose="test-media",
        ledger_path=tmp_path / "costs.jsonl",
        caps={"gemini": 12.0},
        content_type_window_s=12.0,
        full_window_s=40.0,
        hook_window_max_s=9.0,
        interact=FakeInteract(),
    )


def analyze(run, fake, **kwargs):
    return analyze_creative(
        creative(), plan=UrlPlan(MEDIA_URL, "ok"), run=run, media=fake.deps(), **kwargs
    )


@pytest.mark.parametrize("deleted", [True, False])
def test_product_success_and_delete_result(run, deleted):
    fake = FakeMedia(deleted=deleted)
    result = analyze(run, fake)
    assert result.key == creative().key
    assert result.mark_not_analyzable is False
    assert result.cleanup == ("deleted" if deleted else "delete_failed")
    assert [record.kind for record in result.records] == [
        f"{axis}@{run.run_tag}" for axis in ("content_type", "hook", "full")
    ]
    for axis, record, labels in zip(
        ("content_type", "hook", "full"), result.records, responses()
    ):
        assert record.status == JobStatus.done
        assert record.labels == labels
        assert json.loads(record.raw_output) == labels
        assert record.prompt_version == PROMPT_VERSIONS[axis]
        assert record.model == ANALYSIS_MODEL_ID
        assert record.thinking_level == run.thinking_level
        assert record.error_code is None
    assert fake.events == ["download", "upload", "wait", "delete"]
    assert fake.delete_ids == [FILE_ID]


@pytest.mark.parametrize("stage", range(3))
@pytest.mark.parametrize("failure", ["held", "failed"])
def test_axis_failure_stops_later_axes_and_deletes(run, stage, failure):
    replies = responses()[:stage]
    if failure == "held":
        replies += ["invalid", "invalid"]
    else:
        replies += [LlmCallError(kind=ErrorKind.RETRYABLE, code="UNAVAILABLE")]
    fake = FakeMedia()
    interact = FakeInteract(replies)
    result = analyze(run._replace(interact=interact), fake)
    assert len(result.records) == stage + 1
    assert all(record.status == JobStatus.done for record in result.records[:stage])
    assert result.records[-1].status == JobStatus(failure)
    assert result.records[-1].error_code == (
        "INVALID_OUTPUT" if failure == "held" else "LLM_RETRYABLE"
    )
    assert len(interact.calls) == stage + (2 if failure == "held" else 1)
    assert fake.delete_ids == [FILE_ID]
    assert result.cleanup == "deleted"


STOP_ERRORS = [
    DailyLimitReached(kind=ErrorKind.DAILY_LIMIT, code="DAILY_LIMIT"),
    CostCapExceeded("gemini", 12.0, 12.0),
    LlmCallError(kind=ErrorKind.RATE_LIMIT, code="RATE_LIMITED"),
    RuntimeError("synthetic failure"),
    KeyboardInterrupt(),
]


@pytest.mark.parametrize("stage", range(3))
@pytest.mark.parametrize("error", STOP_ERRORS)
@pytest.mark.parametrize("deleted", [True, False])
def test_exceptions_propagate_only_after_exactly_one_delete(run, stage, error, deleted):
    events = []
    fake = FakeMedia(events=events, deleted=deleted)
    interact = FakeInteract(responses()[:stage] + [error], events=events)
    store = Mock()
    with pytest.raises(type(error)) as caught:
        try:
            outcome = analyze(run._replace(interact=interact), fake)
            apply_outcome(store, creative(), outcome)
        except BaseException:
            events.append("propagated")
            raise
    assert caught.value is error
    assert events == ["download", "upload", "wait"] + ["interact"] * (stage + 1) + [
        "delete",
        "propagated",
    ]
    assert fake.delete_ids == [FILE_ID]
    assert store.mock_calls == []


@pytest.mark.parametrize(
    "code,status",
    [
        ("FILE_STATUS_ERROR", JobStatus.held),
        ("FILE_PROCESS_TIMEOUT", JobStatus.failed),
        ("FILE_RETRIEVE_FAILED", JobStatus.failed),
    ],
)
def test_wait_file_error_still_deletes(run, code, status):
    fake = FakeMedia(wait_error=FileError(code))
    result = analyze(run, fake)
    assert fake.events == ["download", "upload", "wait", "delete"]
    assert fake.delete_ids == [FILE_ID]
    assert result.cleanup == "deleted"
    assert len(result.records) == 1
    assert result.records[0].status == status
    assert result.records[0].error_code == code
    assert run.interact.calls == []


@pytest.mark.parametrize(
    "error,status",
    [
        (FileError("EMPTY_FILE"), JobStatus.held),
        (FileError("FILE_UPLOAD_FAILED"), JobStatus.failed),
    ],
)
def test_upload_error_does_not_delete(run, error, status):
    fake = FakeMedia(upload_error=error)
    result = analyze(run, fake)
    assert fake.events == ["download", "upload"]
    assert fake.delete_ids == []
    assert result.cleanup == "none"
    assert result.records[0].status == status
    assert result.records[0].error_code == error.code
    assert run.interact.calls == []


@pytest.mark.parametrize("error", STOP_ERRORS)
def test_unexpected_wait_exception_also_deletes(run, error):
    fake = FakeMedia(wait_error=error)
    with pytest.raises(type(error)) as caught:
        analyze(run, fake)
    assert caught.value is error
    assert fake.events == ["download", "upload", "wait", "delete"]
    assert fake.delete_ids == [FILE_ID]


@pytest.mark.parametrize(
    "state,url,status,code,mark",
    [
        ("gone", None, JobStatus.held, "MEDIA_URL_GONE", True),
        ("missing", None, JobStatus.failed, "MEDIA_URL_MISSING", False),
        ("missing", MEDIA_URL, JobStatus.failed, "MEDIA_URL_MISSING", False),
        ("ok", None, JobStatus.failed, "MEDIA_URL_MISSING", False),
        ("ok", "", JobStatus.failed, "MEDIA_URL_MISSING", False),
    ],
)
def test_unavailable_plan_does_not_call_media(run, state, url, status, code, mark):
    fake = FakeMedia()
    result = analyze_creative(
        creative(), plan=UrlPlan(url, state), run=run, media=fake.deps()
    )
    assert fake.events == []
    assert run.interact.calls == []
    assert result.cleanup == "none"
    assert result.mark_not_analyzable is mark
    assert len(result.records) == 1
    record = result.records[0]
    assert record.kind == f"content_type@{run.run_tag}"
    assert record.status == status and record.error_code == code
    assert record.labels is record.model is record.raw_output is None
    assert code not in RETRYABLE_ERROR_CODES


def test_stopped_refresh_plan_is_a_retryable_failure_without_unmarking(run):
    fake = FakeMedia()
    result = analyze_creative(
        creative(), plan=UrlPlan(None, "refresh_stopped"), run=run, media=fake.deps()
    )
    assert fake.events == [] and run.interact.calls == []
    assert result.mark_not_analyzable is False
    record = result.records[0]
    assert record.kind == f"content_type@{run.run_tag}"
    assert record.status == JobStatus.failed
    assert record.error_code == "MEDIA_REFRESH_STOPPED"
    assert record.error_code in RETRYABLE_ERROR_CODES
    assert "MEDIA_URL_MISSING" not in RETRYABLE_ERROR_CODES


def test_tiktok_without_plan_url_stays_missing(run):
    fake = FakeMedia()
    result = analyze_creative(
        creative(source=Source.tiktok),
        plan=UrlPlan(None, "missing"),
        run=run,
        media=fake.deps(),
    )
    assert result.records[0].error_code == "MEDIA_URL_MISSING"
    assert fake.events == []


@pytest.mark.parametrize(
    "code,status,retryable",
    [
        ("MEDIA_NOT_VIDEO", JobStatus.held, False),
        ("MEDIA_EMPTY", JobStatus.held, False),
        ("MEDIA_REQUEST_FAILED", JobStatus.failed, True),
        ("MEDIA_TRUNCATED", JobStatus.failed, True),
        ("MEDIA_HTTP_500", JobStatus.failed, False),
        ("MEDIA_TOO_LARGE", JobStatus.failed, False),
    ],
)
def test_download_error_records_only_content_type(run, code, status, retryable):
    fake = FakeMedia(downloads=[MediaError(code)])
    refresh = Mock()
    result = analyze(run, fake, rerefresh=refresh)
    assert fake.events == ["download"]
    assert run.interact.calls == []
    refresh.assert_not_called()
    assert len(result.records) == 1
    assert result.records[0].status == status
    assert result.records[0].error_code == code
    assert result.cleanup == "none"
    assert result.mark_not_analyzable is False
    assert (code in RETRYABLE_ERROR_CODES) is retryable


@pytest.mark.parametrize(
    "second",
    [
        None,
        downloaded(),
        MediaError("MEDIA_URL_UNAVAILABLE"),
        MediaError("MEDIA_REQUEST_FAILED"),
    ],
)
def test_unavailable_download_refreshes_at_most_once(run, second):
    fake = FakeMedia(downloads=[MediaError("MEDIA_URL_UNAVAILABLE"), second])
    new_url = "https://example.invalid/NEW_TRANSIENT_SENTINEL"
    refresh = Mock(return_value=None if second is None else new_url)
    result = analyze(run, fake, rerefresh=refresh)
    refresh.assert_called_once_with()
    assert fake.download_urls == (
        [MEDIA_URL] if second is None else [MEDIA_URL, new_url]
    )
    if isinstance(second, DownloadedMedia):
        assert len(result.records) == 3
        assert fake.delete_ids == [FILE_ID]
    else:
        assert result.records[0].status == JobStatus.held
        assert result.records[0].error_code == "MEDIA_UNAVAILABLE"
        assert len(result.records) == 1
        assert result.mark_not_analyzable is False
        assert fake.delete_ids == []


def test_unavailable_without_refresh_is_held(run):
    result = analyze(run, FakeMedia(downloads=[MediaError("MEDIA_URL_UNAVAILABLE")]))
    assert result.records[0].status == JobStatus.held
    assert result.records[0].error_code == "MEDIA_UNAVAILABLE"


def test_retryable_codes_exclude_every_held_code():
    assert RETRYABLE_ERROR_CODES == frozenset(
        {
            "MEDIA_REQUEST_FAILED",
            "MEDIA_TRUNCATED",
            "FILE_UPLOAD_FAILED",
            "FILE_PROCESS_TIMEOUT",
            "FILE_RETRIEVE_FAILED",
            "LLM_RETRYABLE",
            "LLM_FATAL",  # 2026-11-14: 일시 오류로 확인돼 재시도 대상에 추가
            "MEDIA_REFRESH_STOPPED",
        }
    )
    assert RETRYABLE_ERROR_CODES.isdisjoint(
        {
            "MEDIA_NOT_VIDEO",
            "MEDIA_EMPTY",
            "MEDIA_UNAVAILABLE",
            "MEDIA_URL_GONE",
            "FILE_STATUS_ERROR",
            "EMPTY_FILE",
            "INVALID_OUTPUT",
            "MEDIA_URL_MISSING",
        }
    )


@pytest.mark.parametrize("content_type", list(ContentType))
@pytest.mark.parametrize("category", list(Category))
def test_product_gate_uses_domain_combinations(run, content_type, category):
    payload = content_payload(content_type, category)
    target = content_type == ContentType.product_creative and category != Category.other
    interact = FakeInteract([payload] + responses()[1:] if target else [payload])
    fake = FakeMedia()
    result = analyze(run._replace(interact=interact), fake)
    assert result.records[0].labels == payload
    assert all(record.status == JobStatus.done for record in result.records)
    assert len(result.records) == len(interact.calls) == (3 if target else 1)
    assert fake.delete_ids == [FILE_ID]


@pytest.mark.parametrize("member", list(HookType))
def test_hook_labels_preserve_each_enum_member(run, member):
    replies = responses()
    replies[1] = {"hook_type": member.value}
    result = analyze(run._replace(interact=FakeInteract(replies)), FakeMedia())
    assert result.records[1].labels == replies[1]


@pytest.mark.parametrize("hook_max,duration", [(9.0, 45.0), (2.0, None), (9.0, 1.5)])
def test_youtube_skips_files_and_uses_requested_windows(run, hook_max, duration):
    item = creative(
        source=Source.youtube,
        url="https://www.youtube.com/watch?v=synthetic",
        duration_s=duration,
    )
    fake = FakeMedia()
    run = run._replace(hook_window_max_s=hook_max)
    result = analyze_creative(
        item, plan=UrlPlan(None, "none"), run=run, media=fake.deps()
    )
    assert fake.events == []
    assert result.cleanup == "none"
    for call, maximum in zip(
        run.interact.calls,
        [run.content_type_window_s, min(3.0, hook_max), run.full_window_s],
    ):
        part = next(part for part in call["input_parts"] if part.get("type") == "video")
        assert part["uri"] == item.url
        assert "mime_type" not in part
        end = min(maximum, duration) if duration is not None else maximum
        assert part["processing"]["start_offset"] == "0s"
        assert part["processing"]["end_offset"] == f"{end:g}s"
        assert call["thinking_level"] == run.thinking_level
        assert call["purpose"] == run.purpose
        assert call["ledger_path"] == run.ledger_path
        assert call["caps"] == run.caps


def test_uploaded_input_uses_file_id_and_mp4(run):
    analyze(run, FakeMedia())
    for call in run.interact.calls:
        part = next(part for part in call["input_parts"] if part.get("type") == "video")
        assert part["uri"] == FILE_ID
        assert part["mime_type"] == "video/mp4"


def test_instagram_plans_group_each_known_account_once():
    items = [
        creative("ok"),
        creative("gone"),
        creative("missing"),
        creative("second", account="account-b"),
        creative("unknown", account="absent"),
        creative("no-account", account=None),
    ]
    accounts = {
        username: InstagramAccount(brand="synthetic", username=username)
        for username in ("account-a", "account-b")
    }
    calls = []

    def refresh(account, wanted):
        calls.append((account, wanted))
        if account.username == "account-a":
            return RefreshResult({"ok": MEDIA_URL}, {"gone"}, {"missing"}, None)
        return RefreshResult({"second": MEDIA_URL}, set(), set(), None)

    plans = prepare_instagram_plans(items, accounts, refresh=refresh)
    assert len(calls) == len(accounts)
    assert calls == [
        (accounts["account-a"], {"ok", "gone", "missing"}),
        (accounts["account-b"], {"second"}),
    ]
    assert [plans[item.key].state for item in items] == [
        "ok",
        "gone",
        "missing",
        "ok",
        "missing",
        "missing",
    ]
    assert plans[items[0].key].url == MEDIA_URL
    assert all(plans[item.key].url is None for item in (items[1], items[2], *items[4:]))


def test_empty_refresh_result_is_missing_and_other_sources_are_ignored():
    account = InstagramAccount(brand="synthetic", username="account-a")
    refresh = Mock(return_value=RefreshResult({}, set(), set(), None))
    item = creative()
    plans = prepare_instagram_plans(
        [item, creative(source=Source.youtube), creative(source=Source.tiktok)],
        {account.username: account},
        refresh=refresh,
    )
    assert plans == {item.key: UrlPlan(None, "missing")}
    refresh.assert_called_once_with(account, {item.source_id})
    assert prepare_instagram_plans([], {}, refresh=refresh) == {}


def test_interrupted_scan_keeps_found_urls_and_marks_the_rest_stopped():
    account = InstagramAccount(brand="synthetic", username="account-a")
    items = [creative("found"), creative("deep"), creative("vanished")]
    result = RefreshResult(
        {"found": MEDIA_URL}, {"vanished"}, {"deep"}, "INSTAGRAM_USAGE_HIGH"
    )
    plans = prepare_instagram_plans(
        items, {account.username: account}, refresh=Mock(return_value=result)
    )
    # 찾은 것은 그대로, 키가 사라진 것은 gone, 못 찾은 것만 "중단으로 못 찾음".
    assert plans[items[0].key] == UrlPlan(MEDIA_URL, "ok")
    assert plans[items[1].key] == UrlPlan(None, "refresh_stopped")
    assert plans[items[2].key] == UrlPlan(None, "gone")


def test_completed_scan_confirms_missing():
    account = InstagramAccount(brand="synthetic", username="account-a")
    item = creative("absent")
    result = RefreshResult({}, set(), {"absent"}, None)
    plans = prepare_instagram_plans(
        [item], {account.username: account}, refresh=Mock(return_value=result)
    )
    assert plans[item.key] == UrlPlan(None, "missing")


class FakeStore:
    def __init__(self, existing=()):
        self.jobs = set(existing)
        self.calls = []

    def get_job_results(self, kind, keys):
        self.calls.append(("get", kind, keys))
        return [object()] if kind in self.jobs else []

    def enqueue_analysis(self, kind, creatives):
        self.calls.append(("enqueue", kind, creatives))
        self.jobs.add(kind)
        return 1

    def record_analysis(self, kind, key, **kwargs):
        assert kind in self.jobs
        self.calls.append(("record", kind, key, kwargs))

    def upsert_creatives(self, creatives):
        self.calls.append(("upsert", creatives))
        return len(creatives)


def test_apply_outcome_creates_only_absent_jobs_before_recording(run):
    item = creative()
    outcome = analyze(run, FakeMedia())
    existing_kind = outcome.records[0].kind
    store = FakeStore(existing=[existing_kind])
    apply_outcome(store, item, outcome)
    assert [call[1] for call in store.calls if call[0] == "enqueue"] == [
        record.kind for record in outcome.records[1:]
    ]
    writes = [call for call in store.calls if call[0] == "record"]
    for record, (_, kind, key, kwargs) in zip(outcome.records, writes):
        assert kind == record.kind and key == item.key
        assert kwargs == record.model_dump(exclude={"kind"})
    assert not any(call[0] == "upsert" for call in store.calls)
    for record in outcome.records[1:]:
        enqueue = next(
            i
            for i, call in enumerate(store.calls)
            if call[:2] == ("enqueue", record.kind)
        )
        write = next(
            i
            for i, call in enumerate(store.calls)
            if call[:2] == ("record", record.kind)
        )
        assert enqueue < write


def test_apply_gone_records_before_marking_not_analyzable(run):
    item = creative()
    outcome = analyze_creative(
        item, plan=UrlPlan(None, "gone"), run=run, media=FakeMedia().deps()
    )
    store = FakeStore()
    apply_outcome(store, item, outcome)
    assert [call[0] for call in store.calls] == ["get", "enqueue", "record", "upsert"]
    saved = store.calls[-1][1][0]
    assert saved == item.model_copy(update={"analyzable": False})
    assert item.analyzable is True


@pytest.mark.parametrize(
    "replies",
    [None, ["invalid", "invalid"], [LlmCallError(kind=ErrorKind.FATAL, code="FATAL")]],
)
def test_transient_identifiers_never_reach_outcome_or_store(run, replies, capsys):
    result = analyze(run._replace(interact=FakeInteract(replies)), FakeMedia())
    store = FakeStore()
    apply_outcome(store, creative(), result)
    for text in [
        result.model_dump_json(),
        repr(result),
        repr(store.calls),
        capsys.readouterr().out,
        capsys.readouterr().err,
    ]:
        assert MEDIA_URL not in text and FILE_ID not in text
        assert "synthetic-video" not in text


def test_echoed_transient_identifiers_are_redacted_before_persistence(run):
    replies = responses()
    replies[-1]["ingredients"] = [f"{MEDIA_URL} {FILE_ID}"]
    result = analyze(run._replace(interact=FakeInteract(replies)), FakeMedia())
    store = FakeStore()
    apply_outcome(store, creative(), result)
    for text in (result.model_dump_json(), repr(result), repr(store.calls)):
        assert MEDIA_URL not in text and FILE_ID not in text
    assert result.records[-1].labels["ingredients"] == ["[redacted] [redacted]"]


@pytest.mark.parametrize("by_axis", [False, True])
def test_optional_axis_purpose_preserves_legacy_calls(run, by_axis):
    configured = run._replace(purpose_by_axis=True) if by_axis else run
    result = analyze(configured, FakeMedia())
    assert len(result.records) == 3
    assert [call["purpose"] for call in run.interact.calls] == [
        f"{run.purpose}-{axis}" if by_axis else run.purpose
        for axis in ("content_type", "hook", "full")
    ]


def test_unclassified_llm_failures_can_be_requeued():
    # 2026-11-14: 118 LLM_FATAL content_type failures at the end of the YouTube run
    # succeeded when called again, so --retry-failed must be able to requeue them.
    assert "LLM_FATAL" in RETRYABLE_ERROR_CODES
    assert "INVALID_OUTPUT" not in RETRYABLE_ERROR_CODES
