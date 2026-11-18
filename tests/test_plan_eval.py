"""Plan/evaluation loops use synthetic functions, never services or stored data."""

import json
from copy import deepcopy

import pytest
from langgraph.graph import START, StateGraph

from beautyads.agents import plan_eval
from beautyads.agents.plan_eval import (
    PlanEvalState,
    build_plan_eval_graph,
    initial_plan_eval_state,
    run_plan_eval,
)
from beautyads.agents.planning import PlanResult
from beautyads.agents.research import ResearchState
from beautyads.agents.state import AgentState
from beautyads.domain.claims import CLAIM_CHECK_DISCLAIMER
from beautyads.domain.evaluation import EvaluationReport
from beautyads.domain.plan import PlanCheckReport
from beautyads.domain.tenant import summarize_feedback
from beautyads.llm.structured import StructuredFailure


def plan(marker="synthetic-original-plan"):
    return {
        "title": marker,
        "hook_type": "question",
        "hook_text": marker,
        "scenes": [marker],
        "copy_lines": [marker],
        "image_brief": marker,
        "cta_type": "none",
        "angle": "how_to",
        "format": "demo",
        "category": "mask_pack",
        "product_url": None,
        "claimed_efficacy": ["hydration", "soothing"],
        "evidence_ids": ["yt:a"],
    }


def report(*, fail=False, low=False, scoring_failed=False):
    issues = [
        {
            "code": "EFFICACY_UNKNOWN",
            "severity": "unknown",
            "field": "claimed_efficacy",
            "detail": "synthetic unknown reason",
        }
    ]
    if fail:
        issues.append(
            {
                "code": "EVIDENCE_MISSING",
                "severity": "fail",
                "field": "evidence_ids",
                "detail": "synthetic check reason",
            }
        )
    return EvaluationReport(
        check_report=PlanCheckReport(issues=issues).model_dump(mode="json"),
        scores=None
        if scoring_failed
        else {
            "differentiation": 1 if low else 5,
            "fit": 5,
            "rationale": "synthetic score reason",
        },
        efficacy_status={"hydration": "supported", "soothing": "unknown"},
    )


def inputs():
    return {
        "brief": {"goal": "synthetic request"},
        "handoff": {
            "evidence_ids": ["yt:a", "ig:b"],
            "result_counts": [
                {
                    "tool": "find_example_creatives",
                    "row_count": 13,
                    "shown_count": 5,
                    "truncated": True,
                }
            ],
        },
        "profile": {"brand": "synthetic-brand"},
        "feedback": None,
    }


