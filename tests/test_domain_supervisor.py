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


def comparison_rows(*pairs, total):
    return {
        "tool": "compare_axis_by_category",
        "rows": [
            {
                "value": value,
                "creatives": count,
                "creative_ids": ["yt:synthetic"],
                "total": total,
            }
            for value, count in pairs
        ],
    }


def test_pattern_alignment_combines_counts_ties_shares_and_preserves_inputs():
    from beautyads.domain.supervisor import pattern_alignment

    plan = {"hook_type": "question", "angle": "how_to", "format": "demo"}
    outputs = [
        comparison_rows(("question", 2), ("problem", 4), total=6),
        comparison_rows(("question", 3), ("problem", 1), total=4),
        comparison_rows(("how_to", 1), ("desire", 3), total=4),
    ]
    before = deepcopy((plan, outputs))
    result = pattern_alignment(plan, outputs)
    assert result == {
        "axes": {
            "hook_type": {
                "plan": "question",
                "dominant": ["problem", "question"],
                "same": True,
                "share": 0.5,
            },
            "angle": {
                "plan": "how_to",
                "dominant": ["desire"],
                "same": False,
                "share": 0.25,
            },
            "format": {"plan": "demo", "dominant": [], "same": None, "share": None},
        },
        "compared": 2,
        "same_count": 1,
        "skipped": 0,
    }
    assert (plan, outputs) == before
    result["axes"]["hook_type"]["dominant"].append("changed")
    assert (plan, outputs) == before


def test_pattern_alignment_infers_only_one_closed_axis_and_counts_skips():
    from beautyads.domain.supervisor import pattern_alignment

    outputs = [
        comparison_rows(("other", 7), total=7),
        comparison_rows(("question", 1), ("demo", 1), total=2),
        comparison_rows(("unknown", 1), total=1),
        comparison_rows(total=0),
        comparison_rows(("question", 2), ("other", 3), total=5),
        comparison_rows(("demo", 0), total=0),
        {"tool": "other_tool", "rows": [{"value": "question", "creatives": 99}]},
    ]
    result = pattern_alignment(
        {"hook_type": "other", "angle": "desire", "format": "static_image"}, outputs
    )
    assert result["skipped"] == 4
    assert result["compared"] == 2 and result["same_count"] == 1
    assert result["axes"]["hook_type"] == {
        "plan": "other",
        "dominant": ["other"],
        "same": True,
        "share": 0.6,
    }
    assert result["axes"]["angle"]["same"] is None
    assert result["axes"]["format"]["same"] is False
    assert result["axes"]["format"]["share"] is None
    present_zero = pattern_alignment({"format": "demo"}, [outputs[5]])
    assert present_zero["axes"]["format"]["share"] is None


def test_pattern_context_thresholds_pool_and_alignment_are_pure():
    import json
    from fractions import Fraction

    from beautyads.domain.labels import Angle
    from beautyads.domain.supervisor import (
        MIN_DOMINANT_SHARE,
        THIN_POOL_MAX,
        pattern_alignment,
        pattern_context,
    )

    boundary = Fraction(str(MIN_DOMINANT_SHARE))
    outputs = [
        comparison_rows(("question", boundary.numerator), total=boundary.denominator),
        comparison_rows(*[(value.value, 1) for value in Angle], total=100),
        comparison_rows(("demo", 5), total=8),
        comparison_rows(("demo", 1), total=2),
    ]
    before = deepcopy(outputs)
    context = pattern_context(outputs, ["yt:a", "yt:a"])
    assert context["pool_size"] == 100 and context["pool_basis"] == "axis_total"
    assert context["min_dominant_share"] == MIN_DOMINANT_SHARE
    assert context["thin_pool_max"] == THIN_POOL_MAX
    assert not context["thin_pool"]
    assert context["weak_axes"] == ["angle"]
    assert context["dominant_axes"] == [
        {"axis": "hook_type", "values": ["question"], "share": MIN_DOMINANT_SHARE},
        {"axis": "format", "values": ["demo"], "share": 0.6},
    ]
    alignment = pattern_alignment({}, outputs)
    for item in context["dominant_axes"]:
        assert item["values"] == alignment["axes"][item["axis"]]["dominant"]
    assert outputs == before
    json.dumps(context, allow_nan=False)


