"""Request-local SSE queues and tenant-checked, local-only generated designs."""

import asyncio
import re
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from beautyads.agents.tools import get_tool
from beautyads.api.ask_view import IMAGE_MIMES, build_view, image_reference, json_copy
from beautyads.api.feedback import feedback_for_prompt
from beautyads.api.session import resolve_session, resolve_tenant
from beautyads.api.sse import encode_event
from beautyads.domain.tenant import PlanRecord
from beautyads.domain.tools import ToolContext


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=2000)
    thread_id: str | None = Field(default=None, min_length=1)
    with_image: bool = False


def _event(event):
    """Accept only Supervisor event fields; no arbitrary callback data goes out."""
    if event.get("event") == "step":
        return "step", {key: event[key] for key in ("agent", "phase", "status")}
    if event.get("event") == "tool_start":
        tool = get_tool(event.get("name"))
        if tool is not None:
            return "tool_start", {"name": tool.name, "kind": tool.kind.value}
    return None


def register_ask(app: FastAPI) -> None:
    router = APIRouter()
    # The repository exposes get_plan, not a list/search API. Retain only a
    # local-lifetime lookup of created image references to random plan IDs;
    # authorization always rereads the current tenant repository, never this map.
    designs: dict[tuple[str, str, int], list[str]] = {}

    @router.post("/ask")
    async def ask(body: AskRequest, request: Request):
        services = request.app.state.assembly
        tenant_id, thread_id = await asyncio.to_thread(
            resolve_session,
            request.headers.get("X-Tenant-Id"),
            body.thread_id,
            tenants=services.tenants,
            allowed_tenants=services.allowed_tenants,
        )
        profile = services.workspaces.get(tenant_id)
        if profile is None:
            raise HTTPException(403, "WORKSPACE_MISSING")
        if request.query_params:
            raise HTTPException(422, "ASK_INPUT_INVALID")
        ctx = ToolContext(
            tenant_id=tenant_id,
            as_of=services.as_of,
            last_collected_at=services.last_collected_at,
            price_band=services.price_bands.get(tenant_id),
        )
        feedback = await asyncio.to_thread(
            feedback_for_prompt,
            services.tenants,
            tenant_id,
            services.as_of,
        )
        if body.with_image and not services.image_enabled:
            raise HTTPException(400, "IMAGE_DISABLED")
        loop = asyncio.get_running_loop()
        queue = asyncio.Queue()
        done = object()

        def on_event(event):
            # 7a emits tool_start in result_counts order just after research
            # completes, as one batch. Stage events arrive at their callback time.
            try:
                value = _event(event)
                if value is not None:
                    loop.call_soon_threadsafe(queue.put_nowait, json_copy(value))
            except Exception:  # noqa: BLE001 -- callbacks/disconnects cannot stop the worker
                return

        def work():
            result = services.ask(
                body.message,
                ctx,
                profile,
                feedback,
                body.with_image,
                on_event=on_event,
            )
            plan_ids = []
            references = []
            for item in result.get("plans", []):
                if not isinstance(item.get("plan"), dict):
                    plan_ids.append(None)
                    continue
                plan_id = uuid4().hex
                image = image_reference(item.get("image"))
                record = PlanRecord(
                    tenant_id=tenant_id,
                    plan_id=plan_id,
                    thread_id=thread_id,
                    payload=json_copy(
                        {
                            "plan": item["plan"],
                            "report": item.get("report"),
                            "image": image,
                        }
                    ),
                    created_at=datetime.now(UTC),
                )
                services.tenants.save_plan(tenant_id, record)
                plan_ids.append(plan_id)
                if image is not None:
                    references.append((image, plan_id))
            return build_view(
                result, plan_ids=plan_ids, hydrate=services.hydrate
            ), references

        async def events():
            outcome = None
            failure = None

            async def run():
                nonlocal outcome, failure
                try:
                    outcome, references = await asyncio.to_thread(work)
                    for image, plan_id in references:
                        key = (tenant_id, image["request_key"], image["index"])
                        designs.setdefault(key, []).append(plan_id)
                except Exception as exc:  # noqa: BLE001 -- no exception messages or raw data
                    failure = {
                        "code": "AGENT_INTERNAL_ERROR",
                        "detail": type(exc).__name__,
                    }
                    code = getattr(exc, "code", None)
                    if isinstance(code, str) and re.fullmatch(
                        r"[A-Za-z0-9_:]{1,64}", code
                    ):
                        failure["error_code"] = code
                finally:
                    queue.put_nowait(done)

            task = asyncio.create_task(run())
            try:
                while True:
                    item = await queue.get()
                    if item is done:
                        break
                    name, data = item
                    yield encode_event(name, data)
                if failure is not None:
                    yield encode_event("error", failure)
                    return
                for command in outcome.ui_commands:
                    yield encode_event("ui_command", command)
                yield encode_event("token", {"text": outcome.answer_text})
            finally:
                # A disconnected stream cannot cancel a running synchronous
                # request. The task consumes worker exceptions and saves plans.
                if task.done():
                    await task

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"X-Thread-Id": thread_id, "Cache-Control": "no-cache"},
        )

    @router.get("/design/{request_key}/{index}")
    def design(request_key: str, index: int, request: Request):
        services = request.app.state.assembly
        tenant_id = resolve_tenant(
            request.headers.get("X-Tenant-Id"),
            allowed_tenants=services.allowed_tenants,
        )
        image = None
        for plan_id in designs.get((tenant_id, request_key, index), []):
            record = services.tenants.get_plan(tenant_id, plan_id)
            if record is None or record.tenant_id != tenant_id:
                continue
            reference = image_reference(record.payload.get("image"))
            if (
                reference is not None
                and reference["request_key"] == request_key
                and reference["index"] == index
            ):
                image = reference
                break
        if image is None:
            raise HTTPException(404, "DESIGN_NOT_FOUND")
        directory = sha256(image["request_key"].encode("utf-8")).hexdigest()[:16]
        root = services.design_dir.resolve()
        composed = image.get("composed")
        filename = (
            f"{image['index']:02d}_composed.png"
            if composed is not None
            else f"{image['index']:02d}.{IMAGE_MIMES[image['mime']]}"
        )
        path = (root / directory / filename).resolve()
        if not path.is_relative_to(root):
            raise HTTPException(404, "DESIGN_NOT_FOUND")
        try:
            content = path.read_bytes()
        except (OSError, ValueError):
            raise HTTPException(404, "DESIGN_NOT_FOUND") from None
        return Response(
            content,
            media_type=composed["mime"] if composed is not None else image["mime"],
            headers={"Cache-Control": "no-store"},
        )

    app.include_router(router)
