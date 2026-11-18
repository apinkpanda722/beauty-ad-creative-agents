"""Isolated, counter-bounded plan/evaluation subgraph with injected boundaries."""

import re
from copy import deepcopy
from math import isfinite
from typing import TypedDict

from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from beautyads.domain.claims import CLAIM_CHECK_DISCLAIMER
from beautyads.domain.evaluation import EvaluationReport

# Three sequential nodes per attempt, at most three attempts, plus a margin.
# The route node's counter, never this superstep budget, controls reworks.
_RECURSION_LIMIT = 3 * 3 + 1


class PlanEvalState(TypedDict):
    pe_brief: dict
    pe_handoff: dict
    pe_profile: dict
    pe_feedback: dict | None
    pe_plan: dict | None
    pe_report: dict | None
    pe_rework_count: int
    pe_rework_payload: dict | None
    pe_attempts: list[dict]
    pe_image: dict | None
    pe_status: str


def _copy_json(value):
    """Own every nested value; reject objects before they can enter state."""
    if type(value) is dict and all(type(key) is str for key in value):
        return {key: _copy_json(item) for key, item in value.items()}
    if type(value) is list:
        return [_copy_json(item) for item in value]
    if type(value) in (str, int, bool, type(None)):
        return value
    if type(value) is float and isfinite(value):
        return value
    raise ValueError("PLAN_EVAL_NON_JSON_VALUE")


def initial_plan_eval_state(
    *, brief: dict, handoff: dict, profile: dict, feedback: dict | None
) -> PlanEvalState:
    return _copy_json(
        {
            "pe_brief": brief,
            "pe_handoff": handoff,
            "pe_profile": profile,
            "pe_feedback": feedback,
            "pe_plan": None,
            "pe_report": None,
            "pe_rework_count": 0,
            "pe_rework_payload": None,
            "pe_attempts": [],
            "pe_image": None,
            "pe_status": "pending",
        }
    )


def _get(value, key, default=None):
    return (
        value.get(key, default)
        if isinstance(value, dict)
        else getattr(value, key, default)
    )


def _cost(value) -> float | None:
    cost = _get(value, "cost_usd")
    return (
        float(cost)
        if type(cost) in (int, float) and isfinite(cost) and cost >= 0
        else None
    )


def _rework(plan: dict, report: dict) -> dict:
    # Check details can quote invalid IDs, and a scorer can echo plan prose.
    # Retain the reason, but do not replay any prior plan string field values.
    values = set()

    def collect(value):
        if isinstance(value, str) and value:
            values.add(value)
        elif isinstance(value, dict):
            for item in value.values():
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(plan)
    pattern = (
        re.compile(
            "|".join(
                re.escape(value) for value in sorted(values, key=len, reverse=True)
            )
        )
        if values
        else None
    )

    def reason(value):
        return pattern.sub("[omitted]", value) if pattern else value

    scores = report["scores"]
    payload = {
        "check_issues": [
            {
                "code": issue["code"],
                "field": issue.get("field"),
                "detail": reason(issue["detail"]),
            }
            for issue in report["check_report"].get("issues", [])
            if issue.get("severity") == "fail"
        ],
        "low_items": [
            {
                "item": item,
                "score": scores[item],
                "rationale": reason(scores["rationale"]),
            }
            for item in report["low_items"]
        ],
    }
    if report["scoring_failed"]:
        payload["scoring_failed"] = True
    return payload