class Planner:
    def __init__(self, fail_at=None):
        self.calls = []
        self.fail_at = fail_at

    def __call__(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        if len(self.calls) == self.fail_at:
            return PlanResult(False, None, StructuredFailure.SCHEMA_VIOLATION, 0.1)
        return PlanResult(True, plan(f"synthetic-plan-{len(self.calls)}"), None, 0.1)


class Evaluator:
    def __init__(self, reports):
        self.reports = iter(reports)
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        return next(self.reports)


def forbidden(*args, **kwargs):
    pytest.fail("this injected boundary must not be called")


@pytest.mark.parametrize(
    "reports,status,reworks",
    [
        ([report()], "done", 0),
        ([report(low=True), report()], "done", 1),
        ([report(fail=True, low=True)] * 3, "needs_review", 2),
    ],
)
def test_counter_limits_attempts(reports, status, reworks):
    planner, evaluator = Planner(), Evaluator(reports)
    result = run_plan_eval(
        **inputs(), plan_fn=planner, evaluate_fn=evaluator, image_fn=forbidden
    )
    assert result["status"] == status
    assert result["rework_count"] == reworks
    assert (
        len(planner.calls)
        == len(evaluator.calls)
        == len(result["attempts"])
        == reworks + 1
    )
    assert result["plan"] == evaluator.calls[-1]["plan"]
    assert result["report"] == reports[-1].model_dump(mode="json")
    assert planner.calls[0]["rework"] is None


@pytest.mark.parametrize("limit", [3, -1, True, 1.5])
def test_invalid_max_reworks_rejected_before_calls(limit):
    with pytest.raises(ValueError, match="MAX_REWORKS_INVALID"):
        run_plan_eval(
            **inputs(), plan_fn=forbidden, evaluate_fn=forbidden, max_reworks=limit
        )


@pytest.mark.parametrize("limit", [0, 1])
def test_lower_rework_limit(limit):
    planner = Planner()
    output = run_plan_eval(
        **inputs(),
        plan_fn=planner,
        evaluate_fn=lambda **kwargs: report(low=True),
        max_reworks=limit,
    )
    assert output["status"] == "needs_review"
    assert output["rework_count"] == limit
    assert len(planner.calls) == limit + 1


def test_rework_contains_only_failed_checks_and_low_score_reasons():
    planner = Planner()
    original_report = report(fail=True, low=True)
    run_plan_eval(
        **inputs(), plan_fn=planner, evaluate_fn=Evaluator([original_report, report()])
    )
    rework = planner.calls[1]["rework"]
    assert rework == {
        "check_issues": [
            {key: issue[key] for key in ("code", "field", "detail")}
            for issue in original_report.check_report["issues"]
            if issue["severity"] == "fail"
        ],
        "low_items": [
            {
                "item": "differentiation",
                "score": 1,
                "rationale": original_report.scores["rationale"],
            }
        ],
    }
    assert "EFFICACY_UNKNOWN" not in json.dumps(rework)
    assert "synthetic-plan-1" not in json.dumps(planner.calls[1])


def test_scoring_failure_is_explicit_and_still_carries_check_failures():
    planner = Planner()
    run_plan_eval(
        **inputs(),
        plan_fn=planner,
        evaluate_fn=Evaluator([report(fail=True, scoring_failed=True), report()]),
    )
    rework = planner.calls[1]["rework"]
    assert rework["scoring_failed"] is True
    assert rework["low_items"] == []
    assert [item["code"] for item in rework["check_issues"]] == ["EVIDENCE_MISSING"]


def test_rework_reasons_cannot_echo_previous_plan_field_values():
    value = report(fail=True, low=True).model_dump(mode="json")
    value["check_report"]["issues"][-1]["detail"] += ": synthetic-plan-1 / yt:a"
    value["scores"]["rationale"] += ": synthetic-plan-1"
    planner = Planner()
    run_plan_eval(**inputs(), plan_fn=planner, evaluate_fn=Evaluator([value, report()]))
    rework = planner.calls[1]["rework"]
    assert "synthetic-plan-1" not in json.dumps(rework)
    assert "yt:a" not in json.dumps(rework)
    assert "synthetic check reason" in rework["check_issues"][0]["detail"]
    assert "synthetic score reason" in rework["low_items"][0]["rationale"]


def primitive(value):
    if type(value) is dict:
        return all(type(k) is str and primitive(v) for k, v in value.items())
    if type(value) is list:
        return all(primitive(v) for v in value)
    return type(value) in (str, int, float, bool, type(None))


def test_state_is_prefixed_disjoint_and_primitive_at_every_superstep():
    keys = set(PlanEvalState.__annotations__)
    assert keys == {
        "pe_brief",
        "pe_handoff",
        "pe_profile",
        "pe_feedback",
        "pe_plan",
        "pe_report",
        "pe_rework_count",
        "pe_rework_payload",
        "pe_attempts",
        "pe_image",
        "pe_status",
    }
    assert keys.isdisjoint(AgentState.__annotations__)
    assert keys.isdisjoint(ResearchState.__annotations__)
    graph = build_plan_eval_graph(
        plan_fn=Planner(), evaluate_fn=lambda **kwargs: report(low=True)
    )
    snapshots = list(
        graph.stream(
            initial_plan_eval_state(**inputs()),
            {"recursion_limit": 10},
            stream_mode="values",
        )
    )
    assert all(set(state) == keys and primitive(state) for state in snapshots)
    assert {state["pe_rework_count"] for state in snapshots} == {0, 1, 2}
    assert snapshots[-1]["pe_status"] == "needs_review"


def test_counter_finishes_even_with_small_safety_margin(monkeypatch):
    monkeypatch.setattr(plan_eval, "_RECURSION_LIMIT", 4)
    output = run_plan_eval(
        **inputs(),
        plan_fn=Planner(),
        evaluate_fn=lambda **kwargs: report(low=True),
        max_reworks=0,
    )
    assert output["status"] == "needs_review" and output["rework_count"] == 0


@pytest.mark.parametrize("evaluated", [False, True])
def test_safety_net_catches_synthetic_runaway_loop_and_preserves_last_state(
    monkeypatch, evaluated
):
    def build(**kwargs):
        def loop(state):
            return {
                "pe_plan": plan(),
                "pe_report": report().model_dump(mode="json") if evaluated else None,
            }

        graph = StateGraph(PlanEvalState)
        graph.add_node("loop", loop)
        graph.add_edge(START, "loop")
        graph.add_edge("loop", "loop")
        return graph.compile()

    monkeypatch.setattr(plan_eval, "build_plan_eval_graph", build)
    monkeypatch.setattr(plan_eval, "_RECURSION_LIMIT", 2)
    output = run_plan_eval(**inputs(), plan_fn=forbidden, evaluate_fn=forbidden)
    assert output["status"] == ("needs_review" if evaluated else "failed")
    assert output["plan"] == plan()
    assert output["rework_count"] == 0


@pytest.mark.parametrize(
    "image_result",
    [{"ok": True, "path": "synthetic.png"}, {"ok": False, "code": "IMAGE_MISSING"}],
)
def test_image_runs_once_after_all_reworks_and_keeps_plan_report(image_result):
    calls = []

    def image_fn(value):
        calls.append(deepcopy(value))
        return image_result

    output = run_plan_eval(
        **inputs(),
        plan_fn=Planner(),
        evaluate_fn=lambda **kwargs: report(low=True),
        image_fn=image_fn,
        with_image=True,
    )
    assert output["status"] == "needs_review" and output["rework_count"] == 2
    assert calls == [output["plan"]]
    assert output["report"] == report(low=True).model_dump(mode="json")
    assert output["image"] == image_result


@pytest.mark.parametrize("missing", [False, True])
def test_image_exception_or_missing_function_is_a_safe_failure(missing):
    def image_fn(value):
        raise RuntimeError("synthetic private diagnostic")

    output = run_plan_eval(
        **inputs(),
        plan_fn=Planner(),
        evaluate_fn=lambda **kwargs: report(),
        image_fn=None if missing else image_fn,
        with_image=True,
    )
    assert output["status"] == "done"
    assert output["plan"] is not None and output["report"] is not None
    assert output["image"] == {
        "ok": False,
        "code": "IMAGE_FN_MISSING" if missing else "IMAGE_FAILED",
    }
    assert "synthetic private diagnostic" not in json.dumps(output)


@pytest.mark.parametrize("fail_at", [1, 2])
def test_structured_planning_failure_stops_without_stale_report_or_image(fail_at):
    output = run_plan_eval(
        **inputs(),
        plan_fn=Planner(fail_at=fail_at),
        evaluate_fn=lambda **kwargs: report(low=True),
        image_fn=forbidden,
        with_image=True,
    )
    assert output["status"] == "failed"
    assert (
        output["plan"] is None and output["report"] is None and output["image"] is None
    )
    assert len(output["attempts"]) == fail_at


@pytest.mark.parametrize("passed", [False, True])
def test_unknowns_efficacy_counts_and_disclaimer_are_separate(passed):
    final_report = report(low=not passed)
    source = inputs()
    output = run_plan_eval(
        **source,
        plan_fn=Planner(),
        evaluate_fn=lambda **kwargs: final_report,
        max_reworks=0,
    )
    assert set(output) == {
        "status",
        "plan",
        "report",
        "rework_count",
        "attempts",
        "image",
        "unknown_count",
        "unknown_codes",
        "efficacy_status",
        "efficacy_summary",
        "result_counts",
        "evidence_counts",
        "disclaimer",
    }
    assert output["report"]["passed"] is passed
    for key in (
        "unknown_count",
        "unknown_codes",
        "efficacy_status",
        "efficacy_summary",
    ):
        assert output[key] == final_report.model_dump(mode="json")[key]
    assert output["unknown_count"] == 1
    assert output["efficacy_summary"] == {"supported": 1, "unknown": 1}
    assert output["disclaimer"] == CLAIM_CHECK_DISCLAIMER
    assert output["result_counts"] == source["handoff"]["result_counts"]
    assert output["evidence_counts"] == {"in_plan": 1, "in_pool": 2}
    assert primitive(output)
    output["result_counts"][0]["row_count"] = 0
    assert source["handoff"]["result_counts"][0]["row_count"] == 13


def test_attempt_summaries_and_injected_feedback_without_mutating_inputs():
    from datetime import date

    source = inputs()
    source["feedback"] = summarize_feedback([], as_of=date(2026, 1, 1)).model_dump(
        mode="json"
    )
    original = deepcopy(source)
    planner = Planner()
    reports = [report(fail=True, low=True), report()]
    evaluator = Evaluator(
        [{**value.model_dump(mode="json"), "cost_usd": 0.02} for value in reports]
    )
    output = run_plan_eval(**source, plan_fn=planner, evaluate_fn=evaluator)
    assert source == original
    assert all(call["feedback"] == source["feedback"] for call in planner.calls)
    for index, attempt in enumerate(output["attempts"]):
        assert attempt["attempt"] == index + 1
        assert attempt["checks_passed"] is reports[index].check_report["passed"]
        assert attempt["scores"] == reports[index].scores
        assert attempt["low_items"] == reports[index].low_items
        assert attempt["failed_check_codes"] == (
            ["EVIDENCE_MISSING"] if index == 0 else []
        )
        assert attempt["cost_usd"] == pytest.approx(0.12)


def test_mutating_injected_functions_cannot_change_inputs_or_final_artifacts():
    source = inputs()
    original = deepcopy(source)

    def planner(**kwargs):
        kwargs["handoff"].clear()
        kwargs["brief"].clear()
        kwargs["profile"].clear()
        return PlanResult(True, plan(), None, 0.1)

    def evaluator(**kwargs):
        kwargs["plan"].clear()
        return report()

    def image_fn(value):
        value.clear()
        return {"ok": True}

    output = run_plan_eval(
        **source,
        plan_fn=planner,
        evaluate_fn=evaluator,
        image_fn=image_fn,
        with_image=True,
    )
    assert source == original
    assert output["plan"] == plan()


def test_cost_not_available_from_evaluation_report_is_not_reported_as_zero():
    output = run_plan_eval(
        **inputs(), plan_fn=Planner(), evaluate_fn=lambda **kwargs: report()
    )
    assert output["attempts"][0]["cost_usd"] is None
    assert output["attempts"][0]["plan_cost_usd"] == 0.1
    assert output["attempts"][0]["evaluation_cost_usd"] is None


@pytest.mark.parametrize(
    "low,fail,scoring_failed",
    [
        (False, False, False),
        (True, False, False),
        (False, False, True),
        (False, True, False),
    ],
)
def test_attempt_distinguishes_checks_from_final_pass(low, fail, scoring_failed):
    value = report(low=low, fail=fail, scoring_failed=scoring_failed)
    result = run_plan_eval(
        **inputs(), plan_fn=Planner(), evaluate_fn=lambda **kw: value, max_reworks=0
    )
    attempt = result["attempts"][0]
    assert "passed" not in attempt
    assert attempt["checks_passed"] is (not fail)
    assert attempt["final_passed"] is value.passed


def test_unevaluated_attempt_has_two_unknown_pass_fields():
    result = run_plan_eval(
        **inputs(), plan_fn=Planner(fail_at=1), evaluate_fn=forbidden
    )
    attempt = result["attempts"][0]
    assert "passed" not in attempt
    assert attempt["checks_passed"] is attempt["final_passed"] is None
