"""Graph adapters use synthetic rows and never infer negative evidence."""

from types import SimpleNamespace

import pytest

from beautyads.agents.lookups import (
    GraphCertLookup,
    GraphEfficacySupport,
    GraphEvidenceIndex,
)
from beautyads.domain.labels import Claim


class Graph:
    def __init__(self, rows=(), error=False):
        self.rows, self.error, self.calls = list(rows), error, []

    def run(self, query, params=None):
        self.calls.append((query, params))
        if self.error:
            raise RuntimeError("synthetic graph failure")
        return SimpleNamespace(records=self.rows)


def test_existing_filters_inputs_and_returned_ids():
    graph = Graph(
        [{"creative_id": "youtube:a"}, {"creative_id": "youtube:unrequested"}, {}]
    )
    lookup = GraphEvidenceIndex(graph)
    assert lookup.existing(
        ["youtube:a", "instagram:b", "bogus:x", "youtube:", "' DELETE", 1]
    ) == {"youtube:a"}
    assert graph.calls[0][1] == {"ids": ["youtube:a", "instagram:b"]}
    assert lookup.existing(["bad"]) == set()
    assert len(graph.calls) == 1


@pytest.mark.parametrize(
    "rows,expected",
    [
        ([], "unknown"),
        ([{}], "unknown"),
        ([{"ingredient_count": 0, "supporting_count": 1}], "unknown"),
        ([{"ingredient_count": 2, "supporting_count": 0}], "unknown"),
        ([{"ingredient_count": 2, "supporting_count": 1}], "supported"),
    ],
)
def test_efficacy_status(rows, expected):
    lookup = GraphEfficacySupport(Graph(rows))
    result = lookup.efficacy_support("https://example.invalid/product", Claim.hydration)
    assert result == expected
    assert result in {"supported", "unknown"}
    assert lookup.last_error is None


@pytest.mark.parametrize("claim", list(Claim))
def test_certification_mapping(claim):
    lookup = GraphCertLookup(
        Graph([{"certifications": ["brightening", "anti_aging", "sun_protection"]}])
    )
    expected = (
        "certified"
        if claim.value in {"brightening", "anti_aging", "sun_protection"}
        else "unknown"
    )
    assert lookup.cert_status("https://example.invalid/p", claim) == expected
    assert lookup.cert_status("https://example.invalid/p", claim) != "not_certified"


@pytest.mark.parametrize(
    "rows", [[], [{}], [{"certifications": []}], [{"certifications": ["brightening"]}]]
)
def test_missing_certification_is_unknown(rows):
    assert (
        GraphCertLookup(Graph(rows)).cert_status(
            "https://example.invalid/p", Claim.anti_aging
        )
        == "unknown"
    )


@pytest.mark.parametrize(
    "cls,method,args,expected",
    [
        (GraphEvidenceIndex, "existing", (["youtube:a"],), set()),
        (
            GraphEfficacySupport,
            "efficacy_support",
            ("https://example.invalid/p", Claim.hydration),
            "unknown",
        ),
        (
            GraphCertLookup,
            "cert_status",
            ("https://example.invalid/p", Claim.brightening),
            "unknown",
        ),
    ],
)
def test_graph_errors_are_safe_and_error_resets(cls, method, args, expected):
    graph = Graph(error=True)
    lookup = cls(graph)
    assert getattr(lookup, method)(*args) == expected
    assert lookup.last_error == "GRAPH_UNAVAILABLE"
    graph.error = False
    getattr(lookup, method)(*args)
    assert lookup.last_error is None


def test_invalid_claim_rejected_before_graph():
    graph = Graph()
    with pytest.raises(ValueError):
        GraphEfficacySupport(graph).efficacy_support(
            "https://example.invalid/p", "invented"
        )
    assert not graph.calls
