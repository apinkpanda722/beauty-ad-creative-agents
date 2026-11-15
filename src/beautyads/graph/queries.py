"""Frozen CQ-v1 read queries. Only closed classifications are tool inputs.

Hops describe the longest relationship pattern, including EXISTS branches;
separate paths are not concatenated. Context and dates are server supplied.
Public-product comparisons enumerate reference products, retaining their keys;
they do not pretend to select a workspace's private brand profile.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType

from beautyads.domain.labels import Category, Claim
from beautyads.domain.skin import SkinConcern, SkinType


@dataclass(frozen=True)
class Question:
    cypher: str
    parameters: tuple[str, ...]
    hops: int
    inputs: tuple[str, ...] = ()


QUESTIONS = MappingProxyType(
    {
        "CQ-01": Question(
            """
        MATCH (p:Product)-[:CONTAINS]->(i:Ingredient)-[:HAS_EFFICACY]->(e:Efficacy)
        WHERE p.category = $category AND e.value = $claim
        RETURN DISTINCT p.source_url AS product, i.standard_name AS ingredient
    """,
            ("category", "claim"),
            2,
            ("category", "claim"),
        ),
        "CQ-02": Question(
            """
        MATCH (p:Product)-[:CONTAINS]->(i:Ingredient)-[:HAS_EFFICACY]->(:Efficacy)-[:ADDRESSES]->(s:SkinConcern)
        WHERE p.category = $category AND s.value = $concern
        RETURN DISTINCT p.source_url AS product, i.standard_name AS ingredient,
               p.name_ko AS product_name
    """,
            ("category", "concern"),
            3,
            ("category", "concern"),
        ),
        "CQ-03": Question(
            """
        MATCH (p:Product)-[:CERTIFIED_AS]->(f:FunctionalCert)
        WHERE f.value = $cert
        RETURN DISTINCT p.source_url AS product, f.value AS certification
    """,
            ("cert",),
            1,
        ),
        "CQ-04": Question(
            """
        MATCH (c:Creative)-[:PROMOTES]->(p:Product)-[:CONTAINS]->(:Ingredient)-[:HAS_EFFICACY]->(e:Efficacy)
        WHERE p.category = $category AND e.value = $claim
          AND EXISTS { MATCH (c)-[:CLAIMS]->(e) }
        WITH collect(DISTINCT c) AS matches
        WHERE size(matches) > 0
        RETURN size(matches) AS creatives,
               [c IN matches | c.source + ':' + c.source_id] AS creative_ids
    """,
            ("category", "claim"),
            3,
            ("category", "claim"),
        ),
        "CQ-05": Question(
            """
        MATCH (a:IngredientAlias)-[:ALIAS_OF]->(:Ingredient)<-[:CONTAINS]-(p:Product)<-[:PROMOTES]-(c:Creative)-[:CLAIMS]->(e:Efficacy)
        WHERE a.alias IN $aliases
        RETURN e.value AS efficacy, count(DISTINCT c) AS creatives,
               collect(DISTINCT c.source + ':' + c.source_id) AS creative_ids
        ORDER BY creatives DESC
    """,
            ("aliases",),
            4,
        ),
        "CQ-06": Question(
            """
        MATCH (category:Category)<-[:IN_CATEGORY]-(p:Product)<-[:PROMOTES]-(c:Creative)-[:USES_HOOK]->(h:Hook)
        WHERE c.latest_view_count IS NOT NULL AND c.source IN $sources
          AND datetime(c.published_at) <= datetime($mature_before)
        RETURN DISTINCT category.value AS category, c.source AS source, c.brand AS channel_brand,
               c.source + ':' + c.source_id AS creative_id,
               c.latest_view_count AS views, h.value AS hook
    """,
            ("sources", "mature_before"),
            3,
        ),
        "CQ-08": Question(
            """
        MATCH (s:SkinType)<-[:SUITS]-(p:Product)<-[:PROMOTES]-(c:Creative)-[:HAS_ANGLE|HAS_FORMAT]->(axis)
        WHERE s.value = $skin_type
        RETURN labels(axis) AS axis, axis.value AS value, count(DISTINCT c) AS creatives,
               collect(DISTINCT c.source + ':' + c.source_id) AS creative_ids
        ORDER BY creatives DESC
    """,
            ("skin_type",),
            3,
            ("skin_type",),
        ),
        "CQ-09": Question(
            """
        MATCH (c:Creative)-[:USES_HOOK]->(h:Hook)
        WHERE c.source = $source AND c.content_type = $content_type
          AND EXISTS { MATCH (c)-[:HAS_FORMAT]->(:Format) }
        RETURN DISTINCT c.source + ':' + c.source_id AS creative_id,
               c.advertiser_name AS advertiser_name, h.value AS hook
    """,
            ("source", "content_type"),
            1,
        ),
        "CQ-10": Question(
            """
        MATCH (p:Product)-[:CONTAINS]->(i:Ingredient)-[r:HAS_EFFICACY]->(e:Efficacy)
        WHERE e.value = $claim
        OPTIONAL MATCH (p)-[:CERTIFIED_AS]->(f:FunctionalCert)
        RETURN DISTINCT p.source_url AS product, i.standard_name AS ingredient,
               r.conditional AS conditional, r.source_ref AS source_ref,
               collect(DISTINCT f.value) AS certifications
        UNION
        MATCH (p:Product)-[:CERTIFIED_AS]->(f:FunctionalCert)
        WHERE $claim IN $cert_claims[f.value]
        RETURN p.source_url AS product, null AS ingredient, false AS conditional,
               null AS source_ref, collect(DISTINCT f.value) AS certifications
    """,
            ("claim", "cert_claims"),
            2,
            ("claim",),
        ),
        "CQ-11": Question(
            """
        MATCH (r:ClaimRule)-[:APPLIES_TO]->(scope)
        WHERE (scope:Efficacy AND scope.value = $claim)
           OR (scope:SkinConcern AND scope.value = $concern)
           OR (scope:Category AND scope.value = $category)
        RETURN DISTINCT r.rule_id AS rule_id, r.rule_json AS rule, scope.value AS scope
    """,
            ("claim", "concern", "category"),
            1,
            ("claim", "concern", "category"),
        ),
        "CQ-12": Question(
            """
        MATCH (f:Feedback)-[:ABOUT]->(pattern)
        WHERE f.tenant_id = $context.tenant_id AND f.decision = $decision
          AND datetime(f.created_at) >= datetime($recent_since)
          AND datetime(f.created_at) <= datetime($as_of_end)
        RETURN labels(pattern) AS pattern_type, pattern.value AS pattern,
               count(DISTINCT f) AS rejected
    """,
            ("context", "decision", "recent_since", "as_of_end"),
            1,
        ),
        "CQ-13": Question(
            """
        MATCH (own:Product)-[key:CONTAINS]->(i:Ingredient)<-[:CONTAINS]-(competitor:Product)<-[:PROMOTES]-(c:Creative)-[:CLAIMS]->(e:Efficacy)
        WHERE key.is_key = $is_key AND own.brand <> competitor.brand
        RETURN own.source_url AS reference_product, competitor.source_url AS competitor,
               i.standard_name AS ingredient, e.value AS efficacy,
               collect(DISTINCT c.source + ':' + c.source_id) AS creative_ids
    """,
            ("is_key",),
            4,
        ),
        "CQ-14": Question(
            """
        MATCH (own:Product)-[:CONTAINS]->(i:Ingredient)-[:HAS_EFFICACY]->(e:Efficacy)
        WHERE NOT EXISTS {
            MATCH (other:Product)-[:CONTAINS]->(i)
            WHERE other.brand <> own.brand
        } AND NOT EXISTS {
            MATCH (own)-[:IN_CATEGORY]->(:Category)<-[:IN_CATEGORY]-(competitor:Product)<-[:PROMOTES]-(c:Creative)-[:CLAIMS]->(e)
            WHERE competitor.brand <> own.brand
        }
        RETURN DISTINCT own.source_url AS reference_product, e.value AS efficacy,
               i.standard_name AS exclusive_evidence
        UNION
        MATCH (own:Product)-[:CERTIFIED_AS]->(cert:FunctionalCert)
        WHERE NOT EXISTS {
            MATCH (other:Product)-[:CERTIFIED_AS]->(cert)
            WHERE other.brand <> own.brand
        } AND NOT EXISTS {
            MATCH (own)-[:IN_CATEGORY]->(:Category)<-[:IN_CATEGORY]-(competitor:Product)<-[:PROMOTES]-(c:Creative)-[:CLAIMS]->(e:Efficacy)
            WHERE competitor.brand <> own.brand AND e.value IN $cert_claims[cert.value]
        }
        RETURN DISTINCT own.source_url AS reference_product, cert.value AS efficacy,
               cert.value AS exclusive_evidence
    """,
            ("cert_claims",),
            4,
        ),
        "CQ-15": Question(
            """
        MATCH (a:IngredientAlias)-[:ALIAS_OF]->(i:Ingredient)<-[:CONTAINS]-(p:Product)<-[:PROMOTES]-(c:Creative)
        WHERE a.alias IN $aliases AND datetime(c.published_at) >= datetime($previous_since)
          AND datetime(c.published_at) <= datetime($as_of_end)
          AND EXISTS {
              MATCH (c)-[:MENTIONS]->(mention:IngredientAlias)-[:ALIAS_OF]->(i)
          }
        RETURN DISTINCT c.source + ':' + c.source_id AS creative_id,
               c.published_at AS published_at, c.source AS source
    """,
            ("aliases", "previous_since", "as_of_end"),
            3,
        ),
        "CQ-16": Question(
            """
        MATCH (own:Product)-[:IN_CATEGORY]->(:Category)<-[:IN_CATEGORY]-(competitor:Product)<-[:PROMOTES]-(c:Creative)-[:CLAIMS|USES_HOOK]->(axis)
        WHERE own.brand <> competitor.brand AND own.volume_unit = competitor.volume_unit
          AND own.price_basis = $price_basis AND competitor.price_basis = $price_basis
          AND own.unit_list_price IS NOT NULL AND competitor.unit_list_price IS NOT NULL
          AND (competitor.unit_list_price >= $context.price_min OR
               ($context.price_min IS NULL AND competitor.unit_list_price >= own.unit_list_price))
          AND (competitor.unit_list_price <= $context.price_max OR
               ($context.price_max IS NULL AND competitor.unit_list_price <= own.unit_list_price))
        RETURN own.source_url AS reference_product, own.unit_list_price AS reference_price,
               competitor.source_url AS competitor, competitor.unit_list_price AS competitor_price,
               own.volume_unit AS unit, labels(axis) AS axis, axis.value AS value,
               collect(DISTINCT c.source + ':' + c.source_id) AS creative_ids
    """,
            ("price_basis", "context"),
            4,
        ),
    }
)

# Discrete official functional-certification vocabulary differs from Claim.
_CERT_CLAIMS = {
    "brightening": ["brightening"],
    "anti_aging": ["anti_aging"],
    "sun_protection": ["sun_protection"],
}
_INPUT_VALUES = {
    "category": frozenset(v.value for v in Category if v != Category.other),
    "claim": frozenset(v.value for v in Claim),
    "concern": frozenset(v.value for v in SkinConcern),
    "skin_type": frozenset(v.value for v in SkinType),
}


def months_before(day: date, count: int) -> date:
    import calendar

    month_index = day.year * 12 + day.month - 1 - count
    year, month = divmod(month_index, 12)
    month += 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def question_parameters(
    spec: Question,
    *,
    as_of: date,
    inputs: Mapping[str, str] | None = None,
    context: Mapping[str, str] | None = None,
) -> dict:
    """Server date/context cannot be supplied through tool classification inputs."""
    from datetime import timedelta

    given = dict(inputs or {})
    if any(
        k not in spec.inputs or not isinstance(v, str) or v not in _INPUT_VALUES[k]
        for k, v in given.items()
    ):
        raise ValueError("CQ_INPUT_INVALID")
    defaults = {
        "category": Category.serum_ampoule.value,
        "claim": Claim.soothing.value,
        "concern": SkinConcern.acne_trouble.value,
        "skin_type": SkinType.dry.value,
        "cert": "brightening",
        "aliases": ["병풀", "시카", "Centella", "병풀추출물"],
        "source": "tiktok",
        "sources": ["youtube", "instagram"],
        "content_type": "product_creative",
        "is_key": True,
        "price_basis": "list_price",
        "cert_claims": _CERT_CLAIMS,
        "context": dict(context or {}),
        "decision": "rejected",
        "mature_before": (as_of - timedelta(days=14)).isoformat() + "T23:59:59Z",
        "recent_since": months_before(as_of, 3).isoformat() + "T00:00:00Z",
        "previous_since": months_before(as_of, 6).isoformat() + "T00:00:00Z",
        "as_of_end": as_of.isoformat() + "T23:59:59Z",
    }
    if spec is QUESTIONS["CQ-02"]:
        defaults["category"] = Category.mask_pack.value
    defaults.update(given)
    return {name: defaults[name] for name in spec.parameters}
