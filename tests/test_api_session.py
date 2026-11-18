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


@pytest.mark.parametrize(
    "header,status,code",
    [
        (None, 400, "TENANT_CONTEXT_MISSING"),
        ("", 400, "TENANT_CONTEXT_MISSING"),
        ("INVALID SPACE", 400, "TENANT_CONTEXT_MISSING"),
        ("demo-a\n", 400, "TENANT_CONTEXT_MISSING"),
        ("outside", 403, "TENANT_NOT_ALLOWED"),
    ],
)
def test_resolve_tenant_fails_without_creating_thread(
    monkeypatch, header, status, code
):
    from fastapi import HTTPException
    from test_api_chat import Tenants

    from beautyads.api import session

    tenants = Tenants()
    calls = []
    monkeypatch.setattr(tenants, "register_thread", lambda *args: calls.append(args))
    monkeypatch.setattr(
        session, "make_thread_id", lambda *args: pytest.fail("created a thread")
    )
    with pytest.raises(HTTPException) as caught:
        session.resolve_tenant(header, allowed_tenants={"demo-a"})
    assert caught.value.status_code == status
    assert caught.value.detail == code
    assert calls == [] and tenants.threads == {}


def test_resolve_tenant_returns_only_tenant_without_thread(monkeypatch):
    from beautyads.api import session

    monkeypatch.setattr(
        session, "make_thread_id", lambda *args: pytest.fail("created a thread")
    )
    assert session.resolve_tenant("demo-a", allowed_tenants={"demo-a"}) == "demo-a"
