"""Parameterized, repeatable MERGE of product facts and attributed evidence."""

import json
from collections.abc import Sequence
from pathlib import Path

import yaml
from pydantic import ValidationError

from beautyads.domain.claims import ClaimRule
from beautyads.domain.labels import Category, Claim
from beautyads.domain.layer1 import (
    EfficacyConcernTable,
    IngredientEfficacyTable,
    Layer1Tables,
    SyncProduct,
)
from beautyads.domain.skin import SkinConcern, SkinType
from beautyads.graph.connection import GraphConnection, GraphError

MERGE_PRODUCT = """
    UNWIND $rows AS row
    MERGE (p:Product {brand: row.brand, source_url: row.source_url})
    SET p += row.properties
    MERGE (b:Brand {name: row.brand})
    MERGE (b)-[r:OWNS]->(p)
"""
MERGE_INGREDIENT = """
    UNWIND $rows AS row
    MERGE (i:Ingredient {standard_name: row.standard_name})
    SET i += row.properties
"""
MERGE_ALIAS = """
    UNWIND $rows AS row
    MERGE (i:Ingredient {standard_name: row.standard_name})
    MERGE (a:IngredientAlias {alias: row.alias, standard_name: row.standard_name})
    MERGE (a)-[r:ALIAS_OF]->(i)
"""
MERGE_CONTAINS = """
    UNWIND $rows AS row
    MERGE (p:Product {brand: row.brand, source_url: row.source_url})
    MERGE (i:Ingredient {standard_name: row.standard_name})
    MERGE (p)-[r:CONTAINS {order: row.order}]->(i)
    SET r.source = row.source, r.is_key = row.is_key
"""
CLEAN_CONTAINS = """
    UNWIND $rows AS row
    MERGE (p:Product {brand: row.brand, source_url: row.source_url})
    WITH p, row
    MATCH (p)-[r:CONTAINS]->(i:Ingredient)
    WHERE NOT any(expected IN row.ingredients
        WHERE expected.order = r.order AND expected.standard_name = i.standard_name)
    DELETE r
"""
MERGE_EFFICACY = """
    UNWIND $rows AS row
    MERGE (i:Ingredient {standard_name: row.standard_name})
    SET i.name_en = row.inci
    MERGE (e:Efficacy {value: row.efficacy})
    MERGE (i)-[r:HAS_EFFICACY]->(e)
    SET r.basis = row.basis, r.source_ref = row.source_ref,
        r.conditional = row.conditional
"""
MERGE_ADDRESSES = """
    UNWIND $rows AS row
    MERGE (e:Efficacy {value: row.efficacy})
    MERGE (s:SkinConcern {value: row.concern})
    MERGE (e)-[r:ADDRESSES]->(s)
    SET r.basis = row.basis, r.source_ref = row.source_ref
"""
MERGE_RULE = """
    UNWIND $rows AS row
    MERGE (n:ClaimRule {rule_id: row.rule_id})
    SET n += row.properties
"""
# Only fixed identifiers are interpolated into Cypher. Values are parameters.
PRODUCT_RELATIONS = (
    ("IN_CATEGORY", "Category"),
    ("HAS_FORM", "Form"),
    ("SUITS", "SkinType"),
    ("CERTIFIED_AS", "FunctionalCert"),
)
SCOPE_LABELS = {
    "efficacy": "Efficacy",
    "skin_concern": "SkinConcern",
    "category": "Category",
}


def parse_layer1_tables(ingredients: dict, concerns: dict) -> Layer1Tables:
    """Validate both entire tables before any graph writes can take place."""
    try:
        first = IngredientEfficacyTable.model_validate(ingredients)
    except ValidationError:
        raise GraphError("INGREDIENT_EFFICACY_INVALID") from None
    try:
        second = EfficacyConcernTable.model_validate(concerns)
    except ValidationError:
        raise GraphError("EFFICACY_CONCERN_INVALID") from None
    return Layer1Tables(
        first.links, second.rows, len(first.unmatched), len(first.not_linked_for_now)
    )


