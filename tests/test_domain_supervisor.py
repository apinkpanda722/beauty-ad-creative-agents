"""Pure request contracts and numeric provenance, using synthetic data only."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from beautyads.domain.supervisor import (
    AGGREGATE_UNVERIFIED_PREFIX,
    Intent,
    RequestLimits,
    SupervisorDecision,
    cost_exceeded,
    numbers_in_results,
    trim_handoff,
    trim_message,
    verify_aggregates,
)


def decision_data(**changes):
    return {
        "intent": "plan",
        "category": "mask_pack",
        "claim": None,
        "hook_type": None,
        "angle": None,
        "format": None,
        "skin_concern": None,
        "plan_count": 3,
        "goal": "synthetic goal",
        **changes,
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"intent": "feedback"},
        {"category": "other"},
        {"category": "unknown"},
        *[
            {field: "unknown"}
            for field in ("claim", "hook_type", "angle", "format", "skin_concern")
        ],
        {"plan_count": 0},
        {"plan_count": 4},
        {"unexpected": {}},
    ],
)
def test_decision_rejects_open_values(changes):
    with pytest.raises(ValidationError):
        SupervisorDecision.model_validate(decision_data(**changes))


def test_decision_has_only_closed_fields_and_nullable_category():
    assert set(Intent) == {"pattern", "relation", "plan", "boundary"}
    assert (
        SupervisorDecision.model_validate(decision_data(category=None)).category is None
    )
    schema = SupervisorDecision.model_json_schema()

    def walk(node):
        if isinstance(node, dict):
            assert node.get("additionalProperties") is not True
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema)


@pytest.mark.parametrize(
    "spent,hit", [(0, False), (0.299999, False), (0.30, True), (0.31, True)]
)
def test_text_cost_boundary(spent, hit):
    assert cost_exceeded(spent, RequestLimits()) is hit


def test_limits_are_frozen_and_explicitly_exclude_images():
    limits = RequestLimits()
    assert limits.max_text_cost_usd == 0.30
    with pytest.raises((ValidationError, AttributeError)):
        limits.max_plans = 99


@pytest.mark.parametrize("size", [1, 2000, 2001])
def test_message_trim_boundary(size):
    text, trimmed = trim_message("x" * size, RequestLimits())
    assert text == "x" * min(size, 2000)
    assert trimmed is (size > 2000)


@pytest.mark.parametrize("extra", [0, 1])
def test_handoff_trims_are_reported_and_do_not_mutate(extra):
    original = {
        "evidence_ids": [f"yt:{i}" for i in range(30 + extra)],
        "aggregates": {f"a{i}": "synthetic" for i in range(20 + extra)},
        "unresolved": ["synthetic"],
    }
    before = deepcopy(original)
    handoff, trims = trim_handoff(original, RequestLimits())
    assert len(handoff["evidence_ids"]) == 30
    assert list(handoff["aggregates"]) == list(original["aggregates"])[:20]
    assert trims == (
        [
            {"field": "evidence_ids", "kept": 30, "total": 31},
            {"field": "aggregates", "kept": 20, "total": 21},
        ]
        if extra
        else []
    )
    handoff["unresolved"].append("changed")
    assert original == before


def test_numeric_pool_ignores_ids_dates_summary_and_non_numeric_strings():
    values = [
        {
            "row_count": 7,
            "shown_count": 2,
            "evidence_ids": ["yt:999"],
            "summary": "888",
            "ui_command": {"data": {"value": 777}},
            "top_rows": [
                {
                    "count": 1234,
                    "score": -2.5,
                    "nested": [3, {"count": "7.0"}],
                    "numeric": "1,234",
                    "id": "yt:999",
                    "date": "2026-01-02",
                    "text": "666 examples",
                    "flag": True,
                    "null": None,
                }
            ],
        }
    ]
    assert numbers_in_results(values) == {7.0, 2.0, 1.0, 1234.0, -2.5, 3.0}


def test_verify_aggregates_removes_whole_unverified_items_without_computing():
    aggregates = {
        "direct": "7.0건, 1,234회",
        "words": "synthetic",
        "ratio": "50%",
        "sum": "14건",
        "mixed": "7과 99",
        "tolerance": "0.3000000001",
    }
    kept, unresolved = verify_aggregates(aggregates, {7, 1234, 0.3})
    assert set(kept) == {"direct", "words", "tolerance"}
    assert unresolved == [
        f"aggregate:{name}: 도구 출력에 없는 수치" for name in ("ratio", "sum", "mixed")
    ]
    assert AGGREGATE_UNVERIFIED_PREFIX == "aggregate:"
    assert "ratio" in aggregates


def test_numbers_support_multiple_thousands_and_require_all_tokens():
    kept, removed = verify_aggregates(
        {"a": "-1,234,567.0", "b": "7 / 8"}, {-1234567, 7}
    )
    assert kept == {"a": "-1,234,567.0"}
    assert len(removed) == 1
