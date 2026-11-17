"""Live command guards tested without live dependencies."""

from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from beautyads.eval import live_agent
from beautyads.settings import Settings


@pytest.mark.parametrize(
    "code",
    [
        "ENV_MISSING:OPENAI_API_KEY",
        "POSTGRES_NOT_RUNNING",
        "NEO4J_NOT_RUNNING",
        "MIGRATIONS_PENDING",
    ],
)
def test_preflight_failure_never_invokes_app(code, tmp_path):
    out = StringIO()

    def forbidden(*args, **kwargs):
        pytest.fail("failed preflight must not invoke app")

    status = live_agent.main(
        ["--tenant", "demo-a", "--message", "synthetic"],
        out=out,
        check=lambda: [code],
        run=forbidden,
        settings=Settings(ledger_path=tmp_path / "costs.jsonl"),
    )
    assert status == 2 and code in out.getvalue()


def test_tenant_is_required():
    with pytest.raises(SystemExit) as error:
        live_agent.main(["--message", "synthetic"])
    assert error.value.code == 2


def test_budget_guard_stops_before_app(tmp_path):
    def forbidden(*args, **kwargs):
        pytest.fail("over budget must not start app")

    out = StringIO()
    assert (
        live_agent.main(
            ["--tenant", "demo-a", "--message", "synthetic", "--max-usd", "0.00000001"],
            out=out,
            check=list,
            run=forbidden,
            settings=Settings(ledger_path=tmp_path / "ledger"),
        )
        == 2
    )
    assert "CALL_COST_LIMIT" in out.getvalue()


@pytest.mark.parametrize("flag", ["nan", "inf", "-1", "0"])
def test_budget_must_be_finite_positive(flag):
    with pytest.raises(SystemExit):
        live_agent.main(
            ["--tenant", "demo-a", "--message", "synthetic", "--max-usd", flag]
        )


def test_preflight_stops_in_stages_and_never_prints_values():
    def forbidden(*args):
        pytest.fail("later check was called")

    assert live_agent.preflight(
        environ={}, env_file=None, docker_check=forbidden, migration_check=forbidden
    ) == [
        "ENV_MISSING:OPENAI_API_KEY",
        "ENV_MISSING:NEO4J_PASSWORD",
        "ENV_MISSING:POSTGRES_PASSWORD",
    ]
    fake_env = dict.fromkeys(
        ["OPENAI_API_KEY", "NEO4J_PASSWORD", "POSTGRES_PASSWORD"],
        "synthetic-placeholder",
    )
    assert live_agent.preflight(
        environ=fake_env,
        env_file=None,
        docker_check=lambda: True,
        container_check=lambda name: False,
        migration_check=forbidden,
    ) == ["POSTGRES_NOT_RUNNING", "NEO4J_NOT_RUNNING"]
    assert live_agent.preflight(
        environ=fake_env,
        env_file=None,
        docker_check=lambda: True,
        container_check=lambda name: True,
        tcp_check=lambda *a: True,
        migration_check=lambda: False,
    ) == ["MIGRATIONS_PENDING"]


def test_budget_checked_again_for_every_actual_call(tmp_path):
    seen = []
    chat = live_agent.budgeted_chat(
        Settings(ledger_path=tmp_path / "ledger"),
        0.001,
        complete=lambda **kw: seen.append(kw),
    )
    chat(model="gpt-6-luna", reasoning_effort="none", messages=[], tools=[])
    assert len(seen) == 1 and seen[0]["max_tokens"] == 1024
    with pytest.raises(live_agent.CallCostLimit):
        chat(
            model="gpt-6-luna",
            reasoning_effort="none",
            messages=[{"role": "tool", "content": "x" * 100_000}],
            tools=[],
        )
    assert len(seen) == 1


def test_main_reports_event_names_answer_and_ledger_delta(tmp_path):
    out = StringIO()
    seen = []

    def run(app, **kwargs):
        seen.append(kwargs)
        return SimpleNamespace(
            status_code=200,
            events=[("step", {}), ("token", {"text": "synthetic answer"})],
            final_text="synthetic answer",
        )

    assert (
        live_agent.main(
            ["--tenant", "demo-a", "--message", "synthetic"],
            out=out,
            check=list,
            run=run,
            settings=Settings(ledger_path=tmp_path / "ledger"),
        )
        == 0
    )
    assert seen[0]["tenant_id"] == "demo-a"
    assert all(
        word in out.getvalue()
        for word in ("step", "token", "synthetic answer", "cost_usd")
    )
    assert "synthetic-placeholder" not in out.getvalue()


