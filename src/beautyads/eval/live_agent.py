"""User-run one-request agent demo; verification uses injected local fakes only."""

import argparse
import json
import math
import subprocess
import sys
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from functools import partial
from typing import TextIO
from urllib.parse import urlsplit

from beautyads.agents.skeleton import build_graph, skeleton_tools
from beautyads.agents.tools import run_tool
from beautyads.api.app import Assembly, create_app
from beautyads.api.chat_client import run_chat_once
from beautyads.api.checkpointer import (
    build_checkpointer,
    close_checkpointer,
    setup_checkpointer,
)
from beautyads.domain.tenant import TenantContextMissing, validate_tenant_id
from beautyads.graph.connection import connect_graph
from beautyads.llm.chat import chat_complete
from beautyads.llm.prices import compute_cost
from beautyads.obs import check_cap, provider_total
from beautyads.pipeline.preflight import docker_running, tcp_reachable
from beautyads.settings import (
    DEFAULT_ENV_FILE,
    SettingError,
    get_setting,
    load_settings,
    neo4j_uri,
)
from beautyads.store.connection import connect, postgres_dsn
from beautyads.store.repository import PostgresCreativeStore
from beautyads.store.schema import MIGRATIONS
from beautyads.store.tenant_repository import PostgresTenantRepository

MAX_TOKENS = 1024


class CallCostLimit(Exception):
    code = "CALL_COST_LIMIT"


def estimate_call_usd(messages, tools):
    # Conservative uncached bound: at most one token per UTF-8 byte, plus
    # framing allowance. Output is limited in the actual chat wrapper too.
    size = len(
        json.dumps({"messages": messages, "tools": tools}, ensure_ascii=False).encode(
            "utf-8"
        )
    )
    return compute_cost("gpt-6-luna", input_tokens=size + 256, output_tokens=MAX_TOKENS)


def budgeted_chat(settings, max_usd, *, complete=chat_complete):
    caps = dict(settings.provider_caps_usd)

    def chat(**kwargs):
        estimated = estimate_call_usd(
            kwargs.get("messages", []), kwargs.get("tools", [])
        )
        if estimated > max_usd:
            raise CallCostLimit()
        check_cap(settings.ledger_path, "openai", caps, additional_usd=estimated)
        return complete(
            **kwargs,
            purpose="agent-skeleton",
            ledger_path=settings.ledger_path,
            caps=caps,
            max_tokens=MAX_TOKENS,
        )

    return chat


