from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from beautyads.domain import (
    Angle,
    Category,
    Claim,
    CollectionStat,
    ContentType,
    ContentTypeResult,
    Creative,
    CreativeKey,
    CreativeRepository,
    CtaType,
    Format,
    FullResult,
    HookResult,
    HookType,
    JobStatus,
    Metrics,
    PlatformFitFlags,
    Source,
    StructureFlags,
    Talent,
    is_analyzable,
)

FULL_ENUM_FIELDS = {
    "angle": Angle,
    "format": Format,
    "talent": Talent,
    "cta_type": CtaType,
    "claims": Claim,
}
CONTENT_ENUM_FIELDS = {"content_type": ContentType, "category": Category}


def axis_data(model):
    if model in (StructureFlags, PlatformFitFlags):
        return {name: False for name in model.model_fields}
    enums = CONTENT_ENUM_FIELDS if model is ContentTypeResult else FULL_ENUM_FIELDS
    data = {name: next(iter(enum)).value for name, enum in enums.items()}
    if model is FullResult:
        data.update(
            claims=[data["claims"]],
            ingredients=["  시카 ", "nIaCiNaMiDe", " 병풀\t추출물\n", "Unknown Mix"],
            structure=axis_data(StructureFlags),
            platform_fit=axis_data(PlatformFitFlags),
        )
    return data


@pytest.mark.parametrize(
    "model,enums",
    [(ContentTypeResult, CONTENT_ENUM_FIELDS), (FullResult, FULL_ENUM_FIELDS)],
)
def test_new_label_models_accept_all_enum_members_and_reject_outside_values(
    model, enums
):
    for name, enum in enums.items():
        for member in enum:
            data = axis_data(model)
            data[name] = [member.value] if name == "claims" else member.value
            if name == "cta_type":
                data["structure"]["has_cta"] = member is not CtaType.none
            assert model.model_validate(data).model_dump(mode="json") == data
        data = axis_data(model)
        data[name] = ["outside-taxonomy"] if name == "claims" else "outside-taxonomy"
        with pytest.raises(ValidationError):
            model.model_validate(data)


@pytest.mark.parametrize(
    "model", [ContentTypeResult, FullResult, StructureFlags, PlatformFitFlags]
)
def test_new_models_forbid_unknown_fields_and_require_every_field(model):
    data = axis_data(model)
    with pytest.raises(ValidationError) as caught:
        model.model_validate({**data, "unknown": True})
    assert any(error["type"] == "extra_forbidden" for error in caught.value.errors())
    for name in model.model_fields:
        with pytest.raises(ValidationError) as caught:
            model.model_validate(
                {key: value for key, value in data.items() if key != name}
            )
        assert any(error["type"] == "missing" for error in caught.value.errors())


@pytest.mark.parametrize("model", [StructureFlags, PlatformFitFlags])
@pytest.mark.parametrize("value", [False, True])
def test_structure_and_platform_flags_are_booleans(model, value):
    data = {name: value for name in model.model_fields}
    assert model.model_validate(data).model_dump(mode="json") == data
    for name in model.model_fields:
        with pytest.raises(ValidationError):
            model.model_validate({**data, name: "not-a-boolean"})


def test_full_result_preserves_ingredients_verbatim_and_accepts_empty_lists():
    data = axis_data(FullResult)
    result = FullResult.model_validate(data)
    assert result.ingredients == data["ingredients"]
    assert (
        FullResult.model_validate_json(result.model_dump_json()).ingredients
        == data["ingredients"]
    )
    data.update(ingredients=[], claims=[])
    assert FullResult.model_validate(data).model_dump(mode="json") == data


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


def test_creative_attributes_default_to_empty_dict(creative_data):
    assert Creative(**creative_data).attributes == {}


def test_creative_attributes_preserve_nested_json_values(creative_data):
    attributes = {
        "reach": "600K-700K",
        "advertiser": {"business_id": 42, "business_name": "합성 광고주"},
        "observations": ["synthetic", 1.5, {"enabled": True, "missing": None}],
    }
    item = Creative(**creative_data, attributes=attributes)
    assert item.attributes == attributes
    assert Creative.model_validate_json(item.model_dump_json()) == item


def test_creative_attributes_defaults_are_independent(creative_data):
    first = Creative(**creative_data)
    second = Creative(**creative_data)
    assert first.attributes is not second.attributes
    first.attributes["reach"] = "600K-700K"
    assert second.attributes == {}


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


def test_creative_brand_and_account_default_to_none(creative_data):
    item = Creative(**creative_data)
    assert item.brand is None
    assert item.account is None


