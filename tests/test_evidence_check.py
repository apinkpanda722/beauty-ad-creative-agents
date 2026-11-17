"""Read-only CLI behavior with injected preflight and a synthetic reader."""

import io
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from beautyads.eval.evidence_check import main
from beautyads.graph.evidence_queries import axis_rows_query
from beautyads.graph.queries import QUESTIONS, question_parameters

AS_OF = date(2026, 11, 17)


class FakeGraph:
    def __init__(self, *, mismatch=False, error=None):
        self.calls = []
        self.closed = False
        self.mismatch = mismatch
        self.error = error

    def run(self, query, params):
        self.calls.append((query, params))
        if self.error:
            raise self.error
        category = params.get("category", "mask_pack")
        linked = {
            "category": category,
            "creative_id": "youtube:linked",
            "hook": "question",
        }
        if query == QUESTIONS["CQ-06"].cypher:
            records = [
                dict(linked, category=c)
                for c in ("mask_pack", "serum_ampoule", "sun_care")
            ]
        elif query == axis_rows_query("hook_type", "product_link"):
            records = [dict(linked, hook="problem" if self.mismatch else "question")]
        else:
            # Neither label basis includes nor is included by product-link basis.
            records = [dict(linked, creative_id="instagram:label_only")]
        return SimpleNamespace(records=records)

    def close(self):
        self.closed = True


def invoke(graph, **overrides):
    out = io.StringIO()
    options = {
        "environ": {"NEO4J_PASSWORD": "test-placeholder"},
        "out": out,
        "docker_check": lambda: True,
        "tcp_check": lambda *a: True,
        "graph_factory": lambda: graph,
        "as_of": AS_OF,
    }
    options.update(overrides)
    code = main([], **options)
    return code, out.getvalue()


@pytest.mark.parametrize(
    "env,docker,tcp,reason",
    [
        ({}, True, True, "ENV_MISSING:NEO4J_PASSWORD"),
        ({"NEO4J_PASSWORD": "test-placeholder"}, False, True, "DOCKER_DOWN"),
        ({"NEO4J_PASSWORD": "test-placeholder"}, True, False, "NEO4J_UNREACHABLE"),
    ],
)
def test_preflight_failure_has_no_graph_calls(env, docker, tcp, reason):
    graph = FakeGraph()
    factories = []
    code, output = invoke(
        graph,
        environ=env,
        docker_check=lambda: docker,
        tcp_check=lambda *a: tcp,
        graph_factory=lambda: factories.append(1),
    )
    assert code == 2 and reason in output
    assert not graph.calls and not factories
    assert "test-placeholder" not in output


def test_equal_sets_report_three_categories_and_both_differences():
    graph = FakeGraph()
    code, output = invoke(graph)
    assert code == 0 and graph.closed
    reports = [json.loads(line) for line in output.splitlines()]
    assert {r["category"] for r in reports} == {
        "mask_pack",
        "serum_ampoule",
        "sun_care",
    }
    for report in reports:
        assert report["code"] == "OK" and report["cost_usd"] == 0
        assert report["creative_label_count"] == report["product_link_count"] == 1
        assert report["intersection_count"] == 0
        assert (
            report["creative_label_only_count"]
            == report["product_link_only_count"]
            == 1
        )
    expected = question_parameters(QUESTIONS["CQ-06"], as_of=AS_OF)
    for query, params in graph.calls:
        assert params["sources"] == expected["sources"]
        assert params["mature_before"] == expected["mature_before"]
        assert not any(
            word in query for word in ("CREATE ", "MERGE ", "SET ", "DELETE ")
        )
    assert "test-placeholder" not in output and "youtube:linked" not in output


def test_mismatch_stops_immediately_and_reports_difference_counts():
    graph = FakeGraph(mismatch=True)
    code, output = invoke(graph)
    assert code == 3 and graph.closed
    reports = [json.loads(line) for line in output.splitlines()]
    assert len(reports) == 1
    assert reports[0]["code"] == "CQ06_MISMATCH"
    assert reports[0]["cq_only_count"] == reports[0]["query_only_count"] == 1
    assert len(graph.calls) == 2


def test_exception_output_is_sanitized_and_graph_closed():
    graph = FakeGraph(error=RuntimeError("synthetic-private-detail"))
    code, output = invoke(graph)
    assert code == 2 and graph.closed
    assert "CQ_EXECUTION_ERROR" in output and "synthetic-private-detail" not in output


def test_live_target_is_explicit_and_verify_stays_offline():
    makefile = Path("Makefile").read_text()
    assert (
        "\nlive-evidence:\n\tuv run python -m beautyads.eval.evidence_check $(ARGS)\n"
        in makefile
    )
    assert any(
        "live-evidence" in line
        for line in makefile.splitlines()
        if line.startswith(".PHONY:")
    )
    assert "live-" not in makefile.split("verify:\n")[1].split("\n\n")[0]
