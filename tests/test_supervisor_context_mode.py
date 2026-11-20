"""E5 context modes use synthetic services and preserve the default call contract."""

import asyncio
import json
from copy import deepcopy
from datetime import UTC, datetime

import pytest
import test_api_assembly
from test_domain_supervisor import decision_data
from test_evaluation import Scorer, Support
from test_plan_checks import FakeCerts, FakeEvidence, plan_data
from test_planning import Structured as Planner
from test_research_agent import (
    CTX,
    Chat,
    Structured,
    brief,
    call,
    draft,
    primitive,
    reply,
)
from test_supervisor import Fakes, handoff

from beautyads.agents import research, supervisor
from beautyads.agents.evaluation import evaluate_plan
from beautyads.agents.planning import _SYSTEM, make_plan, research_payload
from beautyads.agents.tool_messages import MAX_ROWS, tool_result_payload
from beautyads.api import assembly
from beautyads.domain.supervisor import RequestLimits, trim_handoff
from beautyads.domain.tools import ToolContext, ToolResult

rig = test_api_assembly.rig


def test_default_and_on_requests_have_identical_results_and_calls(monkeypatch):
    stamp = datetime(2026, 11, 20, tzinfo=UTC)
    monkeypatch.setattr(supervisor, "_utcnow", lambda: stamp)
    outputs, calls = [], []
    limits = RequestLimits(handoff_max_evidence_ids=1, handoff_max_aggregates=1)
    for options in ({}, {"context_mode": "on"}):
        fake = Fakes(
            decision=decision_data(plan_count=1),
            research=handoff(evidence_ids=["yt:a", "yt:b", "yt:c"]),
        )
        result = supervisor.run_request(**fake.args(limits=limits), **options)
        assert result["kind"] == "plan"  # Fakes.research accepts exactly two args.
        bounded, trims = trim_handoff(result["handoff"], limits)
        assert fake.plan_calls[0]["handoff"] == bounded
        assert "raw_tool_outputs" not in bounded
        assert result["input_trims"] == trims
        assert trims == [
            {"field": "evidence_ids", "kept": 1, "total": 3},
            {"field": "aggregates", "kept": 1, "total": 2},
        ]
        assert "context_mode" not in result
        outputs.append(result)
        calls.append((fake.order, fake.research_calls, fake.plan_calls))
    assert outputs[0] == outputs[1]
    assert calls[0] == calls[1]


def test_off_passes_original_handoff_and_tool_outputs_without_trimming():
    fake = Fakes(
        decision=decision_data(plan_count=1),
        research=handoff(evidence_ids=["yt:a", "yt:b", "yt:c"]),
    )
    modes = []

    def research_fn(brief, raw_store, *, context_mode):
        modes.append(context_mode)
        return fake.research(brief, raw_store)

    result = supervisor.run_request(
        **fake.args(
            research_fn=research_fn,
            limits=RequestLimits(handoff_max_evidence_ids=1, handoff_max_aggregates=0),
        ),
        context_mode="off",
    )
    assert modes == ["off"]
    assert result["kind"] == "plan" and result["context_mode"] == "off"
    passed = fake.plan_calls[0]["handoff"]
    assert passed["evidence_ids"] == fake.handoff["evidence_ids"]
    assert passed["aggregates"] == result["handoff"]["aggregates"]
    assert passed["aggregates"]
    assert passed["raw_tool_outputs"] == result["tool_outputs"]
    assert passed["raw_tool_outputs"]
    assert result["input_trims"] == []
    assert "raw_tool_outputs" not in result["handoff"]
    passed["raw_tool_outputs"][0]["rows"].clear()
    assert result["tool_outputs"][0]["rows"]
    assert primitive(result)


def test_off_retains_input_safety_trim_and_isolates_each_plan_handoff():
    fake = Fakes()
    modes = []

    def research_fn(brief, raw_store, *, context_mode):
        modes.append(context_mode)
        return fake.research(brief, raw_store)

    def planning(*args, **kwargs):
        result = fake.planning(*args, **kwargs)
        args[1]["raw_tool_outputs"][0]["rows"].clear()
        args[1]["evidence_ids"].clear()
        return result

    result = supervisor.run_request(
        **fake.args(message="x" * 2001, research_fn=research_fn, plan_eval_fn=planning),
        context_mode="off",
    )
    assert modes == ["off"]
    assert result["input_trims"] == [{"field": "message", "kept": 2000, "total": 2001}]
    assert len(fake.plan_calls) == 3
    assert all(
        entry["handoff"]["raw_tool_outputs"] == result["tool_outputs"]
        and entry["handoff"]["evidence_ids"] == ["yt:a"]
        for entry in fake.plan_calls
    )


