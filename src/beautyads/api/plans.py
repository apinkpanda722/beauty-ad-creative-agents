"""Tenant-scoped saved plan summaries and persistent local image lookup."""

import re

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import Response

from beautyads.api.ask_view import image_reference
from beautyads.api.design_files import design_file
from beautyads.api.session import resolve_tenant

# DEMO.md limitation: only the latest 200 feedback rows are considered, not all
# saved plans. Repeated decisions can push an older approval out of this window.
FEEDBACK_LIMIT = 200
_PLAN_ID = re.compile(r"[0-9a-f]{32}")
_PLAN_FIELDS = (
    "title",
    "hook_text",
    "hook_type",
    "angle",
    "format",
    "claimed_efficacy",
    "scenes",
    "copy_lines",
    "evidence_ids",
)


def register_plans(app: FastAPI) -> None:
    router = APIRouter()

    @router.get("/plans")
    def plans(request: Request):
        services = request.app.state.assembly
        tenant_id = resolve_tenant(
            request.headers.get("X-Tenant-Id"), allowed_tenants=services.allowed_tenants
        )
        seen = set()
        saved = []
        for item in services.tenants.list_feedback(tenant_id, limit=FEEDBACK_LIMIT):
            if item.tenant_id != tenant_id or item.plan_id in seen:
                continue
            seen.add(item.plan_id)
            if item.decision != "approved":
                continue
            record = services.tenants.get_plan(tenant_id, item.plan_id)
            if record is None or record.tenant_id != tenant_id:
                continue
            plan = record.payload.get("plan")
            if not isinstance(plan, dict):
                continue
            saved.append(
                {
                    "plan_id": item.plan_id,
                    **{key: plan[key] for key in _PLAN_FIELDS if key in plan},
                    "has_image": image_reference(record.payload.get("image"))
                    is not None,
                    "decided_at": item.created_at,
                    "reason": item.reason,
                }
            )
        return {"plans": saved}

    @router.get("/plans/{plan_id}/image")
    def image(plan_id: str, request: Request):
        if _PLAN_ID.fullmatch(plan_id) is None:
            raise HTTPException(404, "PLAN_NOT_FOUND")
        services = request.app.state.assembly
        tenant_id = resolve_tenant(
            request.headers.get("X-Tenant-Id"), allowed_tenants=services.allowed_tenants
        )
        record = services.tenants.get_plan(tenant_id, plan_id)
        if record is None or record.tenant_id != tenant_id:
            raise HTTPException(404, "PLAN_NOT_FOUND")
        reference = image_reference(record.payload.get("image"))
        if reference is None:
            raise HTTPException(404, "DESIGN_NOT_FOUND")
        try:
            path, mime = design_file(
                services.design_dir, reference, reject_symlinks=True
            )
            content = path.read_bytes()
        except (OSError, ValueError, RuntimeError):
            raise HTTPException(404, "DESIGN_NOT_FOUND") from None
        return Response(content, media_type=mime, headers={"Cache-Control": "no-store"})

    app.include_router(router)
