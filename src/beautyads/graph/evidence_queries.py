"""Read-only evidence expansion; identifiers come only from a closed table."""

from datetime import date, timedelta
from types import MappingProxyType

from beautyads.domain.evidence import (
    CategoryBasis,
    CertificationKind,
    EvidenceAxis,
    EvidenceSource,
)
from beautyads.domain.labels import Angle, Category, Claim, Format, HookType

_AXES = MappingProxyType(
    {
        EvidenceAxis.hook_type: ("USES_HOOK", "Hook"),
        EvidenceAxis.angle: ("HAS_ANGLE", "Angle"),
        EvidenceAxis.format: ("HAS_FORMAT", "Format"),
        EvidenceAxis.claim: ("CLAIMS", "Efficacy"),
    }
)
_LABEL_SCOPE = "MATCH (c:Creative)"
_PRODUCT_SCOPE = (
    "MATCH (category:Category)<-[:IN_CATEGORY]-(p:Product)<-[:PROMOTES]-(c:Creative)"
)
_LABEL_FILTER = "c.category = $category AND c.content_type = 'product_creative'"
_PRODUCT_FILTER = "category.value = $category"
_MATURE_FILTER = """c.latest_view_count IS NOT NULL AND c.source IN $sources
          AND datetime(c.published_at) <= datetime($mature_before)"""


def _scope(basis):
    return (
        (_LABEL_SCOPE, _LABEL_FILTER, "c.category")
        if basis == CategoryBasis.creative_label
        else (_PRODUCT_SCOPE, _PRODUCT_FILTER, "category.value")
    )


def _rows(axis, basis):
    relationship, label = _AXES[axis]
    match, category_filter, category = _scope(basis)
    return f"""
        {match}-[:{relationship}]->(h:{label})
        WHERE {_MATURE_FILTER} AND {category_filter}
        RETURN DISTINCT {category} AS category, c.source AS source, c.brand AS channel_brand,
               c.source + ':' + c.source_id AS creative_id,
               c.latest_view_count AS views, h.value AS hook,
               c.published_at AS published_at, h.value AS value
    """


def _counts(axis, basis):
    relationship, label = _AXES[axis]
    match, category_filter, _ = _scope(basis)
    selection = f"""{match}-[:{relationship}]->(h:{label})
        WHERE {category_filter} AND c.source IN $sources"""
    return f"""
        CALL {{
            {selection}
            RETURN count(DISTINCT c) AS total
        }}
        {selection}
        WITH DISTINCT total, h.value AS value,
             c.source + ':' + c.source_id AS creative_id, c.latest_view_count AS views
        ORDER BY views IS NULL ASC, views DESC, creative_id ASC
        WITH total, value, collect(creative_id) AS ids
        RETURN value, size(ids) AS creatives, ids[0..3] AS creative_ids, total
        ORDER BY creatives DESC, value ASC
    """


def _examples(basis):
    match, category_filter, _ = _scope(basis)
    return f"""
        {match}
        WHERE {category_filter} AND c.source IN $sources
          AND ($hook_type IS NULL OR EXISTS {{
              MATCH (c)-[:USES_HOOK]->(h:Hook) WHERE h.value = $hook_type }})
          AND ($angle IS NULL OR EXISTS {{
              MATCH (c)-[:HAS_ANGLE]->(a:Angle) WHERE a.value = $angle }})
          AND ($format IS NULL OR EXISTS {{
              MATCH (c)-[:HAS_FORMAT]->(f:Format) WHERE f.value = $format }})
          AND ($claim IS NULL OR EXISTS {{
              MATCH (c)-[:CLAIMS]->(e:Efficacy) WHERE e.value = $claim }})
        WITH DISTINCT c
        OPTIONAL MATCH (c)-[:USES_HOOK]->(h:Hook)
        OPTIONAL MATCH (c)-[:HAS_ANGLE]->(a:Angle)
        OPTIONAL MATCH (c)-[:HAS_FORMAT]->(f:Format)
        RETURN DISTINCT c.source + ':' + c.source_id AS creative_id,
               c.brand AS brand, c.source AS source, c.url AS url,
               c.latest_view_count AS views, c.published_at AS published_at,
               h.value AS hook_type, a.value AS angle, f.value AS format
        ORDER BY views IS NULL ASC, views DESC, creative_id ASC
        LIMIT $limit
    """


