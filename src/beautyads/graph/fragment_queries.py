"""Fixed public-knowledge projection for the graph screen, never an agent tool."""

import math
import re
from datetime import date, datetime, time

from neo4j.time import Date, DateTime, Duration, Time

from beautyads.domain.tools import EVIDENCE_ID_PATTERN

_FRAGMENT_QUERY = """
    MATCH (c:Creative)
    WHERE c.source + ':' + c.source_id IN $ids
    OPTIONAL MATCH (c)-[:USES_HOOK]->(h:Hook)
    OPTIONAL MATCH (c)-[:HAS_ANGLE]->(a:Angle)
    OPTIONAL MATCH (c)-[:HAS_FORMAT]->(f:Format)
    OPTIONAL MATCH (c)-[:FEATURES]->(t:Talent)
    OPTIONAL MATCH (c)-[:HAS_CTA]->(cta:CtaType)
    OPTIONAL MATCH (c)-[:CLAIMS]->(e:Efficacy)
    OPTIONAL MATCH (c)-[:PROMOTES]->(p:Product)
    OPTIONAL MATCH (b:Brand)-[:OWNS]->(p)
    RETURN c.source + ':' + c.source_id AS creative_id,
           c {.source, .url, .brand, .published_at,
              .latest_view_count, .latest_like_count} AS creative,
           h.value AS hook_type, a.value AS angle, f.value AS format,
           t.value AS talent, cta.value AS cta_type, e.value AS claim,
           p {.brand, .source_url, .name_ko} AS product, b.name AS brand
    ORDER BY creative_id
    LIMIT $limit
"""
_PROPERTIES = {
    "Creative": (
        "source",
        "url",
        "brand",
        "published_at",
        "latest_view_count",
        "latest_like_count",
    ),
    "Hook": ("value",),
    "Angle": ("value",),
    "Format": ("value",),
    "Talent": ("value",),
    "CtaType": ("value",),
    "Efficacy": ("value",),
    "Product": ("brand", "source_url", "name_ko"),
    "Brand": ("name",),
}
_AXES = (
    ("hook_type", "Hook", "USES_HOOK"),
    ("angle", "Angle", "HAS_ANGLE"),
    ("format", "Format", "HAS_FORMAT"),
    ("talent", "Talent", "FEATURES"),
    ("cta_type", "CtaType", "HAS_CTA"),
    ("claim", "Efficacy", "CLAIMS"),
)


def fragment_query() -> str:
    return _FRAGMENT_QUERY


def fragment_parameters(ids) -> dict:
    if (
        not isinstance(ids, list)
        or not 1 <= len(ids) <= 30
        or any(
            not isinstance(eid, str) or not re.fullmatch(EVIDENCE_ID_PATTERN, eid)
            for eid in ids
        )
    ):
        raise ValueError("GRAPH_FRAGMENT_IDS_INVALID")
    return {"ids": list(dict.fromkeys(ids)), "limit": 500}


def _json_value(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if isinstance(value, (DateTime, Date, Time, Duration)):
        return value.iso_format()
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return {key: _json_value(item) for key, item in value.items()}
    raise ValueError("GRAPH_FRAGMENT_VALUE_INVALID")


def build_fragment(requested_ids, rows) -> dict:
    nodes, edges, found = {}, {}, set()
    requested = fragment_parameters(requested_ids)["ids"]

    def node(identifier, label, name, properties):
        props = {
            key: _json_value(properties.get(key))
            for key in _PROPERTIES[label]
            if key in properties
        }
        nodes[identifier] = {
            "id": identifier,
            "label": label,
            "name": _json_value(name),
            "props": props,
        }
        return identifier

    def edge(source, target, relationship):
        edges[source, target, relationship] = {
            "source": source,
            "target": target,
            "type": relationship,
        }

    for row in rows:
        eid = row.get("creative_id")
        if eid not in requested:
            continue
        found.add(eid)
        creative = node(f"creative:{eid}", "Creative", eid, row.get("creative") or {})
        for field, label, relationship in _AXES:
            value = row.get(field)
            if value is not None:
                value = _json_value(value)
                if not isinstance(value, str):
                    raise ValueError("GRAPH_FRAGMENT_VALUE_INVALID")
                target = node(f"{label}:{value}", label, value, {"value": value})
                edge(creative, target, relationship)
        product = row.get("product")
        if product is not None:
            brand, url = (
                _json_value(product.get("brand")),
                _json_value(product.get("source_url")),
            )
            if not isinstance(brand, str) or not isinstance(url, str):
                raise ValueError("GRAPH_FRAGMENT_VALUE_INVALID")
            target = node(
                f"Product:{brand}:{url}",
                "Product",
                product.get("name_ko") or url,
                product,
            )
            edge(creative, target, "PROMOTES")
            owner = row.get("brand")
            if owner is not None:
                owner = _json_value(owner)
                if not isinstance(owner, str):
                    raise ValueError("GRAPH_FRAGMENT_VALUE_INVALID")
                owner_id = node(f"Brand:{owner}", "Brand", owner, {"name": owner})
                edge(owner_id, target, "OWNS")
    return {
        "nodes": list(nodes.values()),
        "edges": list(edges.values()),
        "missing": [eid for eid in requested if eid not in found],
    }
