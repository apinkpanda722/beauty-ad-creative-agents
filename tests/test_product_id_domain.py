import pytest
from pydantic import ValidationError
from test_links_domain import creative, product

from beautyads.domain.product_id import (
    ProductIdResult,
    candidates_for_brand,
    product_id_schema,
    select_targets,
)
from beautyads.domain.sync import SyncLabel


def sel(candidate, evidence="spoken_name"):
    return {"candidate": candidate, "evidence": evidence}


def test_candidates_are_same_brand_stable_and_decode_to_stored_keys():
    products = [product(url="b"), product(url="a"), product(brand="other")]
    candidates = candidates_for_brand("dev", products)
    assert list(candidates) == ["C1", "C2"]
    assert list(candidates.values()) == sorted(products[:2], key=lambda p: p.source_url)
    for candidate_id, stored in candidates.items():
        result = ProductIdResult.model_validate(
            {"selections": [sel(candidate_id)]}, context={"candidates": candidates}
        )
        assert result.products(candidates) == [stored.key]
    assert candidates_for_brand("absent", products) == {}


@pytest.mark.parametrize(
    "values",
    [
        [sel("C999")],
        [sel("C1"), sel("C1", "on_screen_text")],
        [{"candidate": "C1"}],
        [{"candidate": "C1", "evidence": "guess"}],
        [{"candidate": "", "evidence": "spoken_name"}],
        [sel("합성 푸른 세럼")],
        [{**sel("C1"), "name": "new"}],
        "C1",
    ],
)
def test_rejects_non_candidates_duplicates_missing_or_unknown_evidence(values):
    with pytest.raises(ValidationError):
        ProductIdResult.model_validate(
            {"selections": values}, context={"candidates": {"C1": product()}}
        )


def test_empty_is_valid_and_extra_names_are_rejected():
    assert ProductIdResult.model_validate({"selections": []}).selections == []
    with pytest.raises(ValidationError):
        ProductIdResult.model_validate({"selections": [], "name": "new"})


def test_resemblance_only_evidence_is_dropped_by_validation():
    candidates = candidates_for_brand("dev", [product(url="a"), product(url="b")])
    result = ProductIdResult.model_validate(
        {"selections": [sel("C1", "resembles_only"), sel("C2", "package_label")]},
        context={"candidates": candidates},
    )
    assert result.products(candidates) == [candidates["C2"].key]
    assert result.dropped == 1
    assert result.kept_evidence() == {"C2": "package_label"}
    only_similar = ProductIdResult.model_validate(
        {"selections": [sel("C1", "resembles_only")]},
        context={"candidates": candidates},
    )
    assert only_similar.products(candidates) == [] and only_similar.dropped == 1


def test_json_schema_closes_candidate_and_evidence_values():
    candidates = candidates_for_brand("dev", [product(url="a"), product(url="b")])
    item = product_id_schema(candidates)["properties"]["selections"]["items"]
    assert item["properties"]["candidate"]["enum"] == ["C1", "C2"]
    assert "resembles_only" in item["properties"]["evidence"]["enum"]
    assert item["additionalProperties"] is False


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
            id="done", jobs=[SyncLabel("product-id@v2", "done", {"products": []})]
        ),
    ]
    selected = select_targets(rows, products)
    assert [row.creative.key.source_id for row in selected] == ["eligible", "ambiguous"]
