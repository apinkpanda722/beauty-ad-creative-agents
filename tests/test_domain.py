from datetime import UTC, datetime

import pytest
from beautyads.domain import (
    Creative,
    CreativeKey,
    HookResult,
    HookType,
    JobStatus,
    Metrics,
    Source,
    is_analyzable,
)
from pydantic import ValidationError


@pytest.fixture
def creative_data():
    return {
        "source": Source.youtube,
        "source_id": "video-1",
        "collected_at": datetime(2026, 11, 12, tzinfo=UTC),
    }


def test_missing_metrics_remain_none(creative_data):
    creative = Creative(**creative_data)
    assert creative.metrics.view_count is None
    assert creative.metrics.like_count is None
    assert creative.metrics.comment_count is None
    assert Metrics(view_count=0).view_count == 0
    assert Metrics(like_count=0).like_count == 0
    assert Metrics(comment_count=0).comment_count == 0


def test_partial_metrics_keep_missing_values(creative_data):
    creative = Creative(**creative_data, metrics={"view_count": 12})
    assert creative.metrics.view_count == 12
    assert creative.metrics.like_count is None
    assert creative.metrics.comment_count is None


def test_metrics_defaults_are_independent(creative_data):
    first = Creative(**creative_data)
    second = Creative(**creative_data)
    first.metrics.view_count = 12
    assert second.metrics.view_count is None


def test_missing_analyzable_is_not_eligible(creative_data):
    assert "analyzable" not in creative_data
    creative = Creative.model_validate(creative_data)
    assert creative.analyzable is None
    assert is_analyzable(creative) is False


@pytest.mark.parametrize("value", [None, False, True])
def test_only_explicit_true_is_analyzable(creative_data, value):
    creative = Creative(**creative_data, analyzable=value)
    assert is_analyzable(creative) is (value is True)


@pytest.mark.parametrize("hook_type", list(HookType))
def test_hook_result_accepts_every_member(hook_type):
    assert HookResult(hook_type=hook_type.value).hook_type is hook_type


def test_hook_result_rejects_values_outside_taxonomy():
    with pytest.raises(ValidationError):
        HookResult(hook_type="unknown-hook")


@pytest.mark.parametrize("model", [Creative, CreativeKey, Metrics, HookResult])
def test_unknown_fields_are_rejected(model, creative_data):
    data = {}
    if model is Creative:
        data = creative_data
    elif model is CreativeKey:
        data = {"source": Source.youtube, "source_id": "video-1"}
    elif model is HookResult:
        data = {"hook_type": next(iter(HookType))}
    with pytest.raises(ValidationError) as caught:
        model.model_validate({**data, "unknown": True})
    assert any(error["type"] == "extra_forbidden" for error in caught.value.errors())


def test_creative_key_is_hashable_equal_and_immutable(creative_data):
    creative = Creative(**creative_data)
    key = CreativeKey(source="youtube", source_id="video-1")
    assert creative.key == key
    assert hash(creative.key) == hash(key)
    assert {creative.key: creative}[key] is creative
    assert CreativeKey(source=Source.instagram, source_id="video-1") != key
    assert CreativeKey(source=Source.youtube, source_id="video-2") != key
    with pytest.raises(ValidationError):
        key.source_id = "changed"


@pytest.mark.parametrize("model", [CreativeKey, Creative])
def test_empty_source_id_is_rejected(model, creative_data):
    data = {"source": Source.youtube, "source_id": ""}
    if model is Creative:
        data["collected_at"] = creative_data["collected_at"]
    with pytest.raises(ValidationError):
        model.model_validate(data)


@pytest.mark.parametrize(
    "collected_at", [datetime(2026, 11, 12), "2026-11-12T00:00:00"]
)
def test_naive_collection_timestamp_is_rejected(creative_data, collected_at):
    with pytest.raises(ValidationError):
        Creative.model_validate({**creative_data, "collected_at": collected_at})


def test_optional_metadata_and_timezone_serialization(creative_data):
    creative = Creative(**creative_data)
    for name in (
        "url",
        "title",
        "caption",
        "published_at",
        "duration_s",
        "language",
    ):
        assert getattr(creative, name) is None
    assert Creative.model_validate_json(creative.model_dump_json()) == creative
    assert creative.collected_at.utcoffset() is not None


def test_job_status_uses_held_for_deferred_work():
    assert JobStatus.held.value == "held"
    with pytest.raises(ValueError):
        JobStatus("deferred")
