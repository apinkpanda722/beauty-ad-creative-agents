"""Pure, bounded conversion of driver values at the agent tool boundary."""

import json
import math

from neo4j.graph import Node, Path, Relationship
from neo4j.spatial import Point
from neo4j.time import Date, DateTime, Duration, Time


def to_json_safe(value, *, _depth=0):
    """Return JSON data or a type-only marker, never an external value's repr."""
    try:
        if _depth > 20:
            return "<unserializable:depth>"
        if value is None or isinstance(value, (bool, int, str)):
            return value
        if isinstance(value, float):
            return value if math.isfinite(value) else "<unserializable:float>"
        if isinstance(value, (DateTime, Date, Time, Duration)):
            return value.iso_format()
        if isinstance(value, (bytes, bytearray)):
            return "<unserializable:bytes>"
        if isinstance(value, Point):
            return to_json_safe(
                {"srid": value.srid, "coordinates": list(value)}, _depth=_depth + 1
            )
        if isinstance(value, Node):
            return to_json_safe(
                {
                    "element_id": value.element_id,
                    "labels": sorted(value.labels),
                    "properties": dict(value.items()),
                },
                _depth=_depth + 1,
            )
        if isinstance(value, Relationship):
            return to_json_safe(
                {
                    "element_id": value.element_id,
                    "type": value.type,
                    "start_node_element_id": (
                        value.start_node.element_id
                        if value.start_node is not None
                        else None
                    ),
                    "end_node_element_id": (
                        value.end_node.element_id
                        if value.end_node is not None
                        else None
                    ),
                    "properties": dict(value.items()),
                },
                _depth=_depth + 1,
            )
        if isinstance(value, Path):
            return to_json_safe(
                {
                    "nodes": list(value.nodes),
                    "relationships": list(value.relationships),
                },
                _depth=_depth + 1,
            )
        if isinstance(value, dict):
            return {
                key if isinstance(key, str) else str(key): to_json_safe(
                    item, _depth=_depth + 1
                )
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple, set, frozenset)):
            items = [to_json_safe(item, _depth=_depth + 1) for item in value]
            return (
                sorted(items, key=json.dumps)
                if isinstance(value, (set, frozenset))
                else items
            )
    except Exception:  # noqa: BLE001 -- even broken driver accessors must not escape
        return f"<unserializable:{type.__getattribute__(type(value), '__name__')}>"
    return f"<unserializable:{type.__getattribute__(type(value), '__name__')}>"
