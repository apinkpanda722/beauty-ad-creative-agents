"""Hook analysis uses fake wrapper calls and an in-memory repository only."""

import json
from datetime import UTC, datetime

import pytest

from beautyads.analysis import (
    HOOK_PROMPT_VERSION,
    HOOK_WINDOW_S,
    analyze_hook,
    analyze_pending,
    build_hook_prompt,
    hook_response_schema,
    hook_window,
    select_for_analysis,
)
from beautyads.domain import Creative, HookType, JobStatus, Source
from beautyads.llm import (
    CostCapExceeded,
    DailyLimitReached,
    ErrorKind,
    InteractionResult,
    LlmCallError,
    LlmResponseError,
    UsageInfo,
    json_schema_format,
    text_part,
    video_part,
)


def creative(source_id="video", **kwargs):
    return Creative(
        **{
            "source": Source.youtube,
            "source_id": source_id,
            "url": f"https://www.youtube.com/watch?v={source_id}",
            "analyzable": True,
            "duration_s": 20.0,
            "collected_at": datetime(2026, 11, 12, tzinfo=UTC),
            **kwargs,
        }
    )


def output(text):
    return InteractionResult(
        text=text,
        usage=UsageInfo("fake-response-model", 0, 0, 0, 0, 0.0),
        raw={},
    )


def valid_text():
    return json.dumps({"hook_type": next(iter(HookType)).value})


class FakeInteract:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return output(response)


@pytest.fixture
def call_kwargs(tmp_path):
    return {
        "thinking_level": "minimal",
        "purpose": "test-hook",
        "ledger_path": tmp_path / "costs.jsonl",
        "caps": {"gemini": 12.0},
        "window_max_s": 60.0,
    }


def test_selection_preserves_order_and_rechecks_collection_decision():
    creatives = [
        creative("unknown", analyzable=None),
        creative("no", analyzable=False),
        creative("long", duration_s=601.0),
        creative("unknown-length", duration_s=None),
        creative("boundary", duration_s=600.0),
        creative("short", duration_s=2.0),
        creative("already-excluded", analyzable=False, duration_s=601.0),
    ]
    selection = select_for_analysis(creatives, video_length_cut_s=600.0)
    assert selection.eligible == creatives[3:6]
    assert [(skip.key, skip.reason) for skip in selection.skipped] == [
        (creatives[0].key, "NOT_ANALYZABLE"),
        (creatives[1].key, "NOT_ANALYZABLE"),
        (creatives[2].key, "TOO_LONG"),
        (creatives[6].key, "NOT_ANALYZABLE"),
    ]
    assert select_for_analysis([], video_length_cut_s=600.0) == ([], [])


@pytest.mark.parametrize(
    ("duration", "maximum", "hook", "end"),
    [
        (20, 60, 3, 3),
        (20, 2, 3, 2),
        (1.5, 60, 3, 1.5),
        (None, 60, 3, 3),
        (None, 2, 3, 2),
        (840, 60, 3, 3),
        (20, 60, 1, 1),
    ],
)
def test_hook_window_is_always_bounded(duration, maximum, hook, end):
    assert HOOK_WINDOW_S == 3.0
    assert hook_window(duration, window_max_s=maximum, hook_window_s=hook) == (0.0, end)


def test_hook_schema_uses_domain_enum():
    schema = hook_response_schema()
    assert schema["type"] == "object"
    assert set(schema["properties"]) == {"hook_type"}
    assert schema["required"] == ["hook_type"]
    assert schema["properties"]["hook_type"]["type"] == "string"
    assert set(schema["properties"]["hook_type"]["enum"]) == {
        member.value for member in HookType
    }


def test_prompt_contains_criteria_priority_and_reference_metadata():
    prompt = build_hook_prompt(creative(title="참고 제목", caption="참고 캡션"))
    assert "첫 3초" in prompt
    assert "첫 구간만" in prompt
    assert "JSON 하나" in prompt
    assert "위쪽 값을 우선" in prompt
    assert "화면 자막이나 음성이 의문문으로 시작한다" in prompt
    assert "사용 후 결과나 사용 전후 비교가 먼저 나온다" in prompt
    assert "참고 제목" in prompt and "참고 캡션" in prompt
    positions = [prompt.index(f"{member.value}:") for member in HookType]
    assert positions == sorted(positions)
    assert "None" not in build_hook_prompt(creative())


@pytest.mark.parametrize("member", list(HookType))
def test_all_domain_values_validate_without_changing_raw_output(member, call_kwargs):
    raw = "\n```json\n" + json.dumps({"hook_type": member.value}) + "\n```\n"
    fake = FakeInteract(raw)
    item = creative()
    result = analyze_hook(item, interact=fake, **call_kwargs)
    assert result.key == item.key
    assert result.status == JobStatus.done
    assert result.hook.hook_type == member
    assert result.raw_output == raw
    assert result.model == "fake-response-model"
    assert result.attempts == 1
    assert result.error_code is None
    assert result.prompt_version == HOOK_PROMPT_VERSION == "hook-v1"


