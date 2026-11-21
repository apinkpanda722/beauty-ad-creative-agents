"""Bounded, public exploration projections using synthetic driver rows only."""

import re
from datetime import UTC, datetime

import pytest

from beautyads.graph import explore_queries as explore
from beautyads.graph.fragment_queries import build_fragment
from beautyads.graph.ontology_view import ONTOLOGY_RELATIONSHIPS

LABELS = (
    "Brand",
    "Product",
    "Creative",
    "Hook",
    "Angle",
    "Format",
    "Talent",
    "CtaType",
    "Efficacy",
)
IDS = (
    "Brand:합성",
    "Product:합성:https://example.invalid/a:b",
    "creative:youtube:synthetic",
    "Hook:synthetic",
    "Angle:synthetic",
    "Format:synthetic",
    "Talent:synthetic",
    "CtaType:synthetic",
    "Efficacy:synthetic",
)


def row(
    label,
    props,
    neighbor_label=None,
    neighbor_props=None,
    relationship="OWNS",
    outgoing=True,
):
    return {
        "labels": [label],
        "props": props,
        "neighbor_labels": [neighbor_label] if neighbor_label else [],
        "neighbor_props": neighbor_props,
        "relations": [{"type": relationship, "outgoing": outgoing}]
        if neighbor_label
        else [],
    }


def test_overview_is_bounded_and_reports_truncation_without_dangling_edges():
    rows = [
        row(
            "Brand",
            {"name": f"synthetic-{i}"},
            "Product",
            {"brand": "synthetic", "source_url": "https://example.invalid/p"},
        )
        for i in range(61)
    ]
    result = explore.build_overview(rows)
    assert sorted(result) == ["edges", "nodes", "truncated"]
    assert len(result["nodes"]) == 60
    assert result["truncated"] is True
    ids = [node["id"] for node in result["nodes"]]
    assert all(
        edge["source"] in ids and edge["target"] in ids for edge in result["edges"]
    )
    assert explore.overview_parameters() == {"limit": 61}
    assert explore.build_overview([]) == {"nodes": [], "edges": [], "truncated": False}
    assert (
        explore.build_overview([row("Brand", {"name": str(i)}) for i in range(60)])[
            "truncated"
        ]
        is False
    )


@pytest.mark.parametrize("builder", [explore.build_overview, explore.build_neighbors])
def test_feedback_and_non_public_labels_are_removed_even_on_multi_label_nodes(builder):
    rows = [
        row("Brand", {"name": "public"}, "Feedback", {"tenant_id": "PRIVATE"}, "ABOUT"),
        row(
            "Feedback", {"tenant_id": "PRIVATE"}, "Hook", {"value": "PRIVATE"}, "ABOUT"
        ),
    ]
    rows.append({**row("Brand", {"name": "PRIVATE"}), "labels": ["Brand", "Feedback"]})
    result = builder(rows)
    assert result == {
        "nodes": [
            {
                "id": "Brand:public",
                "label": "Brand",
                "name": "public",
                "props": {"name": "public"},
            }
        ],
        "edges": [],
        "truncated": False,
    }
    for query in [
        explore.overview_query(),
        *(explore.neighbors_query(identifier) for identifier in IDS),
    ]:
        assert "NOT n:Feedback" in query and "NOT m:Feedback" in query
        assert not re.search(r"\b(CREATE|MERGE|SET|DELETE)\b", query)


@pytest.mark.parametrize(
    "identifier",
    [
        None,
        1,
        "",
        "Brand:",
        "Brand",
        "Feedback:private",
        "Ingredient:x",
        "creative:youtube",
        "creative::id",
        "creative:unknown:id",
        "creative:youtube:id:tail",
        "creative:youtube:has space",
        "creative:youtube:" + "x" * 65,
        "Product:brand",
        "Product::url",
        "Product:brand:",
        "Brand:" + "x" * 295,
        "Brand:a\n",
        "Brand:a\x00",
        "Brand:a\x7f",
        "Brand:a\x85",
    ],
)
def test_invalid_ids_fail_before_query_selection(identifier):
    with pytest.raises(ValueError, match="^GRAPH_ID_INVALID$"):
        explore.neighbors_parameters(identifier)
    with pytest.raises(ValueError, match="^GRAPH_ID_INVALID$"):
        explore.neighbors_query(identifier)


