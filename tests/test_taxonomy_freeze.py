"""The partially frozen axes use the document and domain as their sources."""

import re
from enum import StrEnum

import pytest

from beautyads.domain import Category, ContentType
from beautyads.eval.sheets import TAXONOMY_PATH, parse_taxonomy

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
