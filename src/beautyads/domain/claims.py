"""규칙은 기획안 검사에만 쓰고 경쟁 소재에는 관찰만 한다.

Matching reports dictionary evidence and rule types; checks decides the outcome.
Sentence-only rules require overall-impression review outside this dictionary.
"""

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    ValidationInfo,
    field_validator,
)

from beautyads.domain.labels import Category, Claim
from beautyads.domain.skin import SkinConcern

CLAIM_CHECK_DISCLAIMER = "식약처 안내서 기준 점검이며 법적 판단이 아님"
NonEmptyText = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]
PositivePage = Annotated[int, Field(ge=1, strict=True)]


class RuleType(StrEnum):
    prohibited = "prohibited"
    requires_functional_cert = "requires_functional_cert"
    requires_substantiation = "requires_substantiation"


class ClaimRulesError(ValueError):
    """A format error with a stable code and document-relative location."""

    code = "CLAIM_RULES_INVALID"

    def __init__(self, location: tuple[str | int, ...]):
        self.location = location
        path = ".".join(str(part) for part in location) or "<document>"
        super().__init__(f"{self.code} at {path}")


class ClaimScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["efficacy", "skin_concern", "category"]
    value: NonEmptyText
    status: Literal["draft", "advisor_approved", "confirmed"]

    @field_validator("value")
    @classmethod
    def validate_scope_value(cls, value: str, info: ValidationInfo) -> str:
        enum = {
            "efficacy": Claim,
            "skin_concern": SkinConcern,
            "category": Category,
        }.get(info.data.get("kind"))
        if enum is not None:
            enum(value)
        return value


class ClaimRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: NonEmptyText
    rule_type: RuleType
    source_page: PositivePage
    source_page_end: PositivePage | None = None
    law_basis: NonEmptyText
    group: NonEmptyText | None
    source_items: list[NonEmptyText] = Field(min_length=1)
    matchable: bool = Field(strict=True)
    terms_ko: list[NonEmptyText]
    terms_en: list[NonEmptyText]
    en_origin: NonEmptyText | None = None
    terms_en_added: list[NonEmptyText]
    en_pending: bool = Field(strict=True)
    en_waived: bool = Field(strict=True)
    en_note: NonEmptyText | None = None
    exception_note: NonEmptyText | None
    exceptions: list[NonEmptyText]
    exception_refs: list[NonEmptyText]
    applies_to: list[ClaimScope]

    @field_validator("source_page_end")
    @classmethod
    def validate_page_range(cls, value: int | None, info: ValidationInfo) -> int | None:
        if value is not None and value < info.data.get("source_page", 1):
            raise ValueError("source_page_end precedes source_page")
        return value

    @field_validator("terms_ko")
    @classmethod
    def validate_matchable_terms(
        cls, value: list[str], info: ValidationInfo
    ) -> list[str]:
        if "matchable" in info.data and bool(value) != info.data.get("matchable"):
            raise ValueError("terms_ko must be nonempty exactly when matchable is true")
        return value

    @field_validator("terms_en_added")
    @classmethod
    def validate_added_origin(cls, value: list[str], info: ValidationInfo) -> list[str]:
        if value and info.data.get("en_origin") != "advisor_added_en":
            raise ValueError("added English requires advisor_added_en origin")
        return value

    @field_validator("en_waived")
    @classmethod
    def validate_english_coverage(cls, value: bool, info: ValidationInfo) -> bool:
        if (
            info.data.get("matchable")
            and not info.data.get("terms_en")
            and not info.data.get("terms_en_added")
            and not info.data.get("en_pending")
            and not value
        ):
            raise ValueError("matchable rule needs English, en_pending or en_waived")
        return value


class _ClaimSource(BaseModel):
    # The confirmed source also records issued, issuer and file_size_bytes.
    model_config = ConfigDict(extra="allow")

    title: NonEmptyText
    registration_no: NonEmptyText
    page_url: NonEmptyText
    file_url: NonEmptyText
    file_sha256: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
    pages: PositivePage
    legal_effect: NonEmptyText


class _ClaimDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: _ClaimSource
    status: NonEmptyText
    verification: dict[str, Any]
    transcription_rules: list[NonEmptyText]
    general_principles: list[dict[str, Any]]
    excluded_scope: list[dict[str, Any]]
    rules: list[ClaimRule] = Field(min_length=1)


