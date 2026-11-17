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


@pytest.mark.parametrize("weak", ["resembles_only", "package_label"])
def test_only_spoken_screen_text_and_title_caption_evidence_is_accepted(weak):
    candidates = candidates_for_brand(
        "dev", [product(url="a"), product(url="b"), product(url="c")]
    )
    result = ProductIdResult.model_validate(
        {"selections": [sel("C1", weak), sel("C2", "on_screen_text")]},
        context={"candidates": candidates},
    )
    assert result.products(candidates) == [candidates["C2"].key]
    assert result.dropped == 1
    assert result.kept_evidence() == {"C2": "on_screen_text"}
    for good in ("spoken_name", "on_screen_text", "title_caption"):
        kept = ProductIdResult.model_validate(
            {"selections": [sel("C3", good)]}, context={"candidates": candidates}
        )
        assert kept.products(candidates) == [candidates["C3"].key] and not kept.dropped
    only_weak = ProductIdResult.model_validate(
        {"selections": [sel("C1", weak)]}, context={"candidates": candidates}
    )
    assert only_weak.products(candidates) == [] and only_weak.dropped == 1


def test_work_kind_is_v3_and_earlier_versions_are_never_reselected():
    from beautyads.domain.product_id import PRODUCT_ID_KIND

    assert PRODUCT_ID_KIND == "product-id@v3"
    p = product()
    rows = [
        creative(id="fresh"),
        *[
            creative(id=version, jobs=[SyncLabel(f"product-id@{version}", "done", {})])
            for version in ("v1", "v2", "v3")
        ],
        creative(id="held", jobs=[SyncLabel("product-id@v1", "held", None)]),
    ]
    assert [r.creative.key.source_id for r in select_targets(rows, [p])] == [
        "fresh",
        "held",
    ]


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
            id="done", jobs=[SyncLabel("product-id@v3", "done", {"products": []})]
        ),
    ]
    selected = select_targets(rows, products)
    assert [row.creative.key.source_id for row in selected] == ["eligible", "ambiguous"]