def load_layer1_tables(ingredient_path: Path, concern_path: Path) -> Layer1Tables:
    def read(path, code):
        try:
            return yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError):
            raise GraphError(code) from None

    return parse_layer1_tables(
        read(ingredient_path, "INGREDIENT_EFFICACY_INVALID"),
        read(concern_path, "EFFICACY_CONCERN_INVALID"),
    )


def _prepare_product(entry: SyncProduct):
    product = entry.product
    if any(item.product != product.key for item in [*entry.ingredients, *entry.certs]):
        raise GraphError("LAYER1_PRODUCT_INVALID")
    properties = product.model_dump(mode="json")
    # Neo4j accepts primitive numeric values, not Decimal or decimal strings.
    for field in ("volume", "list_price", "sale_price"):
        value = getattr(product, field)
        properties[field] = float(value) if value is not None else None
    price = product.list_price
    if product.price_basis == "sale_price_fallback":
        price = product.sale_price
    properties["unit_list_price"] = (
        float(price / product.volume)
        if price is not None and product.volume is not None
        else None
    )
    key = {"brand": product.brand, "source_url": product.source_url}
    resolved = [
        i
        for i in entry.ingredients
        if i.status == "resolved" and i.standard_name and i.standard_name.strip()
    ]
    contains = [
        {
            **key,
            "standard_name": i.standard_name,
            "order": i.order,
            "source": product.source_url,
            "is_key": None,
        }
        for i in sorted(resolved, key=lambda i: i.order)
    ]
    return {**key, "properties": properties}, contains


