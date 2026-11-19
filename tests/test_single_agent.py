"""Pure baseline tests inspect actual model inputs using synthetic boundaries."""

import ast
import json
from copy import deepcopy
from pathlib import Path

import pytest
from test_plan_checks import FakeCerts, FakeEvidence, FakeSupport, plan_data
from test_research_agent import (
    CTX,
    EXAMPLE,
    Chat,
    Structured,
    brief,
    call,
    reply,
    result,
)

from beautyads.agents.research import build_research_graph, initial_research_state
from beautyads.agents.tool_messages import (
    MAX_EVIDENCE_IDS,
    MAX_ROWS,
    MAX_VALUE_CHARS,
    PARTIAL_RESULT_RULE,
    TOOL_DATA_RULE,
    tool_result_payload,
)
from beautyads.agents.tools import TOOLS, tool_definitions
from beautyads.domain.plan import Plan, PlanCheckReport
from beautyads.domain.research import ResearchBrief
from beautyads.domain.supervisor import RequestLimits
from beautyads.domain.tenant import TenantContextMissing
from beautyads.domain.tools import ToolFailure, ToolKind
from beautyads.eval import single_agent
from beautyads.llm.chat import ToolCall
from beautyads.llm.structured import StructuredFailure, StructuredResult

DEFAULT_LIMIT = ResearchBrief.model_fields["max_tool_calls"].default
PROFILE = {
    "brand": "synthetic brand",
    "tone": "synthetic tone",
    "forbidden_terms": ["synthetic forbidden"],
    "own_product_url": "https://example.invalid/product",
    "ignored": "private profile field",
}
FEEDBACK = {"reason": "synthetic feedback"}
MESSAGE = "  synthetic original request  "


def tool_value(ids=("yt:a",)):
    return result(ids=ids).model_copy(update={"ui_command": None})


def planner(**kwargs):
    return Structured(plan_data(evidence_ids=["yt:a"], claimed_efficacy=[]), **kwargs)


def execute_single(chat, structured=None, runner=None, **options):
    return single_agent.run_single_agent(
        message=MESSAGE,
        ctx=CTX,
        profile=deepcopy(PROFILE),
        feedback=deepcopy(FEEDBACK),
        chat=chat,
        tool_runner=runner or (lambda *args: tool_value()),
        structured=structured if structured is not None else planner(),
        rules=[],
        evidence_index=FakeEvidence(["yt:a", "yt:outside"]),
        support=FakeSupport(),
        certs=FakeCerts(),
        **options,
    )


def loop(chat, runner=None, limit=DEFAULT_LIMIT):
    return single_agent.run_tool_loop(
        seed={"request": MESSAGE},
        system=single_agent.single_agent_system_prompt(),
        ctx=CTX,
        chat=chat,
        tool_runner=runner or (lambda *args: tool_value()),
        model=single_agent.SINGLE_AGENT_MODEL,
        reasoning_effort=single_agent.SINGLE_AGENT_EFFORT,
        max_tool_calls=limit,
        purpose="single-agent",
    )


def nested_keys(value):
    if isinstance(value, dict):
        return set(value) | set().union(*(nested_keys(v) for v in value.values()))
    if isinstance(value, list):
        return set().union(*(nested_keys(v) for v in value))
    return set()