def container_running(name):
    try:
        result = subprocess.run(
            [
                "docker",
                "inspect",
                "--format",
                "{{.State.Running}}",
                f"beautyads-{name}",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        return result.returncode == 0 and result.stdout.strip() == "true"
    except (OSError, subprocess.TimeoutExpired):
        return False


def migrations_ready(conninfo):
    conn = None
    try:
        conn = connect(conninfo)
        rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
        return {version for version, _, _ in MIGRATIONS} <= {row[0] for row in rows}
    except Exception:  # noqa: BLE001 -- all database failures fail the read-only preflight
        return False
    finally:
        if conn is not None:
            conn.close()


def preflight(
    *,
    environ=None,
    env_file=DEFAULT_ENV_FILE,
    docker_check=docker_running,
    container_check=container_running,
    tcp_check=tcp_reachable,
    migration_check=None,
):
    config = {"environ": environ, "env_file": env_file}
    problems = [
        f"ENV_MISSING:{name}"
        for name in ("OPENAI_API_KEY", "NEO4J_PASSWORD", "POSTGRES_PASSWORD")
        if get_setting(name, **config) is None
    ]
    if problems:
        return problems
    if not docker_check():
        return ["DOCKER_DOWN"]
    problems = [
        f"{name.upper()}_NOT_RUNNING"
        for name in ("postgres", "neo4j")
        if not container_check(name)
    ]
    if problems:
        return problems
    try:
        pg_port = int(get_setting("BEAUTYADS_POSTGRES_PORT", "5433", **config))
        uri = urlsplit(neo4j_uri(**config))
        for name, host, port in (
            ("POSTGRES", "127.0.0.1", pg_port),
            ("NEO4J", uri.hostname, uri.port or 7687),
        ):
            if not host or not 1 <= port <= 65535 or not tcp_check(host, port, 1.0):
                problems.append(f"{name}_UNREACHABLE")
    except (TypeError, ValueError):
        return ["SERVICE_CONFIG_INVALID"]
    if problems:
        return problems
    ready = (
        migration_check()
        if migration_check is not None
        else migrations_ready(postgres_dsn(**config))
    )
    return [] if ready else ["MIGRATIONS_PENDING"]


async def assemble_live(*, tenant_id, settings, max_usd):
    """Called inside lifespan; partial startup and normal exit both close resources."""
    async with AsyncExitStack() as stack:
        conn = connect(postgres_dsn())
        stack.callback(conn.close)
        graph_connection = connect_graph()
        stack.callback(graph_connection.close)
        saver = await build_checkpointer(postgres_dsn())
        stack.push_async_callback(close_checkpointer, saver)
        await setup_checkpointer(saver)
        collected = [
            item.last_collected_at
            for item in PostgresCreativeStore(conn).collection_stats()
            if item.last_collected_at is not None
        ]
        chat = budgeted_chat(settings, max_usd)
        runner = partial(run_tool, graph=graph_connection)
        graph = build_graph(chat=chat, tool_runner=runner, checkpointer=saver)
        resources = stack.pop_all()
        return Assembly(
            graph=graph,
            tenants=PostgresTenantRepository(conn),
            allowed_tenants=frozenset({tenant_id}),
            as_of=datetime.now(UTC).date(),
            last_collected_at=max(collected) if collected else None,
            chat=chat,
            tool_runner=runner,
            close=resources.aclose,
        )


def _positive_usd(value):
    try:
        amount = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            "max-usd must be a positive finite number"
        ) from None
    if not math.isfinite(amount) or amount <= 0:
        raise argparse.ArgumentTypeError("max-usd must be a positive finite number")
    return amount


def main(argv=None, *, out: TextIO | None = None, check=None, run=None, settings=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--message", required=True)
    parser.add_argument("--max-usd", type=_positive_usd, default=0.02)
    args = parser.parse_args(argv)
    out = sys.stdout if out is None else out
    try:
        validate_tenant_id(args.tenant)
    except TenantContextMissing:
        print("PREFLIGHT_FAILED TENANT_CONTEXT_MISSING", file=out)
        return 2
    try:
        problems = (preflight if check is None else check)()
        if problems:
            for code in problems:
                print(f"PREFLIGHT_FAILED {code}", file=out)
                if code == "MIGRATIONS_PENDING":
                    print("make db-migrate를 실행하라", file=out)
            return 2
        settings = load_settings() if settings is None else settings
        if (
            estimate_call_usd(
                [{"role": "user", "content": args.message}], skeleton_tools()
            )
            > args.max_usd
        ):
            print("PREFLIGHT_FAILED CALL_COST_LIMIT", file=out)
            return 2
        before = provider_total(settings.ledger_path, "openai")
        app = create_app(
            partial(
                assemble_live,
                tenant_id=args.tenant,
                settings=settings,
                max_usd=args.max_usd,
            )
        )
        outcome = (run_chat_once if run is None else run)(
            app, tenant_id=args.tenant, message=args.message
        )
        cost = provider_total(settings.ledger_path, "openai") - before
        error_fields = {}
        if any(name == "error" for name, _ in outcome.events):
            if outcome.detail is not None:
                error_fields["detail"] = outcome.detail
            if outcome.error_code is not None:
                error_fields["error_code"] = outcome.error_code
        print(
            json.dumps(
                {
                    "status_code": outcome.status_code,
                    "events": [name for name, _ in outcome.events],
                    "final_text": outcome.final_text,
                    "cost_usd": cost,
                    **error_fields,
                },
                ensure_ascii=False,
            ),
            file=out,
        )
        return (
            0
            if outcome.status_code == 200
            and not any(name == "error" for name, _ in outcome.events)
            else 3
        )
    except SettingError as error:
        print(f"PREFLIGHT_FAILED {error.code}:{error.name}", file=out)
        return 2
    except Exception:  # noqa: BLE001 -- public CLI errors must not expose credentials
        print("STOPPED LIVE_AGENT_FAILED", file=out)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