def parse_claim_rules(document: dict) -> list[ClaimRule]:
    """Validate without I/O or mutation; raise CLAIM_RULES_INVALID at its location."""
    try:
        parsed = _ClaimDocument.model_validate(document)
    except ValidationError as error:
        first = next(iter(error.errors(include_input=False)))
        raise ClaimRulesError(tuple(first.get("loc", ()))) from None
    rules = parsed.rules
    seen = set()
    for index, rule in enumerate(rules):
        if rule.rule_id in seen:
            raise ClaimRulesError(("rules", index, "rule_id"))
        seen.add(rule.rule_id)
    for index, rule in enumerate(rules):
        for ref_index, reference in enumerate(rule.exception_refs):
            if reference not in seen or reference == rule.rule_id:
                raise ClaimRulesError(("rules", index, "exception_refs", ref_index))
    return rules


@dataclass(frozen=True)
class ClaimTermMatch:
    rule_id: str
    rule_type: RuleType
    term: str


@dataclass(frozen=True)
class PlanClaimCheck:
    fields: dict[str, list[ClaimTermMatch]]
    disclaimer: str = CLAIM_CHECK_DISCLAIMER


def _normalize(text: str, *, english: bool) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(text.split()) if english else "".join(text.split())


def _is_english(term: str) -> bool:
    # Some original English terms occur in BOTH terms_ko and terms_en. Route
    # ASCII letter terms through boundaries even in terms_ko (drug != drugstore).
    normalized = unicodedata.normalize("NFKC", term)
    return normalized.isascii() and re.search(r"[a-zA-Z]", normalized) is not None


@dataclass(frozen=True)
class _TextView:
    text: str
    positions: tuple[int, ...]


def _text_view(base: str, *, english: bool) -> _TextView:
    """Map both whitespace policies into the same NFKC/casefold coordinate space."""
    letters = []
    positions = []
    for index, char in enumerate(base):
        if char.isspace():
            if english and letters and letters[-1] != " ":
                letters.append(" ")
                positions.append(index)
        else:
            letters.append(char)
            positions.append(index)
    return _TextView("".join(letters), tuple(positions))


def _spans(term: str, view: _TextView, *, english: bool) -> list[tuple[int, int]]:
    needle = _normalize(term, english=english)
    if not needle:
        return []
    pattern = re.escape(needle)
    if english:
        pattern = rf"(?<![a-z0-9]){pattern}(?![a-z0-9])"
    # A lookahead retains overlapping occurrences (including exception intervals).
    return [
        (view.positions[match.start()], view.positions[match.end(1) - 1] + 1)
        for match in re.finditer(rf"(?=({pattern}))", view.text)
    ]


def find_claim_terms(text: str, rules: Sequence[ClaimRule]) -> list[ClaimTermMatch]:
    """Return each matched rule/expression once, excluding overlapping exceptions.

    ASCII English in terms_ko uses the same word boundaries as the English lists.
    Exception spans in either whitespace policy share normalized coordinates.
    No blocking or warning disposition is assigned here.
    """
    base = unicodedata.normalize("NFKC", text).casefold()
    views = {english: _text_view(base, english=english) for english in (False, True)}
    by_id = {rule.rule_id: rule for rule in rules}
    matches = []
    for rule in rules:
        if not rule.matchable:
            continue
        exceptions = [
            *rule.exceptions,
            *(
                term
                for reference in rule.exception_refs
                for term in by_id[reference].terms_ko
            ),
        ]
        excluded = [
            span
            for term in exceptions
            for span in _spans(
                term, views[_is_english(term)], english=_is_english(term)
            )
        ]
        seen = set()
        for terms, english_list in (
            (rule.terms_ko, False),
            (rule.terms_en, True),
            (rule.terms_en_added, True),
        ):
            for term in terms:
                english = english_list or _is_english(term)
                key = (_normalize(term, english=english), english)
                if key in seen:
                    continue
                seen.add(key)
                spans = _spans(term, views[english], english=english)
                if any(
                    not any(
                        start < end_ex and start_ex < end
                        for start_ex, end_ex in excluded
                    )
                    for start, end in spans
                ):
                    matches.append(ClaimTermMatch(rule.rule_id, rule.rule_type, term))
    return matches


def check_plan_fields(
    fields: Mapping[str, str], rules: Sequence[ClaimRule]
) -> PlanClaimCheck:
    """Check every supplied plan field, including title (guide III.7)."""
    return PlanClaimCheck(
        {name: find_claim_terms(text, rules) for name, text in fields.items()}
    )
