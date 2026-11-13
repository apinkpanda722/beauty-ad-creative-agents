"""Frozen axes use the document and domain as their sources, without live data."""

import json
import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import get_args, get_origin

import pytest
from pydantic import ValidationError

from beautyads.analysis.axes import analyze_full
from beautyads.analysis.models import ANALYSIS_MODEL_ID, PROMPT_VERSIONS, VideoInput
from beautyads.analysis.prompts import HOOK_PROMPT_VERSION, build_full_prompt
from beautyads.domain import (
    Angle,
    Category,
    ContentType,
    ContentTypeResult,
    Creative,
    CtaType,
    Format,
    FullResult,
    HookResult,
    JobStatus,
    PlatformFitFlags,
    StructureFlags,
    Talent,
)
from beautyads.eval.sheets import (
    TAXONOMY_PATH,
    build_blind_sheet,
    codebook_rows,
    instructions_text,
    label_columns,
    parse_taxonomy,
)
from beautyads.llm import InteractionResult, UsageInfo

AXES = [("content_type", ContentType), ("category", Category)]
FREEZE_LINE = (
    "> 부분 동결(2026-11-13): 이 절의 값과 정의는 E1 1단계 라벨링 전에 고정했고 "
    "v1 동결 전까지 바꾸지 않는다."
)


@pytest.fixture
def taxonomy_text():
    return TAXONOMY_PATH.read_text(encoding="utf-8")


def _assert_axis(text: str, axis: str, enum: type[StrEnum]) -> None:
    guide = parse_taxonomy(text)[axis]
    assert set(guide.definitions) == {member.value for member in enum}, "값 집합"
    assert all(definition.strip() for definition in guide.definitions.values()), (
        "빈 정의"
    )
    assert enum.other.value in guide.definitions


def _assert_freeze_line(text: str, axis: str) -> None:
    heading = re.search(rf"(?m)^### [^\n]*`{axis}`[^\n]*\n", text)
    assert heading is not None
    following = text[heading.end() :].lstrip("\n")
    assert following.splitlines()[0] == FREEZE_LINE


def _synthetic_section(axis: str, definitions: dict[str, str]) -> str:
    rows = "\n".join(
        f"| `{value}` | {definition} |" for value, definition in definitions.items()
    )
    return f"### 합성 절 `{axis}`\n\n| 값 | 판정 기준 |\n|---|---|\n{rows}\n"


@pytest.mark.parametrize("axis, enum", AXES)
def test_frozen_axis_values_and_definitions_follow_document_and_domain(
    taxonomy_text, axis, enum
):
    _assert_axis(taxonomy_text, axis, enum)


@pytest.mark.parametrize("axis, enum", AXES)
def test_partial_freeze_line_is_immediately_below_each_heading(
    taxonomy_text, axis, enum
):
    _assert_freeze_line(taxonomy_text, axis)


@pytest.mark.parametrize("axis, enum", AXES)
def test_synthetic_document_rejects_each_missing_value(taxonomy_text, axis, enum):
    definitions = parse_taxonomy(taxonomy_text)[axis].definitions
    _assert_axis(_synthetic_section(axis, definitions), axis, enum)
    for value in definitions:
        incomplete = {key: text for key, text in definitions.items() if key != value}
        with pytest.raises(AssertionError, match="값 집합"):
            _assert_axis(_synthetic_section(axis, incomplete), axis, enum)


@pytest.mark.parametrize("axis, enum", AXES)
@pytest.mark.parametrize("empty", ["", "   "])
def test_synthetic_document_rejects_each_empty_definition(
    taxonomy_text, axis, enum, empty
):
    definitions = parse_taxonomy(taxonomy_text)[axis].definitions
    _assert_axis(_synthetic_section(axis, definitions), axis, enum)
    for value in definitions:
        incomplete = {**definitions, value: empty}
        with pytest.raises(AssertionError, match="빈 정의"):
            _assert_axis(_synthetic_section(axis, incomplete), axis, enum)


def _enum_axes():
    axes = []
    for model in (ContentTypeResult, HookResult, FullResult):
        for name, field in model.model_fields.items():
            annotation = field.annotation
            if get_origin(annotation) is list:
                annotation = get_args(annotation)[0]
            if isinstance(annotation, type) and issubclass(annotation, StrEnum):
                axes.append((name, annotation))
    return axes


ALL_AXES = _enum_axes()
FLAG_AXES = [("structure", StructureFlags), ("platform_fit", PlatformFitFlags)]


def _section(text, axis):
    match = re.search(rf"(?ms)^### [^\n]*`{axis}`[^\n]*\n.*?(?=^### |^## |\Z)", text)
    assert match is not None, "누락된 축"
    return match.group()


