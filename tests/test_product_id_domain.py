import pytest
from pydantic import ValidationError
from test_links_domain import creative, product

from beautyads.domain.product_id import (
    ProductIdResult,
    candidates_for_brand,
    select_targets,
)
from beautyads.domain.sync import SyncLabel


def test_candidates_are_same_brand_stable_and_decode_to_stored_keys():
    products = [product(url="b"), product(url="a"), product(brand="other")]
    candidates = candidates_for_brand("dev", products)
    assert list(candidates) == ["C1", "C2"]
    assert list(candidates.values()) == sorted(products[:2], key=lambda p: p.source_url)
    for candidate_id, stored in candidates.items():
        result = ProductIdResult.model_validate(
            {"candidates": [candidate_id]}, context={"candidates": candidates}
        )
        assert result.products(candidates) == [stored.key]
    assert candidates_for_brand("absent", products) == {}


@pytest.mark.parametrize(
    "values",
    [
        ["C999"],
        ["C1", "C1"],
        [[], "C1"],
        ["", "C1"],
        [None, "C1"],
        ["합성 푸른 세럼"],
        "C1",
    ],
)
def test_rejects_non_candidates_duplicates_and_mixed_none(values):
    with pytest.raises(ValidationError):
        ProductIdResult.model_validate(
            {"candidates": values}, context={"candidates": {"C1": product()}}
        )


def test_empty_is_valid_and_extra_names_are_rejected():
    assert ProductIdResult.model_validate({"candidates": []}).candidates == []
    with pytest.raises(ValidationError):
        ProductIdResult.model_validate({"candidates": [], "name": "new"})


def test_selection_hand_count_includes_ambiguous_only_from_supported_sources():
    products = [
        product(aliases=("shared",)),
        product("합성 다른 앰플", url="b", aliases=("shared",)),
    ]
    rows = [
        creative(id="eligible"),
        creative("shared", id="ambiguous"),
        creative(source="tiktok", id="tt"),
        creative(content_type="brand_campaign", id="campaign"),
        creative(products[0].name_ko, id="text"),
        creative(brand="absent", id="absent"),
        creative(
            id="done", jobs=[SyncLabel("product-id@v1", "done", {"products": []})]
        ),
    ]
    selected = select_targets(rows, products)
    assert [row.creative.key.source_id for row in selected] == ["eligible", "ambiguous"]