def load_layer1(
    graph: GraphConnection,
    entries: Sequence[SyncProduct],
    *,
    tables: Layer1Tables,
    rules: Sequence[ClaimRule] = (),
) -> dict:
    """Load complete product sets; counters report writes, never source changes.

    Key ingredient status is unknown in the PostgreSQL schema, so is_key stays
    null rather than being inferred from ingredient order or model output.
    """
    # ClaimScope also serves creative checks, where Category.other is valid.
    # The product ontology deliberately contains only the three product categories.
    if any(
        scope.kind == "category"
        and scope.value == Category.other
        and scope.status in {"advisor_approved", "confirmed"}
        for rule in rules
        for scope in rule.applies_to
    ):
        raise GraphError("CLAIM_RULES_INVALID")
    prepared = [_prepare_product(entry) for entry in entries]
    report = {
        "nodes_created": 0,
        "relationships_created": 0,
        "unmatched": tables.unmatched,
        "not_linked_for_now": tables.not_linked_for_now,
        "draft_not_loaded": sum(r.status == "draft" for r in tables.concerns)
        + sum(s.status == "draft" for r in rules for s in r.applies_to),
        "certification": {
            "products": len(entries),
            "certified": 0,
            "unknown": 0,
            "certified_products": 0,
            "unknown_products": 0,
        },
    }

    def execute(query, rows):
        if rows:
            result = graph.run(query, {"rows": rows})
            report["nodes_created"] += result.nodes_created
            report["relationships_created"] += result.relationships_created

    for label, values in (
        ("Category", [c for c in Category if c is not Category.other]),
        ("Efficacy", Claim),
        ("SkinConcern", SkinConcern),
        ("SkinType", SkinType),
    ):
        execute(
            f"UNWIND $rows AS row MERGE (n:{label} {{value: row.value}})",
            [{"value": v.value} for v in values],
        )

    execute(MERGE_PRODUCT, [p for p, _ in prepared])
    standards = {}
    aliases = set()
    for entry, (_, contains) in zip(entries, prepared, strict=True):
        known = {s.name_ko: s for s in entry.standards}
        for row in contains:
            name = row["standard_name"]
            standard = known.get(name)
            # Do not clear previously known metadata when the cache is absent.
            properties = {}
            if standard is not None:
                properties = {"name_en": standard.name_en, "cas_no": standard.cas_no}
            standards[name] = {"standard_name": name, "properties": properties}
        for ingredient in entry.ingredients:
            if (
                ingredient.status == "resolved"
                and ingredient.standard_name in standards
            ):
                aliases.add((ingredient.raw_name, ingredient.standard_name))
    execute(MERGE_INGREDIENT, [standards[n] for n in sorted(standards)])
    execute(MERGE_ALIAS, [{"alias": a, "standard_name": n} for a, n in sorted(aliases)])
    execute(MERGE_CONTAINS, [row for _, contains in prepared for row in contains])
    # Cleanup is executed even for a product whose current resolved set is empty.
    execute(
        CLEAN_CONTAINS,
        [
            {
                "brand": p["brand"],
                "source_url": p["source_url"],
                "ingredients": [
                    {"order": r["order"], "standard_name": r["standard_name"]}
                    for r in contains
                ],
            }
            for p, contains in prepared
        ],
    )

    for relationship, label in PRODUCT_RELATIONS:
        rows, expected = [], []
        for entry in entries:
            p = entry.product
            key = {"brand": p.brand, "source_url": p.source_url}
            if relationship == "IN_CATEGORY":
                values = [{"value": p.category.value}]
            elif relationship == "HAS_FORM":
                values = [{"value": p.form}] if p.form else []
            elif relationship == "SUITS":
                values = [
                    {"value": s.value, "source": p.source_url} for s in p.skin_types
                ]
            else:
                values = [
                    {
                        "value": c.kind.value,
                        "source": c.evidence_api,
                        "evidence_item_name": c.evidence_item_name,
                    }
                    for c in entry.certs
                    if c.status == "certified"
                ]
                for cert in entry.certs:
                    report["certification"][cert.status.value] += 1
                report["certification"][
                    "certified_products" if values else "unknown_products"
                ] += 1
            rows.extend({**key, **value} for value in values)
            expected.append({**key, "values": [v["value"] for v in values]})
        execute(
            f"""UNWIND $rows AS row
                MERGE (p:Product {{brand: row.brand, source_url: row.source_url}})
                MERGE (n:{label} {{value: row.value}})
                MERGE (p)-[r:{relationship}]->(n)"""
            + (
                " SET r.source = row.source"
                if relationship in {"SUITS", "CERTIFIED_AS"}
                else ""
            )
            + (
                ", r.evidence_item_name = row.evidence_item_name"
                if relationship == "CERTIFIED_AS"
                else ""
            ),
            rows,
        )
        execute(
            f"""UNWIND $rows AS row
                MERGE (p:Product {{brand: row.brand, source_url: row.source_url}})
                WITH p, row MATCH (p)-[r:{relationship}]->(n:{label})
                WHERE NOT n.value IN row.values DELETE r""",
            expected,
        )

    execute(
        MERGE_EFFICACY,
        [
            {
                "standard_name": ingredient.standard_name,
                "inci": ingredient.inci,
                "efficacy": efficacy.value,
                "basis": link.basis,
                "source_ref": link.source_ref,
                "conditional": link.conditional,
            }
            for link in tables.ingredient_links
            for ingredient in link.ingredients
            for efficacy in link.efficacy
        ],
    )
    execute(
        MERGE_ADDRESSES,
        [
            r.model_dump(mode="json", exclude={"status"})
            for r in tables.concerns
            if r.status == "confirmed"
        ],
    )
    rule_rows = []
    for rule in rules:
        properties = rule.model_dump(mode="json", exclude={"applies_to"})
        # Retain the full validated rule as JSON alongside queryable flat fields;
        # Neo4j properties cannot contain maps (nested scopes).
        properties["rule_json"] = json.dumps(
            rule.model_dump(mode="json"), ensure_ascii=False, sort_keys=True
        )
        rule_rows.append({"rule_id": rule.rule_id, "properties": properties})
    execute(MERGE_RULE, rule_rows)
    for kind, label in SCOPE_LABELS.items():
        execute(
            f"""UNWIND $rows AS row
                MERGE (n:ClaimRule {{rule_id: row.rule_id}})
                MERGE (t:{label} {{value: row.value}})
                MERGE (n)-[r:APPLIES_TO]->(t)""",
            [
                {"rule_id": r.rule_id, "value": s.value}
                for r in rules
                for s in r.applies_to
                if s.kind == kind and s.status in {"advisor_approved", "confirmed"}
            ],
        )
    return report
