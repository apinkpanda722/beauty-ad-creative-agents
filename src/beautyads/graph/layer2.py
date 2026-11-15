"""Parameter-only, per-creative transactional replacement of layer-two links."""

import json
from collections.abc import Sequence

from beautyads.domain.links import (
    DEFAULT_SAMPLE_PAIRS,
    DEFAULT_SEED,
    LinkCreative,
    plan_links,
    summarize_links,
)
from beautyads.domain.products import Product
from beautyads.graph.connection import GraphConnection

# One execute_query is one transaction. Never split PROMOTES deletion from its
# replacement: a failure must roll back the old assignment together with the new.
REPLACE_LINKS = """
    UNWIND $rows AS row
    MERGE (c:Creative {source: row.source, source_id: row.source_id})
    SET c.brand = row.brand
    CALL {
        WITH c
        MATCH (c)-[old:PROMOTES]->(:Product)
        DELETE old
        RETURN count(*) AS removed_promotes
    }
    FOREACH (target IN row.promotes |
        MERGE (p:Product {brand: target.brand, source_url: target.source_url})
        MERGE (c)-[r:PROMOTES]->(p)
        SET r.basis = target.basis, r.confidence = target.confidence,
            r.matched_text = target.matched_text,
            r.multi_product = target.multi_product
    )
    CALL {
        WITH c, row
        MATCH (c)-[stale:CLAIMS]->(e:Efficacy)
        WHERE NOT e.value IN row.claims
        DELETE stale
        RETURN count(*) AS removed_claims
    }
    FOREACH (value IN row.claims |
        MERGE (e:Efficacy {value: value})
        MERGE (c)-[:CLAIMS]->(e)
    )
    CALL {
        WITH c, row
        MATCH (c)-[stale:MENTIONS]->(a:IngredientAlias)
        WHERE NOT any(mention IN row.mentions
            WHERE mention.raw_name = a.alias
                AND mention.standard_name = a.standard_name)
        DELETE stale
        RETURN count(*) AS removed_mentions
    }
    FOREACH (mention IN row.mentions |
        MERGE (i:Ingredient {standard_name: mention.standard_name})
        MERGE (a:IngredientAlias {alias: mention.raw_name,
                                  standard_name: mention.standard_name})
        MERGE (a)-[:ALIAS_OF]->(i)
        MERGE (c)-[r:MENTIONS]->(a)
        SET r.raw_name = mention.raw_name
    )
"""

LINK_STATE = """
    UNWIND $rows AS row
    MATCH (c:Creative {source: row.source, source_id: row.source_id})
    OPTIONAL MATCH (c)-[r:PROMOTES|CLAIMS|MENTIONS]->(target)
    RETURN c.source AS source, c.source_id AS source_id, type(r) AS relationship,
        properties(r) AS properties, labels(target) AS target_labels,
        properties(target) AS target_properties
"""


def read_link_state(
    graph: GraphConnection, entries: Sequence[LinkCreative]
) -> list[str]:
    """Compare relationship sets, since PROMOTES is deliberately replaced.

    Unlike step-zero MERGE-only replay, replacement recreates relationships, so
    relationships_created cannot be an idempotence assertion here.
    """
    if not entries:
        return []
    rows = [
        {"source": e.creative.key.source.value, "source_id": e.creative.key.source_id}
        for e in entries
    ]
    result = graph.run(LINK_STATE, {"rows": rows})
    return sorted(
        json.dumps(record, sort_keys=True, ensure_ascii=False, default=str)
        for record in result.records
    )


def load_layer2(
    graph: GraphConnection,
    entries: Sequence[LinkCreative],
    *,
    products: Sequence[Product],
    dev_brands: Sequence[str],
    test_brands: Sequence[str],
    sample_pairs: int = DEFAULT_SAMPLE_PAIRS,
    seed: int = DEFAULT_SEED,
    batch_size: int = 500,
) -> dict:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    report = summarize_links(
        entries,
        products,
        dev_brands=dev_brands,
        test_brands=test_brands,
        sample_pairs=sample_pairs,
        seed=seed,
    )
    report.update(nodes_created=0, relationships_created=0)
    for offset in range(0, len(entries), batch_size):
        rows = []
        for entry in entries[offset : offset + batch_size]:
            plan = plan_links(entry, products)
            promotes = [
                {
                    "brand": match.product.brand,
                    "source_url": match.product.source_url,
                    "basis": match.basis,
                    "confidence": match.confidence,
                    "matched_text": match.matched_text,
                    "multi_product": plan.multi_product,
                }
                for match in plan.links
            ]
            rows.append(
                {
                    "source": entry.creative.key.source.value,
                    "source_id": entry.creative.key.source_id,
                    "brand": entry.creative.properties.get("brand"),
                    "promotes": promotes,
                    "claims": list(plan.claims),
                    "mentions": [
                        {
                            "raw_name": mention.raw_name,
                            "standard_name": mention.standard_name,
                        }
                        for mention in plan.mentions
                    ],
                }
            )
        result = graph.run(REPLACE_LINKS, {"rows": rows})
        report["nodes_created"] += result.nodes_created
        report["relationships_created"] += result.relationships_created
    return report
