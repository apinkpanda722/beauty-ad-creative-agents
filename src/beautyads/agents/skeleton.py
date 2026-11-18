"""One assistant node, one advertised tool, and at most two chat calls."""

import asyncio
import json
from copy import deepcopy
from datetime import date

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from beautyads.agents.state import AgentState
from beautyads.agents.tool_messages import TOOL_DATA_RULE, tool_message_content
from beautyads.agents.tools import tool_definitions
from beautyads.domain.tenant import TenantMismatch, validate_tenant_id
from beautyads.domain.tools import ToolFailure

TOOL_NAME = "lookup_certified_products"
MAX_STEPS = 3
RECURSION_LIMIT = 16
INCOMPLETE = "[미완료: STEP_LIMIT]"


def skeleton_tools() -> list[dict]:
    return [
        {"type": "function", "function": definition}
        for definition in tool_definitions()
        if definition["name"] == TOOL_NAME
    ]


def build_graph(*, chat, tool_runner, checkpointer, max_steps=MAX_STEPS):
    """Injected chat is the configured llm.chat_complete boundary.

    Count each chat/tool operation in state; recursion_limit is only a safety net.
    Runtime context is created by the API, independently of checkpointed state.
    """
    if max_steps < 0:
        raise ValueError("STEP_LIMIT_INVALID")

    async def assistant(state: AgentState, runtime: Runtime):
        ctx = (runtime.context or {}).get("tool_context")
        tenant = validate_tenant_id(state["tenant_id"])
        if (
            ctx is None
            or ctx.tenant_id != tenant
            or ctx.as_of != date.fromisoformat(state["as_of"])
        ):
            raise TenantMismatch()
        messages = deepcopy(state["messages"])
        trace = deepcopy(state["tool_trace"])
        count = state["step_count"]
        text = state["final_text"]

        def output(incomplete=False):
            return {
                "messages": messages,
                "tool_trace": trace,
                "step_count": count,
                "final_text": f"{text}\n{INCOMPLETE}".strip() if incomplete else text,
            }

        async def complete(*, final=False):
            return await asyncio.to_thread(
                chat,
                model="gpt-6-luna",
                reasoning_effort="none",
                messages=[
                    {"role": "system", "content": TOOL_DATA_RULE},
                    *deepcopy(messages),
                ],
                tools=skeleton_tools(),
                tool_choice="none" if final else "auto",
            )

        if count >= max_steps:
            return output(True)
        count += 1
        first = await complete()
        text = first.text or ""
        if not first.tool_calls:
            messages.append({"role": "assistant", "content": text})
            return output()

        messages.append(
            {
                "role": "assistant",
                "content": first.text,
                "tool_calls": [
                    {
                        "id": call.id or f"call-{index}",
                        "type": "function",
                        "function": {
                            "name": call.name or "unknown",
                            "arguments": json.dumps(
                                call.arguments or {}, ensure_ascii=False
                            ),
                        },
                    }
                    for index, call in enumerate(first.tool_calls)
                ],
            }
        )
        for index, call in enumerate(first.tool_calls):
            if count >= max_steps:
                return output(True)
            count += 1
            code = None
            if call.name != TOOL_NAME:
                code = "TOOL_UNKNOWN"
                result = ToolFailure(code=code, retryable=False, message="")
            elif call.arguments_error is not None or call.arguments is None:
                code = "INPUT_INVALID"
                result = ToolFailure(code=code, retryable=False, message="")
            else:
                get_stream_writer()(
                    {"type": "tool_start", "name": TOOL_NAME, "kind": "lookup"}
                )
                result = await asyncio.to_thread(
                    tool_runner, TOOL_NAME, call.arguments, ctx
                )
                if isinstance(result, ToolFailure):
                    code = result.code.value
                else:
                    summary = result.summary
            if code:
                summary = f"도구가 실패했다({code})"
            trace.append(
                {
                    "name": TOOL_NAME if call.name == TOOL_NAME else "unknown",
                    "kind": "lookup",
                    "code": code,
                    "summary": summary,
                }
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id or f"call-{index}",
                    "content": tool_message_content(TOOL_NAME, result),
                }
            )
        if count >= max_steps:
            return output(True)
        count += 1
        final = await complete(final=True)
        text = final.text or ""
        if final.tool_calls:
            text = f"{text}\n[미완료: TOOL_ROUND_LIMIT]".strip()
        messages.append({"role": "assistant", "content": text})
        return output()

    graph = StateGraph(AgentState, context_schema=dict)
    graph.add_node("assistant", assistant)
    graph.add_edge(START, "assistant")
    graph.add_edge("assistant", END)
    return graph.compile(checkpointer=checkpointer)
