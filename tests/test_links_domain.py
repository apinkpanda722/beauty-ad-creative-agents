import inspect
from datetime import UTC, datetime

import pytest

from beautyads.domain.links import (
    MIN_ALIAS_LEN,
    LinkCreative,
    match_products,
    plan_links,
    select_rules,
    summarize_links,
)
from beautyads.domain.products import Product
from beautyads.domain.sync import SyncCreative, SyncLabel

NOW = datetime(2026, 11, 15, tzinfo=UTC)


def product(name="합성 푸른 세럼", *, brand="dev", url="p", aliases=(), name_en=None):
    return Product.model_validate(
        {
            "brand": brand,
            "source_url": f"https://example.test/{url}",
            "name_ko": name,
            "name_en": name_en,
            "aliases": list(aliases),
            "category": "serum_ampoule",
        },
        context={"from_store": True},
    )


def creative(
    title="",
    caption="",
    *,
    brand="dev",
    source="youtube",
    id="1",
    content_type="product_creative",
    jobs=(),
):
    return LinkCreative(
        SyncCreative(
            {
                "source": source,
                "source_id": id,
                "brand": brand,
                "title": title,
                "caption": caption,
            },
            NOW,
        ),
        [SyncLabel("content_type@v1", "done", {"content_type": content_type}), *jobs],
    )


@pytest.mark.parametrize(
    "title,caption,basis",
    [
        ("새로운 합성 푸른 세럼 공개", "", "title"),
        ("", "합성 푸른 세럼 사용법", "caption"),
    ],
)
def test_full_name_in_same_brand_text(title, caption, basis):
    p = product()
    links = match_products(creative(title, caption), [p])
    assert links.status == "matched" and len(links.matches) == 1
    result = links.matches[0]
    assert result.product == p and not links.multi_product
    assert result.basis == basis and result.confidence == "name_full"
    assert result.matched_text == p.name_ko


@pytest.mark.parametrize(
    "text", ["BLUE Serum", "ｂｌｕｅ　ＳＥＲＵＭ", "b l u e\tserum"]
)
def test_normalization_and_english_name(text):
    links = match_products(creative(text), [product(name_en="Blue Serum")])
    assert links.status == "matched" and links.matches[0].confidence == "alias"


def test_alias_minimum_and_no_partial_name_or_cross_brand_match():
    p = product(aliases=("푸세", "푸른빛"))
    assert MIN_ALIAS_LEN == 3
    assert match_products(creative("푸른빛"), [p]).matches[0].confidence == "alias"
    for text in ("푸세", "합성 푸른", ""):
        assert match_products(creative(text), [p]).matches == ()
    assert match_products(creative(p.name_ko, brand="test"), [p]).matches == ()
    other = match_products(creative(p.name_ko, content_type="brand_campaign"), [p])
    assert other.status == "not_product" and other.matches == ()


def test_a_longer_name_containing_a_shorter_one_wins_in_either_product_order():
    a, b = product("합성 세럼"), product("합성 세럼 플러스", url="b")
    for products in ([a, b], [b, a]):
        links = match_products(creative(b.name_ko), products)
        assert [m.product for m in links.matches] == [b]
        assert not links.multi_product
    # The shorter name alone still links the shorter product.
    assert [m.product for m in match_products(creative(a.name_ko), [a, b]).matches] == [
        a
    ]


def test_every_product_named_in_the_text_is_linked_and_marked_multi_product():
    a, c = product("합성 세럼"), product("가상 앰플", url="c")
    for products in ([a, c], [c, a]):
        links = match_products(creative(a.name_ko + " " + c.name_ko), products)
        assert links.status == "matched" and links.multi_product
        # Deterministic order: where each name first appears in the text.
        assert [m.product for m in links.matches] == [a, c]


def test_names_in_title_and_caption_both_link_and_title_comes_first():
    short = product("가상", aliases=("짧음",))
    long = product("합성 긴 세럼", url="long")
    links = match_products(creative(short.name_ko, long.name_ko), [short, long])
    assert [m.product for m in links.matches] == [short, long]
    assert [m.basis for m in links.matches] == ["title", "caption"]
    assert links.multi_product


def test_dalba_employee_best_five_video_links_all_five_products():
    # Regression input: one video introducing five products of the same brand.
    names = [
        "워터풀 에센스 선크림",
        "워터풀 톤업 선크림",
        "화이트 트러플 퍼스트 스프레이 세럼",
        "비타 토닝 캡슐 크림",
        "그린 토마토 모공 세럼",
    ]
    products = [product(n, brand="dalba", url=f"d{i}") for i, n in enumerate(names)]
    title = "달바 직원 BEST 5 " + " / ".join(names)
    links = match_products(creative(title, brand="dalba"), products)
    assert links.status == "matched" and links.multi_product
    assert {m.product.name_ko for m in links.matches} == set(names)
    assert len(links.matches) == 5