@pytest.mark.parametrize("thinking_level", ["minimal", "default", "high"])
@pytest.mark.parametrize("duration,maximum", [(20, 60), (1.5, 60), (None, 2)])
def test_request_forwards_explicit_settings_and_bounded_video(
    thinking_level, duration, maximum, call_kwargs
):
    fake = FakeInteract(valid_text())
    item = creative(duration_s=duration)
    call_kwargs.update(thinking_level=thinking_level, window_max_s=maximum)
    analyze_hook(item, interact=fake, **call_kwargs)
    assert len(fake.calls) == 1
    request = fake.calls[0]
    for name in ("thinking_level", "purpose", "ledger_path", "caps"):
        assert request[name] == call_kwargs[name]
    start, end = hook_window(duration, window_max_s=maximum)
    assert request["input_parts"] == [
        text_part(build_hook_prompt(item)),
        video_part(item.url, start_s=start, end_s=end, fps=1),
    ]
    assert request["model"] == "gemini-3.6-flash"
    assert request["response_format"] == json_schema_format(hook_response_schema())
    assert "temperature" not in request


@pytest.mark.parametrize(
    "raw",
    [
        " \nnot JSON 한글\n ",
        '{"hook_type": "outside-the-taxonomy"}',
        "{}",
        "[]",
        '{"hook_type": null}',
    ],
)
def test_invalid_output_retries_once_then_holds_last_verbatim_text(raw, call_kwargs):
    fake = FakeInteract("first invalid output", raw)
    result = analyze_hook(creative(), interact=fake, **call_kwargs)
    assert len(fake.calls) == 2
    assert fake.calls[0] == fake.calls[1]
    assert result.status == JobStatus.held
    assert result.error_code == "INVALID_OUTPUT"
    assert result.raw_output == raw
    assert result.hook is None
    assert result.attempts == 2
    assert result.model == "fake-response-model"


def test_valid_retry_recovers(call_kwargs):
    raw = valid_text()
    fake = FakeInteract("invalid", raw)
    result = analyze_hook(creative(), interact=fake, **call_kwargs)
    assert result.status == JobStatus.done
    assert result.attempts == 2
    assert result.raw_output == raw


@pytest.mark.parametrize("retries", [0, 2])
def test_validation_retry_budget_is_configurable(retries, call_kwargs):
    fake = FakeInteract(*["invalid"] * (retries + 1))
    result = analyze_hook(
        creative(), interact=fake, max_validation_retries=retries, **call_kwargs
    )
    assert len(fake.calls) == result.attempts == retries + 1
    assert result.status == JobStatus.held


@pytest.mark.parametrize(
    "source,url,code",
    [
        (Source.instagram, "https://example.invalid/video", "UNSUPPORTED_SOURCE"),
        (Source.tiktok, None, "UNSUPPORTED_SOURCE"),
        (Source.youtube, None, "NO_URL"),
        (Source.youtube, "", "NO_URL"),
    ],
)
def test_unsupported_or_missing_input_fails_without_call(
    source, url, code, call_kwargs
):
    fake = FakeInteract()
    result = analyze_hook(
        creative(source=source, url=url), interact=fake, **call_kwargs
    )
    assert result.status == JobStatus.failed
    assert result.error_code == code
    assert result.attempts == 0
    assert result.raw_output is result.hook is result.model is None
    assert fake.calls == []


@pytest.mark.parametrize("kind", [ErrorKind.FATAL, ErrorKind.RETRYABLE])
def test_wrapper_call_failures_become_failed_outcomes(kind, call_kwargs):
    fake = FakeInteract(LlmCallError(kind=kind, code="FAKE_ERROR"))
    result = analyze_hook(creative(), interact=fake, **call_kwargs)
    assert result.status == JobStatus.failed
    assert result.error_code == f"LLM_{kind}"
    assert result.attempts == 1
    assert result.hook is result.raw_output is result.model is None
    assert len(fake.calls) == 1


def test_missing_model_output_fails_without_validation_retry(call_kwargs):
    fake = FakeInteract(LlmResponseError("NO_MODEL_OUTPUT"))
    result = analyze_hook(creative(), interact=fake, **call_kwargs)
    assert result.status == JobStatus.failed
    assert result.error_code == "NO_MODEL_OUTPUT"
    assert result.attempts == len(fake.calls) == 1


def stop_errors():
    return [
        (
            DailyLimitReached(kind=ErrorKind.DAILY_LIMIT, code="DAILY_LIMIT"),
            "DAILY_LIMIT",
        ),
        (LlmCallError(kind=ErrorKind.RATE_LIMIT, code="RATE_LIMIT"), "RATE_LIMITED"),
        (CostCapExceeded("gemini", 12.0, 12.0), "COST_CAP:gemini"),
    ]


@pytest.mark.parametrize("error,reason", stop_errors())
def test_batch_stop_errors_propagate_from_analysis(error, reason, call_kwargs):
    fake = FakeInteract(error)
    with pytest.raises(type(error)) as caught:
        analyze_hook(creative(), interact=fake, **call_kwargs)
    assert caught.value is error
    assert len(fake.calls) == 1