@pytest.mark.parametrize("delta", [-1, 0])
def test_pattern_context_thin_pool_boundary_and_evidence_fallback(delta):
    from beautyads.domain.supervisor import THIN_POOL_MAX, pattern_context

    n = THIN_POOL_MAX + delta
    for outputs, basis in (
        ([], "evidence_ids"),
        ([comparison_rows(("demo", n), total=n)], "axis_total"),
    ):
        context = pattern_context(outputs, [*[f"yt:{i}" for i in range(n)], "yt:0"])
        assert context["pool_size"] == n and context["pool_basis"] == basis
        assert context["thin_pool"] is (delta < 0)


@pytest.mark.parametrize(
    "pairs,total,top,second,value",
    [
        ([("question", 5), ("problem", 3), ("other", 2)], 10, 0.5, 0.3, "question"),
        ([("question", 4), ("problem", 4), ("other", 2)], 10, 0.4, 0.2, "problem"),
        ([("question", 5)], 5, 1.0, None, "question"),
        ([("question", 0), ("problem", 0)], 0, None, None, "problem"),
        ([("question", 1)], None, None, None, "question"),
    ],
)
def test_pattern_context_distribution_ranks_and_unknown_totals(
    pairs, total, top, second, value
):
    from beautyads.domain.supervisor import MIN_DOMINANT_SHARE, pattern_context

    context = pattern_context([comparison_rows(*pairs, total=total)], [])
    assert context["distribution"] == [
        {
            "axis": "hook_type",
            "total": total,
            "top_share": top,
            "second_share": second,
            "top_value": value,
        }
    ]
    dominant_share = (
        sum(count for _, count in pairs if count == max(n for _, n in pairs)) / total
        if total
        else None
    )
    assert bool(context["dominant_axes"]) is (
        dominant_share is not None and dominant_share >= MIN_DOMINANT_SHARE
    )


def test_pattern_context_skips_ambiguous_invalid_and_unrelated_outputs():
    from beautyads.domain.supervisor import pattern_context

    outputs = [
        comparison_rows(("other", 5), total=5),
        comparison_rows(("question", 1), ("demo", 1), total=2),
        comparison_rows(("SYNTHETIC-private-value", 1), total=1000),
        comparison_rows(("question", -1), total=1),
        comparison_rows(total=0),
        {
            "tool": "top_vs_bottom_axis",
            "rows": [{"value": "question", "creatives": 7, "total": 7}],
        },
        None,
    ]
    context = pattern_context(outputs, ["yt:a", "yt:a", "yt:b"])
    assert (
        context["distribution"]
        == context["dominant_axes"]
        == context["weak_axes"]
        == []
    )
    assert context["pool_size"] == 2 and context["pool_basis"] == "evidence_ids"


def test_pattern_context_combines_same_axis_counts_and_repeated_totals_once():
    from beautyads.domain.supervisor import pattern_alignment, pattern_context

    outputs = [
        comparison_rows(("question", 2), ("problem", 4), total=6),
        comparison_rows(("question", 3), ("problem", 1), total=4),
    ]
    context = pattern_context(outputs, [])
    assert context["pool_size"] == 6
    assert context["distribution"] == [
        {
            "axis": "hook_type",
            "total": 10,
            "top_share": 0.5,
            "second_share": None,
            "top_value": "problem",
        }
    ]
    assert context["dominant_axes"] == [
        {
            "axis": "hook_type",
            "values": pattern_alignment({}, outputs)["axes"]["hook_type"]["dominant"],
            "share": 1.0,
        }
    ]


def test_pattern_context_empty_fixed_axes_preserves_legacy_result():
    import json

    from beautyads.domain.supervisor import pattern_context

    outputs = [comparison_rows(("demo", 5), total=8)]
    original = pattern_context(outputs, ["yt:a"])
    assert set(original) == {
        "pool_size",
        "pool_basis",
        "thin_pool",
        "min_dominant_share",
        "thin_pool_max",
        "dominant_axes",
        "weak_axes",
        "distribution",
    }
    for empty in ((), [], iter(())):
        context = pattern_context(outputs, ["yt:a"], fixed_axes=empty)
        assert context == original
        assert json.dumps(context, allow_nan=False) == json.dumps(
            original, allow_nan=False
        )