def test_actual_model_inputs_are_bounded_and_pure():
    ids = [f"yt:{i:02d}" for i in range(MAX_EVIDENCE_IDS + 3)]
    value = tool_value(ids).model_copy(
        update={
            "top_rows": [
                {"caption": "가" * (MAX_VALUE_CHARS + 1), "index": i}
                for i in range(MAX_ROWS + 2)
            ],
            "row_count": MAX_ROWS + 2,
        }
    )
    chat, structured = Chat([reply([call()]), reply()]), planner()
    output = execute_single(chat, structured, lambda *args: value)
    expected = tool_result_payload(EXAMPLE, value.model_dump(mode="json"))
    assert output["kind"] == "plan"
    Plan.model_validate(output["plan"])
    report = PlanCheckReport.model_validate(
        {
            key: value
            for key, value in output["check_report"].items()
            if key in PlanCheckReport.model_fields
        }
    )
    assert report.model_dump(mode="json") == output["check_report"]
    assert output["evidence_pool"] == sorted(ids)
    assert output["tool_calls"] == 1
    assert output["model_calls"] == len(chat.calls) + len(structured.calls)
    assert output["failure_code"] is None
    assert output["prompt_version"] == single_agent.SINGLE_AGENT_PROMPT_VERSION
    assert set(output) == {
        "kind",
        "plan",
        "check_report",
        "evidence_pool",
        "tool_calls",
        "model_calls",
        "failure_code",
        "prompt_version",
    }
    for options in [*chat.calls, structured.calls[0][1]]:
        system, user = options["messages"]
        assert system["role"] == "system" and user["role"] == "user"
        assert TOOL_DATA_RULE in system["content"].splitlines()
        assert PARTIAL_RESULT_RULE in system["content"].splitlines()
        payload = json.loads(user["content"])
        assert payload["request"] == MESSAGE
        assert payload["profile"] == {
            k: PROFILE[k]
            for k in (
                "brand",
                "tone",
                "forbidden_terms",
                "own_product_url",
            )
        }
        assert payload["feedback"] == FEEDBACK
        assert not {
            "pattern_context",
            "available_efficacy",
            "aggregates",
            "rework",
        } & nested_keys(payload)
    for options in (chat.calls[1], structured.calls[0][1]):
        payload = json.loads(options["messages"][1]["content"])
        assert payload["observations"] == [expected]
        observation = payload["observations"][0]
        assert len(observation["rows"]) == MAX_ROWS
        assert len(observation["rows"][0]["caption"]) == MAX_VALUE_CHARS + 1
        assert len(observation["evidence_ids"]) == MAX_EVIDENCE_IDS
        assert observation["truncated"] == {
            "rows": True,
            "values": MAX_ROWS,
            "evidence_ids": True,
        }
    assert json.loads(structured.calls[0][1]["messages"][1]["content"])[
        "evidence_pool"
    ] == sorted(ids)
    names = {tool.name for tool in TOOLS if tool.kind != ToolKind.display}
    definitions = [
        {"type": "function", "function": d}
        for d in tool_definitions()
        if d["name"] in names
    ]
    for options in chat.calls:
        assert set(options) == {
            "model",
            "messages",
            "tools",
            "tool_choice",
            "reasoning_effort",
            "purpose",
        }
        assert options["model"] == "gpt-6.1-terra"
        assert options["reasoning_effort"] == "low"
        assert options["purpose"] == "single-agent"
        assert options["tools"] == definitions
        assert options["tool_choice"] == "auto"
    spec, options = structured.calls[0]
    assert spec.name == "single_agent_plan"
    assert options["purpose"] == "single-plan"
    assert options["reasoning_effort"] == "low"
    assert not {"temperature", "caps", "ledger_path"} & options.keys()
    assert single_agent.SINGLE_AGENT_PROMPT_VERSION == "2026-11-19-1"


@pytest.mark.parametrize("batch_size", [1, 2, DEFAULT_LIMIT + 1])
def test_default_tool_budget_stops_repeated_and_parallel_calls(batch_size):
    chat = Chat([reply([call()] * batch_size)] * (DEFAULT_LIMIT + 1))
    structured, seen = planner(), []
    output = execute_single(chat, structured, lambda *a: seen.append(a) or tool_value())
    assert output["tool_calls"] == len(seen) == DEFAULT_LIMIT
    assert len(chat.calls) == (DEFAULT_LIMIT + batch_size - 1) // batch_size
    assert output["model_calls"] == len(chat.calls) + 1
    assert len(structured.calls) == 1
    assert all(args[2] is CTX for args in seen)


