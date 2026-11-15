"""Idempotent constraints for the shared two-layer skeleton."""

from beautyads.graph.connection import GraphConnection

CONSTRAINTS = (
    (
        "CREATE CONSTRAINT creative_identity IF NOT EXISTS FOR (c:Creative) "
        "REQUIRE (c.source, c.source_id) IS UNIQUE"
    ),
    *(
        f"CREATE CONSTRAINT {name} IF NOT EXISTS FOR (n:{label}) "
        f"REQUIRE n.{prop} IS UNIQUE"
        for name, label, prop in (
            ("hook_value", "Hook", "value"),
            ("angle_value", "Angle", "value"),
            ("format_value", "Format", "value"),
            ("talent_value", "Talent", "value"),
            ("cta_type_value", "CtaType", "value"),
            ("brand_name", "Brand", "name"),
        )
    ),
)


def apply_schema(graph: GraphConnection) -> None:
    for statement in CONSTRAINTS:
        graph.run(statement)
