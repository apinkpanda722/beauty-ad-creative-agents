"""Closed parameterized read queries; no Neo4j connection."""

import re
from datetime import date
from itertools import product

import pytest

from beautyads.domain.evidence import CategoryBasis, CertificationKind, EvidenceAxis
from beautyads.graph.evidence_queries import (
    axis_count_query,
    axis_rows_query,
    certification_parameters,
    certified_by_kind_query,
    evidence_parameters,
    example_query,
)
from beautyads.graph.queries import _CERT_CLAIMS, QUESTIONS, question_parameters

AS_OF = date(2026, 11, 17)


def normalized(query):
    return " ".join(query.split())


def test_product_hook_query_preserves_frozen_cq06_shape_and_columns():
    frozen = normalized(QUESTIONS["CQ-06"].cypher)
    query = normalized(axis_rows_query("hook_type", "product_link"))
    assert frozen.split(" WHERE ")[0] in query
    condition = frozen.split(" WHERE ")[1].split(" RETURN ")[0]
    assert condition in query
    assert set(re.findall(r"AS (\w+)", frozen)) <= set(re.findall(r"AS (\w+)", query))
    assert "h.value AS hook" in query and "h.value AS value" in query
    assert "category.value = $category" in query


@pytest.mark.parametrize("axis,basis", list(product(EvidenceAxis, CategoryBasis)))
@pytest.mark.parametrize("operation", ["rows", "count", "examples"])
def test_all_queries_read_only_and_exact_parameter_contract(axis, basis, operation):
    query = {"rows": axis_rows_query, "count": axis_count_query}.get(operation)
    query = query(axis, basis) if query else example_query(basis)
    params = evidence_parameters(
        category="serum_ampoule",
        source="instagram",
        axis=axis,
        category_basis=basis,
        as_of=AS_OF,
        operation=operation,
    )
    assert not re.search(r"\b(CREATE|MERGE|SET|DELETE)\b", query, re.IGNORECASE)
    assert set(re.findall(r"\$(\w+)", query)) == set(params)
    assert "serum_ampoule" not in query and "instagram" not in query
    if operation == "rows":
        assert (
            params["mature_before"]
            == question_parameters(QUESTIONS["CQ-06"], as_of=AS_OF)["mature_before"]
        )
    if basis == "creative_label":
        assert "c.category = $category" in query
        assert "c.content_type = 'product_creative'" in query
        assert "PROMOTES" not in query
    else:
        assert "PROMOTES" in query


@pytest.mark.parametrize(
    "axis,relationship,label",
    [
        ("hook_type", "USES_HOOK", "Hook"),
        ("angle", "HAS_ANGLE", "Angle"),
        ("format", "HAS_FORMAT", "Format"),
        ("claim", "CLAIMS", "Efficacy"),
    ],
)
def test_axis_mapping_and_count_representatives(axis, relationship, label):
    for basis in CategoryBasis:
        query = axis_count_query(axis, basis)
        assert f"[:{relationship}]->(h:{label})" in query
        assert "count(DISTINCT" in query
        assert "views DESC, creative_id ASC" in query
        assert "[0..3]" in query
        assert "AS total" in query


def test_example_filters_and_bounded_parameters():
    params = evidence_parameters(
        category="mask_pack", as_of=AS_OF, operation="examples"
    )
    assert params["sources"] == ["youtube", "instagram", "tiktok"]
    assert params["limit"] == 10
    for name in ("hook_type", "angle", "format", "claim"):
        assert params[name] is None
        assert f"${name} IS NULL" in example_query("creative_label")
    assert "LIMIT $limit" in example_query("product_link")
    assert "views DESC, creative_id ASC" in example_query("creative_label")


@pytest.mark.parametrize(
    "changes",
    [
        {"category": "other"},
        {"source": "invented"},
        {"axis": "x') DELETE c"},
        {"category_basis": "unknown"},
        {"hook_type": "unknown"},
        {"angle": "unknown"},
        {"format": "unknown"},
        {"claim": "unknown"},
        {"limit": 0},
        {"limit": 21},
        {"limit": True},
        {"source": []},
        {"category": {}},
        {"operation": "mutate"},
    ],
)
def test_invalid_parameters_rejected(changes):
    with pytest.raises((ValueError, TypeError)):
        evidence_parameters(**{"category": "mask_pack", "as_of": AS_OF, **changes})


