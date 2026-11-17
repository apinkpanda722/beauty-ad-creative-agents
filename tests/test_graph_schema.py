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


def test_layer1_constraints_are_additive_and_repeatable():
    from beautyads.graph.schema import LAYER1_CONSTRAINTS

    assert len(CONSTRAINTS) == 7
    assert all("IF NOT EXISTS" in query for query in LAYER1_CONSTRAINTS)
    assert not set(CONSTRAINTS).intersection(LAYER1_CONSTRAINTS)
    for label in (
        "Category",
        "Form",
        "Efficacy",
        "SkinConcern",
        "SkinType",
        "FunctionalCert",
    ):
        assert any(
            f":{label}) REQUIRE n.value IS UNIQUE" in q for q in LAYER1_CONSTRAINTS
        )
    assert any("(p.brand, p.source_url) IS UNIQUE" in q for q in LAYER1_CONSTRAINTS)
    assert any(
        ":Ingredient) REQUIRE n.standard_name IS UNIQUE" in q
        for q in LAYER1_CONSTRAINTS
    )
    assert any(
        ":IngredientAlias) REQUIRE (n.alias, n.standard_name) IS UNIQUE" in q
        for q in LAYER1_CONSTRAINTS
    )
    assert any(
        ":ClaimRule) REQUIRE n.rule_id IS UNIQUE" in q for q in LAYER1_CONSTRAINTS
    )
    driver = Driver()
    graph = GraphConnection(driver)
    for _ in range(2):
        for statement in LAYER1_CONSTRAINTS:
            graph.run(statement)
    assert driver.calls == [(statement, {}) for statement in LAYER1_CONSTRAINTS] * 2


def test_feedback_constraint_is_separate_composite_and_repeatable():
    from beautyads.graph.schema import FEEDBACK_CONSTRAINTS, LAYER1_CONSTRAINTS

    assert len(CONSTRAINTS) == 7 and len(LAYER1_CONSTRAINTS) == 10
    assert len(FEEDBACK_CONSTRAINTS) == 1
    assert not set(FEEDBACK_CONSTRAINTS).intersection(
        (*CONSTRAINTS, *LAYER1_CONSTRAINTS)
    )
    statement = FEEDBACK_CONSTRAINTS[0]
    assert "IF NOT EXISTS" in statement and "FOR (f:Feedback)" in statement
    assert "(f.tenant_id, f.feedback_id) IS UNIQUE" in statement
    driver = Driver()
    graph = GraphConnection(driver)
    for _ in range(2):
        graph.run(statement)
    assert driver.calls == [(statement, {})] * 2