@pytest.mark.parametrize(
    "bad_call,bad_result,code",
    [
        (call("show_plan"), None, "TOOL_UNKNOWN"),
        (call("unregistered"), None, "TOOL_UNKNOWN"),
        (ToolCall("x", EXAMPLE, None, "INVALID_TOOL_ARGUMENTS"), None, "INPUT_INVALID"),
        (ToolCall("x", EXAMPLE, None, None), None, "INPUT_INVALID"),
        (call(arguments={"tenant_id": "other"}), None, "INPUT_INVALID"),
        (
            call(),
            ToolFailure(
                code="GRAPH_UNAVAILABLE", retryable=True, message="private diagnostic"
            ),
            "GRAPH_UNAVAILABLE",
        ),
        (call(), {"private": "private diagnostic"}, "TOOL_RESULT_UNREADABLE"),
        (call(), [], "TOOL_RESULT_UNREADABLE"),
    ],
)
def test_research_equivalence_for_failures_pool_and_actual_observations(
    bad_call, bad_result, code
):
    responses = [reply([bad_call]), reply([call()]), reply()]

    def runner():
        values = iter(
            [bad_result, tool_value()] if bad_result is not None else [tool_value()]
        )
        return lambda *args: next(values)

    research_chat, single_chat, raw_store = Chat(responses), Chat(responses), {}
    graph = build_research_graph(
        ctx=CTX,
        chat=research_chat,
        tool_runner=runner(),
        structured=Structured(),
        raw_store=raw_store,
    )
    state = graph.invoke(initial_research_state(brief(DEFAULT_LIMIT)))
    output = loop(single_chat, runner())
    assert output.tool_calls == state["research_step_count"]
    assert output.evidence_pool == state["evidence_pool"] == ["yt:a"]
    assert output.failures == [code]
    assert output.model_calls == len(single_chat.calls) == len(research_chat.calls)
    expected = [
        tool_result_payload(entry["name"], raw_store[ref])
        for entry, ref in zip(state["tool_log"], state["raw_refs"], strict=True)
    ]
    assert output.observations == expected
    for a, b in zip(single_chat.calls, research_chat.calls, strict=True):
        assert (
            json.loads(a["messages"][1]["content"])["observations"]
            == json.loads(b["messages"][1]["content"])["observations"]
        )
    assert "private diagnostic" not in str(single_chat.calls)


def test_run_research_handoff_matches_reusable_loop():
    from beautyads.agents.research import run_research

    responses = [reply([call(), call()]), reply()]
    research_chat, single_chat = Chat(responses), Chat(responses)
    handoff = run_research(
        brief(DEFAULT_LIMIT),
        ctx=CTX,
        chat=research_chat,
        tool_runner=lambda *a: tool_value(),
        structured=Structured(),
    )
    output = loop(single_chat)
    assert output.tool_calls == sum(len(r.tool_calls) for r in responses)
    assert output.evidence_pool == handoff["evidence_ids"]
    assert (
        output.observations
        == json.loads(research_chat.calls[1]["messages"][1]["content"])["observations"]
    )


def test_raw_output_is_independent_and_pool_is_sorted_unique():
    value = tool_value(["yt:b", "yt:a", "yt:b"])
    output = loop(Chat([reply([call()]), reply()]), lambda *args: value)
    assert output.raw == [value.model_dump(mode="json")]
    assert output.evidence_pool == ["yt:a", "yt:b"]
    value.top_rows[0]["later"] = "mutation"
    assert "later" not in output.raw[0]["top_rows"][0]


@pytest.mark.parametrize("stop_at", [0, 1, 2])
@pytest.mark.parametrize("raises", [False, True])
def test_spend_is_checked_before_every_chat_and_plan_call(stop_at, raises):
    chat, structured, checked = Chat([reply([call()]), reply()]), planner(), []
    limits = RequestLimits(max_text_cost_usd=0.12)

    def spent():
        checked.append(1)
        if len(checked) - 1 >= stop_at:
            if raises:
                raise RuntimeError("private diagnostic")
            return limits.max_text_cost_usd
        return 0

    output = execute_single(chat, structured, spent_fn=spent, limits=limits)
    assert output["kind"] == ("failed" if raises else "limit")
    assert output["failure_code"] == ("SINGLE_SPENT_FAILED" if raises else None)
    assert len(chat.calls) == stop_at and not structured.calls
    assert output["model_calls"] == stop_at
    assert output["tool_calls"] == int(stop_at > 0)
    assert output["evidence_pool"] == (["yt:a"] if stop_at else [])
    assert output["plan"] is output["check_report"] is None
    assert "private diagnostic" not in json.dumps(output)


