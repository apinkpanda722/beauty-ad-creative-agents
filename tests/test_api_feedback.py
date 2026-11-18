"""Feedback uses only session scope and stored plan labels, with fake memory."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from test_api_chat import Tenants, assembly

from beautyads.api.app import create_app
from beautyads.api.feedback import feedback_for_prompt
from beautyads.domain.tenant import Feedback, FeedbackSummary, PlanRecord

NOW = datetime(2026, 11, 18, 12, tzinfo=UTC)
REASON = "  합성 비공개 사유\n원문·기호!  "


class FeedbackTenants(Tenants):
    def __init__(self, *, payload=None):
        super().__init__()
        self.plans = {
            ("demo-a", "plan-a"): PlanRecord(
                tenant_id="demo-a",
                plan_id="plan-a",
                thread_id="demo-a:synthetic",
                payload=payload
                if payload is not None
                else {
                    "plan": {
                        "hook_type": "question",
                        "claimed_efficacy": ["hydration"],
                    },
                    "hook_type": "problem",
                    "claims": ["barrier"],
                },
                created_at=NOW - timedelta(days=1),
            )
        }
        self.reads, self.writes, self.list_calls = [], [], []
        self.feedbacks = []

    def get_plan(self, tenant_id, plan_id):
        self.reads.append((tenant_id, plan_id))
        return self.plans.get((tenant_id, plan_id))

    def add_feedback(self, tenant_id, feedback):
        self.writes.append((tenant_id, feedback))

    def list_feedback(self, tenant_id, *, limit):
        self.list_calls.append((tenant_id, limit))
        return self.feedbacks[:limit]


def services(tenants):
    result = assembly()
    result.tenants = tenants
    return result


def body(**changes):
    return {"plan_id": "plan-a", "decision": "rejected", "reason": REASON, **changes}


@pytest.mark.parametrize("decision", ["approved", "rejected"])
def test_success_uses_stored_labels_and_server_time(decision, caplog):
    tenants = FeedbackTenants()
    before = datetime.now(UTC)
    with TestClient(create_app(lambda: services(tenants))) as client:
        response = client.post(
            "/feedback", headers={"X-Tenant-Id": "demo-a"}, json=body(decision=decision)
        )
    after = datetime.now(UTC)
    assert response.status_code == 200 and response.json() == {"status": "ok"}
    assert tenants.reads == [("demo-a", "plan-a")]
    assert len(tenants.writes) == 1
    tenant_id, item = tenants.writes[0]
    assert isinstance(item, Feedback)
    assert tenant_id == item.tenant_id == "demo-a"
    assert item.plan_id == "plan-a" and item.decision == decision
    assert item.hook_type == "question" and item.claims == ["hydration"]
    assert item.reason == REASON
    assert before <= item.created_at <= after
    assert tenants.threads == {}
    assert REASON not in response.text and REASON not in caplog.text


@pytest.mark.parametrize("payload", [{}, {"plan": {}}, {"plan": None}])
def test_missing_stored_labels_default_to_unclassified(payload):
    tenants = FeedbackTenants(payload=payload)
    with TestClient(create_app(lambda: services(tenants))) as client:
        response = client.post(
            "/feedback", headers={"X-Tenant-Id": "demo-a"}, json=body()
        )
    assert response.status_code == 200
    assert tenants.writes[0][1].hook_type is None
    assert tenants.writes[0][1].claims == []


@pytest.mark.parametrize(
    "header,changes,status,code",
    [
        ("demo-b", {}, 404, "PLAN_NOT_FOUND"),
        ("demo-a", {"plan_id": "missing"}, 404, "PLAN_NOT_FOUND"),
        (None, {}, 400, "TENANT_CONTEXT_MISSING"),
        ("INVALID SPACE", {}, 400, "TENANT_CONTEXT_MISSING"),
        ("outside", {}, 403, "TENANT_NOT_ALLOWED"),
        ("demo-a", {"tenant_id": "demo-b"}, 422, None),
        ("demo-a", {"hook_type": "problem"}, 422, None),
        ("demo-a", {"claims": ["barrier"]}, 422, None),
        ("demo-a", {"decision": "unknown"}, 422, None),
        ("demo-a", {"decision": REASON}, 422, None),
        ("demo-a", {"reason": {"private": REASON}}, 422, None),
        ("demo-a", {REASON: REASON}, 422, None),
        ("demo-a", {"plan_id": None}, 422, None),
    ],
)
def test_refusal_has_no_write_and_no_reason(header, changes, status, code, caplog):
    tenants = FeedbackTenants()
    headers = {"X-Tenant-Id": header} if header is not None else {}
    with TestClient(create_app(lambda: services(tenants))) as client:
        response = client.post("/feedback", headers=headers, json=body(**changes))
    assert response.status_code == status
    if code:
        assert response.json() == {"detail": code}
    assert tenants.writes == [] and tenants.threads == {}
    if status in {400, 403, 422}:
        assert tenants.reads == []
    assert REASON not in response.text and REASON not in caplog.text
    assert "합성 비공개" not in response.text


def test_invalid_json_does_not_echo_input(caplog):
    tenants = FeedbackTenants()
    with TestClient(create_app(lambda: services(tenants))) as client:
        response = client.post(
            "/feedback",
            headers={"X-Tenant-Id": "demo-a", "Content-Type": "application/json"},
            content='{"reason": "synthetic-private-reason",',
        )
    assert response.status_code == 422
    assert tenants.writes == [] and tenants.reads == []
    assert "synthetic-private-reason" not in response.text + caplog.text


def test_storage_failure_does_not_expose_reason(caplog):
    class FailingTenants(FeedbackTenants):
        def add_feedback(self, tenant_id, feedback):
            raise RuntimeError(feedback.reason)

    tenants = FailingTenants()
    with TestClient(create_app(lambda: services(tenants))) as client:
        response = client.post(
            "/feedback", headers={"X-Tenant-Id": "demo-a"}, json=body()
        )
    assert response.status_code == 500
    assert REASON not in response.text + caplog.text
    assert "합성 비공개" not in response.text


def test_lifespan_registers_route_and_looks_up_current_repository():
    first, second = FeedbackTenants(), FeedbackTenants()
    initial = services(first)
    built, closed = [], []
    initial.close = lambda: closed.append(True)

    def assemble():
        built.append(True)
        return initial

    app = create_app(assemble=assemble)
    assert built == []
    assert initial.workspaces == {} and initial.price_bands == {}
    assert initial.workspaces is not assembly().workspaces
    assert initial.price_bands is not assembly().price_bands
    with TestClient(app) as client:
        assert built == [True]
        assert client.post(
            "/feedback", headers={"X-Tenant-Id": "demo-a"}, json=body()
        ).json() == {"status": "ok"}
        app.state.assembly.tenants = second
        assert client.post(
            "/feedback", headers={"X-Tenant-Id": "demo-a"}, json=body()
        ).json() == {"status": "ok"}
    assert len(first.writes) == len(second.writes) == 1
    assert closed == [True]


def test_prompt_summary_is_lossless_newest_first_and_passes_limit():
    tenants = FeedbackTenants()
    older = Feedback(
        tenant_id="demo-a",
        plan_id="plan-a",
        decision="rejected",
        reason="  오래된\n원문  ",
        hook_type="question",
        claims=["hydration"],
        created_at=NOW - timedelta(days=1),
    )
    newer = older.model_copy(update={"reason": REASON, "created_at": NOW})
    tenants.feedbacks = [older, newer]
    result = feedback_for_prompt(tenants, "demo-a", NOW.date(), limit=17)
    assert tenants.list_calls == [("demo-a", 17)]
    assert result["rejected_reasons"] == [REASON, older.reason]
    assert result["rejected"]["count"] == 2
    assert result["rejected"]["hook_counts"] == {"question": 2}
    assert result["rejected"]["claim_counts"] == {"hydration": 2}
    assert FeedbackSummary.model_validate(result)


def test_prompt_summary_empty_and_default_limit():
    tenants = FeedbackTenants()
    result = feedback_for_prompt(tenants, "demo-b", NOW.date())
    assert tenants.list_calls == [("demo-b", 50)]
    assert result == FeedbackSummary().model_dump(mode="json")
