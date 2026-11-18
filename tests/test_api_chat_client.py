"""The in-process client owns the full lifespan, including pool shutdown."""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from test_api_chat import assembly

from beautyads.api.app import create_app
from beautyads.api.chat_client import parse_sse, run_chat_once
from beautyads.api.sse import encode_event


def test_client_opens_and_closes_resources_on_same_loop():
    records = []

    class Pool:
        async def open(self):
            records.append(("open", asyncio.get_running_loop()))

        async def close(self):
            records.append(("close", asyncio.get_running_loop()))

    async def assemble():
        pool = Pool()
        await pool.open()
        return assembly(close=pool.close)

    result = run_chat_once(
        create_app(assemble), tenant_id="demo-a", message="synthetic"
    )
    assert result.status_code == 200 and result.final_text
    assert {name for name, body in result.events} == {"step", "tool_start", "token"}
    assert [op for op, loop in records] == ["open", "close"]
    assert records[0][1] is records[1][1]


def test_client_parses_json_lines_and_rejections():
    assert parse_sse('event: token\r\ndata: {"text":"a\\nb"}\r\n\r\n') == [
        ("token", {"text": "a\nb"})
    ]
    outcome = run_chat_once(
        create_app(lambda: assembly()), tenant_id="outside", message="synthetic"
    )
    assert (
        outcome.status_code == 403 and outcome.events == [] and outcome.final_text == ""
    )


@pytest.mark.parametrize(
    "extra",
    [
        {},
        {"detail": "UnsupportedParamsError"},
        {"error_code": "FATAL"},
        {"detail": "LlmCallError", "error_code": "FATAL"},
    ],
)
def test_client_parses_optional_error_fields(extra):
    app = FastAPI()

    @app.post("/chat")
    def chat():
        return StreamingResponse(
            iter([encode_event("error", {"code": "AGENT_INTERNAL_ERROR", **extra})])
        )

    outcome = run_chat_once(app, tenant_id="demo-a", message="synthetic")
    assert outcome.status_code == 200 and outcome.final_text == ""
    assert outcome.detail == extra.get("detail")
    assert outcome.error_code == extra.get("error_code")


def test_client_success_has_no_error_fields():
    outcome = run_chat_once(
        create_app(lambda: assembly()), tenant_id="demo-a", message="synthetic"
    )
    assert outcome.final_text and outcome.detail is None and outcome.error_code is None


def test_ask_client_parses_commands_text_and_request_options():
    from fastapi import Request

    from beautyads.api.chat_client import run_ask_once

    app = FastAPI()
    seen = []

    @app.post("/ask")
    async def ask(request: Request):
        seen.append((await request.json(), request.headers.get("X-Tenant-Id")))
        return StreamingResponse(
            iter(
                [
                    encode_event(
                        "step",
                        {"agent": "supervisor", "phase": "start", "status": "running"},
                    ),
                    encode_event(
                        "ui_command",
                        {"kind": "show_graph_fragment", "data": {"evidence_ids": []}},
                    ),
                    encode_event("token", {"text": "a"}),
                    encode_event("token", {"text": "b"}),
                ]
            )
        )

    outcome = run_ask_once(
        app,
        tenant_id="demo-a",
        message="synthetic",
        with_image=True,
        thread_id="demo-a:thread",
    )
    assert outcome.status_code == 200 and outcome.final_text == "ab"
    assert outcome.ui_commands == [
        {"kind": "show_graph_fragment", "data": {"evidence_ids": []}}
    ]
    assert seen == [
        (
            {"message": "synthetic", "with_image": True, "thread_id": "demo-a:thread"},
            "demo-a",
        )
    ]
    assert len(outcome.events) == 4


def test_ask_client_rejection_and_lifespan():
    from beautyads.api.chat_client import run_ask_once

    outcome = run_ask_once(
        create_app(lambda: assembly()), tenant_id="outside", message="synthetic"
    )
    assert outcome.status_code == 403 and outcome.events == []
    assert outcome.final_text == "" and outcome.ui_commands == []
