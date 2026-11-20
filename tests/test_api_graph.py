"""Read-only graph HTTP contracts with replaceable, offline services."""

import threading

import pytest
from fastapi.testclient import TestClient
from test_api_ask import services

from beautyads.analysis.prompts import CLAIM_DISPLAY_NAMES, axis_glossary
from beautyads.api.app import create_app
from beautyads.domain.labels import Claim
from beautyads.graph.ontology_view import ONTOLOGY_LABELS, ONTOLOGY_RELATIONSHIPS

HEADERS = {"X-Tenant-Id": "demo-a"}
EID = "youtube:synthetic"


@pytest.mark.parametrize("path", ["/graph/fragment", "/graph/schema"])
@pytest.mark.parametrize(
    "headers,status,detail",
    [
        ({}, 400, "TENANT_CONTEXT_MISSING"),
        ({"X-Tenant-Id": "outside"}, 403, "TENANT_NOT_ALLOWED"),
    ],
)
def test_graph_requires_allowed_tenant_before_ids(path, headers, status, detail):
    with TestClient(create_app(services)) as client:
        response = client.get(path, headers=headers)
    assert response.status_code == status
    assert response.json() == {"detail": detail}


@pytest.mark.parametrize(
    "ids", [None, "", "invalid", EID + ",", ",".join(f"youtube:{i}" for i in range(31))]
)
def test_graph_ids_invalid_before_service_availability(ids):
    with TestClient(create_app(services)) as client:
        response = client.get(
            "/graph/fragment",
            headers=HEADERS,
            params={} if ids is None else {"ids": ids},
        )
    assert response.status_code == 422
    assert response.json() == {"detail": "GRAPH_IDS_INVALID"}


def test_graph_unavailable():
    with TestClient(create_app(services)) as client:
        response = client.get("/graph/fragment", headers=HEADERS, params={"ids": EID})
    assert response.status_code == 503
    assert response.json() == {"detail": "GRAPH_UNAVAILABLE"}


def test_fragment_success_uses_current_assembly_and_worker_thread():
    value = services()
    calls, thread_ids = [], []
    payload = {
        "nodes": [
            {"id": f"creative:{EID}", "label": "Creative", "name": EID, "props": {}}
        ],
        "edges": [],
        "missing": [],
    }
    app = create_app(lambda: value)
    with TestClient(app) as client:

        async def server_thread():
            return threading.get_ident()

        server_id = client.portal.call(server_thread)

        def fragment(ids):
            calls.append(ids)
            thread_ids.append(threading.get_ident())
            return payload

        app.state.assembly.graph_fragment = fragment
        response = client.get(
            "/graph/fragment", headers=HEADERS, params={"ids": EID + "," + EID}
        )
        assert response.status_code == 200 and response.json() == payload
        app.state.assembly = services()
        app.state.assembly.graph_fragment = lambda ids: {
            "nodes": [],
            "edges": [],
            "missing": ids,
        }
        assert client.get(
            "/graph/fragment", headers=HEADERS, params={"ids": EID}
        ).json() == {"nodes": [], "edges": [], "missing": [EID]}
    assert calls == [[EID]] and thread_ids[0] != server_id


def test_graph_query_error_hides_diagnostics(caplog, capsys):
    value = services()

    def fail(ids):
        raise RuntimeError("PRIVATE")

    value.graph_fragment = fail
    with TestClient(create_app(lambda: value)) as client:
        response = client.get("/graph/fragment", headers=HEADERS, params={"ids": EID})
    assert response.status_code == 500
    assert response.json() == {"detail": "GRAPH_QUERY_FAILED"}
    assert "PRIVATE" not in response.text + caplog.text + str(capsys.readouterr())


def test_graph_schema_closed_metadata():
    with TestClient(create_app(services)) as client:
        response = client.get("/graph/schema", headers=HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert data == {
        "labels": list(ONTOLOGY_LABELS),
        "relationships": list(ONTOLOGY_RELATIONSHIPS),
        "taxonomy": axis_glossary(),
        "claims": [
            {"value": claim.value, "name": CLAIM_DISPLAY_NAMES[claim]}
            for claim in Claim
            if claim != Claim.other
        ],
    }
    assert set(data["taxonomy"]) == {"hook_type", "angle", "format"}
    assert "other" not in {claim["value"] for claim in data["claims"]}


@pytest.mark.parametrize("image_enabled", [False, True])
def test_workspace_selection_is_header_free_allowlisted_and_sorted(image_enabled):
    value = services()
    value.image_enabled = image_enabled
    private_fields = ("own_product_url", "tone", "forbidden_terms", "price_band_pct")

    class Profile(dict):
        def get(self, key, default=None):
            assert key not in private_fields
            return super().get(key, default)

    value.workspaces = {
        tenant: Profile(
            tenant_id=tenant,
            display_name=f"name-{tenant}",
            brand="synthetic",
            **dict.fromkeys(private_fields, "PRIVATE"),
        )
        for tenant in ["demo-b", "outside", "demo-a"]
    }
    value.product_names = {"demo-a": "synthetic official name"}
    with TestClient(create_app(lambda: value)) as client:
        response = client.get("/workspaces")
    assert response.status_code == 200
    assert response.json() == {
        "workspaces": [
            {
                "tenant_id": tenant,
                "display_name": f"name-{tenant}",
                "brand": "synthetic",
                "product_name": value.product_names.get(tenant),
            }
            for tenant in ["demo-a", "demo-b"]
        ],
        "image_enabled": image_enabled,
    }
    assert all(
        set(item) == {"tenant_id", "display_name", "brand", "product_name"}
        for item in response.json()["workspaces"]
    )
    assert all(field not in response.text for field in (*private_fields, "PRIVATE"))
