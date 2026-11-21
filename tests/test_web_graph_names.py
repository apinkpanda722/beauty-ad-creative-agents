"""Keep the web's presentation names aligned with closed graph metadata."""

import re
from pathlib import Path

from beautyads.graph.fragment_queries import _PROPERTIES
from beautyads.graph.ontology_view import ONTOLOGY_LABELS, ONTOLOGY_RELATIONSHIPS

GRAPH_SOURCE = Path(__file__).resolve().parents[1] / "web/lib/graph.ts"


def names_for(constant):
    text = GRAPH_SOURCE.read_text()
    block = re.search(rf"export const {constant}[^=]*=\s*\{{(.*?)\}}", text, re.DOTALL)
    assert block is not None, f"Missing {constant}"
    return dict(re.findall(r'(\w+):\s*"([^"]+)"', block.group(1)))


def test_node_names_match_all_ontology_labels():
    names = names_for("NODE_LABEL_NAMES")
    for label in ONTOLOGY_LABELS:
        assert names.get(label["label"]) == label["name_ko"]


def test_relationship_names_cover_all_ontology_types():
    names = names_for("RELATIONSHIP_NAMES")
    for relationship in ONTOLOGY_RELATIONSHIPS:
        assert relationship["type"] in names


def test_property_names_cover_all_projected_properties():
    names = names_for("PROPERTY_NAMES")
    for properties in _PROPERTIES.values():
        for key in properties:
            assert key in names
