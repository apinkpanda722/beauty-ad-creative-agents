"""Supervisor routing, budgets, state isolation and event timing with fakes."""

import json
from copy import deepcopy

import pytest
from test_domain_supervisor import decision_data
from test_research_agent import CTX, primitive
from test_schema_guard import CaptureStructured, strict_violations

from beautyads.agents import supervisor
from beautyads.agents.plan_eval import PlanEvalState
from beautyads.agents.research import ResearchState
from beautyads.agents.state import AgentState
from beautyads.agents.tool_messages import TOOL_DATA_RULE
from beautyads.agents.tools import TOOLS
from beautyads.domain.claims import CLAIM_CHECK_DISCLAIMER
from beautyads.domain.research import ResearchBrief
from beautyads.domain.supervisor import AGGREGATES_LABEL, RequestLimits
from beautyads.llm.structured import StructuredFailure, StructuredResult

AGG = next(tool.name for tool in TOOLS if tool.kind == "aggregate")
LOOKUP = next(tool.name for tool in TOOLS if tool.kind == "lookup")


class Structured(CaptureStructured):
    def generate(self, spec, **options):
        self.calls.append((spec, deepcopy(options)))
        return StructuredResult(True, spec.validate(decision_data()), None, 1, 0, [])


def test_decide_actual_messages_schema_and_fixed_call_options():
    structured = Structured("gpt-6-luna")
    answer = supervisor.decide(
        "x" * 2001, as_of=CTX.as_of, structured=structured, limits=RequestLimits()
    )
    assert answer.ok and answer.trimmed and isinstance(answer.decision, dict)
    spec, options = structured.calls[0]
    assert structured.model == "gpt-6-luna"
    assert (
        options["reasoning_effort"] == supervisor.SUPERVISOR_REASONING_EFFORT == "none"
    )
    assert "temperature" not in options
    assert TOOL_DATA_RULE in options["messages"][0]["content"]
    payload = json.loads(options["messages"][1]["content"])
    assert payload["message"] == "x" * 2000
    assert payload["as_of"] == CTX.as_of.isoformat()
    assert set(payload["supported_categories"]) == {
        "mask_pack",
        "serum_ampoule",
        "sun_care",
    }
    assert set(payload["intents"]) == {"pattern", "relation", "plan", "boundary"}
    assert strict_violations(spec.schema) == []
    assert "ledger_path" in options and options["caps"]["openai"] == 10


def test_decide_structured_failure_is_a_value():
    answer = supervisor.decide(
        "synthetic",
        as_of=CTX.as_of,
        structured=CaptureStructured("gpt-6-luna"),
        limits=RequestLimits(),
    )
    assert not answer.ok and answer.decision is None
    assert answer.failure == StructuredFailure.SCHEMA_VIOLATION


@pytest.mark.parametrize(
    "option", ["temperature", "reasoning_effort", "messages", "model", "thinking"]
)
def test_decide_cannot_override_fixed_parameters(option):
    with pytest.raises(ValueError, match="SUPERVISOR"):
        supervisor.decide(
            "synthetic",
            as_of=CTX.as_of,
            structured=Structured("gpt-6-luna"),
            limits=RequestLimits(),
            **{option: "invalid"},
        )


def handoff(**changes):
    return {
        "status": "ok",
        "conclusion": "synthetic conclusion",
        "evidence_ids": ["yt:a"],
        "aggregates": {"direct": "7건", "invented": "50%", "words": "synthetic"},
        "confidence": "low",
        "unresolved": [],
        "no_evidence_tools": [],
        "basis_notes": [],
        "structured_failure_rate": None,
        "result_counts": [
            {"tool": AGG, "row_count": 7, "shown_count": 1, "truncated": True}
        ],
        **changes,
    }


class Fakes:
    def __init__(self, decision=None, research=None, plan=None):
        self.decision = decision_data() if decision is None else decision
        self.handoff = handoff() if research is None else research
        self.plan = (
            {
                "status": "done",
                "plan": {"title": "synthetic"},
                "rework_count": 0,
                "image": None,
            }
            if plan is None
            else plan
        )
        self.order, self.research_calls, self.plan_calls = [], [], []
        self.cost = 0.01

    def decide(self, message):
        self.order.append("decide")
        return deepcopy(self.decision)

    def research(self, brief, raw_store):
        self.order.append("research")
        self.research_calls.append(deepcopy(brief))
        raw_store["ref"] = {
            "tool": AGG,
            "kind": "aggregate",
            "row_count": 7,
            "shown_count": 1,
            "top_rows": [{"count": 7}],
            "evidence_ids": ["yt:a"],
            "summary": "raw-only",
        }
        return deepcopy(self.handoff)

    def planning(self, brief, handoff, profile, feedback, *, max_reworks):
        self.order.append("plan")
        self.plan_calls.append(
            deepcopy(
                {
                    "brief": brief,
                    "handoff": handoff,
                    "profile": profile,
                    "feedback": feedback,
                    "max_reworks": max_reworks,
                }
            )
        )
        return deepcopy(self.plan)

    def spent(self):
        self.order.append("spent")
        return self.cost

    def event(self, event):
        self.order.append(deepcopy(event))

    def args(self, **changes):
        return {
            "message": "conversation-private",
            "ctx": CTX,
            "profile": {"tone": "synthetic"},
            "feedback": None,
            "decide_fn": self.decide,
            "research_fn": self.research,
            "plan_eval_fn": self.planning,
            "spent_fn": self.spent,
            "on_event": self.event,
            **changes,
        }