def test_two_products_sharing_the_same_mention_are_ambiguous_and_not_linked():
    one = product("합성 세럼", aliases=("푸른빛",), url="one")
    two = product("가상 앰플", aliases=("푸른빛",), url="two")
    links = match_products(creative("푸른빛 추천"), [one, two])
    assert links.status == "ambiguous" and links.matches == ()
    # A third product named elsewhere in the text still links on its own.
    third = product("전혀 다른 크림", url="three")
    links = match_products(creative("푸른빛 추천", third.name_ko), [one, two, third])
    assert links.status == "matched"
    assert [m.product for m in links.matches] == [third]
    assert not links.multi_product


def test_one_product_multiple_matches_is_one_link_and_prefers_full_title():
    p = product("Blue Serum", name_en="BLUE SERUM", aliases=("blue serum",))
    links = match_products(creative("blue serum", "Blue Serum"), [p, p])
    assert len(links.matches) == 1 and not links.multi_product
    result = links.matches[0]
    assert result.basis == "title" and result.confidence == "name_full"


def test_longest_name_of_one_product_precedes_basis_and_short_names_are_allowed():
    short = product("가상", aliases=("짧음",))
    assert (
        match_products(creative("가상"), [short]).matches[0].confidence == "name_full"
    )
    p = product("합성 긴 세럼", aliases=("합성 긴",), url="p")
    result = match_products(creative("합성 긴", p.name_ko), [p]).matches[0]
    assert result.matched_text == p.name_ko and result.basis == "caption"


def test_plan_exposes_links_and_status():
    a, c = product("합성 세럼"), product("가상 앰플", url="c")
    plan = plan_links(creative(a.name_ko + c.name_ko), [a, c])
    assert plan.status == "matched" and len(plan.links) == 2
    assert plan.multi_product is True
    single = plan_links(creative(a.name_ko), [a, c])
    assert single.multi_product is False and len(single.links) == 1


def test_claims_and_mentions_use_only_completed_final_jobs_and_exact_raw_names():
    jobs = [
        SyncLabel(
            "full@v1",
            "done",
            {
                "claims": ["hydration", "other", "invalid", "hydration"],
                "ingredients": ["합성 표기(1%)", "미해결", "오래된 표기"],
            },
        ),
        SyncLabel(
            "ingredient-matches@v1",
            "done",
            {
                "ingredients": [
                    {
                        "raw_name": "합성 표기(1%)",
                        "standard_name": "표준성분",
                        "status": "resolved",
                    },
                    {
                        "raw_name": "미해결",
                        "standard_name": None,
                        "status": "unresolved",
                    },
                    {
                        "raw_name": "다른 원문",
                        "standard_name": "표준성분",
                        "status": "resolved",
                    },
                ]
            },
        ),
    ]
    plan = plan_links(creative(jobs=jobs), [])
    assert plan.claims == ("hydration",)
    assert [(m.raw_name, m.standard_name) for m in plan.mentions] == [
        ("합성 표기(1%)", "표준성분")
    ]
    assert plan.unresolved == 2


@pytest.mark.parametrize(
    "kind,status",
    [
        ("full@minimal", "done"),
        ("full@default", "done"),
        ("full@v0", "done"),
        ("full@v1", "held"),
        ("full@v1", "pending"),
    ],
)
def test_nonfinal_labels_are_not_read(kind, status):
    plan = plan_links(
        creative(
            jobs=[
                SyncLabel(
                    kind, status, {"claims": ["hydration"], "ingredients": ["raw"]}
                )
            ]
        ),
        [],
    )
    assert plan.claims == plan.mentions == () and plan.unresolved == 0


def test_conflicting_or_incomplete_ingredient_matches_are_unresolved():
    c = creative(
        jobs=[
            SyncLabel("full@v1", "done", {"ingredients": ["raw"], "claims": []}),
            SyncLabel(
                "ingredient-matches@v1",
                "done",
                {
                    "ingredients": [
                        {"raw_name": "raw", "standard_name": "A", "status": "resolved"},
                        {"raw_name": "raw", "standard_name": "B", "status": "resolved"},
                    ]
                },
            ),
        ]
    )
    assert plan_links(c, []).mentions == () and plan_links(c, []).unresolved == 1


@pytest.mark.parametrize(
    "kind,status",
    [
        ("ingredient-matches@v0", "done"),
        ("ingredient-matches@v1", "pending"),
    ],
)
def test_mentions_do_not_use_nonfinal_or_unfinished_matching_jobs(kind, status):
    c = creative(
        jobs=[
            SyncLabel("full@v1", "done", {"ingredients": ["raw"], "claims": []}),
            SyncLabel(
                kind,
                status,
                {
                    "ingredients": [
                        {
                            "raw_name": "raw",
                            "standard_name": "표준성분",
                            "status": "resolved",
                        },
                    ]
                },
            ),
        ]
    )
    assert plan_links(c, []).mentions == () and plan_links(c, []).unresolved == 1


