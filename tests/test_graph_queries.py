import re
from datetime import date
from pathlib import Path

import pytest

from beautyads.graph.queries import QUESTIONS, question_parameters


def test_question_set_matches_frozen_document_table():
    document = Path("docs/COMPETENCY_QUESTIONS.md").read_text()
    ids = set(re.findall(r"^\| (CQ-\d+) \|", document, re.MULTILINE)) - {"CQ-07"}
    assert set(QUESTIONS) == ids


def test_hops_count_relationships_in_each_pattern_not_property_filters():
    # Separate MATCH/EXISTS branches are separate paths, not one concatenated path.
    node = r"\([^()]*\)"
    edge = r"\s*<?-\[[^\]]*\]->?\s*"
    for spec in QUESTIONS.values():
        paths = re.findall(node + "(?:" + edge + node + ")+", spec.cypher)
        counts = [len(re.findall(r"\[[^\]]*\]", path)) for path in paths]
        assert counts and max(counts) == spec.hops
        assert 1 <= spec.hops <= 4
        assert not re.search(r"\[[^\]]*\*", spec.cypher)
        assert set(re.findall(r"\$(\w+)", spec.cypher)) == set(spec.parameters)
        assert not {"tenant_id", "user_id", "today", "date", "as_of"} & set(spec.inputs)
        params = question_parameters(spec, as_of=date(2026, 11, 15))
        assert set(params) == set(spec.parameters)
        assert "2026-11-15" not in spec.cypher


def test_closed_inputs_and_server_date():
    spec = QUESTIONS["CQ-01"]
    params = question_parameters(
        spec, as_of=date(2026, 11, 15), inputs={"claim": "soothing"}
    )
    assert params["claim"] == "soothing"
    assert "soothing" not in spec.cypher
    for inputs in ({"claim": "x') DELETE n"}, {"tenant_id": "x"}, {"as_of": "x"}):
        with pytest.raises(ValueError):
            question_parameters(spec, as_of=date(2026, 11, 15), inputs=inputs)


def test_tiktok_and_scoped_feedback_and_frozen_paths():
    assert "$source" in QUESTIONS["CQ-09"].cypher
    assert (
        question_parameters(QUESTIONS["CQ-09"], as_of=date.today())["source"]
        == "tiktok"
    )
    assert "f.tenant_id = $context.tenant_id" in QUESTIONS["CQ-12"].cypher
    assert "PROMOTES" not in QUESTIONS["CQ-09"].cypher
    for qid in ("CQ-05", "CQ-15"):
        assert "ALIAS_OF" in QUESTIONS[qid].cypher
    assert "IS NOT NULL" in QUESTIONS["CQ-06"].cypher
    assert "price_basis" in QUESTIONS["CQ-16"].cypher


def test_certification_can_support_claim_without_ingredient_efficacy_connection():
    query = QUESTIONS["CQ-10"].cypher
    assert "UNION" in query
    assert "$cert_claims[f.value]" in query


def test_price_band_is_server_supplied_parameter_without_new_cutoff():
    spec = QUESTIONS["CQ-16"]
    assert "competitor.unit_list_price >= $context.price_min" in spec.cypher
    assert "competitor.unit_list_price <= $context.price_max" in spec.cypher
    assert "context" not in spec.inputs


def test_non_scalar_classifications_are_rejected_before_querying():
    for value in ([], {}, 1, None):
        with pytest.raises(ValueError, match="CQ_INPUT_INVALID"):
            question_parameters(
                QUESTIONS["CQ-01"], as_of=date.today(), inputs={"claim": value}
            )
