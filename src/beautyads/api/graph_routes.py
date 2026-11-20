"""Read-only public graph and workspace-selection views."""

import asyncio

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from beautyads.analysis.prompts import CLAIM_DISPLAY_NAMES, axis_glossary
from beautyads.api.session import resolve_tenant
from beautyads.domain.labels import Claim
from beautyads.graph.fragment_queries import fragment_parameters
from beautyads.graph.ontology_view import ONTOLOGY_LABELS, ONTOLOGY_RELATIONSHIPS


def register_graph(app: FastAPI) -> None:
    @app.get("/graph/fragment")
    async def fragment(request: Request):
        services = request.app.state.assembly
        resolve_tenant(
            request.headers.get("X-Tenant-Id"), allowed_tenants=services.allowed_tenants
        )
        try:
            ids = fragment_parameters(request.query_params.get("ids", "").split(","))[
                "ids"
            ]
        except ValueError:
            raise HTTPException(422, "GRAPH_IDS_INVALID") from None
        if services.graph_fragment is None:
            raise HTTPException(503, "GRAPH_UNAVAILABLE")
        try:
            result = await asyncio.to_thread(services.graph_fragment, ids)
            return JSONResponse(result)
        except Exception:  # noqa: BLE001 -- graph errors and values never cross the HTTP boundary
            raise HTTPException(500, "GRAPH_QUERY_FAILED") from None

    @app.get("/graph/schema")
    async def schema(request: Request):
        services = request.app.state.assembly
        resolve_tenant(
            request.headers.get("X-Tenant-Id"), allowed_tenants=services.allowed_tenants
        )
        return {
            "labels": ONTOLOGY_LABELS,
            "relationships": ONTOLOGY_RELATIONSHIPS,
            "taxonomy": axis_glossary(),
            "claims": [
                {"value": claim.value, "name": CLAIM_DISPLAY_NAMES[claim]}
                for claim in Claim
                if claim is not Claim.other
            ],
        }

    @app.get("/workspaces")
    async def workspaces(request: Request):
        services = request.app.state.assembly
        # ADR-009 exception: selection precedes a tenant session; expose only allowlisted names.
        return {
            "workspaces": [
                {
                    "tenant_id": tenant,
                    "display_name": profile.get("display_name"),
                    "brand": profile.get("brand"),
                    "product_name": services.product_names.get(tenant),
                }
                for tenant in sorted(services.allowed_tenants)
                if (profile := services.workspaces.get(tenant)) is not None
            ],
            "image_enabled": services.image_enabled,
        }