def test_summary_split_missing_products_tiktok_and_hand_counts():
    p = product()
    a, b = (
        product("가상 세럼", brand="test"),
        product("시험 세럼", brand="test", url="b"),
    )
    entries = [
        creative(p.name_ko),
        creative("없음", id="2"),
        creative(source="tiktok", id="3"),
        creative(brand="missing", id="4"),
        creative(a.name_ko + b.name_ko, brand="test", id="5"),
        creative(a.name_ko, brand="test", source="instagram", id="6"),
        creative("이름 없는 제품 소개", brand="test", id="7"),
    ]
    report = summarize_links(
        entries, [p, a, b], dev_brands=["dev"], test_brands=["test", "missing"]
    )
    # Entry 5 names two products: it links to both and counts once as a creative.
    assert report["promotes"] == 3 and report["product_creatives"] == 6
    assert report["all_product_creatives"] == 7 and report["ambiguous"] == 0
    assert report["promotes_links"] == 4 and report["multi_product_creatives"] == 1
    assert report["dev"]["promotes"] == 1 and report["test"]["promotes"] == 2
    assert report["dev"]["coverage"] == 1 / 3 and report["test"]["coverage"] == 2 / 3
    assert report["no_product_info_brands"] == ["missing"]
    assert report["candidates_by_source"] == {"youtube": 4, "instagram": 1, "tiktok": 0}
    assert report["claims"] == report["mentions"] == report["unresolved"] == 0
    assert "별도 추출" in report["recommendation"]
    assert list(inspect.signature(select_rules).parameters) == ["dev_creatives"]
    assert select_rules([entries[0]]) == select_rules([])


def test_empty_summary_is_zero_and_mentions_counts_are_per_creative():
    report = summarize_links([], [], dev_brands=[], test_brands=[])
    for field in (
        "promotes",
        "product_creatives",
        "ambiguous",
        "claims",
        "mentions",
        "unresolved",
    ):
        assert report[field] == 0
    assert report["sample_pairs"] == [] and report["recommendation"] is None
    c = creative(
        jobs=[
            SyncLabel(
                "full@v1", "done", {"claims": ["soothing"], "ingredients": ["unknown"]}
            )
        ]
    )
    report = summarize_links([c], [], dev_brands=["dev"], test_brands=[])
    assert report["claims"] == 1 and report["unresolved"] == 1


def test_seeded_pairs_are_reproducible_truncated_and_subset_of_links():
    p = product()
    entries = [creative(p.name_ko + "x" * 130, "c" * 130, id=str(i)) for i in range(35)]

    def sample(seed, rows=entries):
        return summarize_links(
            rows, [p], dev_brands=["dev"], test_brands=[], seed=seed
        )["sample_pairs"]

    assert sample(7) == sample(7, list(reversed(entries)))
    assert len(sample(7)) == 20 and len(sample(7, entries[:4])) == 4
    all_ids = {str(i) for i in range(35)}
    for pairs in (sample(7), sample(8)):
        assert {pair["source_id"] for pair in pairs} <= all_ids
        assert all(
            pair["product_name"] == p.name_ko
            and len(pair["title"]) <= 120
            and len(pair["caption"]) == 120
            and pair["basis"] == "title"
            and pair["confidence"] == "name_full"
            and pair["matched_text"]
            for pair in pairs
        )
    assert sample(7) != sample(8)


def test_rule_selection_receives_dev_entries_only(monkeypatch):
    seen = []

    def select(dev_creatives):
        seen.extend(dev_creatives)
        return {"min_alias_len": MIN_ALIAS_LEN, "candidate_selection": "longest_unique"}

    monkeypatch.setattr("beautyads.domain.links.select_rules", select)
    dev, test = creative(), creative(brand="test", id="2")
    summarize_links([dev, test], [], dev_brands=["dev"], test_brands=["test"])
    assert seen == [dev]


def test_summary_reports_multi_product_creatives_and_link_counts_separately():
    a, c = product("합성 세럼"), product("가상 앰플", url="c")
    entries = [
        creative(a.name_ko, id="1"),
        creative(a.name_ko + " " + c.name_ko, id="2"),
        creative("무관한 영상", id="3"),
    ]
    report = summarize_links(entries, [a, c], dev_brands=["dev"], test_brands=[])
    # promotes counts creatives, as before; links count every PROMOTES relationship.
    assert report["promotes"] == 2 and report["product_creatives"] == 3
    assert report["promotes_links"] == 3 and report["multi_product_creatives"] == 1
    assert report["by_source"]["youtube"]["multi_product_creatives"] == 1
    pairs = report["sample_pairs"]
    assert {(p["source_id"], p["multi_product"]) for p in pairs} >= {("1", False)}
    assert any(p["multi_product"] for p in pairs)