# Build once from enum members. Public builders only select fixed strings.
AXIS_ROWS = MappingProxyType(
    {(a, b): _rows(a, b) for a in EvidenceAxis for b in CategoryBasis}
)
AXIS_COUNTS = MappingProxyType(
    {(a, b): _counts(a, b) for a in EvidenceAxis for b in CategoryBasis}
)
EXAMPLES = MappingProxyType({b: _examples(b) for b in CategoryBasis})


def axis_rows_query(axis, basis) -> str:
    return AXIS_ROWS[EvidenceAxis(axis), CategoryBasis(basis)]


def axis_count_query(axis, basis) -> str:
    return AXIS_COUNTS[EvidenceAxis(axis), CategoryBasis(basis)]


def example_query(basis) -> str:
    return EXAMPLES[CategoryBasis(basis)]


def evidence_parameters(
    *,
    category,
    as_of: date,
    source=None,
    axis=EvidenceAxis.hook_type,
    category_basis=CategoryBasis.creative_label,
    hook_type=None,
    angle=None,
    format=None,
    claim=None,
    limit=10,
    operation="rows",
) -> dict:
    """Validate closed tool values; only the trusted server supplies as_of."""
    if Category(category) == Category.other:
        raise ValueError("EVIDENCE_INPUT_INVALID")
    EvidenceAxis(axis)
    CategoryBasis(category_basis)
    sources = (
        [EvidenceSource(source).value]
        if source is not None
        else [s.value for s in EvidenceSource]
    )
    for value, enum in (
        (hook_type, HookType),
        (angle, Angle),
        (format, Format),
        (claim, Claim),
    ):
        if value is not None:
            enum(value)
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError("EVIDENCE_INPUT_INVALID")
    if operation not in {"rows", "count", "examples"}:
        raise ValueError("EVIDENCE_INPUT_INVALID")
    params = {"category": Category(category).value, "sources": sources}
    if operation == "rows":
        params["mature_before"] = (
            as_of - timedelta(days=14)
        ).isoformat() + "T23:59:59Z"
    elif operation == "examples":
        params.update(
            hook_type=hook_type, angle=angle, format=format, claim=claim, limit=limit
        )
    return params


def certified_by_kind_query() -> str:
    """Frozen CQ-03 product set, with readable product metadata added."""
    return """
        MATCH (p:Product)-[:CERTIFIED_AS]->(f:FunctionalCert)
        WHERE f.value = $cert
        RETURN DISTINCT p.source_url AS product, f.value AS certification,
               p.brand AS brand, p.name_ko AS product_name
        ORDER BY p.brand, p.source_url
    """


def certification_parameters(*, cert) -> dict:
    """Accept only official functional-certification kinds as a bound value."""
    return {"cert": CertificationKind(cert).value}


def existing_creatives_query() -> str:
    """Resolve only the requested public creative keys."""
    return """
        MATCH (c:Creative)
        WHERE c.source + ':' + c.source_id IN $ids
        RETURN DISTINCT c.source + ':' + c.source_id AS creative_id
    """


def product_support_query() -> str:
    """Count ingredients independently from optional efficacy and cert links."""
    return """
        MATCH (p:Product)
        WHERE p.source_url = $product_url
        OPTIONAL MATCH (p)-[:CONTAINS]->(i:Ingredient)
        OPTIONAL MATCH (i)-[:HAS_EFFICACY]->(e:Efficacy)
        WHERE e.value = $claim
        WITH p, count(DISTINCT i) AS ingredient_count,
             count(DISTINCT CASE WHEN e IS NOT NULL THEN i END) AS supporting_count
        OPTIONAL MATCH (p)-[:CERTIFIED_AS]->(f:FunctionalCert)
        RETURN ingredient_count, supporting_count,
               collect(DISTINCT f.value) AS certifications
    """