@pytest.mark.parametrize("raw", [None, [], [{"rows": [{"count": 7}]}]])
def test_planning_payload_preserves_bytes_and_adds_raw_only_when_present(raw):
    fake = Planner()
    source = {
        **handoff(),
        "available_efficacy": ["hydration", "other", "invalid"],
        "pattern_context": {"thin_pool": True},
    }
    if raw is not None:
        source["raw_tool_outputs"] = raw
    expected = {
        "brief": {"goal": "합성"},
        "research": research_payload(source),
        "available_efficacy": ["hydration"],
        "claim_choice": None,
        "profile": {
            "brand": "synthetic",
            "tone": None,
            "forbidden_terms": None,
            "own_product_url": None,
        },
        "feedback": {"rejected_reasons": ["합성"]},
        "rework": {"check_issues": [], "low_items": []},
    }
    if raw is not None:
        expected["raw_tool_outputs"] = raw
    original = deepcopy(source)
    make_plan(
        brief=expected["brief"],
        handoff=source,
        profile={"brand": "synthetic", "tenant_id": "private"},
        feedback=expected["feedback"],
        rework={**expected["rework"], "previous_plan": "ignored"},
        structured=fake,
    )
    messages = fake.calls[0][1]["messages"]
    assert messages == [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": json.dumps(expected, ensure_ascii=False)},
    ]
    keys = {
        "brief",
        "research",
        "available_efficacy",
        "claim_choice",
        "profile",
        "feedback",
        "rework",
    }
    assert set(json.loads(messages[1]["content"])) == (
        keys if raw is None else keys | {"raw_tool_outputs"}
    )
    assert source == original


def test_off_raw_tool_output_reaches_planning_model_with_text_policy():
    fake = Fakes(decision=decision_data(plan_count=1))
    planner = Planner()

    def research_fn(brief, raw_store, *, context_mode):
        assert context_mode == "off"
        output = fake.research(brief, raw_store)
        raw_store["ref"]["top_rows"] = [
            {
                "count": 7,
                "url": "https://example.invalid/collected",
                "nested": [{"image": "synthetic-image", "caption": "합성"}],
                "thumbnail_url": "https://example.invalid/preview",
            }
        ]
        return output

    def plan_eval_fn(brief, handoff, profile, feedback, *, max_reworks):
        make_plan(
            brief=brief,
            handoff=handoff,
            profile=profile,
            feedback=feedback,
            rework=None,
            structured=planner,
        )
        return fake.planning(brief, handoff, profile, feedback, max_reworks=max_reworks)

    result = supervisor.run_request(
        **fake.args(research_fn=research_fn, plan_eval_fn=plan_eval_fn),
        context_mode="off",
    )
    assert result["kind"] == "plan"
    payload = json.loads(planner.calls[0][1]["messages"][1]["content"])
    assert payload["raw_tool_outputs"] == [
        {
            "tool": result["tool_outputs"][0]["tool"],
            "row_count": 7,
            "rows": [{"count": 7, "nested": [{"caption": "합성"}]}],
        }
    ]
    assert "raw_tool_outputs" not in payload["research"]


def test_research_observation_modes_keep_pool_and_log_counts():
    value = ToolResult(
        tool="find_example_creatives",
        kind="lookup",
        summary="synthetic",
        row_count=8,
        top_rows=[],
        evidence_ids=[f"yt:{i}" for i in range(8)],
        no_evidence=False,
    ).model_copy(
        update={"top_rows": [{"index": i, "caption": "가" * 201} for i in range(8)]}
    )
    states, model_calls = [], []
    for options in ({}, {"context_mode": "on"}, {"context_mode": "off"}):
        chat, structured, store = (
            Chat([reply([call()]), reply()]),
            Structured(draft(value.evidence_ids)),
            {},
        )
        graph = research.build_research_graph(
            ctx=CTX,
            chat=chat,
            tool_runner=lambda *args: value,
            structured=structured,
            raw_store=store,
            **options,
        )
        snapshots = list(
            graph.stream(research.initial_research_state(brief()), stream_mode="values")
        )
        assert all(primitive(state) for state in snapshots)
        state = snapshots[-1]
        assert state["tool_log"][0]["shown_count"] == MAX_ROWS
        assert state["evidence_pool"] == sorted(value.evidence_ids)
        assert set(state) == set(research.ResearchState.__annotations__)
        expected = (
            value.model_dump(mode="json")
            if options.get("context_mode") == "off"
            else tool_result_payload(value.tool, value)
        )
        for args in (chat.calls[1], structured.calls[0][1]):
            payload = json.loads(args["messages"][1]["content"])
            assert payload["observations"] == [expected]
            assert payload["evidence_pool"] == sorted(value.evidence_ids)
        assert len(
            expected["top_rows"] if "top_rows" in expected else expected["rows"]
        ) == (8 if options.get("context_mode") == "off" else MAX_ROWS)
        assert next(iter(store.values())) == value.model_dump(mode="json")
        states.append(state)
        model_calls.append((chat.calls, structured.calls[0][1]))
    assert states[0]["tool_log"] == states[1]["tool_log"] == states[2]["tool_log"]
    assert states[0]["handoff"] == states[1]["handoff"] == states[2]["handoff"]
    assert model_calls[0] == model_calls[1]


