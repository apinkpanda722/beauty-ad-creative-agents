"""Fixed, bounded projections of public knowledge; never expose feedback."""

import re
import unicodedata

from beautyads.domain.tools import EVIDENCE_ID_PATTERN
from beautyads.graph.fragment_queries import _PROPERTIES, _json_value
from beautyads.graph.ontology_view import ONTOLOGY_RELATIONSHIPS

_LABELS = (
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
_CATALOG = ("Brand", "Product", "Efficacy")
_OVERVIEW_QUERY = """
    MATCH (n)
    WHERE (n:Brand OR n:Product OR n:Efficacy) AND NOT n:Feedback
    WITH n ORDER BY labels(n), n.name, n.brand, n.source_url, n.value
    LIMIT $limit
    WITH collect(n) AS nodes
    UNWIND nodes AS n
    OPTIONAL MATCH (n)-[r:OWNS]->(m)
    WHERE m IN nodes AND NOT m:Feedback
    RETURN labels(n) AS labels, properties(n) AS props,
           labels(m) AS neighbor_labels, properties(m) AS neighbor_props,
           collect({type: type(r), outgoing: true}) AS relations
    ORDER BY labels, props.name, props.brand, props.source_url, props.value,
             neighbor_props.name, neighbor_props.brand, neighbor_props.source_url
"""
_BRAND_QUERY = """
    MATCH (n:Brand)
    WHERE n.name = $name AND NOT n:Feedback
    OPTIONAL MATCH (n)-[r]-(m)
    WHERE NOT m:Feedback AND any(label IN labels(m) WHERE label IN
          ['Brand', 'Product', 'Creative', 'Hook', 'Angle', 'Format', 'Talent', 'CtaType', 'Efficacy'])
    WITH n, m, collect({type: type(r), outgoing: startNode(r) = n}) AS relations
    ORDER BY labels(m), m.name, m.brand, m.source_url, m.source, m.source_id, m.value
    LIMIT $limit
    RETURN labels(n) AS labels, properties(n) AS props,
           labels(m) AS neighbor_labels, properties(m) AS neighbor_props, relations
"""
_PRODUCT_QUERY = """
    MATCH (n:Product)
    WHERE n.brand = $brand AND n.source_url = $source_url AND NOT n:Feedback
    OPTIONAL MATCH (n)-[r]-(m)
    WHERE NOT m:Feedback AND any(label IN labels(m) WHERE label IN
          ['Brand', 'Product', 'Creative', 'Hook', 'Angle', 'Format', 'Talent', 'CtaType', 'Efficacy'])
    WITH n, m, collect({type: type(r), outgoing: startNode(r) = n}) AS relations
    ORDER BY labels(m), m.name, m.brand, m.source_url, m.source, m.source_id, m.value
    LIMIT $limit
    RETURN labels(n) AS labels, properties(n) AS props,
           labels(m) AS neighbor_labels, properties(m) AS neighbor_props, relations
"""
_CREATIVE_QUERY = """
    MATCH (n:Creative)
    WHERE n.source = $source AND n.source_id = $source_id AND NOT n:Feedback
    OPTIONAL MATCH (n)-[r]-(m)
    WHERE NOT m:Feedback AND any(label IN labels(m) WHERE label IN
          ['Brand', 'Product', 'Creative', 'Hook', 'Angle', 'Format', 'Talent', 'CtaType', 'Efficacy'])
    WITH n, m, collect({type: type(r), outgoing: startNode(r) = n}) AS relations
    ORDER BY labels(m), m.name, m.brand, m.source_url, m.source, m.source_id, m.value
    LIMIT $limit
    RETURN labels(n) AS labels, properties(n) AS props,
           labels(m) AS neighbor_labels, properties(m) AS neighbor_props, relations
"""
_HOOK_QUERY = """
    MATCH (n:Hook)
    WHERE n.value = $value AND NOT n:Feedback
    OPTIONAL MATCH (n)-[r]-(m)
    WHERE NOT m:Feedback AND any(label IN labels(m) WHERE label IN
          ['Brand', 'Product', 'Creative', 'Hook', 'Angle', 'Format', 'Talent', 'CtaType', 'Efficacy'])
    WITH n, m, collect({type: type(r), outgoing: startNode(r) = n}) AS relations
    ORDER BY labels(m), m.name, m.brand, m.source_url, m.source, m.source_id, m.value
    LIMIT $limit
    RETURN labels(n) AS labels, properties(n) AS props,
           labels(m) AS neighbor_labels, properties(m) AS neighbor_props, relations
"""
_ANGLE_QUERY = """
    MATCH (n:Angle)
    WHERE n.value = $value AND NOT n:Feedback
    OPTIONAL MATCH (n)-[r]-(m)
    WHERE NOT m:Feedback AND any(label IN labels(m) WHERE label IN
          ['Brand', 'Product', 'Creative', 'Hook', 'Angle', 'Format', 'Talent', 'CtaType', 'Efficacy'])
    WITH n, m, collect({type: type(r), outgoing: startNode(r) = n}) AS relations
    ORDER BY labels(m), m.name, m.brand, m.source_url, m.source, m.source_id, m.value
    LIMIT $limit
    RETURN labels(n) AS labels, properties(n) AS props,
           labels(m) AS neighbor_labels, properties(m) AS neighbor_props, relations
"""
_FORMAT_QUERY = """
    MATCH (n:Format)
    WHERE n.value = $value AND NOT n:Feedback
    OPTIONAL MATCH (n)-[r]-(m)
    WHERE NOT m:Feedback AND any(label IN labels(m) WHERE label IN
          ['Brand', 'Product', 'Creative', 'Hook', 'Angle', 'Format', 'Talent', 'CtaType', 'Efficacy'])
    WITH n, m, collect({type: type(r), outgoing: startNode(r) = n}) AS relations
    ORDER BY labels(m), m.name, m.brand, m.source_url, m.source, m.source_id, m.value
    LIMIT $limit
    RETURN labels(n) AS labels, properties(n) AS props,
           labels(m) AS neighbor_labels, properties(m) AS neighbor_props, relations
"""
_TALENT_QUERY = """
    MATCH (n:Talent)
    WHERE n.value = $value AND NOT n:Feedback
    OPTIONAL MATCH (n)-[r]-(m)
    WHERE NOT m:Feedback AND any(label IN labels(m) WHERE label IN
          ['Brand', 'Product', 'Creative', 'Hook', 'Angle', 'Format', 'Talent', 'CtaType', 'Efficacy'])
    WITH n, m, collect({type: type(r), outgoing: startNode(r) = n}) AS relations
    ORDER BY labels(m), m.name, m.brand, m.source_url, m.source, m.source_id, m.value
    LIMIT $limit
    RETURN labels(n) AS labels, properties(n) AS props,
           labels(m) AS neighbor_labels, properties(m) AS neighbor_props, relations
"""
_CTATYPE_QUERY = """
    MATCH (n:CtaType)
    WHERE n.value = $value AND NOT n:Feedback
    OPTIONAL MATCH (n)-[r]-(m)
    WHERE NOT m:Feedback AND any(label IN labels(m) WHERE label IN
          ['Brand', 'Product', 'Creative', 'Hook', 'Angle', 'Format', 'Talent', 'CtaType', 'Efficacy'])
    WITH n, m, collect({type: type(r), outgoing: startNode(r) = n}) AS relations
    ORDER BY labels(m), m.name, m.brand, m.source_url, m.source, m.source_id, m.value
    LIMIT $limit
    RETURN labels(n) AS labels, properties(n) AS props,
           labels(m) AS neighbor_labels, properties(m) AS neighbor_props, relations
"""
_EFFICACY_QUERY = """
    MATCH (n:Efficacy)
    WHERE n.value = $value AND NOT n:Feedback
    OPTIONAL MATCH (n)-[r]-(m)
    WHERE NOT m:Feedback AND any(label IN labels(m) WHERE label IN
          ['Brand', 'Product', 'Creative', 'Hook', 'Angle', 'Format', 'Talent', 'CtaType', 'Efficacy'])
    WITH n, m, collect({type: type(r), outgoing: startNode(r) = n}) AS relations
    ORDER BY labels(m), m.name, m.brand, m.source_url, m.source, m.source_id, m.value
    LIMIT $limit
    RETURN labels(n) AS labels, properties(n) AS props,
           labels(m) AS neighbor_labels, properties(m) AS neighbor_props, relations
"""
_QUERIES = {
    "Brand": _BRAND_QUERY,
    "Product": _PRODUCT_QUERY,
    "Creative": _CREATIVE_QUERY,
    "Hook": _HOOK_QUERY,
    "Angle": _ANGLE_QUERY,
    "Format": _FORMAT_QUERY,
    "Talent": _TALENT_QUERY,
    "CtaType": _CTATYPE_QUERY,
    "Efficacy": _EFFICACY_QUERY,
}


def overview_query() -> str:
    return _OVERVIEW_QUERY


def overview_parameters() -> dict:
    # One extra node makes truncation detectable without a count query.
    return {"limit": 61}


def _identity(identifier):
    if (
        not isinstance(identifier, str)
        or not 1 <= len(identifier) <= 300
        or any(unicodedata.category(char) == "Cc" for char in identifier)
    ):
        raise ValueError("GRAPH_ID_INVALID")
    prefix, _, value = identifier.partition(":")
    # The fragment wire format uses lowercase creative, unlike its Neo4j label.
    label = "Creative" if prefix == "creative" else prefix
    if label not in _LABELS or not value.strip():
        raise ValueError("GRAPH_ID_INVALID")
    if label == "Product":
        brand, _, url = value.partition(":")
        if not brand.strip() or not url.strip():
            raise ValueError("GRAPH_ID_INVALID")
        return label, {"brand": brand, "source_url": url}
    if label == "Creative":
        source, _, source_id = value.partition(":")
        if source not in ("youtube", "instagram", "tiktok") or not re.fullmatch(
            EVIDENCE_ID_PATTERN, value
        ):
            raise ValueError("GRAPH_ID_INVALID")
        return label, {"source": source, "source_id": source_id}
    return label, {"name" if label == "Brand" else "value": value}


def neighbors_parameters(identifier) -> dict:
    _, params = _identity(identifier)
    # At most 50 distinct neighbors plus the root; conversion retains 50 nodes.
    return {**params, "limit": 50}


def neighbors_query(identifier) -> str:
    label, _ = _identity(identifier)
    return _QUERIES[label]


def _node(labels, properties, allowed):
    if not labels or "Feedback" in labels:
        return None
    label = next((label for label in allowed if label in labels), None)
    if label is None:
        return None
    properties = properties or {}
    if label == "Creative":
        source, source_id = properties.get("source"), properties.get("source_id")
        if not isinstance(source, str) or not isinstance(source_id, str):
            raise ValueError("GRAPH_FRAGMENT_VALUE_INVALID")
        name = f"{source}:{source_id}"
        identifier = f"creative:{name}"
    elif label == "Product":
        brand, url = properties.get("brand"), properties.get("source_url")
        if not isinstance(brand, str) or not isinstance(url, str):
            raise ValueError("GRAPH_FRAGMENT_VALUE_INVALID")
        identifier = f"Product:{brand}:{url}"
        name = properties.get("name_ko") or url
    else:
        name = properties.get("name" if label == "Brand" else "value")
        if not isinstance(name, str):
            raise ValueError("GRAPH_FRAGMENT_VALUE_INVALID")
        identifier = f"{label}:{name}"
    return {
        "id": identifier,
        "label": label,
        "name": _json_value(name),
        "props": {
            key: _json_value(properties.get(key))
            for key in _PROPERTIES[label]
            if key in properties
        },
    }


def _build(rows, *, allowed, limit):
    nodes, edges = {}, {}
    relationships = [item["type"] for item in ONTOLOGY_RELATIONSHIPS]
    for row in rows:
        node = _node(row.get("labels"), row.get("props"), allowed)
        if node is None:
            continue
        nodes[node["id"]] = node
        neighbor = _node(row.get("neighbor_labels"), row.get("neighbor_props"), allowed)
        if neighbor is None:
            continue
        nodes[neighbor["id"]] = neighbor
        for relation in row.get("relations") or []:
            kind = relation.get("type")
            if kind not in relationships:
                continue
            source, target = node["id"], neighbor["id"]
            if relation.get("outgoing") is False:
                source, target = target, source
            edges[source, target, kind] = {
                "source": source,
                "target": target,
                "type": kind,
            }
    kept = list(nodes)[:limit]
    return {
        "nodes": [nodes[identifier] for identifier in kept],
        "edges": [
            edge
            for edge in edges.values()
            if edge["source"] in kept and edge["target"] in kept
        ],
        "truncated": len(nodes) > limit,
    }


def build_overview(rows) -> dict:
    return _build(rows, allowed=_CATALOG, limit=60)


def build_neighbors(rows) -> dict:
    return _build(rows, allowed=_LABELS, limit=50)