@pytest.mark.parametrize(
    "fixed_axes",
    [("format",), ("angle",), ("hook_type",), ("hook_type", "angle", "format")],
)
def test_pattern_context_fixed_axes_only_exclude_classification(fixed_axes):
    import json
    from fractions import Fraction

    from beautyads.domain.supervisor import MIN_DOMINANT_SHARE, pattern_context

    boundary = Fraction(str(MIN_DOMINANT_SHARE))
    outputs = [
        comparison_rows(("question", boundary.numerator), total=boundary.denominator),
        comparison_rows(("desire", 1), total=100),
        comparison_rows(("demo", 5), total=8),
    ]
    ids = ["yt:a", "yt:a"]
    before = deepcopy((outputs, ids))
    original = pattern_context(outputs, ids)
    assert {item["axis"] for item in original["dominant_axes"]} == {
        "hook_type",
        "format",
    }
    assert original["weak_axes"] == ["angle"]
    context = pattern_context(outputs, ids, fixed_axes=fixed_axes)
    assert context == {
        **original,
        "dominant_axes": [
            item for item in original["dominant_axes"] if item["axis"] not in fixed_axes
        ],
        "weak_axes": [axis for axis in original["weak_axes"] if axis not in fixed_axes],
        "fixed_axes": sorted(fixed_axes),
    }
    assert set(fixed_axes) <= {item["axis"] for item in context["distribution"]}
    assert (outputs, ids) == before
    json.dumps(context, allow_nan=False)


@pytest.mark.parametrize("observed", [False, True])
def test_pattern_context_retains_unobserved_fixed_axes(observed):
    from beautyads.domain.supervisor import pattern_context

    outputs = [comparison_rows(("question", 1), total=1)] if observed else []
    original = pattern_context(outputs, ["yt:a"])
    context = pattern_context(outputs, ["yt:a"], fixed_axes=("format", "angle"))
    assert context == {**original, "fixed_axes": ["angle", "format"]}


@pytest.mark.parametrize("fixed_axes", [("unknown",), ("format", "unknown"), ("",)])
def test_pattern_context_rejects_unknown_fixed_axes_without_mutation(fixed_axes):
    from beautyads.domain.supervisor import pattern_context

    outputs = [comparison_rows(("demo", 5), total=8)]
    ids = ["yt:a"]
    before = deepcopy((outputs, ids))
    with pytest.raises(ValueError, match="^PATTERN_FIXED_AXES_INVALID$"):
        pattern_context(outputs, ids, fixed_axes=fixed_axes)
    assert (outputs, ids) == before


def test_pattern_context_fixed_axes_are_sorted_unique_for_iterables():
    from beautyads.domain.supervisor import pattern_context

    axes = ("hook_type", "format", "angle", "format")
    expected = pattern_context([], [], fixed_axes=("angle", "format", "hook_type"))
    assert expected["fixed_axes"] == sorted(set(axes))
    for fixed_axes in (axes, list(reversed(axes)), set(axes), (axis for axis in axes)):
        assert pattern_context([], [], fixed_axes=fixed_axes) == expected


