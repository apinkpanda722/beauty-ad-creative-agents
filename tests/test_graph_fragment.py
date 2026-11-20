"""Public graph projections and ontology drift guards, entirely offline."""

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from neo4j.time import DateTime

from beautyads.graph.fragment_queries import (
    build_fragment,
    fragment_parameters,
    fragment_query,
)
from beautyads.graph.layer1 import PRODUCT_RELATIONS, SCOPE_LABELS
from beautyads.graph.load import AXES
from beautyads.graph.ontology_view import ONTOLOGY_LABELS, ONTOLOGY_RELATIONSHIPS
from beautyads.graph.schema import CONSTRAINTS, FEEDBACK_CONSTRAINTS, LAYER1_CONSTRAINTS

EID = "youtube:synthetic"


@pytest.mark.parametrize(
    "ids",
    [
        [],
        EID,
        None,
        [None],
        ["invalid"],
        ["youtube:x\n"],
        [f"youtube:{i}" for i in range(31)],
    ],
)
def test_fragment_rejects_invalid_ids(ids):
    with pytest.raises(ValueError, match="^GRAPH_FRAGMENT_IDS_INVALID$"):
        fragment_parameters(ids)


def test_fragment_query_is_fixed_public_and_bounded():
    assert fragment_parameters([EID, "instagram:b", EID]) == {
        "ids": [EID, "instagram:b"],
        "limit": 500,
    }
    query = fragment_query()
    assert query == fragment_query()
    assert set(re.findall(r"\$(\w+)", query)) == {"ids", "limit"}
    assert not re.search(
        r"Feedback|tenant|ClaimRule|\b(CREATE|MERGE|SET|DELETE)\b", query, re.IGNORECASE
    )
    assert "c.source + ':' + c.source_id IN $ids" in query
    assert "OPTIONAL MATCH" in query and "LIMIT $limit" in query
    for relationship in [r[2] for r in AXES] + ["CLAIMS", "PROMOTES", "OWNS"]:
        assert f":{relationship}" in query


def test_fragment_serializes_real_driver_dates_and_preserves_unlabelled_creatives():
    stamp = DateTime.from_native(datetime(2026, 1, 2, tzinfo=UTC))
    row = {
        "creative_id": EID,
        "creative": {"source": "youtube", "published_at": stamp, "title": "PRIVATE"},
        "hook_type": "synthetic-axis",
        "angle": "synthetic-angle",
        "format": "synthetic-format",
        "talent": "synthetic-talent",
        "cta_type": "synthetic-cta",
        "claim": "synthetic-efficacy",
        "product": {
            "brand": "synthetic",
            "source_url": "https://example.invalid/p",
            "name_ko": "synthetic product",
            "private": "PRIVATE",
        },
        "brand": "synthetic",
    }
    bare = {"creative_id": "instagram:bare", "creative": {"source": "instagram"}}
    result = build_fragment([EID, "instagram:bare", "tiktok:missing"], [row, row, bare])
    assert set(result) == {"nodes", "edges", "missing"}
    assert result["missing"] == ["tiktok:missing"]
    assert "PRIVATE" not in json.dumps(result, allow_nan=False)
    nodes = {node["id"]: node for node in result["nodes"]}
    assert len(nodes) == len(result["nodes"]) == 10
    assert nodes[f"creative:{EID}"]["props"]["published_at"] == stamp.iso_format()
    assert nodes["creative:instagram:bare"]["label"] == "Creative"
    assert all(set(node) == {"id", "label", "name", "props"} for node in nodes.values())
    edges = {(edge["source"], edge["target"], edge["type"]) for edge in result["edges"]}
    assert len(edges) == len(result["edges"]) == 8
    assert all(source in nodes and target in nodes for source, target, _ in edges)
    assert (
        "Brand:synthetic",
        "Product:synthetic:https://example.invalid/p",
        "OWNS",
    ) in edges
    assert build_fragment([EID], []) == {"nodes": [], "edges": [], "missing": [EID]}


