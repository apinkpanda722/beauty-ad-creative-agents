"""Synthetic research contracts and deterministic evidence restriction."""

import pytest
from pydantic import ValidationError

from beautyads.domain.labels import Category
from beautyads.domain.research import (
    ResearchBrief,
    ResearchHandoffDraft,
    restrict_evidence_ids,
)


@pytest.mark.parametrize(
    "claimed,pool,expected",
    [
        (
            ["yt:b", "yt:a", "yt:b", "yt:outside"],
            ["yt:b", "yt:a"],
            (["yt:a", "yt:b"], ["yt:outside"]),
        ),
        (["yt:a", "yt:a"], [], ([], ["yt:a"])),
        ([], ["yt:a"], ([], [])),
        (["z", "a", "z"], [], ([], ["a", "z"])),
    ],
)
def test_restrict_ids(claimed, pool, expected):
    originals = (claimed.copy(), pool.copy())
    assert restrict_evidence_ids(claimed, pool) == expected
    assert (claimed, pool) == originals


@pytest.mark.parametrize("field", ["tenant_id", "tenant", "user", "date", "today"])
def test_brief_rejects_server_fields(field):
    assert field not in ResearchBrief.model_fields
    with pytest.raises(ValidationError):
        ResearchBrief(
            goal="synthetic", category="mask_pack", output="both", **{field: "x"}
        )


@pytest.mark.parametrize("limit", [0, 11])
def test_brief_bounds(limit):
    with pytest.raises(ValidationError):
        ResearchBrief(
            goal="synthetic", category="mask_pack", output="both", max_tool_calls=limit
        )


def test_closed_brief_and_defaults():
    for category in Category:
        if category == Category.other:
            with pytest.raises(ValidationError):
                ResearchBrief(goal="synthetic", category=category, output="both")
        else:
            brief = ResearchBrief(goal="synthetic", category=category, output="both")
            assert brief.max_tool_calls == 6
            assert brief.claim is None and brief.skin_concern is None
    with pytest.raises(ValidationError):
        ResearchBrief(goal="synthetic", category="mask_pack", output="arbitrary")


@pytest.mark.parametrize(
    "field",
    [
        "status",
        "no_evidence_tools",
        "basis_notes",
        "structured_failure_rate",
        "tenant_id",
    ],
)
def test_draft_cannot_choose_code_owned_fields(field):
    assert field not in ResearchHandoffDraft.model_fields
    with pytest.raises(ValidationError):
        ResearchHandoffDraft(
            conclusion="synthetic",
            evidence_ids=[],
            aggregates=[],
            confidence="low",
            unresolved=[],
            **{field: None},
        )


@pytest.mark.parametrize(
    "total,shown,label",
    [
        (13, 5, "13건 중 5건 표시"),
        (3, 3, "3건"),
        (0, 0, "0건"),
        (4, 0, "4건 중 0건 표시"),
    ],
)
def test_count_label_contract(total, shown, label):
    from beautyads.domain.research import count_label

    assert count_label(total, shown) == label


@pytest.mark.parametrize("total,shown", [(-1, 0), (1, -1), (-1, -1), (3, 4)])
def test_count_label_rejects_invalid_counts(total, shown):
    from beautyads.domain.research import count_label

    with pytest.raises(ValueError):
        count_label(total, shown)


@pytest.mark.parametrize("total,shown", [(13, 5), (3, 3), (0, 0)])
def test_result_count_derives_truncation_and_roundtrips(total, shown):
    from beautyads.domain.research import ResultCount

    count = ResultCount(tool="synthetic", row_count=total, shown_count=shown)
    assert count.model_dump(mode="json") == {
        "tool": "synthetic",
        "row_count": total,
        "shown_count": shown,
        "truncated": shown < total,
    }
    assert ResultCount.model_validate(count.model_dump(mode="json")) == count


def test_handoff_counts_default_is_independent_and_never_model_authored():
    from beautyads.domain.research import ResearchHandoff

    draft = {
        "conclusion": "synthetic",
        "evidence_ids": [],
        "aggregates": [],
        "confidence": "low",
        "unresolved": [],
    }
    assert "result_counts" not in ResearchHandoffDraft.model_fields
    assert "result_counts" not in ResearchHandoffDraft.model_json_schema()["properties"]
    with pytest.raises(ValidationError):
        ResearchHandoffDraft(**draft, result_counts=[])
    fields = dict(
        **{**draft, "aggregates": {}},
        status="no_evidence",
        no_evidence_tools=[],
        basis_notes=[],
        structured_failure_rate=None,
    )
    first, second = ResearchHandoff(**fields), ResearchHandoff(**fields)
    assert first.result_counts == second.result_counts == []
    assert first.result_counts is not second.result_counts


@pytest.mark.parametrize(
    "values,expected",
    [
        ([], {}),
        ([{"name": "n", "value": "1"}], {"n": "1"}),
        (
            [
                {"name": "n", "value": "first"},
                {"name": "n", "value": "later"},
                {"name": "other", "value": "2"},
            ],
            {"n": "first", "other": "2"},
        ),
    ],
)
def test_aggregates_from_items_preserves_first_and_string_values(values, expected):
    from beautyads.domain.research import AggregateItem, aggregates_from_items

    items = [AggregateItem.model_validate(value) for value in values]
    before = [item.model_dump() for item in items]
    converted = aggregates_from_items(items)
    assert converted == expected
    assert all(isinstance(value, str) for value in converted.values())
    assert [item.model_dump() for item in items] == before


def test_aggregate_item_forbids_extra_fields_and_nonstring_values():
    from beautyads.domain.research import AggregateItem

    for value in ({"name": "n", "value": 1}, {"name": "n", "value": "1", "extra": "x"}):
        with pytest.raises(ValidationError):
            AggregateItem.model_validate(value)


def test_draft_fields_remain_model_owned_and_aggregates_are_described():
    from beautyads.domain.research import ResearchHandoff

    assert set(ResearchHandoffDraft.model_fields) == {
        "conclusion",
        "evidence_ids",
        "aggregates",
        "confidence",
        "unresolved",
    }
    for contract in (ResearchHandoffDraft, ResearchHandoff):
        description = contract.model_fields["aggregates"].description
        assert "모델이 작성한 값이며 검증된 수치가 아니다" in description


def test_final_handoff_preserves_free_value_dictionary_contract():
    from typing import Any

    from beautyads.domain.research import ResearchHandoff

    assert ResearchHandoff.model_fields["aggregates"].annotation == dict[str, Any]
    value = ResearchHandoff(
        conclusion="synthetic",
        evidence_ids=[],
        aggregates={"n": 1, "text": "1"},
        confidence="low",
        unresolved=[],
        status="ok",
        no_evidence_tools=[],
        basis_notes=[],
        structured_failure_rate=None,
    )
    assert value.aggregates == {"n": 1, "text": "1"}