def test_claim_policy_table_is_exact_and_pure():
    from beautyads.domain.supervisor import resolve_claim_policy

    cases = [
        (
            "hydration",
            ["hydration", "soothing"],
            "ok",
            None,
            {
                "action": "proceed",
                "claim": "hydration",
                "claim_choice": {
                    "mode": "selected",
                    "claims": ["hydration"],
                    "requested_claim": "hydration",
                },
                "notice": None,
                "clarification": {},
            },
        ),
        (
            "brightening",
            ["hydration"],
            "ok",
            None,
            {
                "action": "clarify",
                "claim": None,
                "claim_choice": {},
                "notice": None,
                "clarification": {
                    "reason": "requested_not_confirmed",
                    "requested_claim": "brightening",
                    "available_efficacy": ["hydration"],
                    "available_status": "ok",
                    "options": ["keep_requested", "select_confirmed", "none"],
                },
            },
        ),
        (
            "brightening",
            [],
            "ok",
            None,
            {
                "action": "clarify",
                "claim": None,
                "claim_choice": {},
                "notice": None,
                "clarification": {
                    "reason": "requested_not_confirmed",
                    "requested_claim": "brightening",
                    "available_efficacy": [],
                    "available_status": "ok",
                    "options": ["keep_requested", "none"],
                },
            },
        ),
        (
            None,
            ["soothing", "hydration"],
            "ok",
            None,
            {
                "action": "clarify",
                "claim": None,
                "claim_choice": {},
                "notice": None,
                "clarification": {
                    "reason": "no_claim_requested",
                    "requested_claim": None,
                    "available_efficacy": ["soothing", "hydration"],
                    "available_status": "ok",
                    "options": ["select_one", "select_many", "none"],
                },
            },
        ),
        (
            None,
            [],
            "ok",
            None,
            {
                "action": "proceed",
                "claim": None,
                "claim_choice": {"mode": "none", "claims": [], "requested_claim": None},
                "notice": "none_confirmed",
                "clarification": {},
            },
        ),
        (
            "other",
            ["hydration"],
            "ok",
            None,
            {
                "action": "clarify",
                "claim": None,
                "claim_choice": {},
                "notice": None,
                "clarification": {
                    "reason": "no_claim_requested",
                    "requested_claim": None,
                    "available_efficacy": ["hydration"],
                    "available_status": "ok",
                    "options": ["select_one", "select_many", "none"],
                },
            },
        ),
        (
            "other",
            [],
            "ok",
            None,
            {
                "action": "proceed",
                "claim": None,
                "claim_choice": {"mode": "none", "claims": [], "requested_claim": None},
                "notice": "none_confirmed",
                "clarification": {},
            },
        ),
        (
            "brightening",
            ["hydration", "soothing"],
            "ok",
            {
                "mode": "selected",
                "claims": ["soothing", "hydration"],
                "requested_claim": "brightening",
            },
            {
                "action": "proceed",
                "claim": "soothing",
                "claim_choice": {
                    "mode": "selected",
                    "claims": ["soothing", "hydration"],
                    "requested_claim": "brightening",
                },
                "notice": None,
                "clarification": {},
            },
        ),
        (
            None,
            ["hydration"],
            "ok",
            {"mode": "selected", "claims": ["hydration"], "requested_claim": None},
            {
                "action": "proceed",
                "claim": "hydration",
                "claim_choice": {
                    "mode": "selected",
                    "claims": ["hydration"],
                    "requested_claim": None,
                },
                "notice": None,
                "clarification": {},
            },
        ),
        (
            None,
            ["hydration"],
            "ok",
            {
                "mode": "selected",
                "claims": ["hydration", "soothing"],
                "requested_claim": None,
            },
            {
                "action": "invalid",
                "claim": None,
                "claim_choice": {},
                "notice": None,
                "clarification": {},
            },
        ),
        (
            "brightening",
            [],
            "ok",
            {"mode": "keep_requested", "claims": [], "requested_claim": "brightening"},
            {
                "action": "proceed",
                "claim": "brightening",
                "claim_choice": {
                    "mode": "keep_requested",
                    "claims": [],
                    "requested_claim": "brightening",
                },
                "notice": None,
                "clarification": {},
            },
        ),
        (
            None,
            [],
            "ok",
            {"mode": "keep_requested", "claims": [], "requested_claim": "brightening"},
            {
                "action": "invalid",
                "claim": None,
                "claim_choice": {},
                "notice": None,
                "clarification": {},
            },
        ),
        (
            "other",
            [],
            "ok",
            {"mode": "keep_requested", "claims": [], "requested_claim": "brightening"},
            {
                "action": "invalid",
                "claim": None,
                "claim_choice": {},
                "notice": None,
                "clarification": {},
            },
        ),
        (
            "brightening",
            ["hydration"],
            "ok",
            {"mode": "none", "claims": [], "requested_claim": "brightening"},
            {
                "action": "proceed",
                "claim": None,
                "claim_choice": {"mode": "none", "claims": [], "requested_claim": None},
                "notice": None,
                "clarification": {},
            },
        ),
    ]
    # Failed/skipped lookups take precedence even over a confirmed selection.
    for status in ("failed", "skipped"):
        cases.extend(
            [
                (
                    "brightening",
                    [],
                    status,
                    {
                        "mode": "selected",
                        "claims": ["hydration"],
                        "requested_claim": None,
                    },
                    {
                        "action": "proceed",
                        "claim": "brightening",
                        "claim_choice": {
                            "mode": "keep_requested",
                            "claims": [],
                            "requested_claim": "brightening",
                        },
                        "notice": "lookup_unconfirmed",
                        "clarification": {},
                    },
                ),
                (
                    None,
                    [],
                    status,
                    None,
                    {
                        "action": "proceed",
                        "claim": None,
                        "claim_choice": {
                            "mode": "none",
                            "claims": [],
                            "requested_claim": None,
                        },
                        "notice": "lookup_unconfirmed",
                        "clarification": {},
                    },
                ),
            ]
        )
    checked = 0
    for requested, available, status, choice, expected in cases:
        before = deepcopy((available, choice))
        result = resolve_claim_policy(
            requested=requested, available=available, status=status, choice=choice
        )
        assert set(result) == {
            "action",
            "claim",
            "claim_choice",
            "notice",
            "clarification",
        }
        assert result == expected
        assert (available, choice) == before
        checked += 1
    assert checked == len(cases) > 0


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"mode": "invalid"},
        {"mode": "selected"},
        {"mode": "selected", "claims": ["other"]},
        {"mode": "selected", "claims": ["hydration", "hydration"]},
        {"mode": "selected", "claims": ["unknown"]},
        {"mode": "selected", "claims": ["hydration"], "requested_claim": "other"},
        {"mode": "keep_requested"},
        {
            "mode": "keep_requested",
            "requested_claim": "hydration",
            "claims": ["hydration"],
        },
        {"mode": "none", "claims": ["hydration"]},
        *[
            {"mode": "none", field: "synthetic"}
            for field in ("tenant_id", "user_id", "today")
        ],
    ],
)
def test_claim_choice_rejects_each_structure_violation(value):
    from beautyads.domain.supervisor import ClaimChoice

    with pytest.raises(ValidationError):
        ClaimChoice.model_validate(value)


