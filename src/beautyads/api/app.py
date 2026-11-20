"""Lifespan-owned services and a single tenant-checked SSE request."""

import asyncio
import inspect
import os
import re
from collections.abc import Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from beautyads.agents.skeleton import RECURSION_LIMIT
from beautyads.api.ask import register_ask
from beautyads.api.feedback import register_feedback
from beautyads.api.graph_routes import register_graph
from beautyads.api.session import resolve_session
from beautyads.api.sse import encode_event
from beautyads.domain.tenant import TenantRepository
from beautyads.domain.tools import ToolContext


@dataclass
class Assembly:
    graph: Any
    tenants: TenantRepository
    allowed_tenants: frozenset[str]
    as_of: date
    last_collected_at: datetime | None
    chat: Callable | None
    tool_runner: Callable | None
    close: Callable
    workspaces: Mapping[str, dict] = field(default_factory=dict)
    price_bands: Mapping[str, dict] = field(default_factory=dict)
    ask: Callable | None = None
    hydrate: Callable | None = None
    design_dir: Path = Path("data/design")
    image_enabled: bool = False
    graph_fragment: Callable | None = None
    product_names: Mapping[str, str] = field(default_factory=dict)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1)
    thread_id: str | None = Field(default=None, min_length=1)


def create_app(assemble: Callable[[], Assembly]) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")
        services = assemble()
        if inspect.isawaitable(services):
            services = await services
        app.state.assembly = services
        try:
            yield
        finally:
            result = services.close()
            if inspect.isawaitable(result):
                await result

    app = FastAPI(lifespan=lifespan)
    register_feedback(app)
    register_ask(app)
    register_graph(app)

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.post("/chat")
    async def chat(body: ChatRequest, request: Request):
        services = request.app.state.assembly
        tenant_id, thread_id = await asyncio.to_thread(
            resolve_session,
            request.headers.get("X-Tenant-Id"),
            body.thread_id,
            tenants=services.tenants,
            allowed_tenants=services.allowed_tenants,
        )
        ctx = ToolContext(
            tenant_id=tenant_id,
            as_of=services.as_of,
            last_collected_at=services.last_collected_at,
        )
        state = {
            "messages": [
                {
                    "role": "system",
                    "content": "skeleton-v1: 제품 인증 근거를 조회하고, 연결되지 않은 인증은 unknown으로 설명한다.",
                },
                {
                    "role": "system",
                    "content": f"기준일: {services.as_of.isoformat()}; 마지막 수집: {services.last_collected_at.isoformat() if services.last_collected_at else 'unknown'}",
                },
                {"role": "user", "content": body.message},
            ],
            "tenant_id": tenant_id,
            "thread_id": thread_id,
            "as_of": services.as_of.isoformat(),
            "last_collected_at": services.last_collected_at.isoformat()
            if services.last_collected_at
            else None,
            "final_text": "",
            "tool_trace": [],
            "step_count": 0,
        }

        async def events():
            yield encode_event("step", {"agent": "assistant", "phase": "start"})
            try:
                final_text = ""
                async for mode, chunk in services.graph.astream(
                    state,
                    {
                        "configurable": {"thread_id": thread_id},
                        "recursion_limit": RECURSION_LIMIT,
                    },
                    context={"tool_context": ctx},
                    stream_mode=["updates", "custom"],
                ):
                    if (
                        mode == "custom"
                        and chunk.get("type") == "tool_start"
                        and chunk.get("name") == "lookup_certified_products"
                    ):
                        yield encode_event(
                            "tool_start",
                            {"name": "lookup_certified_products", "kind": "lookup"},
                        )
                    elif mode == "updates":
                        update = chunk.get("assistant") or {}
                        if isinstance(update.get("final_text"), str):
                            final_text = update["final_text"]
                yield encode_event(
                    "step",
                    {
                        "agent": "assistant",
                        "phase": "end",
                        "incomplete": "[미완료:" in final_text,
                    },
                )
                yield encode_event("token", {"text": final_text})
            except Exception as exc:  # noqa: BLE001 -- expose only class name and a validated code
                error = {"code": "AGENT_INTERNAL_ERROR", "detail": type(exc).__name__}
                code = getattr(exc, "code", None)
                if isinstance(code, str) and re.fullmatch(r"[A-Za-z0-9_:]{1,64}", code):
                    error["error_code"] = code
                yield encode_event("error", error)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"X-Thread-Id": thread_id, "Cache-Control": "no-cache"},
        )

    return app
