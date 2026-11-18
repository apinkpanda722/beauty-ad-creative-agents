"""Session-scoped feedback writes and lossless, tenant-local prompt summaries."""

from datetime import UTC, date, datetime
from typing import Literal

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict

from beautyads.api.session import resolve_tenant
from beautyads.domain.tenant import Feedback, TenantRepository, summarize_feedback


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    plan_id: str
    decision: Literal["approved", "rejected"]
    reason: str


class _FeedbackRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def safe_handler(request: Request):
            try:
                return await handler(request)
            except RequestValidationError:
                # FastAPI's default detail includes rejected input values.
                return JSONResponse(
                    {"detail": "FEEDBACK_INPUT_INVALID"}, status_code=422
                )
            except HTTPException:
                raise
            except Exception:  # noqa: BLE001 -- storage errors may contain raw reasons
                return JSONResponse(
                    {"detail": "FEEDBACK_INTERNAL_ERROR"}, status_code=500
                )

        return safe_handler


def register_feedback(app: FastAPI) -> None:
    router = APIRouter(route_class=_FeedbackRoute)

    @router.post("/feedback")
    def feedback(body: FeedbackRequest, request: Request):
        services = request.app.state.assembly
        tenant_id = resolve_tenant(
            request.headers.get("X-Tenant-Id"), allowed_tenants=services.allowed_tenants
        )
        record = services.tenants.get_plan(tenant_id, body.plan_id)
        if record is None:
            raise HTTPException(404, "PLAN_NOT_FOUND")
        plan = record.payload.get("plan")
        plan = plan if isinstance(plan, dict) else {}
        item = Feedback(
            tenant_id=tenant_id,
            plan_id=body.plan_id,
            decision=body.decision,
            reason=body.reason,
            hook_type=plan.get("hook_type"),
            claims=plan.get("claimed_efficacy", []),
            created_at=datetime.now(UTC),
        )
        services.tenants.add_feedback(tenant_id, item)
        return {"status": "ok"}

    app.include_router(router)


def feedback_for_prompt(
    tenants: TenantRepository, tenant_id: str, as_of: date, *, limit: int = 50
) -> dict:
    items = tenants.list_feedback(tenant_id, limit=limit)
    return summarize_feedback(items, as_of=as_of).model_dump(mode="json")
