"""Exercise the server entry point and lifespan with replaceable dependencies."""

import os
from datetime import date

from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from beautyads.api import checkpointer
from beautyads.api.app import Assembly, create_app
from beautyads.api.chat_client import parse_sse


class Tenants:
    def __init__(self):
        self.threads = {}

    def register_thread(self, tenant, thread):
        self.threads[thread] = tenant

    def assert_thread_access(self, tenant, thread):
        from beautyads.domain.tenant import TenantMismatch

        if self.threads.get(thread) != tenant:
            raise TenantMismatch()


class Graph:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    async def astream(self, state, config, *, context, stream_mode):
        self.calls.append((state, config, context))
        if self.fail:
            raise RuntimeError("private diagnostic must stay private")
        yield (
            "custom",
            {
                "type": "tool_start",
                "name": "lookup_certified_products",
                "kind": "lookup",
                "raw": "private",
            },
        )
        yield (
            "updates",
            {"assistant": {"final_text": "synthetic answer", "raw": "private"}},
        )


def assembly(graph=None, close=lambda: None):
    return Assembly(
        graph=graph or Graph(),
        tenants=Tenants(),
        allowed_tenants=frozenset({"demo-a", "demo-b"}),
        as_of=date(2026, 1, 2),
        last_collected_at=None,
        chat=None,
        tool_runner=None,
        close=close,
    )


def test_lifespan_and_request_time_service_lookup(monkeypatch):
    monkeypatch.delenv("LANGGRAPH_STRICT_MSGPACK", raising=False)
    first, second, closed, built = Graph(), Graph(), [], []
    services = assembly(first, lambda: closed.append(True))

    def assemble():
        built.append(True)
        return services

    app = create_app(assemble)
    assert built == []
    with TestClient(app) as client:
        assert built == [True] and os.environ["LANGGRAPH_STRICT_MSGPACK"] == "true"
        response = client.post(
            "/chat", headers={"X-Tenant-Id": "demo-a"}, json={"message": "synthetic"}
        )
        assert response.status_code == 200 and response.headers[
            "content-type"
        ].startswith("text/event-stream")
        events = parse_sse(response.text)
        assert {name for name, body in events} <= {"step", "tool_start", "token"}
        assert [body["phase"] for name, body in events if name == "step"] == [
            "start",
            "end",
        ]
        assert "private" not in response.text and "X-Tenant-Id" not in response.text
        assert first.calls[0][2]["tool_context"].tenant_id == "demo-a"
        assert first.calls[0][0]["as_of"] == "2026-01-02"
        app.state.assembly.graph = second
        assert (
            client.post(
                "/chat",
                headers={"X-Tenant-Id": "demo-a"},
                json={"message": "next", "thread_id": response.headers["X-Thread-Id"]},
            ).status_code
            == 200
        )
        assert len(first.calls) == len(second.calls) == 1
    assert closed == [True]


def test_error_is_code_only_and_health_calls_no_dependency():
    graph = Graph(fail=True)
    with TestClient(create_app(lambda: assembly(graph))) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        assert graph.calls == []
        response = client.post(
            "/chat", headers={"X-Tenant-Id": "demo-a"}, json={"message": "synthetic"}
        )
    events = parse_sse(response.text)
    assert events[-1] == ("error", {"code": "AGENT_INTERNAL_ERROR"})
    assert "private" not in response.text


def test_pool_configuration_and_separate_setup(monkeypatch):
    import asyncio

    seen = []

    class Pool:
        def __init__(self, conninfo, **kwargs):
            seen.append((conninfo, kwargs))

        async def open(self):
            seen.append("open")

        async def close(self):
            seen.append("close")

    class Saver:
        def __init__(self, pool):
            self.conn = pool

        async def setup(self):
            seen.append("setup")

    monkeypatch.setattr(checkpointer, "AsyncConnectionPool", Pool)
    monkeypatch.setattr(checkpointer, "AsyncPostgresSaver", Saver)

    async def exercise():
        saver = await checkpointer.build_checkpointer("synthetic-dsn")
        assert seen[-1] == "open"
        await checkpointer.setup_checkpointer(saver)
        await saver.conn.close()

    asyncio.run(exercise())
    assert seen[0][1]["kwargs"] == {
        "autocommit": True,
        "row_factory": dict_row,
        "prepare_threshold": 0,
    }
    assert seen[1:] == ["open", "setup", "close"]


def test_chat_entry_point_runs_real_graph_and_registered_tool():
    from functools import partial
    from types import SimpleNamespace

    from langgraph.checkpoint.memory import InMemorySaver
    from test_agent_skeleton import reply

    from beautyads.agents.skeleton import build_graph
    from beautyads.agents.tools import run_tool
    from beautyads.api.chat_client import run_chat_once
    from beautyads.llm.chat import ToolCall

    queries, seen = [], []

    class FakeNeo4j:
        def run(self, query, params):
            queries.append((query, params))
            return SimpleNamespace(records=[])

    responses = iter(
        [
            reply(calls=[ToolCall("c", "lookup_certified_products", {}, None)]),
            reply("synthetic final"),
        ]
    )

    def chat(**kwargs):
        seen.append(kwargs)
        return next(responses)

    services = assembly(
        build_graph(
            chat=chat,
            tool_runner=partial(run_tool, graph=FakeNeo4j()),
            checkpointer=InMemorySaver(),
        )
    )
    outcome = run_chat_once(
        create_app(lambda: services), tenant_id="demo-a", message="synthetic"
    )
    assert outcome.status_code == 200
    assert [name for name, _ in outcome.events] == [
        "step",
        "tool_start",
        "step",
        "token",
    ]
    assert len(queries) == 1 and len(seen) == 2 and outcome.final_text
    assert seen[-1]["messages"][-1]["role"] == "tool"