@pytest.mark.parametrize(
    "value,expected",
    [
        (
            {"mode": "selected", "claims": ["hydration", "soothing"]},
            {
                "mode": "selected",
                "claims": ["hydration", "soothing"],
                "requested_claim": None,
            },
        ),
        (
            {"mode": "keep_requested", "requested_claim": "hydration"},
            {"mode": "keep_requested", "claims": [], "requested_claim": "hydration"},
        ),
        ({"mode": "none"}, {"mode": "none", "claims": [], "requested_claim": None}),
    ],
)
def test_claim_choice_has_only_json_request_fields(value, expected):
    from beautyads.domain.supervisor import ClaimChoice, ClarifyOption, ClarifyReason

    assert ClaimChoice.model_validate(value).model_dump(mode="json") == expected
    assert set(ClaimChoice.model_fields) == {"mode", "claims", "requested_claim"}
    assert {item.value for item in ClarifyReason} == {
        "requested_not_confirmed",
        "no_claim_requested",
    }
    assert {item.value for item in ClarifyOption} == {
        "keep_requested",
        "select_confirmed",
        "select_one",
        "select_many",
        "none",
    }


def test_clarification_copy_is_fixed_and_rendered_with_display_names():
    from beautyads.domain import supervisor as policy

    assert (
        policy.CLARIFY_REQUESTED_TEXT
        == "요청하신 '{requested}' 효능은 이 제품의 성분·인증으로 근거가 확인되지 않았습니다. 확인된 효능은 {available}입니다. 어떻게 진행할까요?"
    )
    assert (
        policy.CLARIFY_REQUESTED_NO_CONFIRMED_TEXT
        == "요청하신 '{requested}' 효능은 이 제품의 성분·인증으로 근거가 확인되지 않았습니다. 이 제품에서 근거가 확인된 효능이 없습니다. 어떻게 진행할까요?"
    )
    assert (
        policy.CLARIFY_UNSPECIFIED_TEXT
        == "효능을 지정하지 않으셨습니다. 이 제품에서 근거가 확인된 효능은 {available}입니다. 어떤 효능을 강조할까요?"
    )
    assert (
        policy.OPTION_KEEP_REQUESTED
        == "요청하신 '{requested}'로 진행 (효능을 단정하는 표현은 제한됩니다)"
    )
    assert policy.OPTION_SELECT_CONFIRMED == "확인된 효능 중에서 선택"
    assert policy.OPTION_SELECT_ONE == "한 가지 효능 선택"
    assert policy.OPTION_SELECT_MANY == "여러 효능 선택"
    assert policy.OPTION_NONE == "효능 강조 없이 제품 홍보"
    assert policy.EFFICACY_NOTICE_TEXT == {
        "lookup_unconfirmed": "효능 근거를 확인하지 못해 효능 강조 없이 작성했습니다.",
        "none_confirmed": "이 제품에서 근거가 확인된 효능이 없어 효능 강조 없이 작성했습니다.",
    }
    cases = [
        (
            "brightening",
            ["hydration", "soothing"],
            {
                "text": "요청하신 '미백' 효능은 이 제품의 성분·인증으로 근거가 확인되지 않았습니다. 확인된 효능은 보습, 진정입니다. 어떻게 진행할까요?",
                "options": [
                    {
                        "id": "keep_requested",
                        "label": "요청하신 '미백'로 진행 (효능을 단정하는 표현은 제한됩니다)",
                    },
                    {"id": "select_confirmed", "label": "확인된 효능 중에서 선택"},
                    {"id": "none", "label": "효능 강조 없이 제품 홍보"},
                ],
            },
        ),
        (
            "brightening",
            [],
            {
                "text": "요청하신 '미백' 효능은 이 제품의 성분·인증으로 근거가 확인되지 않았습니다. 이 제품에서 근거가 확인된 효능이 없습니다. 어떻게 진행할까요?",
                "options": [
                    {
                        "id": "keep_requested",
                        "label": "요청하신 '미백'로 진행 (효능을 단정하는 표현은 제한됩니다)",
                    },
                    {"id": "none", "label": "효능 강조 없이 제품 홍보"},
                ],
            },
        ),
        (
            None,
            ["hydration", "soothing"],
            {
                "text": "효능을 지정하지 않으셨습니다. 이 제품에서 근거가 확인된 효능은 보습, 진정입니다. 어떤 효능을 강조할까요?",
                "options": [
                    {"id": "select_one", "label": "한 가지 효능 선택"},
                    {"id": "select_many", "label": "여러 효능 선택"},
                    {"id": "none", "label": "효능 강조 없이 제품 홍보"},
                ],
            },
        ),
    ]
    for requested, available, expected in cases:
        clarification = policy.resolve_claim_policy(
            requested=requested, available=available, status="ok", choice=None
        )["clarification"]
        before = deepcopy(clarification)
        assert (
            policy.clarification_texts(
                clarification,
                {"brightening": "미백", "hydration": "보습", "soothing": "진정"},
            )
            == expected
        )
        assert clarification == before
    fallback = policy.clarification_texts(
        {
            "reason": "requested_not_confirmed",
            "requested_claim": "brightening",
            "available_efficacy": ["hydration"],
            "options": ["keep_requested"],
        },
        {},
    )
    assert fallback == {
        "text": "요청하신 'brightening' 효능은 이 제품의 성분·인증으로 근거가 확인되지 않았습니다. 확인된 효능은 hydration입니다. 어떻게 진행할까요?",
        "options": [
            {
                "id": "keep_requested",
                "label": "요청하신 'brightening'로 진행 (효능을 단정하는 표현은 제한됩니다)",
            }
        ],
    }