def build_plan_eval_graph(*, plan_fn, evaluate_fn, max_reworks: int = 2):
    """Inject make_plan/evaluate_plan wrappers; never resolve services here.

    plan_fn returns PlanResult (or a dict with the same fields). evaluate_fn
    returns EvaluationReport or its JSON dict. A wrapper may add cost_usd to
    that dict; absent evaluation cost stays unknown rather than becoming zero.
    """
    if type(max_reworks) is not int or not 0 <= max_reworks <= 2:
        raise ValueError("MAX_REWORKS_INVALID")

    def plan(state: PlanEvalState):
        result = plan_fn(
            **deepcopy(
                {
                    "brief": state["pe_brief"],
                    "handoff": state["pe_handoff"],
                    "profile": state["pe_profile"],
                    "feedback": state["pe_feedback"],
                    "rework": state["pe_rework_payload"],
                }
            )
        )
        attempt = {
            "attempt": len(state["pe_attempts"]) + 1,
            "checks_passed": None,
            "final_passed": None,
            "scores": None,
            "low_items": [],
            "failed_check_codes": [],
            "plan_cost_usd": _cost(result),
            "evaluation_cost_usd": None,
            "cost_usd": None,
        }
        ok = bool(_get(result, "ok")) and isinstance(_get(result, "plan"), dict)
        if not ok:
            failure = _get(result, "failure")
            attempt["planning_failure"] = (
                str(failure) if failure is not None else "PLANNING_FAILED"
            )
            attempt["cost_usd"] = _cost(result)
        return Command(
            update={
                "pe_plan": _copy_json(_get(result, "plan")) if ok else None,
                "pe_report": None,
                "pe_status": "running" if ok else "failed",
                "pe_attempts": [*state["pe_attempts"], attempt],
            },
            goto="evaluate" if ok else END,
        )

    def evaluate(state: PlanEvalState):
        result = evaluate_fn(
            plan=deepcopy(state["pe_plan"]),
            brief=deepcopy(state["pe_brief"]),
            handoff=deepcopy(state["pe_handoff"]),
        )
        if isinstance(result, EvaluationReport):
            report = result.model_dump(mode="json")
        else:
            report = EvaluationReport.model_validate(
                {
                    key: result[key]
                    for key in EvaluationReport.model_fields
                    if key in result
                }
            ).model_dump(mode="json")
        attempt = deepcopy(state["pe_attempts"][-1])
        evaluation_cost = _cost(result)
        plan_cost = attempt["plan_cost_usd"]
        attempt.update(
            checks_passed=bool(report["check_report"].get("passed")),
            final_passed=report["passed"],
            scores=report["scores"],
            low_items=report["low_items"],
            failed_check_codes=list(
                dict.fromkeys(
                    issue["code"]
                    for issue in report["check_report"].get("issues", [])
                    if issue.get("severity") == "fail"
                )
            ),
            evaluation_cost_usd=evaluation_cost,
            cost_usd=plan_cost + evaluation_cost
            if plan_cost is not None and evaluation_cost is not None
            else None,
        )
        return _copy_json(
            {
                "pe_report": report,
                "pe_attempts": [*state["pe_attempts"][:-1], attempt],
            }
        )

    def route(state: PlanEvalState):
        if state["pe_report"]["passed"]:
            return Command(update={"pe_status": "done"}, goto=END)
        if state["pe_rework_count"] >= max_reworks:
            return Command(update={"pe_status": "needs_review"}, goto=END)
        return Command(
            update={
                "pe_rework_count": state["pe_rework_count"] + 1,
                "pe_rework_payload": _rework(state["pe_plan"], state["pe_report"]),
            },
            goto="plan",
        )

    graph = StateGraph(PlanEvalState)
    graph.add_node("plan", plan, destinations=("evaluate", END))
    graph.add_node("evaluate", evaluate)
    graph.add_node("route", route, destinations=("plan", END))
    graph.add_edge(START, "plan")
    graph.add_edge("evaluate", "route")
    return graph.compile()


def run_plan_eval(
    *,
    brief: dict,
    handoff: dict,
    profile: dict,
    feedback: dict | None,
    plan_fn,
    evaluate_fn,
    image_fn=None,
    with_image: bool = False,
    max_reworks: int = 2,
) -> dict:
    """Map caller dictionaries to private state, then return final UI fields."""
    graph = build_plan_eval_graph(
        plan_fn=plan_fn, evaluate_fn=evaluate_fn, max_reworks=max_reworks
    )
    state = initial_plan_eval_state(
        brief=brief, handoff=handoff, profile=profile, feedback=feedback
    )
    try:
        for snapshot in graph.stream(
            state, {"recursion_limit": _RECURSION_LIMIT}, stream_mode="values"
        ):
            state = _copy_json(snapshot)
    except GraphRecursionError:
        # Keep the last completed superstep without a checkpointer or replay.
        # A fresh plan clears its predecessor's report, so mismatched pairs
        # cannot become a reviewed result when the safety net fires.
        state["pe_status"] = (
            "needs_review"
            if state["pe_plan"] is not None and state["pe_report"] is not None
            else "failed"
        )
    if with_image and state["pe_status"] in {"done", "needs_review"}:
        if image_fn is None:
            state["pe_image"] = {"ok": False, "code": "IMAGE_FN_MISSING"}
        else:
            try:
                image = _copy_json(image_fn(deepcopy(state["pe_plan"])))
                if not isinstance(image, dict) or type(image.get("ok")) is not bool:
                    raise ValueError("IMAGE_RESULT_INVALID")
                state["pe_image"] = image
            except Exception:  # noqa: BLE001 -- image failure must preserve the plan, without diagnostics
                state["pe_image"] = {"ok": False, "code": "IMAGE_FAILED"}
    report = state["pe_report"] or {}
    plan = state["pe_plan"] or {}
    return _copy_json(
        {
            "status": state["pe_status"],
            "plan": state["pe_plan"],
            "report": state["pe_report"],
            "rework_count": state["pe_rework_count"],
            "attempts": state["pe_attempts"],
            "image": state["pe_image"],
            "unknown_count": report.get("unknown_count", 0),
            "unknown_codes": report.get("unknown_codes", {}),
            "efficacy_status": report.get("efficacy_status", {}),
            "efficacy_summary": report.get(
                "efficacy_summary", {"supported": 0, "unknown": 0}
            ),
            "result_counts": state["pe_handoff"].get("result_counts", []),
            "evidence_counts": {
                "in_plan": len(set(plan.get("evidence_ids") or [])),
                "in_pool": len(set(state["pe_handoff"].get("evidence_ids") or [])),
            },
            "disclaimer": CLAIM_CHECK_DISCLAIMER,
        }
    )
