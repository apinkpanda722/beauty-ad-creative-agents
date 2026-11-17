"""Tenant contracts and feedback memory use synthetic, service-free inputs."""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from beautyads.domain.labels import Claim, HookType
from beautyads.domain.tenant import (
    Feedback,
    FeedbackDecision,
    FeedbackSummary,
    PlanRecord,
    TenantContextMissing,
    TenantMismatch,
    WorkspaceProfile,
    make_thread_id,
    price_band,
    summarize_feedback,
    thread_tenant,
    validate_tenant_id,
)
from beautyads.domain.tools import PriceBand

NOW = datetime(2026, 11, 17, 12, tzinfo=UTC)


def profile(tenant_id="brand-a", **changes):
    return WorkspaceProfile(
        tenant_id=tenant_id,
        display_name="합성 작업 공간",
        brand="합성 브랜드",
        own_product_url="https://example.com/product",
        tone="간결하게",
        forbidden_terms=["합성 금지어"],
        **changes,
    )


def feedback(tenant_id="brand-a", **changes):
    return Feedback.model_validate(
        {
            "tenant_id": tenant_id,
            "plan_id": "plan-1",
            "decision": "rejected",
            "reason": "  원문 사유\n줄바꿈·기호!  ",
            "hook_type": "question",
            "claims": ["hydration"],
            "created_at": NOW,
            **changes,
        }
    )


def plan(tenant_id="brand-a", **changes):
    return PlanRecord.model_validate(
        {
            "tenant_id": tenant_id,
            "plan_id": "plan-1",
            "thread_id": f"{tenant_id}:synthetic",
            "payload": {"evidence_ids": ["youtube:synthetic"], "nested": [None, 1]},
            "created_at": NOW,
            **changes,
        }
    )


@pytest.mark.parametrize("value", ["ab", "0a", "brand-a_1", "a" * 32])
def test_valid_tenant_and_thread_roundtrip(value):
    assert validate_tenant_id(value) == value
    thread_id = make_thread_id(value)
    assert thread_tenant(thread_id) == value
    prefix, suffix = thread_id.split(":")
    assert prefix == value and UUID(hex=suffix).version == 4
    assert len(suffix) == 32 and "-" not in suffix
    assert thread_id != make_thread_id(value)


@pytest.mark.parametrize(
    "value",
    [None, 42, "", " ", "\t", "a", "Ab", "a" * 33, "a.b", "a:b", "-ab", "한글", "ab\n"],
)
def test_invalid_tenant_fails_closed(value):
    for operation in (validate_tenant_id, make_thread_id):
        with pytest.raises(TenantContextMissing) as caught:
            operation(value)
        assert caught.value.code == "TENANT_CONTEXT_MISSING"
    assert thread_tenant(value) is None


@pytest.mark.parametrize("value", ["ab", "plain-id", ":id", "Ab:id", "a:id"])
def test_thread_without_valid_prefix_returns_none(value):
    assert thread_tenant(value) is None


def test_mismatch_has_stable_code():
    assert TenantMismatch().code == "TENANT_MISMATCH"


@pytest.mark.parametrize("pct", [0.01, 30, 100])
def test_price_band_includes_computed_boundaries(pct):
    result = price_band(1234.5, pct)
    assert isinstance(result, PriceBand)
    assert result.price_min == 1234.5 * (1 - pct / 100)
    assert result.price_max == 1234.5 * (1 + pct / 100)
    assert profile().price_band_pct == 30.0
    assert profile(price_band_pct=pct).price_band_pct == pct


@pytest.mark.parametrize("price", [0, -1, float("nan"), float("inf")])
def test_price_band_rejects_nonpositive_or_nonfinite_price(price):
    with pytest.raises(ValueError):
        price_band(price, 30)


@pytest.mark.parametrize("pct", [0, -1, 100.01, float("nan"), float("inf")])
def test_price_band_and_profile_reject_invalid_percentage(pct):
    with pytest.raises(ValueError):
        price_band(100, pct)
    with pytest.raises(ValidationError):
        profile(price_band_pct=pct)


@pytest.mark.parametrize("factory", [profile, feedback, plan])
def test_tenant_models_reject_invalid_tenant(factory):
    with pytest.raises(TenantContextMissing):
        factory(tenant_id="INVALID")


def test_feedback_closed_values():
    assert set(FeedbackDecision) == {"approved", "rejected"}
    with pytest.raises(ValidationError):
        feedback(decision="other")
    with pytest.raises(ValidationError):
        feedback(hook_type="invalid")
    with pytest.raises(ValidationError):
        feedback(claims=["invalid"])


def test_feedback_summary_window_order_and_unmodified_reasons():
    oldest = feedback(created_at=NOW - timedelta(days=91), reason="윈도 밖")
    boundary = feedback(created_at=NOW - timedelta(days=90), reason="경계 원문")
    newer = feedback(created_at=NOW - timedelta(days=1), reason="  두 번째\n원문  ")
    latest = feedback(
        reason="  최신\n원문!  ", claims=["hydration", "soothing", "soothing"]
    )
    approved = feedback(decision="approved", hook_type="problem", claims=["barrier"])
    unclassified = feedback(hook_type=None, claims=[], reason="분류 없음")
    future = feedback(created_at=NOW + timedelta(days=1), reason="미래")
    items = [oldest, newer, boundary, latest, approved, unclassified, future]
    before = [item.model_dump() for item in items]
    result = summarize_feedback(items, as_of=NOW.date(), max_reasons=2)
    assert isinstance(result, FeedbackSummary)
    assert result.rejected.hook_counts == {HookType.question: 3}
    assert result.rejected.claim_counts == {Claim.hydration: 3, Claim.soothing: 1}
    assert result.rejected.count == 4  # Includes omitted and unclassified reasons.
    assert result.approved.hook_counts == {HookType.problem: 1}
    assert result.approved.claim_counts == {Claim.barrier: 1}
    assert result.approved.count == 1
    assert result.rejected_reasons == [latest.reason, unclassified.reason]
    all_reasons = summarize_feedback(items, as_of=NOW.date()).rejected_reasons
    assert all_reasons == [
        latest.reason,
        unclassified.reason,
        newer.reason,
        boundary.reason,
    ]
    assert [item.model_dump() for item in items] == before


def test_empty_summary_and_zero_reason_budget():
    result = summarize_feedback([], as_of=date(2026, 11, 17))
    assert result.rejected.count == result.approved.count == 0
    assert result.rejected.hook_counts == result.approved.hook_counts == {}
    assert result.rejected.claim_counts == result.approved.claim_counts == {}
    assert result.rejected_reasons == []
    result = summarize_feedback([feedback()], as_of=NOW.date(), max_reasons=0)
    assert result.rejected_reasons == [] and result.rejected.count == 1


@pytest.mark.parametrize(
    "kwargs", [{"window_days": 0}, {"window_days": -1}, {"max_reasons": -1}]
)
def test_summary_rejects_invalid_budgets(kwargs):
    with pytest.raises(ValueError):
        summarize_feedback([], as_of=NOW.date(), **kwargs)
