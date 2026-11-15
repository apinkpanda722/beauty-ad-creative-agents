"""Synthetic product names exercise deterministic rules, never model accuracy."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from beautyads.domain.products import (
    CONTAINER_WORDS,
    FORM_WORDS,
    STOPWORDS,
    Product,
    ProductCert,
    ProductExtraction,
    ProductIngredient,
    derive_aliases,
)


def product_data(**changes):
    return {
        "brand": "합성브랜드",
        "source_url": "https://shop.example/products/one",
        "category": "serum_ampoule",
        "name_ko": "합성성분 워터리 복합 세럼 50ml",
        **changes,
    }


def aliases(name, products=()):
    return derive_aliases(name, brand_products=products)


def test_alias_three_rules_and_determinism():
    name = "합성성분 워터리 복합 세럼 50ml 튜브 SPF50+ PA++++ 1+1"
    expected = ["합성성분 워터리 복합 세럼", "합성성분 복합 세럼", "합성성분 세럼"]
    assert aliases(name) == expected
    assert aliases(name) == aliases(name)
    assert aliases("ＸＹＺ NEW Mixed 세럼 1.5g") == [
        "xyz new mixed 세럼",
        "xyz mixed 세럼",
        "xyz 세럼",
    ]


@pytest.mark.parametrize("word", sorted(CONTAINER_WORDS))
def test_containers_are_removed(word):
    assert aliases(f"합성성분 세럼 {word}") == ["합성성분 세럼"]


@pytest.mark.parametrize("capacity", ["50ml", "1.5g", "3매", "5입", "10EA", "2+3"])
def test_capacity_tokens_are_removed(capacity):
    assert aliases(f"합성성분 세럼 {capacity}") == ["합성성분 세럼"]


def test_constants_include_approved_vocabulary():
    assert {
        "더",
        "the",
        "new",
        "리뉴얼",
        "어드밴스드",
        "플러스",
        "하이퍼",
        "마일드",
        "워터리",
        "릴리프",
    } <= STOPWORDS
    assert {
        "튜브",
        "펌프",
        "캡",
        "리필",
        "용기",
        "파우치",
        "데일리",
        "픽",
    } <= CONTAINER_WORDS
    assert {
        "세럼",
        "앰플",
        "마스크",
        "시트",
        "팩",
        "선크림",
        "선세럼",
        "선스틱",
        "에센스",
        "크림",
        "젤",
        "로션",
    } <= FORM_WORDS


@pytest.mark.parametrize(
    "name", ["", " \t", "X", "XY", "세럼", "선세럼", "선 세럼", "50ml 튜브"]
)
def test_empty_short_and_form_only_aliases_are_discarded(name):
    assert aliases(name) == []


@pytest.mark.parametrize(
    "form",
    [
        "선 세럼",
        "선세럼",
        "선크림",
        "선스틱",
        "선 스크린",
        "선로션",
        "선젤",
        "선쿠션",
        "선플루이드",
        "선파우더",
    ],
)
def test_sun_is_preserved_in_every_alias(form):
    result = aliases(f"X Y {form} 50ml")
    assert result and all("선" in value for value in result)
    assert not {"x 세럼", "y 세럼", "x y 세럼"}.intersection(result)
    assert any(
        value.replace(" ", "") == "x" + form.replace(" ", "") for value in result
    )


def test_split_and_joined_sun_form_are_equivalent_and_plain_serum_still_works():
    compact = lambda values: [value.replace(" ", "") for value in values]
    assert compact(aliases("X Y 선 세럼 50ml")) == compact(aliases("X Y 선세럼"))
    assert "x 세럼" in aliases("X Y 세럼")
    assert aliases("X 마일드 선 세럼") == ["x 마일드 선 세럼", "x 선 세럼"]


def test_sun_form_is_kept_even_with_a_later_plain_form_word():
    result = aliases("X Y 선 세럼 젤 50ml")
    assert result and all("선" in value for value in result)
    assert "x 선 세럼" in result


def test_ambiguous_alias_removed_for_both_products_but_unique_names_remain():
    names = ["X 선 세럼 A", "X 선 세럼 B"]
    for name in names:
        result = aliases(name, names)
        assert "x 선 세럼" not in result
        assert name.lower() in result


def test_variants_count_once_and_self_is_included_even_if_missing_from_listing():
    names = ["X 선 세럼 50ml", "[1+1] X 선 세럼 50ml 더블"]
    assert aliases(names[0], names) == ["x 선 세럼"]
    assert aliases(names[1], names) == ["x 선 세럼 더블", "x 선 세럼"]
    assert aliases("X 선 세럼", ["X 선 세럼 B"]) == []
    assert aliases("X 선 세럼", []) == ["x 선 세럼"]


def test_full_same_brand_listing_drives_ambiguity_not_selected_subset():
    assert aliases("X 선 세럼", ["X 선 세럼"]) == ["x 선 세럼"]
    assert aliases("X 선 세럼", ["X 선 세럼", "X 선 세럼 B"]) == []
    # Callers pass only this brand's names; unrelated brands are not global state.
    assert aliases("X 선 세럼", ["X 선 세럼"]) == ["x 선 세럼"]


def test_product_derives_aliases_with_brand_context_and_rejects_user_aliases():
    item = Product.model_validate(product_data())
    assert item.aliases == aliases(item.name_ko)
    assert Product.model_validate(product_data(name_ko="합성브랜드")).aliases == []
    names = ["X 선 세럼", "X 선 세럼 B"]
    item = Product.model_validate(
        product_data(name_ko=names[0]), context={"brand_products": names}
    )
    assert item.aliases == []
    with pytest.raises(ValidationError):
        Product.model_validate(product_data(aliases=["임의 별칭"]))


@pytest.mark.parametrize(
    "changes",
    [
        {"category": "other"},
        {"skin_types": ["없는 타입"]},
        {"price_basis": "unknown"},
        {"list_price": -1},
        {"sale_price": "NaN"},
        {"volume": 0},
        {"volume_unit": "invalid"},
        {"source_url": "file:///somewhere"},
        {"source_url": "https://name:password@shop.example/a"},
        {"price_collected_at": datetime(2026, 11, 15)},
    ],
)
def test_product_rejects_invalid_closed_values(changes):
    with pytest.raises(ValidationError):
        Product.model_validate(product_data(**changes))


def test_product_normalizes_identity_and_retains_original_texts():
    item = Product.model_validate(
        product_data(
            source_url=" HTTPS://SHOP.EXAMPLE:443/products/one?product_no=1#details ",
            name_en=None,
            skin_types=["건성", "민감성"],
            efficacy_texts=["합성 효능 원문"],
            functional_texts=["기능성 표기 원문"],
            volume="50.5",
            volume_unit="ml",
            form="세럼",
            list_price="10000",
            sale_price="9000",
            price_basis="list_price",
            price_collected_at=datetime(2026, 11, 15, tzinfo=UTC),
        )
    )
    assert item.source_url == "https://shop.example/products/one?product_no=1"
    assert item.key.brand == item.brand and item.key.source_url == item.source_url
    assert item.efficacy_texts == ["합성 효능 원문"]
    assert item.functional_texts == ["기능성 표기 원문"]


def test_related_records_preserve_unresolved_and_extraction_evidence():
    key = Product.model_validate(product_data()).key
    ingredient = ProductIngredient(
        product=key, order=1, raw_name="미해결 원문", status="unresolved"
    )
    assert ingredient.standard_name is None and ingredient.raw_name == "미해결 원문"
    for status, standard in [("unresolved", "표준명"), ("resolved", None)]:
        with pytest.raises(ValidationError):
            ProductIngredient(
                product=key,
                order=1,
                raw_name="원문",
                status=status,
                standard_name=standard,
            )
    cert = ProductCert(
        product=key, kind="brightening", status="unknown", evidence_api="report"
    )
    assert cert.evidence_item_name is None
    extraction = ProductExtraction(
        product=key, prompt_version="synthetic-v1", raw_output="  unparsed\n원문  "
    )
    assert extraction.raw_output == "  unparsed\n원문  "
