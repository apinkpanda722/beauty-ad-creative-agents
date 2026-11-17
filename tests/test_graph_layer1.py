"""Layer-one facts use synthetic inputs and an offline graph recorder only."""

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from beautyads.domain.claims import ClaimRule
from beautyads.domain.labels import Claim
from beautyads.domain.layer1 import SyncProduct
from beautyads.domain.mfds import IngredientStandard
from beautyads.domain.products import Product, ProductCert, ProductIngredient
from beautyads.domain.skin import SkinConcern, SkinType
from beautyads.graph.connection import GraphError, GraphResult
from beautyads.graph.layer1 import (
    CLEAN_CONTAINS,
    MERGE_CONTAINS,
    load_layer1,
    load_layer1_tables,
    parse_layer1_tables,
)

NOW = datetime(2026, 11, 15, tzinfo=UTC)


def documents():
    return (
        {
            "links": [
                {
                    "efficacy": ["hydration", "barrier"],
                    "basis": "literature_review",
                    "conditional": False,
                    "source_ref": "synthetic reference",
                    "ingredients": [
                        {
                            "inci": "INCI A",
                            "standard_name": "성분가",
                            "matched_by": "eng_name_exact",
                        },
                        {
                            "inci": "INCI B",
                            "standard_name": "성분나",
                            "matched_by": "eng_name_exact",
                        },
                    ],
                }
            ],
            "unmatched": [{"inci": "unmatched marker"}],
            "not_linked_for_now": ["unlinked marker"],
        },
        {
            "rows": [
                {
                    "efficacy": "hydration",
                    "concern": "건조",
                    "status": "confirmed",
                    "basis": "taxonomy_definition",
                    "source_ref": "synthetic taxonomy",
                },
                {
                    "efficacy": "soothing",
                    "concern": "홍조·민감",
                    "status": "draft",
                    "basis": None,
                    "source_ref": None,
                },
            ]
        },
    )


def product_entry(names=("성분가", "성분나", None), *, cert_status="unknown"):
    product = Product(
        brand="synthetic brand",
        source_url="https://example.test/product",
        category="serum_ampoule",
        name_ko="합성 세럼",
        name_en="Synthetic serum",
        volume=20,
        volume_unit="ml",
        list_price=10000,
        sale_price=8000,
        price_collected_at=NOW,
        form="세럼",
        skin_types=["건성"],
        updated_at=NOW,
    )
    return SyncProduct(
        product=product,
        updated_at=NOW,
        ingredients=[
            ProductIngredient(
                product=product.key,
                order=n,
                raw_name=f"표기{n}",
                standard_name=name,
                status="resolved" if name else "unresolved",
            )
            for n, name in enumerate(names, 1)
        ],
        certs=[
            ProductCert(
                product=product.key,
                kind="brightening",
                status=cert_status,
                evidence_api="report",
            )
        ],
        standards=[
            IngredientStandard(
                name_ko="성분가", name_en="INCI A", cas_no="synthetic CAS"
            )
        ],
    )


class Graph:
    def __init__(self):
        self.calls = []
        self.contains = set()

    def run(self, query, params=None):
        params = deepcopy(params or {})
        self.calls.append((query, params))
        if query == MERGE_CONTAINS:
            for row in params["rows"]:
                self.contains.add(
                    (
                        row["brand"],
                        row["source_url"],
                        row["order"],
                        row["standard_name"],
                    )
                )
        if query == CLEAN_CONTAINS:
            for row in params["rows"]:
                self.contains = {
                    rel
                    for rel in self.contains
                    if rel[:2] != (row["brand"], row["source_url"])
                    or {"order": rel[2], "standard_name": rel[3]} in row["ingredients"]
                }
        return GraphResult([], 0, 0)


def relation_rows(graph, relation):
    return [
        row
        for query, params in graph.calls
        if f"[r:{relation}" in query and "MERGE" in query and "DELETE r" not in query
        for row in params.get("rows", [])
    ]


