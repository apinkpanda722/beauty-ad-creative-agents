"""Subjective scores and deterministic reports, with uncertainty kept separate."""

from collections import Counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from beautyads.domain.claims import CLAIM_CHECK_DISCLAIMER

PASS_MIN_SCORE = 3  # 잠정값, 최종 평가 전 동결


class EvaluationScores(BaseModel):
    model_config = ConfigDict(extra="forbid")

    differentiation: int = Field(ge=1, le=5, strict=True)
    fit: int = Field(ge=1, le=5, strict=True)
    rationale: str = Field(max_length=200)


def low_items(scores: EvaluationScores) -> list[str]:
    return [
        item
        for item in ("differentiation", "fit")
        if getattr(scores, item) < PASS_MIN_SCORE
    ]


class EvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check_report: dict
    scores: dict | None
    efficacy_status: dict[str, str]
    disclaimer: Literal[CLAIM_CHECK_DISCLAIMER] = CLAIM_CHECK_DISCLAIMER

    @field_validator("scores")
    @classmethod
    def validate_scores(cls, value: dict | None) -> dict | None:
        return (
            EvaluationScores.model_validate(value).model_dump()
            if value is not None
            else None
        )

    @computed_field
    @property
    def low_items(self) -> list[str]:
        return (
            low_items(EvaluationScores.model_validate(self.scores))
            if self.scores is not None
            else []
        )

    @computed_field
    @property
    def scoring_failed(self) -> bool:
        return self.scores is None

    @computed_field
    @property
    def passed(self) -> bool:
        return (
            bool(self.check_report.get("passed"))
            and not self.scoring_failed
            and not self.low_items
        )

    @computed_field
    @property
    def unknown_count(self) -> int:
        return self.check_report.get("unknown_count", 0)

    @computed_field
    @property
    def unknown_codes(self) -> dict[str, int]:
        return dict(self.check_report.get("unknown_codes", {}))

    @computed_field
    @property
    def efficacy_summary(self) -> dict[str, int]:
        counts = Counter(self.efficacy_status.values())
        # Alternate injected lookups may explicitly report unsupported; retain
        # that bucket too rather than silently losing a claimed efficacy.
        return {"supported": 0, "unknown": 0, **counts}
