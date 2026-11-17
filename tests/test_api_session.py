"""Rejected requests cannot reach a graph."""

import pytest
from fastapi.testclient import TestClient
from test_api_chat import Graph, assembly

from beautyads.api.app import create_app


@pytest.mark.parametrize(
    "headers,body,status,code",
    [
        ({}, {"message": "synthetic"}, 400, "TENANT_CONTEXT_MISSING"),
        (
            {"X-Tenant-Id": "INVALID SPACE"},
            {"message": "synthetic"},
            400,
            "TENANT_CONTEXT_MISSING",
        ),
        (
            {"X-Tenant-Id": "outside"},
            {"message": "synthetic"},
            403,
            "TENANT_NOT_ALLOWED",
        ),
        (
            {"X-Tenant-Id": "demo-b"},
            {"message": "synthetic", "thread_id": "demo-a:owned"},
            403,
            "TENANT_MISMATCH",
        ),
        (
            {"X-Tenant-Id": "demo-a"},
            {"message": "synthetic", "thread_id": "demo-a:missing"},
            403,
            "TENANT_MISMATCH",
        ),
        (
            {"X-Tenant-Id": "demo-a"},
            {"message": "synthetic", "tenant_id": "demo-b"},
            422,
            None,
        ),
        (
            {"X-Tenant-Id": "demo-a"},
            {"message": "synthetic", "as_of": "2026-01-01"},
            422,
            None,
        ),
    ],
)
def test_session_refuses_before_graph(headers, body, status, code):
    class Forbidden(Graph):
        async def astream(self, *args, **kwargs):
            pytest.fail("rejected session called graph")
            yield

    graph = Forbidden()
    services = assembly(graph)
    services.tenants.register_thread("demo-a", "demo-a:owned")
    with TestClient(create_app(lambda: services)) as client:
        response = client.post("/chat", headers=headers, json=body)
    assert response.status_code == status
    if code:
        assert response.json() == {"detail": code}
    assert graph.calls == []