def _document_values(section):
    tabled = re.findall(r"(?m)^\| `([a-z_]+)` \|", section)
    if tabled:
        return set(tabled)
    # talent has a comma-separated closed list, with definitions in bullets.
    values = re.search(r"(?m)^`[a-z_]+`(?:, `[a-z_]+`)+$", section)
    assert values is not None, "값 목록 누락"
    return set(re.findall(r"`([a-z_]+)`", values.group()))


def _assert_closed_axis(text, axis, enum):
    section = _section(text, axis)
    values = _document_values(section)
    assert values == {member.value for member in enum}, "값 집합"
    definitions = parse_taxonomy(text)[axis].definitions
    for value in values:
        if enum is Talent and value != Talent.ordinary_person.value:
            continue
        if enum in (Angle, Format) and value == enum.other.value:
            continue
        assert definitions.get(value, "").strip(), "빈 정의"


@pytest.mark.parametrize("axis, enum", ALL_AXES)
def test_all_frozen_closed_axes_match_document(taxonomy_text, axis, enum):
    _assert_closed_axis(taxonomy_text, axis, enum)


@pytest.mark.parametrize("axis, enum", ALL_AXES)
def test_all_axes_reject_synthetic_missing_values(taxonomy_text, axis, enum):
    guide = parse_taxonomy(taxonomy_text)[axis]
    definitions = {
        value: guide.definitions.get(value, "")
        for value in _document_values(_section(taxonomy_text, axis))
    }
    _assert_closed_axis(_synthetic_section(axis, definitions), axis, enum)
    for value in definitions:
        incomplete = {key: text for key, text in definitions.items() if key != value}
        with pytest.raises(AssertionError, match="값 집합"):
            _assert_closed_axis(_synthetic_section(axis, incomplete), axis, enum)


@pytest.mark.parametrize("axis, enum", ALL_AXES)
def test_all_required_definitions_reject_synthetic_blanks(taxonomy_text, axis, enum):
    guide = parse_taxonomy(taxonomy_text)[axis]
    definitions = {
        value: guide.definitions.get(value, "")
        for value in _document_values(_section(taxonomy_text, axis))
    }
    for value, definition in definitions.items():
        if not definition.strip():
            continue
        for empty in ("", "   "):
            with pytest.raises(AssertionError, match="빈 정의"):
                _assert_closed_axis(
                    _synthetic_section(axis, {**definitions, value: empty}), axis, enum
                )


def _assert_flags(text, axis, model):
    guide = parse_taxonomy(text)[axis]
    assert _document_values(_section(text, axis)) == set(model.model_fields), (
        "불리언 열"
    )
    assert all(field.annotation is bool for field in model.model_fields.values())
    assert all(value.strip() for value in guide.definitions.values()), "빈 정의"


@pytest.mark.parametrize("axis, model", FLAG_AXES)
def test_boolean_columns_match_document_and_reject_missing_columns(
    taxonomy_text, axis, model
):
    _assert_flags(taxonomy_text, axis, model)
    definitions = parse_taxonomy(taxonomy_text)[axis].definitions
    for value in definitions:
        incomplete = {key: text for key, text in definitions.items() if key != value}
        with pytest.raises(AssertionError, match="불리언 열"):
            _assert_flags(_synthetic_section(axis, incomplete), axis, model)
        with pytest.raises(AssertionError, match="빈 정의"):
            _assert_flags(
                _synthetic_section(axis, {**definitions, value: ""}), axis, model
            )


def _assert_v1_freeze(text):
    assert text.splitlines()[0] == "# 소재 분류 목록 (v1, 2026-11-13 동결)"
    assert "> v1 동결(2026-11-13). 동결 뒤의 변경은 ADR에 남긴다." in text
    assert "미확정 쟁점" not in text
    assert "초안" not in text


def test_v1_freeze_header_and_no_unresolved_issues(taxonomy_text):
    _assert_v1_freeze(taxonomy_text)
    for marker in ("미확정 쟁점", "초안"):
        with pytest.raises(AssertionError):
            _assert_v1_freeze(taxonomy_text + f"\n- {marker}: 합성 문제\n")
    with pytest.raises(AssertionError):
        _assert_v1_freeze(taxonomy_text.replace("2026-11-13", "1900-01-01"))


def _creative():
    return Creative(
        source="youtube",
        source_id="synthetic-freeze",
        collected_at=datetime(2026, 11, 13, tzinfo=UTC),
    )


def _full_payload(cta):
    data = {}
    for axis, enum in ALL_AXES:
        if axis in FullResult.model_fields:
            value = next(iter(enum)).value
            data[axis] = (
                [value]
                if get_origin(FullResult.model_fields[axis].annotation) is list
                else value
            )
    data.update(
        cta_type=cta.value,
        structure={name: False for name in StructureFlags.model_fields},
        platform_fit={name: False for name in PlatformFitFlags.model_fields},
        ingredients=[],
    )
    data["structure"]["has_cta"] = cta is not CtaType.none
    return data


