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


# Kept separate so the step-zero schema contract remains unchanged. Layer-one
# synchronization installs these in addition to the public skeleton constraints.
LAYER1_CONSTRAINTS = (
    (
        "CREATE CONSTRAINT product_identity IF NOT EXISTS FOR (p:Product) "
        "REQUIRE (p.brand, p.source_url) IS UNIQUE"
    ),
    (
        "CREATE CONSTRAINT ingredient_alias_identity IF NOT EXISTS FOR (n:IngredientAlias) "
        "REQUIRE (n.alias, n.standard_name) IS UNIQUE"
    ),
    *(
        f"CREATE CONSTRAINT {name} IF NOT EXISTS FOR (n:{label}) "
        f"REQUIRE n.{prop} IS UNIQUE"
        for name, label, prop in (
            ("category_value", "Category", "value"),
            ("form_value", "Form", "value"),
            ("ingredient_standard_name", "Ingredient", "standard_name"),
            ("efficacy_value", "Efficacy", "value"),
            ("skin_concern_value", "SkinConcern", "value"),
            ("skin_type_value", "SkinType", "value"),
            ("functional_cert_value", "FunctionalCert", "value"),
            ("claim_rule_id", "ClaimRule", "rule_id"),
        )
    ),
)


def apply_schema(graph: GraphConnection) -> None:
    for statement in CONSTRAINTS:
        graph.run(statement)
