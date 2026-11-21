"""Saved plans use fake tenant memory and temporary, synthetic image files only."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from test_api_chat import assembly

from beautyads.api.app import create_app
from beautyads.domain.tenant import Feedback, PlanRecord

NOW = datetime(2026, 11, 21, 12, tzinfo=UTC)
PLAN_A = "a" * 32
PLAN_B = "b" * 32
PLAN_C = "c" * 32
PLAN_D = "d" * 32
PLAN_E = "e" * 32
PNG = b"\x89PNG\r\n\x1a\nsynthetic-image"
HEADERS = {"X-Tenant-Id": "demo-a"}
PLAN_FIELDS = [
    "title",
    "hook_text",
    "hook_type",
    "angle",
    "format",
    "claimed_efficacy",
    "scenes",
    "copy_lines",
    "evidence_ids",
]


def image(**changes):
    return {
        "request_key": "synthetic-request",
        "index": 0,
        "mime": "image/png",
        "size": len(PNG),
        "sha256": "1" * 64,
        **changes,
    }


def plan(plan_id=PLAN_A, tenant="demo-a", **payload):
    return PlanRecord(
        tenant_id=tenant,
        plan_id=plan_id,
        thread_id=f"{tenant}:synthetic",
        created_at=NOW - timedelta(days=1),
        payload={
            "plan": {
                "title": "합성 제목",
                "hook_text": "합성 훅",
                "hook_type": "question",
                "angle": "how_to",
                "format": "demo",
                "claimed_efficacy": ["hydration"],
                "scenes": ["합성 장면"],
                "copy_lines": ["합성 카피"],
                "evidence_ids": ["youtube:synthetic"],
                "image_prompt": "private-prompt",
                "report": {"private": True},
                "sha256": "private-hash",
                "path": "/synthetic/private-path",
            },
            "image": image(),
            "report": {"private": True},
            **payload,
        },
    )


def feedback(plan_id=PLAN_A, decision="approved", tenant="demo-a", minutes=0):
    return Feedback(
        tenant_id=tenant,
        plan_id=plan_id,
        decision=decision,
        reason=f"합성 사유 {minutes}",
        hook_type=None,
        claims=[],
        created_at=NOW - timedelta(minutes=minutes),
    )


class SavedTenants:
    def __init__(self, records=(), feedbacks=()):
        self.records = {
            (record.tenant_id, record.plan_id): record for record in records
        }
        self.feedbacks = list(feedbacks)
        self.reads = []
        self.list_calls = []

    def get_plan(self, tenant_id, plan_id):
        self.reads.append((tenant_id, plan_id))
        return self.records.get((tenant_id, plan_id))

    def list_feedback(self, tenant_id, *, limit):
        self.list_calls.append((tenant_id, limit))
        return [item for item in self.feedbacks if item.tenant_id == tenant_id][:limit]


def app_for(tmp_path, tenants):
    services = assembly()
    services.tenants = tenants
    services.design_dir = tmp_path / "design"
    return create_app(lambda: services)


def write_image(tmp_path, reference, *, composed=False, content=PNG):
    directory = (
        tmp_path / "design" / sha256(reference["request_key"].encode()).hexdigest()[:16]
    )
    directory.mkdir(parents=True, exist_ok=True)
    suffix = (
        "_composed.png"
        if composed
        else "."
        + {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}[
            reference["mime"]
        ]
    )
    path = directory / f"{reference['index']:02d}{suffix}"
    path.write_bytes(content)
    return path


def test_list_latest_decisions_only_in_latest_approval_order(tmp_path, caplog):
    records = [
        plan(),
        plan(PLAN_B),
        plan(PLAN_C, image=None),
        plan(PLAN_D),  # No feedback.
        plan(PLAN_E, "demo-b"),
    ]
    feedbacks = [
        feedback(PLAN_B, "rejected"),
        feedback(PLAN_C, minutes=1),
        feedback(PLAN_E, tenant="demo-b", minutes=2),
        feedback(PLAN_A, minutes=3),
        feedback("f" * 32, minutes=4),  # Missing record.
        feedback(PLAN_A, "rejected", minutes=5),
        feedback(PLAN_B, minutes=6),
        feedback(PLAN_C, minutes=7),
    ]
    tenants = SavedTenants(records, feedbacks)
    with TestClient(app_for(tmp_path, tenants)) as client:
        response = client.get("/plans", headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert list(body) == ["plans"]
    assert [item["plan_id"] for item in body["plans"]] == [PLAN_C, PLAN_A]
    for item, record, decision in zip(
        body["plans"],
        [records[2], records[0]],
        [feedbacks[1], feedbacks[3]],
        strict=True,
    ):
        assert sorted(item) == sorted(
            ["plan_id", *PLAN_FIELDS, "has_image", "decided_at", "reason"]
        )
        assert {key: item[key] for key in PLAN_FIELDS} == {
            key: record.payload["plan"][key] for key in PLAN_FIELDS
        }
        assert datetime.fromisoformat(item["decided_at"]) == decision.created_at
        assert item["reason"] == decision.reason
    assert [item["has_image"] for item in body["plans"]] == [False, True]
    assert tenants.list_calls == [("demo-a", 200)]
    assert tenants.reads == [
        ("demo-a", PLAN_C),
        ("demo-a", PLAN_A),
        ("demo-a", "f" * 32),
    ]
    for private in ["private", "sha256", str(tmp_path), "request_key", "report"]:
        assert private not in response.text + caplog.text


def test_list_empty_and_recent_feedback_limit(tmp_path):
    tenants = SavedTenants([plan()], [])
    with TestClient(app_for(tmp_path, tenants)) as client:
        assert client.get("/plans", headers=HEADERS).json() == {"plans": []}
        tenants.feedbacks = [
            feedback(PLAN_B, "rejected", minutes=n) for n in range(200)
        ]
        tenants.feedbacks.append(feedback(PLAN_A, minutes=200))
        assert client.get("/plans", headers=HEADERS).json() == {"plans": []}
    assert tenants.list_calls == [("demo-a", 200), ("demo-a", 200)]
    assert tenants.reads == []


@pytest.mark.parametrize(
    "reference", [None, {}, image(index=-1), image(mime="text/plain")]
)
def test_list_has_image_uses_reference_validity(tmp_path, reference):
    tenants = SavedTenants([plan(image=reference)], [feedback()])
    with TestClient(app_for(tmp_path, tenants)) as client:
        response = client.get("/plans", headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["plans"][0]["has_image"] is False


@pytest.mark.parametrize("route", ["/plans", f"/plans/{PLAN_A}/image"])
@pytest.mark.parametrize(
    "tenant,status,code",
    [
        (None, 400, "TENANT_CONTEXT_MISSING"),
        ("INVALID SPACE", 400, "TENANT_CONTEXT_MISSING"),
        ("outside", 403, "TENANT_NOT_ALLOWED"),
    ],
)
def test_session_refusal_precedes_storage(tmp_path, route, tenant, status, code):
    tenants = SavedTenants([plan()], [feedback()])
    with TestClient(app_for(tmp_path, tenants)) as client:
        response = client.get(route, headers={"X-Tenant-Id": tenant} if tenant else {})
    assert response.status_code == status
    assert response.json() == {"detail": code}
    assert tenants.reads == tenants.list_calls == []


@pytest.mark.parametrize("route", ["/plans", f"/plans/{PLAN_A}/image"])
def test_query_tenant_neither_supplies_nor_overrides_session(tmp_path, route):
    record = plan()
    write_image(tmp_path, record.payload["image"])
    tenants = SavedTenants([record], [feedback()])
    with TestClient(app_for(tmp_path, tenants)) as client:
        response = client.get(route, params={"tenant_id": "demo-a"})
        assert response.status_code == 400
        assert response.json() == {"detail": "TENANT_CONTEXT_MISSING"}
        assert tenants.reads == tenants.list_calls == []
        response = client.get(route, params={"tenant_id": "demo-b"}, headers=HEADERS)
    assert response.status_code == 200
    assert tenants.reads == [("demo-a", PLAN_A)]
    if route == "/plans":
        assert tenants.list_calls == [("demo-a", 200)]
        assert [item["plan_id"] for item in response.json()["plans"]] == [PLAN_A]
    else:
        assert response.content == PNG
        assert tenants.list_calls == []


@pytest.mark.parametrize("misbehaving_store", [False, True])
def test_other_workspace_image_is_indistinguishable_from_missing(
    tmp_path, misbehaving_store
):
    record = plan(tenant="demo-b")
    write_image(tmp_path, record.payload["image"])
    tenants = SavedTenants([record])
    if misbehaving_store:
        tenants.records["demo-a", PLAN_A] = record
    with TestClient(app_for(tmp_path, tenants)) as client:
        for plan_id in [PLAN_A, PLAN_B]:
            response = client.get(f"/plans/{plan_id}/image", headers=HEADERS)
            assert response.status_code == 404
            assert response.json() == {"detail": "PLAN_NOT_FOUND"}
    assert tenants.reads == [("demo-a", PLAN_A), ("demo-a", PLAN_B)]


def test_list_rejects_mismatched_record_and_feedback_tenants(tmp_path):
    tenants = SavedTenants([plan(tenant="demo-b")], [feedback()])
    tenants.records["demo-a", PLAN_A] = plan(tenant="demo-b")
    tenants.list_feedback = lambda tenant_id, limit: [
        feedback(PLAN_B, tenant="demo-b"),
        feedback(),
    ]
    with TestClient(app_for(tmp_path, tenants)) as client:
        response = client.get("/plans", headers=HEADERS)
    assert response.status_code == 200 and response.json() == {"plans": []}
    assert tenants.reads == [("demo-a", PLAN_A)]


@pytest.mark.parametrize(
    "plan_id",
    ["../", "..%2f", "/etc/passwd", "short", "a" * 31, "a" * 33, "A" * 32, "g" * 32],
)
def test_invalid_plan_id_never_accesses_storage_or_files(
    tmp_path, monkeypatch, plan_id
):
    from beautyads.api import plans

    def forbidden(*args, **kwargs):
        pytest.fail("Invalid plan_id reached the filesystem")

    monkeypatch.setattr(plans, "design_file", forbidden)
    tenants = SavedTenants([plan()])
    with TestClient(app_for(tmp_path, tenants)) as client:
        response = client.get(f"/plans/{plan_id}/image", headers=HEADERS)
    assert response.status_code == 404
    assert tenants.reads == []
    if "/" not in plan_id and "%" not in plan_id:
        assert response.json() == {"detail": "PLAN_NOT_FOUND"}


@pytest.mark.parametrize("request_key", ["synthetic-request", "../x", "/etc/passwd"])
@pytest.mark.parametrize("mime", ["image/png", "image/jpeg", "image/webp"])
def test_image_uses_stored_reference_without_in_memory_design_lookup(
    tmp_path, request_key, mime
):
    reference = image(request_key=request_key, index=12, mime=mime)
    path = write_image(tmp_path, reference)
    assert path.is_relative_to(tmp_path / "design")
    tenants = SavedTenants([plan(image=reference)])
    with TestClient(app_for(tmp_path, tenants)) as client:
        response = client.get(f"/plans/{PLAN_A}/image", headers=HEADERS)
    assert response.status_code == 200 and response.content == PNG
    assert response.headers["content-type"] == mime
    assert response.headers["cache-control"] == "no-store"
    assert tenants.reads == [("demo-a", PLAN_A)]


def test_image_prefers_composed_png(tmp_path):
    reference = image(
        mime="image/jpeg",
        composed={"mime": "image/png", "size": len(PNG), "sha256": "2" * 64},
    )
    write_image(tmp_path, reference, content=b"synthetic-original")
    write_image(tmp_path, reference, composed=True)
    tenants = SavedTenants([plan(image=reference)])
    with TestClient(app_for(tmp_path, tenants)) as client:
        response = client.get(f"/plans/{PLAN_A}/image", headers=HEADERS)
    assert response.status_code == 200 and response.content == PNG
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("reference", [None, {}, image(size=-1), image(index=True)])
def test_missing_or_invalid_image_is_design_not_found(tmp_path, reference):
    tenants = SavedTenants([plan(image=reference)])
    with TestClient(app_for(tmp_path, tenants)) as client:
        response = client.get(f"/plans/{PLAN_A}/image", headers=HEADERS)
    assert response.status_code == 404
    assert response.json() == {"detail": "DESIGN_NOT_FOUND"}


@pytest.mark.parametrize("failure", ["missing", "directory", "permission", "resolve"])
def test_unreadable_image_returns_safe_404(tmp_path, monkeypatch, failure, caplog):
    reference = image()
    path = write_image(tmp_path, reference)
    if failure == "missing":
        path.unlink()
    elif failure == "directory":
        path.unlink()
        path.mkdir()
    else:

        def fail(*args, **kwargs):
            raise OSError(f"private-error {tmp_path}")

        monkeypatch.setattr(
            Path, "read_bytes" if failure == "permission" else "resolve", fail
        )
    tenants = SavedTenants([plan(image=reference)])
    with TestClient(app_for(tmp_path, tenants)) as client:
        response = client.get(f"/plans/{PLAN_A}/image", headers=HEADERS)
    assert response.status_code == 404
    assert response.json() == {"detail": "DESIGN_NOT_FOUND"}
    assert str(tmp_path) not in response.text + caplog.text
    assert "private-error" not in response.text + caplog.text


@pytest.mark.parametrize(
    "kind",
    [
        "file-outside",
        "file-inside",
        "directory-outside",
        "directory-inside",
        "composed",
    ],
)
def test_image_rejects_symlink_files_and_directories(tmp_path, monkeypatch, kind):
    reference = image(request_key="../x")
    if kind == "composed":
        reference["composed"] = {
            "mime": "image/png",
            "size": len(PNG),
            "sha256": "2" * 64,
        }
    path = write_image(tmp_path, reference, composed=kind == "composed")
    inside = kind.endswith("inside")
    target_root = tmp_path / "design" / "target" if inside else tmp_path / "outside"
    target_root.mkdir()
    target = target_root / path.name
    target.write_bytes(b"private-target")
    directory_link = kind.startswith("directory")
    path.unlink()
    if directory_link:
        path.parent.rmdir()
    link = path.parent if directory_link else path
    try:
        link.symlink_to(
            target_root if directory_link else target,
            target_is_directory=directory_link,
        )
    except (OSError, NotImplementedError):
        # Platforms without symlink privileges still exercise the same helper guard.
        from beautyads.api.design_files import design_file

        monkeypatch.setattr(Path, "is_symlink", lambda self: self == link)
        with pytest.raises(HTTPException) as error:
            design_file(tmp_path / "design", reference, reject_symlinks=True)
        assert error.value.status_code == 404
        assert error.value.detail == "DESIGN_NOT_FOUND"
        return
    tenants = SavedTenants([plan(image=reference)])
    with TestClient(app_for(tmp_path, tenants)) as client:
        response = client.get(f"/plans/{PLAN_A}/image", headers=HEADERS)
    assert response.status_code == 404
    assert response.json() == {"detail": "DESIGN_NOT_FOUND"}
    assert b"private-target" not in response.content


def test_path_containment_is_checked_even_after_resolution(tmp_path, monkeypatch):
    reference = image(request_key="../x")
    path = write_image(tmp_path, reference)
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"private-outside")
    original = Path.resolve

    def resolve(self, *args, **kwargs):
        return outside if self == path else original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    tenants = SavedTenants([plan(image=reference)])
    with TestClient(app_for(tmp_path, tenants)) as client:
        response = client.get(f"/plans/{PLAN_A}/image", headers=HEADERS)
    assert response.status_code == 404
    assert response.json() == {"detail": "DESIGN_NOT_FOUND"}
    assert b"private-outside" not in response.content