def test_run_research_forwards_off_to_observations():
    chat = Chat([reply([call()]), reply()])
    value = ToolResult(
        tool="find_example_creatives",
        kind="lookup",
        summary="synthetic",
        row_count=0,
        top_rows=[],
        evidence_ids=[],
        no_evidence=True,
    )
    research.run_research(
        brief(),
        ctx=CTX,
        chat=chat,
        tool_runner=lambda *args: value,
        structured=Structured(),
        context_mode="off",
    )
    assert json.loads(chat.calls[1]["messages"][1]["content"])["observations"] == [
        value.model_dump(mode="json")
    ]


@pytest.mark.parametrize("mode", ["invalid", "ON", "", None, False, [], {}])
@pytest.mark.parametrize(
    "entry",
    ["run_request", "build_supervisor_graph", "run_research", "build_research_graph"],
)
def test_invalid_mode_fails_before_any_injected_call(mode, entry):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid context mode must fail before calls")

    if entry in {"run_request", "build_supervisor_graph"}:
        args = Fakes().args(
            decide_fn=forbidden,
            research_fn=forbidden,
            plan_eval_fn=forbidden,
            spent_fn=forbidden,
            on_event=forbidden,
        )
        if entry == "build_supervisor_graph":
            args.pop("message")
        fn = getattr(supervisor, entry)
        positional = ()
    else:
        args = {
            "ctx": CTX,
            "chat": forbidden,
            "tool_runner": forbidden,
            "structured": forbidden,
        }
        fn = getattr(research, entry)
        positional = (brief(),) if entry == "run_research" else ()
    with pytest.raises(ValueError, match="^CONTEXT_MODE_INVALID$"):
        fn(*positional, **args, context_mode=mode)
    assert "context_mode" not in RequestLimits.model_fields


@pytest.mark.parametrize("mode", [None, "on", "off"])
def test_assembly_forwards_only_off_and_keeps_two_argument_research(
    rig, monkeypatch, mode
):
    request_calls, research_calls = [], []

    def run_research(brief, **options):
        research_calls.append(options)
        return {}

    def request(**options):
        request_calls.append(options)
        if mode == "off":
            options["research_fn"]({}, {}, context_mode="off")
        else:
            options["research_fn"]({}, {})
        return {}

    monkeypatch.setattr(assembly, "run_request", request)
    monkeypatch.setattr(assembly, "run_research", run_research)

    async def run():
        services = await rig.start()
        try:
            tenant = next(iter(services.allowed_tenants))
            services.ask(
                "synthetic",
                ToolContext(tenant_id=tenant, as_of=services.as_of),
                services.workspaces[tenant],
                {},
                False,
                **({} if mode is None else {"context_mode": mode}),
            )
        finally:
            await services.close()

    asyncio.run(run())
    for options in (request_calls[0], research_calls[0]):
        if mode == "off":
            assert options["context_mode"] == "off"
        else:
            assert "context_mode" not in options


def test_evaluator_model_input_ignores_raw_tool_outputs():
    messages = []
    for extra in ({}, {"raw_tool_outputs": [{"rows": [{"count": 8}]}]}):
        scorer = Scorer("claude-haiku-5-5")
        evaluate_plan(
            plan=plan_data(),
            brief={},
            handoff={"evidence_ids": plan_data()["evidence_ids"], **extra},
            rules=[],
            evidence_index=FakeEvidence(),
            support=Support(),
            certs=FakeCerts(),
            structured=scorer,
        )
        messages.append(scorer.calls[0][1]["messages"])
    assert messages[0] == messages[1]


@pytest.mark.parametrize("mode", ["on", "off"])
@pytest.mark.parametrize(
    "choice",
    [
        {
            "mode": "selected",
            "claims": ["hydration", "soothing"],
            "requested_claim": None,
        },
        {"mode": "keep_requested", "claims": [], "requested_claim": "other"},
        {"mode": "none", "claims": [], "requested_claim": None},
    ],
)
def test_claim_choice_reaches_planning_and_evaluation_messages_in_both_modes(
    mode, choice
):
    from beautyads.agents.plan_eval import run_plan_eval

    fake = Fakes(decision=decision_data(plan_count=1))
    planner, scorer = Planner(), Scorer("claude-haiku-5-5")

    def research_fn(brief, raw_store, **kwargs):
        return fake.research(brief, raw_store)

    def plan_eval_fn(brief, handoff, profile, feedback, **kwargs):
        return run_plan_eval(
            brief=brief,
            handoff=handoff,
            profile=profile,
            feedback=feedback,
            plan_fn=lambda **options: make_plan(**options, structured=planner),
            evaluate_fn=lambda **options: evaluate_plan(
                **options,
                rules=[],
                evidence_index=FakeEvidence(),
                support=Support(),
                certs=FakeCerts(),
                structured=scorer,
            ),
            **kwargs,
        )

    result = supervisor.run_request(
        **fake.args(
            research_fn=research_fn,
            plan_eval_fn=plan_eval_fn,
            claims_fn=lambda _: (["hydration", "soothing"], "ok"),
            claim_choice=choice,
        ),
        context_mode=mode,
    )
    assert result["kind"] == "plan"
    for generator in (planner, scorer):
        assert generator.calls
        for _, options in generator.calls:
            payload = json.loads(options["messages"][1]["content"])
            assert payload["claim_choice"] == choice
            assert "claim_choice" not in payload["research"]
