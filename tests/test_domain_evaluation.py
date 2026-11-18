"""Pure evaluation contracts with synthetic deterministic reports."""

import inspect

import pytest
from pydantic import ValidationError

from beautyads.domain import evaluation
from beautyads.domain.claims import CLAIM_CHECK_DISCLAIMER
from beautyads.domain.evaluation import (
    PASS_MIN_SCORE,
    EvaluationReport,
    EvaluationScores,
    low_items,
)
from beautyads.domain.plan import CheckIssue, PlanCheckReport


def check_report(severity="unknown"):
    return PlanCheckReport(
        issues=[
            CheckIssue(
                code="EFFICACY_UNKNOWN",
                severity=severity,
                field=None,
                detail="synthetic",
            )
        ]
    ).model_dump(mode="json")


def test_threshold_annotation_and_boundary():
    assert PASS_MIN_SCORE == 3
    line = next(
        line
        for line in inspect.getsource(evaluation).splitlines()
        if line.startswith("PASS_MIN_SCORE =")
    )
    assert "잠정값, 최종 평가 전 동결" in line
    assert low_items(EvaluationScores(differentiation=2, fit=3, rationale="")) == [
        "differentiation"
    ]
    assert low_items(EvaluationScores(differentiation=3, fit=2, rationale="")) == [
        "fit"
    ]
    assert low_items(EvaluationScores(differentiation=2, fit=2, rationale="")) == [
        "differentiation",
        "fit",
    ]
    assert low_items(EvaluationScores(differentiation=3, fit=3, rationale="")) == []


@pytest.mark.parametrize("value", [0, 6, True, 2.5, "3"])
@pytest.mark.parametrize("field", ["differentiation", "fit"])
def test_invalid_scores(value, field):
    with pytest.raises(ValidationError):
        EvaluationScores(
            **{"differentiation": 3, "fit": 3, "rationale": "", field: value}
        )


def test_rationale_limit():
    EvaluationScores(differentiation=3, fit=3, rationale="가" * 200)
    with pytest.raises(ValidationError):
        EvaluationScores(differentiation=3, fit=3, rationale="가" * 201)


@pytest.mark.parametrize(
    "status", [{}, {"hydration": "supported"}, {"hydration": "unknown"}]
)
def test_unknowns_and_efficacy_are_separate_from_pass(status):
    checks = check_report()
    report = EvaluationReport(
        check_report=checks,
        scores={"differentiation": 3, "fit": 3, "rationale": ""},
        efficacy_status=status,
    )
    dumped = report.model_dump()
    assert dumped["passed"] is True
    assert dumped["unknown_count"] == checks["unknown_count"] == 1
    assert dumped["unknown_codes"] == checks["unknown_codes"]
    assert dumped["efficacy_status"] == status
    assert dumped["efficacy_summary"] == {
        "supported": list(status.values()).count("supported"),
        "unknown": list(status.values()).count("unknown"),
    }
    assert report.disclaimer == CLAIM_CHECK_DISCLAIMER
    assert report.scoring_failed is False


@pytest.mark.parametrize(
    "severity,score", [("fail", 3), ("unknown", 2), ("unknown", None)]
)
def test_failed_checks_low_scores_or_missing_scores_never_pass(severity, score):
    report = EvaluationReport(
        check_report=check_report(severity),
        scores=None
        if score is None
        else {"differentiation": score, "fit": 3, "rationale": ""},
        efficacy_status={},
    )
    assert not report.passed
    assert report.scoring_failed == (score is None)
    assert report.low_items == (
        [] if score is None or score == 3 else ["differentiation"]
    )
