"""Research briefs and handoffs, independent of model and graph transports."""

from collections.abc import Iterable
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from beautyads.domain.labels import Angle, Category, Claim, Format, HookType
from beautyads.domain.skin import SkinConcern


class ResearchBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: str
    category: Literal[Category.mask_pack, Category.serum_ampoule, Category.sun_care]
    claim: Claim | None = None
    hook_type: HookType | None = None
    angle: Angle | None = None
    format: Format | None = None
    skin_concern: SkinConcern | None = None
    output: Literal["patterns", "examples", "both"]
    max_tool_calls: int = Field(default=6, ge=1, le=10)


class ResearchStatus(StrEnum):
    ok = "ok"
    no_evidence = "no_evidence"
    failed = "failed"


class Confidence(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"


class ResearchHandoffDraft(BaseModel):
    """Only these fields may be authored by the structured generator."""

    model_config = ConfigDict(extra="forbid")

    conclusion: str
    evidence_ids: list[str]
    aggregates: dict[str, Any]
    confidence: Confidence
    unresolved: list[str]


class ResultCount(BaseModel):
    """Counts derived from one tool call, independently of generated prose."""

    tool: str
    row_count: int
    shown_count: int

    @computed_field
    @property
    def truncated(self) -> bool:
        return self.shown_count < self.row_count


class ResearchHandoff(ResearchHandoffDraft):
    status: ResearchStatus
    no_evidence_tools: list[str]
    basis_notes: list[str]
    structured_failure_rate: float | None = Field(ge=0, le=1)
    result_counts: list[ResultCount] = Field(default_factory=list)


def count_label(row_count: int, shown_count: int) -> str:
    """Render validated total and displayed counts for screens and evaluations."""
    if row_count < 0 or shown_count < 0 or shown_count > row_count:
        raise ValueError("RESULT_COUNT_INVALID")
    if shown_count == row_count:
        return f"{row_count}건"
    return f"{row_count}건 중 {shown_count}건 표시"


def restrict_evidence_ids(
    claimed: Iterable[str], pool: Iterable[str]
) -> tuple[list[str], list[str]]:
    """Return unique, sorted allowed IDs and the separately rejected IDs."""
    claimed_ids, pool_ids = set(claimed), set(pool)
    return sorted(claimed_ids & pool_ids), sorted(claimed_ids - pool_ids)
