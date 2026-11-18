"""Session tenant boundaries, workspace records, and lossless feedback memory."""

import math
import re
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Annotated, Protocol, runtime_checkable
from uuid import uuid4

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from beautyads.domain.labels import Claim, HookType
from beautyads.domain.tools import PriceBand

_TENANT_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]{1,31}")


class TenantContextMissing(Exception):
    code = "TENANT_CONTEXT_MISSING"

    def __init__(self):
        super().__init__(self.code)


class TenantMismatch(Exception):
    code = "TENANT_MISMATCH"

    def __init__(self):
        super().__init__(self.code)


def validate_tenant_id(value: object) -> str:
    if not isinstance(value, str) or _TENANT_PATTERN.fullmatch(value) is None:
        raise TenantContextMissing()
    return value


def make_thread_id(tenant_id: str) -> str:
    return f"{validate_tenant_id(tenant_id)}:{uuid4().hex}"


def thread_tenant(thread_id: str) -> str | None:
    if not isinstance(thread_id, str) or ":" not in thread_id:
        return None
    prefix = thread_id.split(":", 1)[0]
    try:
        return validate_tenant_id(prefix)
    except TenantContextMissing:
        return None


_TenantId = Annotated[str, BeforeValidator(validate_tenant_id)]


class WorkspaceProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: _TenantId
    display_name: str
    brand: str
    own_product_url: str
    tone: str
    forbidden_terms: list[str]
    price_band_pct: float = Field(default=30.0, gt=0, le=100, allow_inf_nan=False)


def price_band(unit_list_price: float, pct: float) -> PriceBand:
    if not math.isfinite(unit_list_price) or unit_list_price <= 0:
        raise ValueError("unit_list_price must be finite and positive")
    if not math.isfinite(pct) or not 0 < pct <= 100:
        raise ValueError("pct must be in (0, 100]")
    return PriceBand(
        price_min=unit_list_price * (1 - pct / 100),
        price_max=unit_list_price * (1 + pct / 100),
    )


class FeedbackDecision(StrEnum):
    approved = "approved"
    rejected = "rejected"


class Feedback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: _TenantId
    plan_id: str
    decision: FeedbackDecision
    reason: str
    hook_type: HookType | None
    claims: list[Claim]
    created_at: datetime


class PlanRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: _TenantId
    plan_id: str
    thread_id: str
    payload: dict
    created_at: datetime


class FeedbackCounts(BaseModel):
    count: int = 0
    hook_counts: dict[HookType, int] = Field(default_factory=dict)
    claim_counts: dict[Claim, int] = Field(default_factory=dict)


class FeedbackSummary(BaseModel):
    approved: FeedbackCounts = Field(default_factory=FeedbackCounts)
    rejected: FeedbackCounts = Field(default_factory=FeedbackCounts)
    rejected_reasons: list[str] = Field(default_factory=list)


def summarize_feedback(
    feedbacks: Sequence[Feedback],
    *,
    as_of: date,
    window_days: int = 90,
    max_reasons: int = 10,
) -> FeedbackSummary:
    """Count feedback in [as_of - window_days, as_of], preserving raw reasons.

    Dates and ordering use UTC (naive timestamps are treated as UTC). Each
    efficacy is counted once per feedback. Reason limits never affect counts.
    """
    if window_days <= 0 or max_reasons < 0:
        raise ValueError("window_days must be positive and max_reasons nonnegative")
    start = as_of - timedelta(days=window_days)
    summary = FeedbackSummary()
    dated = [
        (
            item,
            item.created_at.replace(tzinfo=UTC)
            if item.created_at.tzinfo is None
            else item.created_at.astimezone(UTC),
        )
        for item in feedbacks
    ]
    for item, timestamp in sorted(dated, key=lambda pair: pair[1], reverse=True):
        if not start <= timestamp.date() <= as_of:
            continue
        counts = (
            summary.approved
            if item.decision == FeedbackDecision.approved
            else summary.rejected
        )
        counts.count += 1
        if item.hook_type is not None:
            counts.hook_counts[item.hook_type] = (
                counts.hook_counts.get(item.hook_type, 0) + 1
            )
        for claim in set(item.claims):
            counts.claim_counts[claim] = counts.claim_counts.get(claim, 0) + 1
        if (
            item.decision == FeedbackDecision.rejected
            and len(summary.rejected_reasons) < max_reasons
        ):
            summary.rejected_reasons.append(item.reason)
    return summary


@runtime_checkable
class TenantRepository(Protocol):
    """The first argument comes from the server session, never a model tool."""

    def save_profile(self, tenant_id: str, profile: WorkspaceProfile) -> None: ...

    def get_profile(self, tenant_id: str) -> WorkspaceProfile | None: ...

    def save_plan(self, tenant_id: str, plan: PlanRecord) -> None: ...

    def get_plan(self, tenant_id: str, plan_id: str) -> PlanRecord | None: ...

    def add_feedback(self, tenant_id: str, feedback: Feedback) -> None: ...

    def list_feedback(
        self,
        tenant_id: str,
        *,
        decision: FeedbackDecision | None = None,
        since: datetime | None = None,
        limit: int,
    ) -> list[Feedback]: ...

    def register_thread(self, tenant_id: str, thread_id: str) -> None: ...

    def assert_thread_access(self, tenant_id: str, thread_id: str) -> None: ...