@pytest.mark.parametrize(
    "builder,args",
    [
        (axis_rows_query, ("unknown", "creative_label")),
        (axis_count_query, ("hook_type", "unknown")),
        (example_query, ("unknown",)),
    ],
)
def test_query_builders_reject_unlisted_identifiers(builder, args):
    with pytest.raises(ValueError):
        builder(*args)


def test_certification_vocabulary_and_frozen_cq03_pattern_and_columns():
    assert {kind.value for kind in CertificationKind} == set(_CERT_CLAIMS)
    frozen = normalized(QUESTIONS["CQ-03"].cypher)
    query = normalized(certified_by_kind_query())
    assert frozen.split(" WHERE ")[0] in query
    assert frozen.split(" WHERE ")[1].split(" RETURN ")[0] in query
    assert set(re.findall(r"AS (\w+)", frozen)) <= set(re.findall(r"AS (\w+)", query))
    assert "p.source_url AS product, f.value AS certification" in query
    assert "p.brand AS brand" in query and "p.name_ko AS product_name" in query
    assert query.endswith("ORDER BY p.brand, p.source_url")
    assert "RETURN DISTINCT" in query


@pytest.mark.parametrize("kind", CertificationKind)
def test_certification_query_is_fixed_read_only_and_parameterized(kind):
    query = certified_by_kind_query()
    params = certification_parameters(cert=kind)
    assert params == {"cert": kind.value}
    assert certification_parameters(cert=kind.value) == params
    assert set(re.findall(r"\$(\w+)", query)) == set(params)
    assert not re.search(r"\b(CREATE|MERGE|SET|DELETE)\b", query, re.IGNORECASE)
    assert kind.value not in query


@pytest.mark.parametrize(
    "cert", ["unknown", "hydration", "' DELETE p", "", None, [], {}, 1]
)
def test_certification_parameters_reject_unlisted_values(cert):
    with pytest.raises((ValueError, TypeError)):
        certification_parameters(cert=cert)


def test_plan_lookup_queries_are_fixed_read_only_and_bound():
    from beautyads.graph.evidence_queries import (
        existing_creatives_query,
        product_support_parameters,
        product_support_query,
    )

    queries = [
        (existing_creatives_query(), {"ids"}),
        (product_support_query(), {"product_url", "claim"}),
    ]
    for query, params in queries:
        assert set(re.findall(r"\$(\w+)", query)) == params
        assert not re.search(
            r"\b(CREATE|MERGE|SET|DELETE|REMOVE|CALL)\b", query, re.IGNORECASE
        )
    query = product_support_query()
    for fragment in (
        "CONTAINS",
        "HAS_EFFICACY",
        "CERTIFIED_AS",
        "ingredient_count",
        "supporting_count",
        "certifications",
        "DISTINCT",
    ):
        assert fragment in query
    assert "OPTIONAL MATCH" in query
    url = "https://example.invalid/' DELETE p"
    assert product_support_parameters(product_url=url, claim="hydration") == {
        "product_url": url,
        "claim": "hydration",
    }
    assert url not in query and "hydration" not in query
    assert "c.source + ':' + c.source_id" in existing_creatives_query()


@pytest.mark.parametrize("claim", ["invented", "' DELETE p", None, [], {}])
def test_plan_lookup_claim_validation(claim):
    from beautyads.graph.evidence_queries import product_support_parameters

    with pytest.raises((ValueError, TypeError)):
        product_support_parameters(product_url="https://example.invalid/p", claim=claim)


def test_product_unit_price_is_fixed_read_only_and_bound():
    from beautyads.graph.evidence_queries import (
        product_unit_price_parameters,
        product_unit_price_query,
    )

    query = product_unit_price_query()
    brand, url = "synthetic' OR true", "https://example.invalid/' DELETE p"
    params = product_unit_price_parameters(brand=brand, url=url)
    assert params == {"brand": brand, "url": url}
    assert set(re.findall(r"\$(\w+)", query)) == set(params)
    assert not re.search(
        r"\b(CREATE|MERGE|SET|DELETE|REMOVE|CALL)\b", query, re.IGNORECASE
    )
    assert "p.brand = $brand" in query and "p.source_url = $url" in query
    for name in ("unit_list_price", "price_basis", "volume_unit"):
        assert f"p.{name} AS {name}" in query
    assert brand not in query and url not in query
    assert product_unit_price_query() == query


