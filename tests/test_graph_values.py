"""JSON boundary normalization with actual, locally constructed Neo4j values."""

import json
from datetime import timedelta, timezone

import pytest
from neo4j.graph import Graph, Node, Path, Relationship
from neo4j.spatial import CartesianPoint, WGS84Point
from neo4j.time import Date, DateTime, Duration, Time

from beautyads.graph.values import to_json_safe


@pytest.mark.parametrize(
    "value",
    [
        DateTime(2026, 11, 18, 1, 2, 3, 456789123),
        Date(2026, 11, 18),
        Time(1, 2, 3, 456789123),
        Duration(months=2, days=3, seconds=4, nanoseconds=5),
    ],
)
def test_actual_temporal_values_are_iso_strings(value):
    output = to_json_safe(value)
    assert type(output) is str
    assert output == value.iso_format()
    assert json.loads(json.dumps(output)) == output


@pytest.mark.parametrize("offset", [-330, 0, 540])
def test_actual_temporal_timezone_and_nanoseconds_survive(offset):
    zone = timezone(timedelta(minutes=offset))
    for value in (
        DateTime(2026, 11, 18, 1, 2, 3, 456789123, tzinfo=zone),
        Time(1, 2, 3, 456789123, tzinfo=zone),
    ):
        output = to_json_safe(value)
        assert output == value.iso_format()
        assert output.endswith(value.iso_format()[-6:])
        assert "456789123" in output


@pytest.mark.parametrize("point", [CartesianPoint((1, 2)), WGS84Point((1, 2, 3))])
def test_actual_points_preserve_srid_and_coordinates(point):
    assert to_json_safe(point) == {
        "srid": point.srid,
        "coordinates": list(point),
    }
    json.dumps(to_json_safe(point), allow_nan=False)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_floats_are_markers(value):
    assert to_json_safe(value) == "<unserializable:float>"
    json.dumps(to_json_safe(value), allow_nan=False)


@pytest.mark.parametrize(
    "value", [b"synthetic-private", bytearray(b"synthetic-private")]
)
def test_binary_values_are_redacted(value):
    assert to_json_safe(value) == "<unserializable:bytes>"
    assert "synthetic-private" not in json.dumps(to_json_safe(value))


def test_unknown_objects_never_expose_or_call_repr_or_str():
    class Private:
        def __repr__(self):
            return "synthetic-private-value"

        def __str__(self):
            raise AssertionError("must not stringify unknown values")

    output = to_json_safe(Private())
    assert output == "<unserializable:Private>"
    assert "synthetic-private-value" not in output


def test_nested_containers_keys_and_deterministic_sets():
    value = {
        7: [{"temporal": Date(2026, 11, 18)}, (True, None)],
        "set": {"z", 2, ("a", 1)},
        "frozen": frozenset({"z", "a"}),
    }
    output = to_json_safe(value)
    assert output["7"] == [
        {"temporal": value[7][0]["temporal"].iso_format()},
        [True, None],
    ]
    expected = ["z", 2, ["a", 1]]
    assert output["set"] == sorted(expected, key=json.dumps)
    assert output["frozen"] == ["a", "z"]
    assert output == to_json_safe(value)
    assert output["set"] == to_json_safe(frozenset(value["set"]))
    json.dumps(output, allow_nan=False)


@pytest.mark.parametrize("kind", ["list", "dict", "mutual"])
def test_cycles_and_depth_over_twenty_are_bounded(kind):
    value = [] if kind != "dict" else {}
    if kind == "list":
        value.append(value)
    elif kind == "dict":
        value["cycle"] = value
    else:
        value.append({"cycle": value})
    assert "<unserializable:depth>" in json.dumps(to_json_safe(value))
    assert to_json_safe("safe", _depth=20) == "safe"
    assert to_json_safe("safe", _depth=21) == "<unserializable:depth>"


@pytest.mark.parametrize("value", [None, True, False, 0, -7, 1.25, "text", [], {}])
def test_safe_values_are_unchanged(value):
    assert to_json_safe(value) == value
    nested = {"row": [value, {"n": 2}]}
    assert to_json_safe(nested) == nested


def test_actual_nodes_relationships_and_paths_recurse_into_properties():
    graph = Graph()
    date = Date(2026, 11, 18)
    start = Node(graph, "node-a", 1, ["Z", "A"], {"date": date})
    end = Node(graph, "node-b", 2, ["B"], {"count": 2})
    relation = graph.relationship_type("LINKS")(graph, "rel-a", 3, {"date": date})
    assert isinstance(relation, Relationship)
    # Wire local SDK entities as the driver hydrator does; no driver or service.
    relation._start_node, relation._end_node = start, end
    path = Path(start, relation)
    a = {
        "element_id": "node-a",
        "labels": ["A", "Z"],
        "properties": {"date": date.iso_format()},
    }
    b = {
        "element_id": "node-b",
        "labels": ["B"],
        "properties": {"count": 2},
    }
    r = {
        "element_id": "rel-a",
        "type": "LINKS",
        "start_node_element_id": "node-a",
        "end_node_element_id": "node-b",
        "properties": {"date": date.iso_format()},
    }
    assert to_json_safe(start) == a
    assert to_json_safe(end) == b
    assert to_json_safe(relation) == r
    assert to_json_safe(path) == {"nodes": [a, b], "relationships": [r]}
    json.dumps(to_json_safe(path), allow_nan=False)
    assert start.get("date") is date


def test_broken_accessors_and_key_conversion_never_raise_or_expose_values():
    class BrokenDict(dict):
        def items(self):
            raise ValueError("synthetic-private-value")

    class BrokenKey:
        def __str__(self):
            raise ValueError("synthetic-private-value")

    class BrokenDate(Date):
        def iso_format(self):
            raise ValueError("synthetic-private-value")

    for value in (BrokenDict(), {BrokenKey(): 1}, BrokenDate(2026, 11, 18)):
        output = to_json_safe(value)
        assert output == f"<unserializable:{type(value).__name__}>"
        assert "synthetic-private-value" not in json.dumps(output)


def test_actual_relationship_keeps_empty_property_node_identifiers():
    graph = Graph()
    start = Node(graph, "empty-a", 1, [], {})
    end = Node(graph, "empty-b", 2, [], {})
    relation = graph.relationship_type("LINKS")(graph, "empty-rel", 3, {})
    relation._start_node, relation._end_node = start, end
    output = to_json_safe(relation)
    assert output["start_node_element_id"] == start.element_id
    assert output["end_node_element_id"] == end.element_id
    assert output["properties"] == {}


def test_actual_point_coordinates_are_recursively_normalized():
    point = CartesianPoint((float("nan"), float("inf")))
    output = to_json_safe(point)
    assert output == {
        "srid": point.srid,
        "coordinates": ["<unserializable:float>", "<unserializable:float>"],
    }
    json.dumps(output, allow_nan=False)
