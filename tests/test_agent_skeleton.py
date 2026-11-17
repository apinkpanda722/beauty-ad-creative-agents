"""One-node graph contracts, with synthetic chat responses only."""

import asyncio
from copy import deepcopy
from datetime import date

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from beautyads.agents.skeleton import build_graph
from beautyads.domain.tools import ToolContext, ToolErrorCode, ToolFailure, ToolResult
from beautyads.llm.chat import ChatResult, ToolCall


def reply(text=None, calls=()):
    return ChatResult(text, list(calls), "stop", {}, 0, "price_table", {})


def initial(**updates):
    return dict(
        messages=[{"role": "user", "content": "synthetic request"}],
        tenant_id="demo-a",
        thread_id="demo-a:thread",
        as_of="2026-01-02",
        last_collected_at=None,
        final_text="",
        tool_trace=[],
        step_count=0,
        **updates,
    )


def primitive(value):
    if type(value) is dict:
        return all(type(k) is str and primitive(v) for k, v in value.items())
    if type(value) is list:
        return all(primitive(v) for v in value)
    return type(value) in (str, int, float, bool, type(None))


def run(graph, state):
    return asyncio.run(
        graph.ainvoke(
            state,
            {"configurable": {"thread_id": state["thread_id"]}, "recursion_limit": 16},
            context={
                "tool_context": ToolContext(
                    tenant_id=state["tenant_id"], as_of=date(2026, 1, 2)
                )
            },
        )
    )


@pytest.mark.parametrize("failure", [False, True])
def test_one_tool_two_calls_and_primitive_checkpoint(failure):
    calls, contexts = [], []
    responses = iter(
        [
            reply(calls=[ToolCall("call-1", "lookup_certified_products", {}, None)]),
            reply("synthetic answer"),
        ]
    )

    def chat(**kwargs):
        calls.append(deepcopy(kwargs))
        return next(responses)

    def tool(name, arguments, ctx):
        contexts.append(ctx)
        if failure:
            return ToolFailure(
                code=ToolErrorCode.GRAPH_UNAVAILABLE,
                retryable=True,
                message="private diagnostic",
            )
        return ToolResult(
            tool=name,
            kind="lookup",
            summary="synthetic summary",
            top_rows=[{"private_raw": "hidden"}],
            row_count=1,
            evidence_ids=[],
            no_evidence=False,
        )

    saver = InMemorySaver()
    result = run(
        build_graph(chat=chat, tool_runner=tool, checkpointer=saver), initial()
    )
    assert primitive(result)
    assert result["step_count"] == 3 and result["final_text"]
    assert len(result["tool_trace"]) == 1 and len(calls) == 2
    assert contexts[0].tenant_id == "demo-a" and contexts[0].as_of == date(2026, 1, 2)
    for call in calls:
        assert call["model"] == "gpt-6-luna" and call["reasoning_effort"] == "none"
        assert "temperature" not in call
    definitions = calls[0]["tools"]
    assert len(definitions) == 1
    assert definitions[0]["function"]["name"] == "lookup_certified_products"
    fields = definitions[0]["function"]["parameters"].get("properties", {})
    assert not any(
        set(name.split("_")) & {"tenant", "user", "date", "today"} for name in fields
    )
    tool_message = calls[1]["messages"][-1]
    assert tool_message["role"] == "tool"
    assert "private_raw" not in str(calls) and "private diagnostic" not in str(calls)
    if failure:
        assert (
            "도구가 실패했다" in tool_message["content"]
            and "GRAPH_UNAVAILABLE" in tool_message["content"]
        )
    assert primitive(
        saver.get_tuple({"configurable": {"thread_id": "demo-a:thread"}}).checkpoint[
            "channel_values"
        ]["messages"]
    )


@pytest.mark.parametrize("limit,expected", [(0, 0), (1, 1), (2, 2)])
def test_counter_stops_before_next_operation(limit, expected):
    seen = []

    def chat(**kwargs):
        seen.append("chat")
        return reply(calls=[ToolCall("c", "lookup_certified_products", {}, None)])

    def tool(*args):
        seen.append("tool")
        return ToolFailure(code="INPUT_INVALID", retryable=False, message="unused")

    graph = build_graph(chat=chat, tool_runner=tool, checkpointer=None, max_steps=limit)
    state = run(graph, initial())
    assert len(seen) == expected and state["step_count"] == expected
    assert "미완료" in state["final_text"] and "STEP_LIMIT" in state["final_text"]


def test_invalid_or_unadvertised_tool_does_not_run():
    for call in [
        ToolCall("c", "show_plan", {}, None),
        ToolCall("c", "lookup_certified_products", None, "INVALID_TOOL_ARGUMENTS"),
    ]:
        responses = iter([reply(calls=[call]), reply("synthetic answer")])

        def forbidden(*args):
            pytest.fail("invalid call must not dispatch")

        state = run(
            build_graph(
                chat=lambda responses=responses, **kw: next(responses),
                tool_runner=forbidden,
                checkpointer=None,
            ),
            initial(),
        )
        assert state["tool_trace"][0]["code"] in {"INPUT_INVALID", "TOOL_UNKNOWN"}