@pytest.mark.parametrize(
    "decision", [decision_data(intent="boundary"), decision_data(category=None)]
)
def test_out_of_scope_stops_in_code(decision):
    f = Fakes(decision=decision)
    output = supervisor.run_request(**f.args())
    assert output["kind"] == "out_of_scope"
    assert not f.research_calls and not f.plan_calls


def test_no_evidence_stops_before_planning():
    f = Fakes(research=handoff(status="no_evidence", evidence_ids=[]))
    output = supervisor.run_request(**f.args())
    assert output["kind"] == "no_evidence" and not f.plan_calls


@pytest.mark.parametrize("intent", ["pattern", "relation"])
def test_research_only_and_numeric_verification(intent):
    f = Fakes(decision=decision_data(intent=intent))
    output = supervisor.run_request(**f.args())
    assert output["kind"] == "research" and not f.plan_calls
    assert output["aggregates_removed"] == ["invented"]
    assert "invented" not in output["handoff"]["aggregates"]
    assert output["handoff"]["unresolved"] == [
        "aggregate:invented: 도구 출력에 없는 수치"
    ]
    assert output["aggregates_label"] == AGGREGATES_LABEL


def test_three_plans_have_briefs_and_pre_call_cost_checks():
    f = Fakes()
    output = supervisor.run_request(**f.args())
    assert output["kind"] == "plan" and len(output["plans"]) == len(f.plan_calls) == 3
    for i, item in enumerate(f.order):
        if item in ("decide", "research", "plan"):
            # planning start is emitted after its cost precheck, before the call.
            before = f.order[i - 1]
            if item == "plan":
                assert before == {
                    "event": "step",
                    "agent": "planning",
                    "phase": "start",
                    "status": "running",
                }
                assert f.order[i - 2] == "spent"
            else:
                assert before == "spent"
    assert not output["limit_hit"] and output["limit_kinds"] == []
    brief = f.research_calls[0]
    ResearchBrief.model_validate(brief)
    assert "conversation-private" not in json.dumps(brief)
    assert all(
        call["brief"] == brief and call["max_reworks"] == 2 for call in f.plan_calls
    )
    assert output["disclaimer"] == CLAIM_CHECK_DISCLAIMER
    assert "raw-only" not in json.dumps(output)
    json.dumps(output, allow_nan=False)


def test_text_limit_preserves_completed_plans_and_does_not_call_next_plan():
    f = Fakes()
    original = f.planning

    def plan(*args, **kwargs):
        result = original(*args, **kwargs)
        f.cost = 0.30
        return result

    output = supervisor.run_request(**f.args(plan_eval_fn=plan))
    assert len(f.plan_calls) == len(output["plans"]) == 1
    assert output["kind"] == "plan" and output["limit_kinds"] == ["text"]
    assert output["limit_hit"] and output["incomplete"]
    assert output["limits"] == {"text_spent_usd": 0.30, "max_text_cost_usd": 0.30}


@pytest.mark.parametrize("text_hit", [False, True])
def test_image_limit_is_separate_from_text_cost(text_hit):
    f = Fakes(
        plan={
            "status": "done",
            "rework_count": 0,
            "image": {"ok": False, "code": "IMAGE_CAP_REACHED", "cost_usd": 9.0},
        }
    )
    original = f.planning

    def plan(*args, **kwargs):
        result = original(*args, **kwargs)
        if text_hit:
            f.cost = 0.30
        return result

    output = supervisor.run_request(**f.args(plan_eval_fn=plan))
    assert output["limit_kinds"] == (["image", "text"] if text_hit else ["image"])
    assert len(f.plan_calls) == (1 if text_hit else 3)
    assert output["limits"]["text_spent_usd"] == f.cost


def test_plan_and_rework_caps_and_reported_input_trims():
    f = Fakes(
        research=handoff(
            evidence_ids=[f"yt:{i}" for i in range(31)],
            aggregates={f"a{i}": "synthetic" for i in range(21)},
        )
    )
    output = supervisor.run_request(
        **f.args(message="x" * 2001, limits=RequestLimits(max_plans=1, max_reworks=0))
    )
    assert len(f.plan_calls) == 1
    passed = f.plan_calls[0]
    assert passed["max_reworks"] == 0
    assert (
        len(passed["handoff"]["evidence_ids"]) == 30
        and len(passed["handoff"]["aggregates"]) == 20
    )
    assert output["input_trims"] == [
        {"field": "message", "kept": 2000, "total": 2001},
        {"field": "evidence_ids", "kept": 30, "total": 31},
        {"field": "aggregates", "kept": 20, "total": 21},
    ]
    assert "plans" in output["limit_kinds"] and output["incomplete"]


