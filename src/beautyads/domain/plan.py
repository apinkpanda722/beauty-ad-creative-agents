"""Plan schema and service-independent deterministic check reports."""

from collections import Counter
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, ValidationError, computed_field

from beautyads.domain.claims import CLAIM_CHECK_DISCLAIMER
from beautyads.domain.labels import Angle, Category, Claim, CtaType, Format, HookType


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    hook_type: HookType
    hook_text: str
    scenes: list[str]
    copy_lines: list[str]
    image_brief: str | None
    cta_type: CtaType
    angle: Angle
    format: Format
    category: Category
    product_url: str | None
    claimed_efficacy: list[Claim]
    # Invalid ID syntax must reach the checker as EVIDENCE_NOT_FOUND, rather
    # than being mistaken for a taxonomy/schema error during Plan validation.
    evidence_ids: list[str]


class CheckSeverity(StrEnum):
    fail = "fail"
    unknown = "unknown"


class CheckCode(StrEnum):
    EVIDENCE_MISSING = "EVIDENCE_MISSING"
    EVIDENCE_NOT_IN_HANDOFF = "EVIDENCE_NOT_IN_HANDOFF"
    EVIDENCE_NOT_FOUND = "EVIDENCE_NOT_FOUND"
    TAXONOMY_INVALID = "TAXONOMY_INVALID"
    PROHIBITED_EXPRESSION = "PROHIBITED_EXPRESSION"
    CERT_REQUIRED_UNVERIFIED = "CERT_REQUIRED_UNVERIFIED"
    EFFICACY_UNSUPPORTED = "EFFICACY_UNSUPPORTED"
    EFFICACY_UNKNOWN = "EFFICACY_UNKNOWN"


class CheckIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: CheckCode
    severity: CheckSeverity
    field: str | None
    detail: str


class PlanCheckReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issues: list[CheckIssue]
    disclaimer: str = CLAIM_CHECK_DISCLAIMER
    rule_count: int = Field(default=0, ge=0)
    substantiation_observations: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def passed(self) -> bool:
        """No deterministic failure; unknowns and rule coverage remain separate."""
        return not any(issue.severity == CheckSeverity.fail for issue in self.issues)

    @computed_field
    @property
    def unknown_count(self) -> int:
        return sum(issue.severity == CheckSeverity.unknown for issue in self.issues)

    @computed_field
    @property
    def unknown_codes(self) -> dict[str, int]:
        return dict(
            Counter(
                issue.code.value
                for issue in self.issues
                if issue.severity == CheckSeverity.unknown
            )
        )


def validate_plan(data: dict) -> tuple[Plan | None, list[CheckIssue]]:
    """Convert Pydantic errors to domain issues without echoing input values."""
    try:
        return Plan.model_validate(data), []
    except ValidationError as error:
        issues = []
        for item in error.errors(include_input=False, include_url=False):
            field = ""
            for part in item.get("loc", ()):
                if isinstance(part, int):
                    field += f"[{part}]"
                else:
                    field += f".{part}" if field else part
            issues.append(
                CheckIssue(
                    code=CheckCode.TAXONOMY_INVALID,
                    severity=CheckSeverity.fail,
                    field=field or None,
                    detail=f"기획안 형식·분류 검증 실패: {field} ({item.get('type')})",
                )
            )
        return None, issues