@pytest.mark.parametrize("brand, account", [(None, None), ("브랜드", "@brand_handle")])
def test_creative_preserves_brand_and_account(creative_data, brand, account):
    item = Creative(**creative_data, brand=brand, account=account)
    assert item.brand == brand
    assert item.account == account
    assert Creative.model_validate_json(item.model_dump_json()) == item
    with pytest.raises(ValidationError) as caught:
        Creative(**creative_data, brand=brand, account=account, unknown=True)
    assert any(error["type"] == "extra_forbidden" for error in caught.value.errors())


@pytest.mark.parametrize(
    "brand, account, last_collected_at",
    [
        (None, None, None),
        ("브랜드", "@brand_handle", datetime(2026, 11, 12, tzinfo=UTC)),
    ],
)
def test_collection_stat_fields(brand, account, last_collected_at):
    stat = CollectionStat(
        source="youtube",
        brand=brand,
        account=account,
        total=6,
        analyzable_true=1,
        analyzable_false=2,
        analyzable_null=3,
        last_collected_at=last_collected_at,
    )
    assert stat.source is Source.youtube
    assert stat.brand == brand
    assert stat.account == account
    assert stat.total == 6
    assert stat.analyzable_true == 1
    assert stat.analyzable_false == 2
    assert stat.analyzable_null == 3
    assert stat.last_collected_at == last_collected_at


def test_creative_repository_declares_collection_stats():
    from typing import get_type_hints

    assert get_type_hints(CreativeRepository.collection_stats) == {
        "return": list[CollectionStat]
    }


@pytest.mark.parametrize("status", list(JobStatus))
@pytest.mark.parametrize("nullable", [False, True])
def test_job_result_fields_and_nested_labels(creative_data, status, nullable):
    from beautyads.domain import JobResult

    data = {
        "key": Creative(**creative_data).key,
        "kind": "hook@minimal",
        "status": status,
        "labels": {"items": ["synthetic", {"enabled": True}], "flag": False},
        "error_code": "SYNTHETIC_ERROR",
        "model": "synthetic-model",
        "thinking_level": "minimal",
        "prompt_version": "test-v1",
        "raw_output": "unparsed output",
        "attempts": 2,
        "updated_at": creative_data["collected_at"],
    }
    if nullable:
        for name in (
            "labels",
            "error_code",
            "model",
            "thinking_level",
            "prompt_version",
            "raw_output",
            "updated_at",
        ):
            data[name] = None
    result = JobResult.model_validate(data)
    assert set(JobResult.model_fields) == set(data)
    for name, value in data.items():
        assert getattr(result, name) == value
    assert JobResult.model_validate_json(result.model_dump_json()) == result
    with pytest.raises(ValidationError) as caught:
        JobResult.model_validate({**data, "unknown": True})
    assert any(error["type"] == "extra_forbidden" for error in caught.value.errors())
    with pytest.raises(ValidationError):
        JobResult.model_validate({**data, "status": "unknown"})


def test_repository_protocols_declare_batch_queries_and_general_labels():
    from collections.abc import Collection, Mapping, Sequence
    from typing import Any, get_type_hints

    from beautyads.domain import AnalysisRepository, JobResult

    assert get_type_hints(AnalysisRepository.record_analysis)["labels"] == (
        Mapping[str, Any] | None
    )
    assert get_type_hints(AnalysisRepository.requeue_jobs) == {
        "kind": str,
        "error_codes": Collection[str],
        "return": int,
    }
    assert get_type_hints(AnalysisRepository.job_counts) == {
        "kind": str,
        "return": dict[str, int],
    }
    assert get_type_hints(AnalysisRepository.get_job_results) == {
        "kind": str,
        "keys": Sequence[CreativeKey],
        "return": list[JobResult],
    }
    assert get_type_hints(CreativeRepository.list_creatives) == {
        "brands": Collection[str] | None,
        "sources": Collection[Source] | None,
        "analyzable_only": bool,
        "limit": int | None,
        "return": list[Creative],
    }


def test_skin_values_match_adr_012_followup_decision_5():
    from enum import StrEnum
    from pathlib import Path

    from beautyads.domain.skin import SkinConcern, SkinType

    adr = (Path(__file__).resolve().parents[1] / "docs" / "ADR.md").read_text(
        encoding="utf-8"
    )
    decision = adr.split("5. **`SkinType`·`SkinConcern` 값 목록", 1)[1].split("\n", 1)[
        0
    ]
    types = decision.split("`SkinType` = ", 1)[1].split(". `SkinConcern`", 1)[0]
    concerns = decision.split("`SkinConcern` = ", 1)[1].split("(8개)", 1)[0]
    assert issubclass(SkinType, StrEnum) and issubclass(SkinConcern, StrEnum)
    assert {item.value for item in SkinType} == set(types.split("·"))
    assert {item.value for item in SkinConcern} == set(concerns.split(", "))