@pytest.mark.parametrize("spent", [float("nan"), float("inf")])
def test_nonfinite_cost_fails_closed(spent):
    chat, structured = Chat([]), planner()
    output = execute_single(chat, structured, spent_fn=lambda: spent)
    assert output["kind"] == "limit" and not chat.calls and not structured.calls


def test_no_evidence_skips_planning_and_checks():
    chat, structured = Chat([reply()]), planner()
    output = execute_single(chat, structured)
    assert output["kind"] == "no_evidence"
    assert output["evidence_pool"] == [] and not structured.calls
    assert output["plan"] is output["check_report"] is None
    assert output["model_calls"] == 1 and output["tool_calls"] == 0


def test_checks_run_once_and_report_evidence_outside_pool(monkeypatch):
    calls = []
    original = single_agent.run_checks_on_dict

    def capture(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(single_agent, "run_checks_on_dict", capture)
    structured = Structured(plan_data(evidence_ids=["yt:outside"], claimed_efficacy=[]))
    output = execute_single(Chat([reply([call()]), reply()]), structured)
    assert output["kind"] == "plan" and len(calls) == 1
    assert calls[0][1]["handoff_evidence_ids"] == ["yt:a"]
    assert "EVIDENCE_NOT_IN_HANDOFF" in {
        issue["code"] for issue in output["check_report"]["issues"]
    }
    assert len(structured.calls) == 1


@pytest.mark.parametrize("failure", list(StructuredFailure))
def test_structured_failure_uses_only_fixed_codes(failure):
    class Failed:
        def generate(self, spec, **options):
            return StructuredResult(False, None, failure, 2, 0, [])

    output = execute_single(Chat([reply([call()]), reply()]), Failed())
    assert output["kind"] == "failed"
    assert output["failure_code"] == f"STRUCTURED_FAILED_{failure.value}"
    assert output["plan"] is output["check_report"] is None
    assert output["model_calls"] == 3


def test_structured_exception_does_not_leak_diagnostics():
    class Failed:
        def generate(self, spec, **options):
            raise RuntimeError("private diagnostic")

    output = execute_single(Chat([reply([call()]), reply()]), Failed())
    assert output["kind"] == "failed" and output["failure_code"] == "STRUCTURED_FAILED"
    assert "private diagnostic" not in json.dumps(output)


def test_invalid_tenant_precedes_boundaries():
    with pytest.raises(TenantContextMissing):
        single_agent.run_tool_loop(
            seed={},
            system="synthetic",
            ctx=CTX.model_copy(update={"tenant_id": " "}),
            chat=Chat([]),
            tool_runner=lambda *a: pytest.fail("must not run"),
            model=single_agent.SINGLE_AGENT_MODEL,
            reasoning_effort=single_agent.SINGLE_AGENT_EFFORT,
            max_tool_calls=DEFAULT_LIMIT,
            purpose="synthetic",
        )


def test_module_has_no_supervisor_evaluation_imports_or_cap_literals():
    source = Path(single_agent.__file__).read_text()
    tree = ast.parse(source)
    imports = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    imports.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    assert (
        not {
            "beautyads.agents.evaluation",
            "beautyads.agents.plan_eval",
            "beautyads.agents.supervisor",
        }
        & imports
    )
    strings = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert not {"caps", "ledger_path", "api_key"} & strings
    assert not {"gemini", "openai", "anthropic"} <= strings
    assert (
        not {
            "pattern_context",
            "dominant_axes",
            "thin_pool",
            "available_efficacy",
            "rework",
        }
        & strings
    )
    assert "temperature" not in source