def test_parameterized_repeatable_loading_and_closed_nodes():
    graph = Graph()
    tables = parse_layer1_tables(*documents())
    load_layer1(graph, [product_entry()], tables=tables)
    first = deepcopy(graph.calls)
    load_layer1(graph, [product_entry()], tables=tables)
    assert graph.calls == first * 2
    assert all("CREATE" not in q and "MERGE" in q and "$rows" in q for q, _ in first)
    assert all("synthetic" not in q and "성분가" not in q for q, _ in first)
    for label, values in (
        ("Efficacy", Claim),
        ("SkinConcern", SkinConcern),
        ("SkinType", SkinType),
    ):
        rows = [r for q, p in first if f"(n:{label} " in q for r in p["rows"]]
        assert {r["value"] for r in rows} == {v.value for v in values}


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_ref", ""),
        ("source_ref", "  "),
        ("source_ref", None),
        ("basis", "unverified"),
        ("efficacy", ["invented"]),
        ("conditional", "true"),
        ("conditional", 1),
        ("ingredients", [{"inci": "A", "standard_name": "가", "matched_by": "guess"}]),
    ],
)
def test_bad_efficacy_document_refuses_before_any_write(field, value):
    ingredients, concerns = documents()
    ingredients["links"][0][field] = value
    graph = Graph()
    with pytest.raises(GraphError, match="INGREDIENT_EFFICACY_INVALID"):
        load_layer1(graph, [], tables=parse_layer1_tables(ingredients, concerns))
    assert graph.calls == []


def test_efficacy_cartesian_product_provenance_and_unlinked_counts():
    graph = Graph()
    report = load_layer1(
        graph,
        [product_entry(("표에없는성분",))],
        tables=parse_layer1_tables(*documents()),
    )
    rows = relation_rows(graph, "HAS_EFFICACY")
    assert {(r["standard_name"], r["efficacy"]) for r in rows} == {
        (name, claim)
        for name in ("성분가", "성분나")
        for claim in ("hydration", "barrier")
    }
    assert len(rows) == 4
    assert all(
        r["basis"] == "literature_review"
        and r["source_ref"]
        and r["conditional"] is False
        for r in rows
    )
    query = next(q for q, _ in graph.calls if "[r:HAS_EFFICACY]" in q)
    assert "r.basis" in query and "r.source_ref" in query and "r.conditional" in query
    assert "r.source =" not in query
    assert report["unmatched"] == report["not_linked_for_now"] == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_ref", ""),
        ("basis", "literature_review"),
        ("efficacy", "invented"),
        ("concern", "invented"),
        ("status", "invented"),
    ],
)
def test_invalid_confirmed_taxonomy_refused(field, value):
    ingredients, concerns = documents()
    concerns["rows"][0][field] = value
    with pytest.raises(GraphError, match="EFFICACY_CONCERN_INVALID"):
        parse_layer1_tables(ingredients, concerns)


def scope_rule(scopes):
    return ClaimRule(
        rule_id="synthetic rule",
        rule_type="prohibited",
        source_page=9,
        law_basis="synthetic source",
        group=None,
        source_items=["synthetic original"],
        terms_ko=[],
        terms_en=[],
        terms_en_added=[],
        matchable=False,
        en_pending=False,
        en_waived=False,
        exception_note=None,
        exceptions=[],
        exception_refs=[],
        applies_to=scopes,
    )


def test_only_confirmed_taxonomy_and_approved_rule_scopes_are_loaded():
    rule = scope_rule(
        [
            {"kind": "efficacy", "value": "hydration", "status": "advisor_approved"},
            {"kind": "skin_concern", "value": "건조", "status": "confirmed"},
            {"kind": "category", "value": "mask_pack", "status": "confirmed"},
            {"kind": "efficacy", "value": "barrier", "status": "draft"},
        ]
    )
    graph = Graph()
    report = load_layer1(
        graph, [], tables=parse_layer1_tables(*documents()), rules=[rule]
    )
    addresses = relation_rows(graph, "ADDRESSES")
    assert len(addresses) == 1 and addresses[0]["basis"] == "taxonomy_definition"
    assert addresses[0]["source_ref"]
    query = next(q for q, _ in graph.calls if "[r:ADDRESSES]" in q)
    assert "r.basis" in query and "r.source_ref" in query
    scopes = relation_rows(graph, "APPLIES_TO")
    assert {r["value"] for r in scopes} == {"hydration", "건조", "mask_pack"}
    assert all(":Product" not in q for q, _ in graph.calls if "APPLIES_TO" in q)
    assert report["draft_not_loaded"] == 2