def product_support_parameters(*, product_url, claim) -> dict:
    """The product key is bound data; the efficacy is a closed taxonomy value."""
    if not isinstance(product_url, str) or not product_url.strip():
        raise ValueError("PRODUCT_SUPPORT_INPUT_INVALID")
    return {"product_url": product_url, "claim": Claim(claim).value}


def product_unit_price_query() -> str:
    """Resolve a workspace's exact product key for unit-price band calculation."""
    return """
        MATCH (p:Product)
        WHERE p.brand = $brand AND p.source_url = $url
        RETURN p.unit_list_price AS unit_list_price,
               p.price_basis AS price_basis, p.volume_unit AS volume_unit
    """


def product_unit_price_parameters(*, brand, url) -> dict:
    """Keep product identifiers as bound data, including any punctuation."""
    if any(not isinstance(value, str) or not value.strip() for value in (brand, url)):
        raise ValueError("PRODUCT_UNIT_PRICE_INPUT_INVALID")
    return {"brand": brand, "url": url}


def product_name_query() -> str:
    """Read only the official mall name for a workspace's exact product key."""
    return """
        MATCH (p:Product)
        WHERE p.brand = $brand AND p.source_url = $url
        RETURN p.name_ko AS product_name
    """


def product_name_parameters(*, brand, url) -> dict:
    """Keep the same identifier validation as the unit-price lookup."""
    if any(not isinstance(value, str) or not value.strip() for value in (brand, url)):
        raise ValueError("PRODUCT_NAME_INPUT_INVALID")
    return {"brand": brand, "url": url}


_CREATIVE_LABELS_QUERY = """
    MATCH (c:Creative)
    WHERE c.source + ':' + c.source_id IN $ids
    OPTIONAL MATCH (c)-[:USES_HOOK]->(h:Hook)
    OPTIONAL MATCH (c)-[:HAS_ANGLE]->(a:Angle)
    OPTIONAL MATCH (c)-[:HAS_FORMAT]->(f:Format)
    OPTIONAL MATCH (c)-[:FEATURES]->(t:Talent)
    OPTIONAL MATCH (c)-[:HAS_CTA]->(cta:CtaType)
    OPTIONAL MATCH (c)-[:CLAIMS]->(e:Efficacy)
    RETURN c.source + ':' + c.source_id AS creative_id,
           h.value AS hook_type, a.value AS angle, f.value AS format,
           t.value AS talent, cta.value AS cta_type,
           collect(DISTINCT e.value) AS claims
"""


def creative_labels_query() -> str:
    """Read optional analysis labels without dropping unlabelled creatives."""
    return _CREATIVE_LABELS_QUERY


def creative_labels_parameters(ids) -> dict:
    """Bind at most thirty validated evidence keys, preserving their order."""
    import re

    from beautyads.domain.tools import EVIDENCE_ID_PATTERN

    if (
        not isinstance(ids, list)
        or not 1 <= len(ids) <= 30
        or any(
            not isinstance(eid, str) or not re.fullmatch(EVIDENCE_ID_PATTERN, eid)
            for eid in ids
        )
    ):
        raise ValueError("CREATIVE_LABELS_IDS_INVALID")
    return {"ids": list(dict.fromkeys(ids))}


def card_labels_by_id(rows) -> dict[str, dict]:
    """Missing classification relationships are normal, not missing creatives."""
    return {
        row.get("creative_id"): {
            **{
                field: row.get(field)
                for field in ("hook_type", "angle", "format", "talent", "cta_type")
            },
            "claims": list(row.get("claims") or []),
        }
        for row in rows
        if isinstance(row.get("creative_id"), str)
    }
