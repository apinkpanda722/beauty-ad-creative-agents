from types import SimpleNamespace

from beautyads.graph.connection import GraphConnection
from beautyads.graph.schema import CONSTRAINTS, apply_schema


class Driver:
    def __init__(self):
        self.calls = []

    def execute_query(self, query, *, parameters_, **kwargs):
        self.calls.append((query, parameters_))
        return SimpleNamespace(
            records=[],
            summary=SimpleNamespace(
                counters=SimpleNamespace(nodes_created=0, relationships_created=0)
            ),
        )


def test_constraints_are_repeatable_and_composite():
    driver = Driver()
    graph = GraphConnection(driver)
    apply_schema(graph)
    first = driver.calls.copy()
    apply_schema(graph)
    assert driver.calls == first * 2
    assert len(CONSTRAINTS) == 7
    assert all("IF NOT EXISTS" in query for query, _ in first)
    assert all(params == {} for _, params in first)
    assert any("(c.source, c.source_id) IS UNIQUE" in query for query, _ in first)
    for label in ("Hook", "Angle", "Format", "Talent", "CtaType"):
        assert any(f":{label}) REQUIRE n.value IS UNIQUE" in q for q, _ in first)
    assert any(":Brand) REQUIRE n.name IS UNIQUE" in q for q, _ in first)
