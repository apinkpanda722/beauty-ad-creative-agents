"""Tenant-checked exploration routes and lazy assembly, entirely offline."""

import asyncio
import threading
from types import SimpleNamespace

import pytest
import test_api_assembly
from fastapi.testclient import TestClient
from test_api_ask import services

from beautyads.api.app import create_app
from beautyads.graph import explore_queries as explore

rig = test_api_assembly.rig
HEADERS = {"X-Tenant-Id": "demo-a"}
PATHS = ("/graph/overview", "/graph/neighbors?id=Brand:synthetic")


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize(
    "headers,status,code",
    [
        ({}, 400, "TENANT_CONTEXT_MISSING"),
        ({"X-Tenant-Id": "outside"}, 403, "TENANT_NOT_ALLOWED"),
    ],
)
def test_tenant_check_precedes_validation_and_service(path, headers, status, code):
    with TestClient(create_app(services)) as client:
        response = client.get(path, headers=headers)
        invalid = client.get("/graph/neighbors?id=invalid", headers=headers)
    assert response.status_code == invalid.status_code == status
    assert response.json() == invalid.json() == {"detail": code}


@pytest.mark.parametrize("path", PATHS)
def test_unavailable(path):
    with TestClient(create_app(services)) as client:
        response = client.get(path, headers=HEADERS)
    assert response.status_code == 503
    assert response.json() == {"detail": "GRAPH_UNAVAILABLE"}


@pytest.mark.parametrize(
    "identifier",
    [
        None,
        "",
        "invalid",
        "Feedback:private",
        "Product:brand",
        "creative:youtube",
        "creative:youtube:id:tail",
        "Brand:" + "x" * 295,
        "Brand:a\n",
        "Brand:a\x7f",
    ],
)
def test_invalid_id_returns_422_even_without_service(identifier):
    with TestClient(create_app(services)) as client:
        response = client.get(
            "/graph/neighbors",
            headers=HEADERS,
            params={} if identifier is None else {"id": identifier},
        )
    assert response.status_code == 422
    assert response.json() == {"detail": "GRAPH_ID_INVALID"}


@pytest.mark.parametrize(
    "path,field", list(zip(PATHS, ("graph_overview", "graph_neighbors"), strict=True))
)
def test_success_in_worker_thread_and_internal_error_redaction(
    path, field, caplog, capsys
):
    value = services()
    calls, threads = [], []
    payload = {"nodes": [], "edges": [], "truncated": False}

    def query(*args):
        calls.append(args)
        threads.append(threading.get_ident())
        return payload

    setattr(value, field, query)
    with TestClient(create_app(lambda: value)) as client:

        async def server_thread():
            return threading.get_ident()

        server_id = client.portal.call(server_thread)
        response = client.get(path, headers=HEADERS)
        assert response.status_code == 200 and response.json() == payload

        def fail(*args):
            raise RuntimeError("PRIVATE_QUERY_DIAGNOSTIC")

        setattr(value, field, fail)
        failure = client.get(path, headers=HEADERS)
    assert calls == [() if field == "graph_overview" else ("Brand:synthetic",)]
    assert threads[0] != server_id
    assert failure.status_code == 500
    assert failure.json() == {"detail": "GRAPH_QUERY_FAILED"}
    assert "PRIVATE_QUERY_DIAGNOSTIC" not in failure.text + caplog.text + str(
        capsys.readouterr()
    )


def test_assembly_injects_lazy_queries_and_validated_parameters(rig, monkeypatch):
    original = rig.graph.run
    selected = (explore.overview_query(), explore.neighbors_query("Brand:synthetic"))
    rows = [{"labels": ["Brand"], "props": {"name": "synthetic"}}]

    def query(text, params):
        if text in selected:
            rig.queries.append((text, params))
            return SimpleNamespace(records=rows)
        return original(text, params)

    monkeypatch.setattr(rig.graph, "run", query)

    async def run():
        value = await rig.start()
        try:
            assert callable(value.graph_overview) and callable(value.graph_neighbors)
            assert not any(text in selected for text, _ in rig.queries)
            rig.queries.clear()
            assert value.graph_overview() == explore.build_overview(rows)
            assert value.graph_neighbors("Brand:synthetic") == explore.build_neighbors(
                rows
            )
            assert rig.queries == [
                (selected[0], explore.overview_parameters()),
                (selected[1], explore.neighbors_parameters("Brand:synthetic")),
            ]
        finally:
            await value.close()

    asyncio.run(run())