def test_migration_check_is_read_only_and_always_closes(monkeypatch):
    seen = []

    class Conn:
        def execute(self, query):
            assert query.strip().startswith("SELECT")
            return SimpleNamespace(
                fetchall=lambda: [(version,) for version, _, _ in live_agent.MIGRATIONS]
            )

        def close(self):
            seen.append("close")

    monkeypatch.setattr(live_agent, "connect", lambda _: Conn())
    assert live_agent.migrations_ready("synthetic-dsn")
    assert seen == ["close"]


def test_entry_point_imports_only_allowed_sdk():
    import ast

    tree = ast.parse(Path(live_agent.__file__).read_text())
    modules = [
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    ]
    modules += [
        a.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for a in node.names
    ]
    assert not any(
        name
        and name.split(".")[0] in {"fastapi", "httpx", "litellm", "psycopg", "neo4j"}
        for name in modules
    )


@pytest.mark.parametrize("setup_fails", [False, True])
def test_real_assembly_resources_are_lifespan_owned(monkeypatch, tmp_path, setup_fails):
    import asyncio
    from datetime import UTC, datetime

    from langgraph.checkpoint.memory import InMemorySaver
    from test_agent_skeleton import reply
    from test_api_chat import Tenants

    from beautyads.api.app import create_app
    from beautyads.api.chat_client import run_chat_once

    seen = []
    collected = datetime(2026, 1, 2, tzinfo=UTC)

    class Conn:
        def close(self):
            seen.append(("postgres-close", None))

    class GraphConn:
        def close(self):
            seen.append(("neo4j-close", None))

    class Pool:
        async def close(self):
            seen.append(("pool-close", asyncio.get_running_loop()))

    async def build(conninfo):
        seen.append(("pool-open", asyncio.get_running_loop()))
        saver = InMemorySaver()
        saver.conn = Pool()
        return saver

    async def setup(saver):
        seen.append(("setup", asyncio.get_running_loop()))
        if setup_fails:
            raise RuntimeError("synthetic setup failure")

    calls = []

    def chat(**kwargs):
        calls.append(kwargs)
        return reply("synthetic")

    monkeypatch.setattr(live_agent, "postgres_dsn", lambda: "synthetic-dsn")
    monkeypatch.setattr(live_agent, "connect", lambda _: Conn())
    monkeypatch.setattr(live_agent, "connect_graph", GraphConn)
    monkeypatch.setattr(live_agent, "build_checkpointer", build)
    monkeypatch.setattr(live_agent, "setup_checkpointer", setup)
    monkeypatch.setattr(live_agent, "PostgresTenantRepository", lambda _: Tenants())
    monkeypatch.setattr(
        live_agent,
        "PostgresCreativeStore",
        lambda _: SimpleNamespace(
            collection_stats=lambda: [SimpleNamespace(last_collected_at=collected)]
        ),
    )
    monkeypatch.setattr(live_agent, "budgeted_chat", lambda *a: chat)
    app = create_app(
        lambda: live_agent.assemble_live(
            tenant_id="demo-a",
            settings=Settings(ledger_path=tmp_path / "ledger"),
            max_usd=0.02,
        )
    )
    assert seen == []
    if setup_fails:
        with pytest.raises(RuntimeError, match="synthetic setup failure"):
            run_chat_once(app, tenant_id="demo-a", message="synthetic")
        assert calls == []
    else:
        outcome = run_chat_once(app, tenant_id="demo-a", message="synthetic")
        assert outcome.status_code == 200 and outcome.final_text
        assert any(
            collected.isoformat() in message["content"]
            for message in calls[0]["messages"]
        )
    assert [name for name, _ in seen] == [
        "pool-open",
        "setup",
        "pool-close",
        "neo4j-close",
        "postgres-close",
    ]
    assert seen[0][1] is seen[1][1] is seen[2][1]