class MemoryRepo:
    def __init__(self, creatives):
        self.creatives = creatives
        self.statuses = {item.key: JobStatus.pending for item in creatives}
        self.records = []
        self.requests = []

    def next_pending(self, kind, limit):
        self.requests.append((kind, limit))
        return [
            item
            for item in self.creatives
            if self.statuses[item.key] == JobStatus.pending
        ][:limit]

    def record_analysis(self, kind, key, **kwargs):
        self.records.append((kind, key, kwargs))
        self.statuses[key] = kwargs["status"]


def test_batch_continues_after_failed_and_held_and_records_domain_values(call_kwargs):
    items = [creative(str(index)) for index in range(4)]
    repo = MemoryRepo(items)
    raw = valid_text()
    fake = FakeInteract(
        LlmCallError(kind=ErrorKind.FATAL, code="FATAL"),
        "invalid",
        "still invalid",
        raw,
        raw,
    )
    summary = analyze_pending(repo, limit=4, interact=fake, **call_kwargs)
    assert repo.requests == [("hook", 4)]
    assert [key for _, key, _ in repo.records] == [item.key for item in items]
    assert summary.stopped is None
    expected_statuses = [
        JobStatus.failed,
        JobStatus.held,
        JobStatus.done,
        JobStatus.done,
    ]
    assert summary.counts == {
        status.value: expected_statuses.count(status) for status in JobStatus
    }
    for (_, _, record), status in zip(repo.records, expected_statuses, strict=True):
        assert record["status"] == status
        assert record["thinking_level"] == call_kwargs["thinking_level"]
        assert record["prompt_version"] == HOOK_PROMPT_VERSION
        if status == JobStatus.done:
            assert record["labels"] == json.loads(raw)
            assert record["raw_output"] == raw
            assert record["model"] == "fake-response-model"
            assert record["error_code"] is None
        else:
            assert record["labels"] is None


@pytest.mark.parametrize("error,reason", stop_errors())
def test_batch_leaves_interrupted_and_remaining_creatives_pending(
    error, reason, call_kwargs
):
    items = [creative(str(index)) for index in range(3)]
    repo = MemoryRepo(items)
    fake = FakeInteract(valid_text(), error)
    summary = analyze_pending(repo, limit=3, interact=fake, **call_kwargs)
    assert summary.stopped == reason
    assert summary.counts == {
        status.value: int(status == JobStatus.done) for status in JobStatus
    }
    assert len(repo.records) == 1
    assert len(fake.calls) == 2
    assert repo.statuses == {
        items[0].key: JobStatus.done,
        items[1].key: JobStatus.pending,
        items[2].key: JobStatus.pending,
    }


def test_batch_preserves_default_thinking_level_and_respects_limit(call_kwargs):
    repo = MemoryRepo([creative("first"), creative("second")])
    fake = FakeInteract(valid_text())
    call_kwargs["thinking_level"] = "default"
    summary = analyze_pending(repo, limit=1, interact=fake, **call_kwargs)
    assert summary.stopped is None
    assert repo.records[0][2]["thinking_level"] == "default"
    assert fake.calls[0]["thinking_level"] == "default"
    assert repo.statuses[repo.creatives[1].key] == JobStatus.pending


def test_empty_batch_does_not_call_model(call_kwargs):
    fake = FakeInteract()
    summary = analyze_pending(MemoryRepo([]), limit=5, interact=fake, **call_kwargs)
    assert summary.stopped is None
    assert summary.counts == {status.value: 0 for status in JobStatus}
    assert fake.calls == []


@pytest.mark.parametrize("source", list(Source))
@pytest.mark.parametrize("url", [None, "https://example.invalid/permalink"])
def test_hook_accepts_explicit_video_for_any_source(source, url, call_kwargs):
    from beautyads.analysis.models import ANALYSIS_MODEL_ID, VideoInput

    video = VideoInput("files/synthetic", "video/mp4")
    fake = FakeInteract(valid_text())
    item = creative(source=source, url=url)
    result = analyze_hook(item, video=video, interact=fake, **call_kwargs)
    assert result.status is JobStatus.done
    assert fake.calls[0]["input_parts"][1] == video_part(
        video.uri, start_s=0, end_s=3, fps=1, mime_type=video.mime_type
    )
    assert fake.calls[0]["model"] == ANALYSIS_MODEL_ID


@pytest.mark.parametrize(
    "source,url,code",
    [(Source.instagram, None, "UNSUPPORTED_SOURCE"), (Source.youtube, None, "NO_URL")],
)
def test_hook_explicit_none_retains_original_input_errors(
    source, url, code, call_kwargs
):
    fake = FakeInteract()
    result = analyze_hook(
        creative(source=source, url=url), video=None, interact=fake, **call_kwargs
    )
    assert result.status is JobStatus.failed
    assert result.error_code == code
    assert result.attempts == 0
    assert fake.calls == []