@pytest.mark.parametrize("cta", list(CtaType))
def test_cta_equivalence_accepts_matching_and_rejects_opposite(cta):
    data = _full_payload(cta)
    assert FullResult.model_validate(data).model_dump(mode="json") == data
    data["structure"]["has_cta"] = not data["structure"]["has_cta"]
    with pytest.raises(ValidationError):
        FullResult.model_validate(data)


@pytest.mark.parametrize("cta", list(CtaType))
@pytest.mark.parametrize("recover", [False, True])
def test_cta_mismatch_uses_existing_validation_retry(tmp_path, cta, recover):
    valid = _full_payload(cta)
    invalid = _full_payload(cta)
    invalid["structure"]["has_cta"] = not valid["structure"]["has_cta"]
    responses = iter([json.dumps(invalid), json.dumps(valid if recover else invalid)])
    calls = []

    def fake_interact(**kwargs):
        calls.append(kwargs)
        return InteractionResult(
            next(responses), UsageInfo(ANALYSIS_MODEL_ID, 0, 0, 0, 0, 0.0), {}
        )

    outcome = analyze_full(
        _creative(),
        VideoInput("files/synthetic", "video/mp4"),
        thinking_level="minimal",
        purpose="test-freeze",
        ledger_path=tmp_path / "costs.jsonl",
        caps={"gemini": 12.0},
        window_max_s=60,
        interact=fake_interact,
    )
    assert len(calls) == outcome.attempts == 2
    assert calls[0] == calls[1]
    assert outcome.raw_output == json.dumps(valid if recover else invalid)
    assert outcome.status is (JobStatus.done if recover else JobStatus.held)
    assert outcome.error_code == (None if recover else "INVALID_OUTPUT")
    assert outcome.labels == (valid if recover else None)


@pytest.mark.parametrize("value", [False, True])
def test_removed_hook_segment_is_forbidden_in_outputs_and_absent_from_artifacts(value):
    data = _full_payload(CtaType.none)
    data["structure"]["has_hook_segment"] = value
    with pytest.raises(ValidationError) as caught:
        FullResult.model_validate(data)
    assert any(
        error["type"] == "extra_forbidden"
        and error["loc"] == ("structure", "has_hook_segment")
        for error in caught.value.errors()
    )
    assert "has_hook_segment" not in label_columns()
    assert all(row["axis"] != "has_hook_segment" for row in codebook_rows())
    assert "has_hook_segment" not in build_full_prompt(_creative())
    sheet = build_blind_sheet(
        [_creative()],
        seed=1,
        job_results={},
        run_tags=[],
        split_sha256="synthetic",
        selection_seed=1,
    )
    assert set(sheet.rows[0]) == {"item_id", "link", "text", *label_columns()}


def test_v1_codebook_and_prompt_use_document_definitions(taxonomy_text):
    guides = parse_taxonomy(taxonomy_text)
    notes = {
        (row["axis"], row["value"]): row["note"] for row in codebook_rows(taxonomy_text)
    }
    for axis, enum in ALL_AXES:
        for member in enum:
            definition = guides[axis].definitions.get(member.value)
            if definition:
                assert notes[axis, member.value].startswith(f"정의: {definition}.")
    prompt = build_full_prompt(_creative())
    definition = guides["talent"].definitions[Talent.ordinary_person.value]
    assert definition in prompt
    priority = " > ".join(guides["format"].order)
    assert priority in prompt
    for index, value in enumerate(guides["format"].order, start=1):
        assert (
            f"우선순위 {index}/{len(guides['format'].order)}" in notes["format", value]
        )
    cta_rule = next(bullet for bullet in guides["cta_type"].bullets if ">" in bullet)
    assert " > ".join(re.findall(r"`([a-z_]+)`", cta_rule)) in prompt
    claims_rule = next(
        bullet for bullet in guides["claims"].bullets if "해시태그" in bullet
    )
    assert claims_rule in prompt
    for member in CtaType:
        assert cta_rule in notes["cta_type", member.value]
    for member in FullResult.model_fields["claims"].annotation.__args__[0]:
        assert claims_rule in notes["claims", member.value]
    assert "캡션 본문 문장" in instructions_text() and "해시태그" in instructions_text()


def test_hook_version_matches_v1_registry_and_model_is_unchanged():
    assert HOOK_PROMPT_VERSION == PROMPT_VERSIONS["hook"] == "hook-v1"
    assert ANALYSIS_MODEL_ID == "gemini-3.6-flash"