@pytest.mark.parametrize("value", [None, "", " \t", [], {}, 123, True])
@pytest.mark.parametrize("field", ["brand", "url"])
def test_product_unit_price_validates_inputs_without_values(field, value):
    from beautyads.graph.evidence_queries import product_unit_price_parameters

    with pytest.raises(ValueError, match="^PRODUCT_UNIT_PRICE_INPUT_INVALID$"):
        product_unit_price_parameters(
            **{"brand": "synthetic", "url": "https://example.invalid/p", field: value}
        )


def test_product_name_is_only_fixed_read_query_with_bound_identifiers():
    from beautyads.graph.evidence_queries import (
        product_name_parameters,
        product_name_query,
    )

    brand, url = "brand' OR true", "https://example.invalid/' DELETE p"
    query = product_name_query()
    assert normalized(query) == (
        "MATCH (p:Product) WHERE p.brand = $brand AND p.source_url = $url "
        "RETURN p.name_ko AS product_name"
    )
    assert product_name_parameters(brand=brand, url=url) == {"brand": brand, "url": url}
    assert set(re.findall(r"\$(\w+)", query)) == {"brand", "url"}
    assert not re.search(
        r"\b(CREATE|MERGE|SET|DELETE|REMOVE|CALL)\b", query, re.IGNORECASE
    )
    assert brand not in query and url not in query
    assert query == product_name_query()


@pytest.mark.parametrize("field", ["brand", "url"])
@pytest.mark.parametrize("value", [None, "", " \t", [], {}, 123, True])
def test_product_name_validates_inputs_without_diagnostics(field, value):
    from beautyads.graph.evidence_queries import product_name_parameters

    with pytest.raises(ValueError, match="^PRODUCT_NAME_INPUT_INVALID$"):
        product_name_parameters(
            **{"brand": "synthetic", "url": "https://example.invalid/p", field: value}
        )


def test_creative_labels_is_fixed_public_read_query():
    from beautyads.graph.evidence_queries import creative_labels_query
    from beautyads.graph.load import AXES

    query = creative_labels_query()
    assert query == creative_labels_query()
    assert set(re.findall(r"\$(\w+)", query)) == {"ids"}
    assert not re.search(
        r"Feedback|tenant|\b(CREATE|MERGE|SET|DELETE)\b", query, re.IGNORECASE
    )
    assert "c.source + ':' + c.source_id IN $ids" in query
    assert "collect(DISTINCT e.value) AS claims" in query
    for field, label, relationship, _ in AXES:
        assert f":{relationship}" in query and f":{label}" in query
        assert f"AS {field}" in query
    assert ":CLAIMS" in query and ":Efficacy" in query


@pytest.mark.parametrize(
    "ids",
    [
        [],
        "youtube:synthetic",
        None,
        [None],
        ["invalid"],
        ["youtube:x\n"],
        [f"youtube:{i}" for i in range(31)],
    ],
)
def test_creative_labels_parameters_reject_invalid_ids(ids):
    from beautyads.graph.evidence_queries import creative_labels_parameters

    with pytest.raises(ValueError):
        creative_labels_parameters(ids)


def test_card_labels_group_by_id_and_preserve_absent_axes():
    from beautyads.graph.evidence_queries import (
        card_labels_by_id,
        creative_labels_parameters,
    )

    eid = "youtube:synthetic"
    values = {
        field: f"synthetic-{field}"
        for field in ("hook_type", "angle", "format", "talent", "cta_type")
    }
    claims = ["synthetic-efficacy-a", "synthetic-efficacy-b"]
    empty = dict.fromkeys(values)
    assert creative_labels_parameters([eid, "instagram:bare", eid]) == {
        "ids": [eid, "instagram:bare"]
    }
    assert card_labels_by_id(
        [
            {"creative_id": eid, **values, "claims": claims},
            {"creative_id": "instagram:bare", **empty, "claims": None},
            {"creative_id": "tiktok:bare"},
        ]
    ) == {
        eid: {**values, "claims": claims},
        "instagram:bare": {**empty, "claims": []},
        "tiktok:bare": {**empty, "claims": []},
    }
    assert card_labels_by_id([]) == {}
