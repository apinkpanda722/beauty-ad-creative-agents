"""Full-axis validation uses synthetic outputs and fake interactions only."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from beautyads.analysis.axes import (
    analyze_content_type,
    analyze_full,
    content_type_schema,
    full_schema,
    full_window,
    is_product_target,
)
from beautyads.analysis.models import (
    ANALYSIS_MODEL_ID,
    FINAL_RUN_TAG,
    PROMPT_VERSIONS,
    VideoInput,
    models_match,
    video_input_for,
)
from beautyads.analysis.prompts import build_content_type_prompt, build_full_prompt
from beautyads.domain import (
    Angle,
    Category,
    Claim,
    ContentType,
    ContentTypeResult,
    Creative,
    CtaType,
    Format,
    FullResult,
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
    InteractionResult,
    LlmCallError,
    LlmResponseError,
    UsageInfo,
    json_schema_format,
    text_part,
    video_part,
)

CONTENT_ENUMS = {"content_type": ContentType, "category": Category}
FULL_ENUMS = {
    "angle": Angle,
    "format": Format,
    "talent": Talent,
    "cta_type": CtaType,
    "claims": Claim,
}
AXES = [
    (analyze_content_type, ContentTypeResult, content_type_schema, "content_type"),
    (analyze_full, FullResult, full_schema, "full"),
]


def creative(**overrides):
    return Creative.model_validate(
        {
            "source": Source.youtube,
            "source_id": "synthetic",
            "url": "https://www.youtube.com/watch?v=synthetic",
            "duration_s": 20.0,
            "collected_at": datetime(2026, 11, 12, tzinfo=UTC),
            **overrides,
        }
    )


def payload(model):
    enums = CONTENT_ENUMS if model is ContentTypeResult else FULL_ENUMS
    data = {name: next(iter(enum)).value for name, enum in enums.items()}
    if model is FullResult:
        data["claims"] = [data["claims"]]
        data.update(
            structure={name: False for name in StructureFlags.model_fields},
            platform_fit={name: False for name in PlatformFitFlags.model_fields},
            ingredients=["  시카 ", "nIaCiNaMiDe", " 병풀\t추출물\n", "Unknown Mix"],
        )
    return data


class FakeInteract:
    def __init__(self, *responses, model=ANALYSIS_MODEL_ID):
        self.responses = iter(responses)
        self.model = model
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return InteractionResult(response, UsageInfo(self.model, 0, 0, 0, 0, 0.0), {})


@pytest.fixture
def call_kwargs(tmp_path):
    return {
        "thinking_level": "minimal",
        "purpose": "test-full",
        "ledger_path": tmp_path / "costs.jsonl",
        "caps": {"gemini": 12.0},
        "window_max_s": 60.0,
    }


@pytest.mark.parametrize(
    "model,schema_fn,enums",
    [
        (ContentTypeResult, content_type_schema, CONTENT_ENUMS),
        (FullResult, full_schema, FULL_ENUMS),
    ],
)
def test_schemas_derive_fields_and_enum_values_from_domain(model, schema_fn, enums):
    schema = schema_fn()
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == set(model.model_fields)
    assert set(schema["required"]) == set(model.model_fields)
    for name, enum in enums.items():
        prop = schema["properties"][name]
        if name == "claims":
            prop = prop["items"]
        assert set(prop["enum"]) == {member.value for member in enum}
    if model is FullResult:
        for name, flags in [
            ("structure", StructureFlags),
            ("platform_fit", PlatformFitFlags),
        ]:
            prop = schema["properties"][name]
            assert set(prop["properties"]) == set(flags.model_fields)
            assert set(prop["required"]) == set(flags.model_fields)
            assert prop["additionalProperties"] is False
            assert all(
                field["type"] == "boolean" for field in prop["properties"].values()
            )


@pytest.mark.parametrize("analyze,model,schema_fn,axis", AXES)
def test_every_enum_member_survives_analysis(
    analyze, model, schema_fn, axis, call_kwargs
):
    enums = CONTENT_ENUMS if model is ContentTypeResult else FULL_ENUMS
    item = creative()
    for name, enum in enums.items():
        for member in enum:
            data = payload(model)
            data[name] = [member.value] if name == "claims" else member.value
            if name == "cta_type":
                data["structure"]["has_cta"] = member is not CtaType.none
            raw = "\n```json\n" + json.dumps(data, ensure_ascii=False) + "\n```\n"
            fake = FakeInteract(raw)
            result = analyze(item, video_input_for(item), interact=fake, **call_kwargs)
            assert result.key == item.key
            assert result.axis == axis
            assert result.status is JobStatus.done
            assert result.labels == data
            assert result.raw_output == raw
            assert result.model == ANALYSIS_MODEL_ID
            assert result.model_matches_request is True
            assert result.prompt_version == PROMPT_VERSIONS[axis]
            assert result.error_code is None
            assert result.attempts == len(fake.calls) == 1


@pytest.mark.parametrize("analyze,model,schema_fn,axis", AXES)
def test_invalid_outputs_retry_identical_request_and_preserve_last_raw(
    analyze, model, schema_fn, axis, call_kwargs
):
    enums = CONTENT_ENUMS if model is ContentTypeResult else FULL_ENUMS
    invalid = ["  not JSON 한글\n", "{}", "[]"]
    for name in enums:
        data = payload(model)
        data[name] = ["outside-taxonomy"] if name == "claims" else "outside-taxonomy"
        invalid.append(json.dumps(data))
    for name in model.model_fields:
        data = payload(model)
        del data[name]
        invalid.append(json.dumps(data))
    invalid.append(json.dumps({**payload(model), "unknown": True}))
    for raw in invalid:
        fake = FakeInteract("first invalid", raw)
        result = analyze(
            creative(),
            VideoInput("files/synthetic", "video/mp4"),
            interact=fake,
            **call_kwargs,
        )
        assert result.status is JobStatus.held
        assert result.error_code == "INVALID_OUTPUT"
        assert result.labels is None
        assert result.raw_output == raw
        assert result.model == ANALYSIS_MODEL_ID
        assert result.attempts == len(fake.calls) == 2
        assert fake.calls[0] == fake.calls[1]


@pytest.mark.parametrize("analyze,model,schema_fn,axis", AXES)
@pytest.mark.parametrize("retries", [0, 2])
def test_validation_retry_budget_and_recovery(
    analyze, model, schema_fn, axis, retries, call_kwargs
):
    data = payload(model)
    fake = FakeInteract(*(["invalid"] * retries), json.dumps(data))
    result = analyze(
        creative(),
        VideoInput("files/synthetic", "video/mp4"),
        interact=fake,
        max_validation_retries=retries,
        **call_kwargs,
    )
    assert result.status is JobStatus.done
    assert result.labels == data
    assert result.attempts == len(fake.calls) == retries + 1
    fake = FakeInteract(*(["invalid"] * (retries + 1)))
    result = analyze(
        creative(),
        VideoInput("files/synthetic", "video/mp4"),
        interact=fake,
        max_validation_retries=retries,
        **call_kwargs,
    )
    assert result.status is JobStatus.held
    assert result.error_code == "INVALID_OUTPUT"
    assert len(fake.calls) == retries + 1


@pytest.mark.parametrize("analyze,model,schema_fn,axis", AXES)
@pytest.mark.parametrize(
    "error",
    [
        DailyLimitReached(kind=ErrorKind.DAILY_LIMIT, code="DAILY_LIMIT"),
        CostCapExceeded("gemini", 12.0, 12.0),
        LlmCallError(kind=ErrorKind.RATE_LIMIT, code="RATE_LIMIT"),
    ],
)
def test_batch_stop_exceptions_propagate(
    analyze, model, schema_fn, axis, error, call_kwargs
):
    fake = FakeInteract(error)
    with pytest.raises(type(error)) as caught:
        analyze(
            creative(),
            VideoInput("files/synthetic", "video/mp4"),
            interact=fake,
            **call_kwargs,
        )
    assert caught.value is error
    assert len(fake.calls) == 1


@pytest.mark.parametrize("analyze,model,schema_fn,axis", AXES)
@pytest.mark.parametrize(
    "error,code",
    [
        (LlmCallError(kind=ErrorKind.FATAL, code="SYNTHETIC"), "LLM_FATAL"),
        (LlmCallError(kind=ErrorKind.RETRYABLE, code="SYNTHETIC"), "LLM_RETRYABLE"),
        (LlmResponseError("NO_MODEL_OUTPUT"), "NO_MODEL_OUTPUT"),
    ],
)
def test_call_failures_return_failed_without_validation_retry(
    analyze, model, schema_fn, axis, error, code, call_kwargs
):
    fake = FakeInteract(error)
    result = analyze(
        creative(),
        VideoInput("files/synthetic", "video/mp4"),
        interact=fake,
        **call_kwargs,
    )
    assert result.status is JobStatus.failed
    assert result.axis == axis
    assert result.error_code == code
    assert (
        result.labels
        is result.raw_output
        is result.model
        is result.model_matches_request
        is None
    )
    assert result.attempts == len(fake.calls) == 1


@pytest.mark.parametrize("analyze,model,schema_fn,axis", AXES)
@pytest.mark.parametrize(
    "duration,maximum,end", [(20, 60, 20), (100, 60, 60), (None, 60, 60), (2, 1, 1)]
)
@pytest.mark.parametrize("thinking_level", ["minimal", "default", "high"])
@pytest.mark.parametrize(
    "video",
    [
        VideoInput("files/synthetic", "video/mp4"),
        VideoInput("https://www.youtube.com/watch?v=synthetic", None),
    ],
)
def test_request_uses_supplied_video_window_schema_and_settings(
    analyze,
    model,
    schema_fn,
    axis,
    duration,
    maximum,
    end,
    thinking_level,
    video,
    call_kwargs,
):
    item = creative(
        source=Source.instagram,
        duration_s=duration,
        title="합성 제목",
        caption="합성 캡션",
    )
    call_kwargs.update(window_max_s=maximum, thinking_level=thinking_level)
    fake = FakeInteract(json.dumps(payload(model)))
    analyze(item, video, interact=fake, **call_kwargs)
    (request,) = fake.calls
    prompt_fn = (
        build_content_type_prompt if model is ContentTypeResult else build_full_prompt
    )
    assert request["input_parts"] == [
        text_part(prompt_fn(item)),
        video_part(video.uri, start_s=0, end_s=end, fps=1, mime_type=video.mime_type),
    ]
    assert request["model"] == ANALYSIS_MODEL_ID
    assert request["response_format"] == json_schema_format(schema_fn())
    for name in ("thinking_level", "purpose", "ledger_path", "caps"):
        assert request[name] == call_kwargs[name]
    assert "temperature" not in request


@pytest.mark.parametrize("analyze,model,schema_fn,axis", AXES)
@pytest.mark.parametrize(
    "actual,matches",
    [
        (ANALYSIS_MODEL_ID, True),
        (ANALYSIS_MODEL_ID + "-preview", True),
        ("different-model", False),
        (None, False),
    ],
)
def test_actual_model_is_recorded_without_rejecting_labels(
    analyze, model, schema_fn, axis, actual, matches, call_kwargs
):
    data = payload(model)
    fake = FakeInteract(json.dumps(data), model=actual)
    result = analyze(
        creative(),
        VideoInput("files/synthetic", "video/mp4"),
        interact=fake,
        **call_kwargs,
    )
    assert result.status is JobStatus.done
    assert result.labels == data
    assert result.model == actual
    assert result.model_matches_request is matches


@pytest.mark.parametrize(
    "duration,maximum,end", [(None, 60, 60), (20, 60, 20), (100, 60, 60), (60, 60, 60)]
)
def test_full_window(duration, maximum, end):
    assert full_window(duration, window_max_s=maximum) == (0.0, end)


def test_callers_can_set_content_and_full_windows_independently(call_kwargs):
    fake = FakeInteract(
        json.dumps(payload(ContentTypeResult)), json.dumps(payload(FullResult))
    )
    item = creative(duration_s=120)
    video = video_input_for(item)
    analyze_content_type(
        item, video, interact=fake, **{**call_kwargs, "window_max_s": 15}
    )
    analyze_full(item, video, interact=fake, **{**call_kwargs, "window_max_s": 60})
    assert [
        call["input_parts"][1]["processing"]["end_offset"] for call in fake.calls
    ] == ["15s", "60s"]


@pytest.mark.parametrize(
    "content_type,category,expected",
    [
        (ContentType.product_creative, Category.mask_pack, True),
        (ContentType.product_creative, Category.other, False),
        (ContentType.event_place, Category.mask_pack, False),
    ],
)
def test_product_target_gate(content_type, category, expected):
    assert (
        is_product_target(
            ContentTypeResult(content_type=content_type, category=category)
        )
        is expected
    )


def test_video_input_for_youtube():
    item = creative()
    assert video_input_for(item) == (item.url, None)


@pytest.mark.parametrize("url", [None, ""])
def test_video_input_requires_url(url):
    with pytest.raises(ValueError):
        video_input_for(creative(url=url))


@pytest.mark.parametrize("source", [Source.instagram, Source.tiktok])
def test_other_sources_require_explicit_uploaded_video(source):
    with pytest.raises(ValueError):
        video_input_for(creative(source=source))


@pytest.mark.parametrize(
    "actual,expected",
    [
        (None, False),
        ("", False),
        ("requested", True),
        ("requested-preview", True),
        ("requestedextra", False),
        ("other-requested", False),
    ],
)
def test_model_matching_boundaries(actual, expected):
    assert models_match("requested", actual) is expected


def test_run_and_prompt_versions():
    assert FINAL_RUN_TAG == "v1"
    assert FINAL_RUN_TAG not in {"minimal", "default"}
    assert PROMPT_VERSIONS == {
        "content_type": "content-type-v1",
        "hook": "hook-v1",
        "full": "full-v1",
    }


def test_analysis_model_id_has_one_source():
    directory = Path(__file__).resolve().parents[1] / "src" / "beautyads" / "analysis"
    occurrences = {
        path.name
        for path in directory.rglob("*.py")
        if "gemini-3.6-flash" in path.read_text(encoding="utf-8")
    }
    assert occurrences == {"models.py"}


def test_prompts_include_taxonomy_criteria_and_observation_limits():
    item = creative(title="합성 제목", caption="합성 캡션")
    content = build_content_type_prompt(item)
    full = build_full_prompt(item)
    for prompt in (content, full):
        assert item.title in prompt and item.caption in prompt
        assert "JSON" in prompt
    for enum in CONTENT_ENUMS.values():
        for member in enum:
            assert member.value in content
    for enum in FULL_ENUMS.values():
        for member in enum:
            assert member.value in full
    assert "특정 제품을 보여주거나 설명하는 것이 중심" in content
    assert "매장·팝업·행사·협업 공간 안내가 중심" in content
    assert "특정 제품 없이 브랜드 메시지·모델·캠페인" in content
    assert "중심이 아니면" in content
    assert "명시된" in full and "추정하지" in full
    assert "원문 그대로" in full
    assert "ordinary_person" in full
    for model in (StructureFlags, PlatformFitFlags):
        assert all(name in full for name in model.model_fields)
    assert "None" not in build_content_type_prompt(creative())
    assert "None" not in build_full_prompt(creative())


@pytest.mark.parametrize("analyze,model,schema_fn,axis", AXES)
def test_call_failure_reason_is_logged_without_urls_or_keys(
    analyze, model, schema_fn, axis, call_kwargs, caplog
):
    error = LlmCallError(
        kind=ErrorKind.FATAL,
        code="SYNTHETIC",
        message="HTTP 400 bad request https://example.invalid/watch?v=SYNTHETIC_ID",
    )
    with caplog.at_level("WARNING", logger="beautyads.analysis"):
        analyze(
            creative(),
            VideoInput("files/synthetic", "video/mp4"),
            interact=FakeInteract(error),
            **call_kwargs,
        )
    text = " ".join(record.getMessage() for record in caplog.records)
    assert "LLM_CALL_FAILED" in text and "kind=FATAL" in text
    assert "SYNTHETIC" in text and "HTTP 400" in text
    assert "example.invalid" not in text and "SYNTHETIC_ID" not in text