def test_rule_scope_cannot_add_other_to_product_categories():
    rule = scope_rule([{"kind": "category", "value": "other", "status": "confirmed"}])
    graph = Graph()
    with pytest.raises(GraphError, match="CLAIM_RULES_INVALID"):
        load_layer1(graph, [], tables=parse_layer1_tables(*documents()), rules=[rule])
    assert graph.calls == []


def test_contains_replacement_removes_shortened_and_renamed_rows_and_unresolved():
    graph = Graph()
    tables = parse_layer1_tables(*documents())
    load_layer1(graph, [product_entry()], tables=tables)
    assert len(graph.contains) == 2
    assert "표기3" not in repr(graph.calls)
    aliases = relation_rows(graph, "ALIAS_OF")
    assert any(
        r["alias"] == "표기1" and r["standard_name"] == "성분가" for r in aliases
    )
    load_layer1(graph, [product_entry(("바뀐표준명",))], tables=tables)
    assert graph.contains == {
        ("synthetic brand", "https://example.test/product", 1, "바뀐표준명")
    }
    load_layer1(graph, [product_entry(())], tables=tables)
    assert graph.contains == set()
    assert "DELETE r" in CLEAN_CONTAINS and "NOT" in CLEAN_CONTAINS
    assert "r.order" in CLEAN_CONTAINS and "i.standard_name" in CLEAN_CONTAINS


@pytest.mark.parametrize("status,expected", [("unknown", 0), ("certified", 1)])
def test_certification_unknown_is_coverage_only(status, expected):
    graph = Graph()
    report = load_layer1(
        graph,
        [product_entry(cert_status=status)],
        tables=parse_layer1_tables(*documents()),
    )
    assert len(relation_rows(graph, "CERTIFIED_AS")) == expected
    assert report["certification"]["products"] == 1
    assert report["certification"][status] == 1
    assert report["certification"]["certified"] == expected


def test_product_prices_metadata_and_source_are_preserved():
    graph = Graph()
    load_layer1(graph, [product_entry()], tables=parse_layer1_tables(*documents()))
    product = next(
        p["rows"][0]["properties"]
        for q, p in graph.calls
        if "SET p += row.properties" in q
    )
    assert product["unit_list_price"] == 500
    assert product["price_basis"] == "list_price"
    assert product["name_en"] == "Synthetic serum"
    assert datetime.fromisoformat(product["price_collected_at"]) == NOW
    assert product["source_url"] == "https://example.test/product"
    contains = relation_rows(graph, "CONTAINS")
    assert contains[0]["source"] == product["source_url"]
    assert (
        contains[0]["is_key"] is None
    )  # source records do not establish key ingredients
    standard = next(
        r
        for q, p in graph.calls
        if "SET i += row.properties" in q
        for r in p["rows"]
        if r["standard_name"] == "성분가"
    )
    assert standard["properties"]["cas_no"] == "synthetic CAS"


def test_confirmed_repository_tables_validate_without_freezing_contents():
    root = Path(__file__).resolve().parents[1]
    tables = load_layer1_tables(
        root / "config/ingredient_efficacy.yaml", root / "config/efficacy_concerns.yaml"
    )
    assert all(
        link.source_ref.strip() and link.basis for link in tables.ingredient_links
    )
    assert all(
        row.source_ref.strip() and row.basis
        for row in tables.concerns
        if row.status == "confirmed"
    )


@pytest.mark.parametrize("missing", [True, False])
def test_unreadable_or_malformed_tables_fail_closed(tmp_path, missing):
    first, second = tmp_path / "ingredients.yaml", tmp_path / "concerns.yaml"
    _ingredients, concerns = documents()
    if not missing:
        first.write_text("links: [broken", encoding="utf-8")
    second.write_text(yaml.safe_dump(concerns), encoding="utf-8")
    with pytest.raises(GraphError, match="INGREDIENT_EFFICACY_INVALID"):
        load_layer1_tables(first, second)