def test_label_specific_queries_bind_each_identity_component():
    queries = [explore.neighbors_query(identifier) for identifier in IDS]
    assert len(dict.fromkeys(queries)) == len(LABELS)
    for label, identifier, query in zip(LABELS, IDS, queries, strict=True):
        assert f"(n:{label})" in query
        assert identifier not in query
        assert "LIMIT $limit" in query
    assert explore.neighbors_parameters(IDS[0]) == {"name": "합성", "limit": 50}
    assert explore.neighbors_parameters(IDS[1]) == {
        "brand": "합성",
        "source_url": "https://example.invalid/a:b",
        "limit": 50,
    }
    assert explore.neighbors_parameters(IDS[2]) == {
        "source": "youtube",
        "source_id": "synthetic",
        "limit": 50,
    }
    assert explore.neighbors_parameters(IDS[3]) == {"value": "synthetic", "limit": 50}
    assert explore.neighbors_parameters("Brand:" + "x" * 294)["name"] == "x" * 294
    assert explore.neighbors_query("Brand:other") == queries[0]
    assert (
        explore.neighbors_parameters("Brand:a' MATCH (x) RETURN x")["name"]
        == "a' MATCH (x) RETURN x"
    )


def test_neighbors_cap_includes_selected_node_and_preserves_direction():
    rows = [
        row(
            "Brand",
            {"name": "synthetic"},
            "Product",
            {"brand": "synthetic", "source_url": f"https://example.invalid/{i}"},
        )
        for i in range(50)
    ]
    result = explore.build_neighbors(rows + rows)
    assert len(result["nodes"]) == 50 and len(result["edges"]) == 49
    assert result["truncated"] is True
    assert explore.build_neighbors(rows[:49])["truncated"] is False
    reverse = explore.build_neighbors(
        [
            row(
                "Hook",
                {"value": "synthetic"},
                "Creative",
                {"source": "youtube", "source_id": "synthetic"},
                "USES_HOOK",
                False,
            )
        ]
    )
    assert reverse["edges"] == [
        {
            "source": "creative:youtube:synthetic",
            "target": "Hook:synthetic",
            "type": "USES_HOOK",
        }
    ]


def test_projection_exactly_matches_fragment_ids_fields_and_json_values():
    creative = {
        "source": "youtube",
        "source_id": "synthetic",
        "published_at": datetime(2026, 1, 2, tzinfo=UTC),
        "private": "PRIVATE",
    }
    product = {
        "brand": "synthetic",
        "source_url": "https://example.invalid/p:a",
        "name_ko": "합성 제품",
        "private": "PRIVATE",
    }
    fragment_row = {
        "creative_id": "youtube:synthetic",
        "creative": creative,
        "product": product,
        "brand": "synthetic",
        **{
            field: f"synthetic-{field}"
            for field in ("hook_type", "angle", "format", "talent", "cta_type", "claim")
        },
    }
    rows = [
        row("Creative", creative, "Product", product, "PROMOTES"),
        row("Brand", {"name": "synthetic"}, "Product", product),
    ]
    rows += [
        row("Creative", creative, label, {"value": fragment_row[field]}, relationship)
        for field, label, relationship in (
            ("hook_type", "Hook", "USES_HOOK"),
            ("angle", "Angle", "HAS_ANGLE"),
            ("format", "Format", "HAS_FORMAT"),
            ("talent", "Talent", "FEATURES"),
            ("cta_type", "CtaType", "HAS_CTA"),
            ("claim", "Efficacy", "CLAIMS"),
        )
    ]
    actual = explore.build_neighbors(rows)
    expected = build_fragment(["youtube:synthetic"], [fragment_row])
    assert sorted(actual["nodes"], key=lambda n: n["id"]) == sorted(
        expected["nodes"], key=lambda n: n["id"]
    )
    assert sorted(
        actual["edges"], key=lambda e: (e["source"], e["target"], e["type"])
    ) == sorted(expected["edges"], key=lambda e: (e["source"], e["target"], e["type"]))
    assert all(
        sorted(node) == ["id", "label", "name", "props"] for node in actual["nodes"]
    )


def test_all_cypher_constants_use_only_ontology_relationship_types():
    constants = [
        value
        for name, value in vars(explore).items()
        if name.endswith("_QUERY") and isinstance(value, str)
    ]
    assert len(constants) == 10
    found = re.findall(r"\[\w*:([A-Z][A-Z_]+)", " ".join(constants))
    assert found
    assert all(
        kind in [item["type"] for item in ONTOLOGY_RELATIONSHIPS] for kind in found
    )