def test_events_arrive_at_stage_boundaries_including_tools_reworks_image():
    f = Fakes(plan={"status": "done", "rework_count": 2, "image": {"ok": True}})
    supervisor.run_request(**f.args())
    events = [item for item in f.order if isinstance(item, dict)]
    step = lambda agent, phase, status: {
        "event": "step",
        "agent": agent,
        "phase": phase,
        "status": status,
    }
    assert events == [
        step("supervisor", "end", "ok"),
        step("research", "end", "ok"),
        {"event": "tool_start", "name": AGG, "kind": "aggregate"},
        *[
            event
            for _ in range(3)
            for event in [
                step("planning", "start", "running"),
                step("evaluation", "end", "done"),
                step("rework", "end", "done"),
                step("rework", "end", "done"),
                step("image", "end", "ok"),
            ]
        ],
        step("supervisor", "done", "plan"),
    ]
    assert f.order.index(step("supervisor", "end", "ok")) < f.order.index("research")
    assert f.order.index(step("research", "end", "ok")) < f.order.index("plan")


def test_callback_exceptions_only_increment_safe_code():
    f = Fakes()

    def event(_):
        raise RuntimeError("private callback body")

    output = supervisor.run_request(**f.args(on_event=event))
    assert len(output["plans"]) == 3
    assert "private callback body" not in json.dumps(output)
    assert output["event_errors"] == {"EVENT_CALLBACK_FAILED": 10}


def test_private_state_is_json_and_disjoint_from_all_other_graphs():
    keys = set(supervisor.SupervisorState.__annotations__)
    assert keys == {
        "sv_message",
        "sv_decision",
        "sv_brief",
        "sv_handoff",
        "sv_results",
        "sv_index",
        "sv_status",
        "sv_steps",
        "sv_trims",
        "sv_tool_outputs",
        "sv_spent",
    }
    for other in (AgentState, ResearchState, PlanEvalState):
        assert not keys & set(other.__annotations__)
    f = Fakes()
    graph = supervisor.build_supervisor_graph(
        **{key: value for key, value in f.args().items() if key != "message"},
        limits=RequestLimits(),
    )
    state = graph.invoke(
        supervisor.initial_supervisor_state("synthetic", RequestLimits())
    )
    assert primitive(state)
    assert set(state) == keys
    assert "raw-only" not in json.dumps(state)
    assert state["sv_status"]["node_count"] == 5


def test_step_counter_stops_before_small_recursion_safety_net(monkeypatch):
    f = Fakes()
    monkeypatch.setattr(supervisor, "_RECURSION_LIMIT", 3)
    output = supervisor.run_request(**f.args(limits=RequestLimits(max_steps=1)))
    assert not f.research_calls and not f.plan_calls
    assert output["limit_kinds"] == ["steps"] and output["incomplete"]


@pytest.mark.parametrize("phase", ["decide", "research", "planning"])
def test_boundary_failure_preserves_safe_partial_result(phase):
    f = Fakes()

    def fail(*args, **kwargs):
        raise RuntimeError("private response body")

    arg = {
        "decide": "decide_fn",
        "research": "research_fn",
        "planning": "plan_eval_fn",
    }[phase]
    output = supervisor.run_request(**f.args(**{arg: fail}))
    assert output["kind"] == "failed" and output["incomplete"]
    assert "private response body" not in json.dumps(output)


def test_tools_only_include_bounded_json_aggregate_and_compare_rows():
    f = Fakes(decision=decision_data(intent="pattern"))
    original = f.research

    def research(brief, raw_store):
        result = original(brief, raw_store)
        raw_store["ref"]["ui_command"] = {
            "data": {"rows": [{"count": i, "bytes": b"x"} for i in range(60)]}
        }
        raw_store["lookup"] = {
            "tool": LOOKUP,
            "kind": "lookup",
            "top_rows": [{"private": "lookup-only"}],
        }
        return result

    output = supervisor.run_request(**f.args(research_fn=research))
    assert len(output["tool_outputs"]) == 1
    tool = output["tool_outputs"][0]
    assert tool["tool"] == AGG and tool["row_count"] == 7
    assert len(tool["rows"]) == 50
    assert "lookup-only" not in json.dumps(output)
    json.dumps(output, allow_nan=False)


def test_final_plan_reaching_text_cap_is_reported_without_discarding_result():
    f = Fakes(decision=decision_data(plan_count=1))
    original = f.planning

    def plan(*args, **kwargs):
        result = original(*args, **kwargs)
        f.cost = 0.30
        return result

    output = supervisor.run_request(**f.args(plan_eval_fn=plan))
    assert len(output["plans"]) == 1
    assert output["limit_hit"] and output["limit_kinds"] == ["text"]
    assert output["incomplete"]
