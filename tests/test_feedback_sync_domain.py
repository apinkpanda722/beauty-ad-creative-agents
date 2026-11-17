from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime

import pytest

from beautyads.domain.feedback_sync import (
    TENANT_PATTERN,
    FeedbackSyncSource,
    SyncFeedback,
)
from beautyads.domain.tenant import _TENANT_PATTERN

NOW = datetime(2026, 11, 17, tzinfo=UTC)


def feedback(**changes):
    values = {
        "tenant_id": "brand_a",
        "feedback_id": "1",
        "plan_id": "plan-1",
        "decision": "rejected",
        "hook_type": "question",
        "claims": ("hydration",),
        "created_at": NOW,
        "updated_at": NOW,
    }
    return SyncFeedback(**(values | changes))


def test_sync_feedback_is_frozen_text_free_contract():
    item = feedback()
    assert item.feedback_id == "1" and isinstance(item.claims, tuple)
    assert {f.name for f in fields(item)} == {
        "tenant_id",
        "feedback_id",
        "plan_id",
        "decision",
        "hook_type",
        "claims",
        "created_at",
        "updated_at",
    }
    with pytest.raises(FrozenInstanceError):
        item.plan_id = "changed"
    assert {"read_changed", "get_watermark", "set_watermark"} <= set(
        vars(FeedbackSyncSource)
    )


def test_tenant_patterns_are_identical():
    assert TENANT_PATTERN.pattern == _TENANT_PATTERN.pattern
    assert TENANT_PATTERN.flags == _TENANT_PATTERN.flags