@pytest.mark.parametrize("value", [object(), float("nan"), float("inf")])
def test_fragment_unknown_or_non_json_values_fail_closed(value):
    with pytest.raises(ValueError, match="^GRAPH_FRAGMENT_VALUE_INVALID$"):
        build_fragment(
            [EID], [{"creative_id": EID, "creative": {"published_at": value}}]
        )


def test_ontology_covers_constraints_and_all_relationship_identifiers():
    labels = {item["label"] for item in ONTOLOGY_LABELS}
    relationships = {item["type"] for item in ONTOLOGY_RELATIONSHIPS}
    assert len(labels) == len(ONTOLOGY_LABELS) == 18
    constraints = (*CONSTRAINTS, *LAYER1_CONSTRAINTS, *FEEDBACK_CONSTRAINTS)
    found_labels = set(re.findall(r"\(\w+:(\w+)\)", " ".join(constraints)))
    assert found_labels and found_labels <= labels
    found_relationships = set()
    files = list(Path("src/beautyads/graph").glob("*.py"))
    assert files
    for path in files:
        found_relationships.update(
            re.findall(r"\[\w*:([A-Z][A-Z_]+)", path.read_text())
        )
    assert found_relationships and found_relationships <= relationships
    assert AXES and PRODUCT_RELATIONS and SCOPE_LABELS
    assert {axis[1] for axis in AXES} <= labels
    assert {axis[2] for axis in AXES} <= relationships
    assert {rel for rel, _ in PRODUCT_RELATIONS} <= relationships
    measured = {
        "CONTAINS",
        "CLAIMS",
        "ALIAS_OF",
        "USES_HOOK",
        "HAS_ANGLE",
        "HAS_FORMAT",
        "FEATURES",
        "HAS_CTA",
        "MENTIONS",
        "PROMOTES",
        "OWNS",
        "IN_CATEGORY",
        "HAS_EFFICACY",
        "CERTIFIED_AS",
        "HAS_FORM",
        "APPLIES_TO",
        "ADDRESSES",
        "SUITS",
    }
    assert relationships == measured | {"ABOUT"}
    triples = {(r["type"], r["from"], r["to"]) for r in ONTOLOGY_RELATIONSHIPS}
    assert len(triples) == len(ONTOLOGY_RELATIONSHIPS) == 22
    assert {(rel, "Creative", label) for _, label, rel, _ in AXES} <= triples
    assert {(rel, "Product", label) for rel, label in PRODUCT_RELATIONS} <= triples
    assert {
        ("APPLIES_TO", "ClaimRule", label) for label in SCOPE_LABELS.values()
    } <= triples
    assert {
        ("ABOUT", "Feedback", "Hook"),
        ("ABOUT", "Feedback", "Efficacy"),
        ("OWNS", "Brand", "Product"),
        ("CONTAINS", "Product", "Ingredient"),
        ("ALIAS_OF", "IngredientAlias", "Ingredient"),
        ("HAS_EFFICACY", "Ingredient", "Efficacy"),
        ("ADDRESSES", "Efficacy", "SkinConcern"),
        ("PROMOTES", "Creative", "Product"),
        ("CLAIMS", "Creative", "Efficacy"),
        ("MENTIONS", "Creative", "IngredientAlias"),
    } <= triples
    assert all(
        set(item) == {"label", "layer", "name_ko"}
        and item["layer"] in {1, 2, 3}
        and item["name_ko"]
        for item in ONTOLOGY_LABELS
    )
    assert all(
        set(item) == {"type", "from", "to", "layer"}
        and item["from"] in labels
        and item["to"] in labels
        and item["layer"] in {1, 2, 3}
        for item in ONTOLOGY_RELATIONSHIPS
    )
    assert (
        next(item for item in ONTOLOGY_LABELS if item["label"] == "Feedback")["layer"]
        == 3
    )
