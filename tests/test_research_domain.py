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
            aggregates={},
            confidence="low",
            unresolved=[],
            **{field: None},
        )
