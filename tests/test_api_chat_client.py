"""The in-process client owns the full lifespan, including pool shutdown."""

import asyncio

from test_api_chat import assembly

from beautyads.api.app import create_app
from beautyads.api.chat_client import parse_sse, run_chat_once


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
