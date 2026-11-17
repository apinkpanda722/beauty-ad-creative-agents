import io
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from beautyads.eval.cq_verify import (
    CERT_COVERAGE,
    CREATIVE_SCOPE,
    FEEDBACK_COUNT,
    GRAPH_COUNT,
    LIMITATIONS,
    main,
    run_verification,
    sample_warning,
)
from beautyads.graph.connection import GraphConnection
from beautyads.graph.queries import QUESTIONS


class Driver:
    def __init__(self, answers=None, scope=None, feedback=0, error=None, count=1):
        self.calls = []
        self.answers = answers or {}
        self.scope = scope or []
        self.feedback = feedback
        self.error = error or {}
        self.count = count
        self.closed = False

    def execute_query(self, query, *, parameters_, **kwargs):
        self.calls.append((query, parameters_))
        if query in self.error:
            raise self.error[query]
        records = self.answers.get(query, [])
        if query == GRAPH_COUNT:
            records = [{"count": self.count}]
        elif query == CREATIVE_SCOPE:
            records = self.scope
        elif query == FEEDBACK_COUNT:
            records = [{"count": self.feedback}]
        elif query == CERT_COVERAGE:
            records = [{"products": 5, "certified": 2, "unknown": 3}]
        return SimpleNamespace(
            records=records,
            summary=SimpleNamespace(
                counters=SimpleNamespace(nodes_created=0, relationships_created=0)
            ),
        )

    def close(self):
        self.closed = True


def run(driver, **kwargs):
    out = io.StringIO()
    report = run_verification(
        GraphConnection(driver),
        as_of=date(2026, 11, 15),
        out=out,
        advertiser_path=Path("config/advertiser_classes.yaml"),
        **kwargs,
    )
    lines = [json.loads(line) for line in out.getvalue().splitlines()]
    return report, {line["id"]: line for line in lines if "id" in line}, lines


def test_success_and_empty_are_separate_and_feedback_is_skipped():
    driver = Driver(answers={QUESTIONS["CQ-01"].cypher: [{"product": "synthetic"}]})
    summary, rows, _ = run(driver)
    assert summary["hop_compliant"] == len(QUESTIONS) - 1
    assert summary["zero_rows"] == len(QUESTIONS) - 2
    assert rows["CQ-01"]["rows"] == 1 and rows["CQ-01"]["success"]
    assert rows["CQ-12"]["code"] == "SKIPPED_SYNTHETIC_ONLY"
    assert QUESTIONS["CQ-12"].cypher not in [q for q, _ in driver.calls]
    assert rows["CQ-03"]["certification"] == {
        "products": 5,
        "certified": 2,
        "unknown": 3,
    }
    for qid, row in rows.items():
        assert row["limitations"] == list(LIMITATIONS[qid])
        assert row["connected_creatives"] == 0
    assert summary["cost_usd"] == 0


@pytest.mark.parametrize(
    "code, expected",
    [
        ("Neo.ClientError.Statement.SyntaxError", "CQ_SYNTAX_ERROR"),
        ("NEO4J_UNREACHABLE", "NEO4J_UNREACHABLE"),
        ("Neo.ClientError.Security.Unauthorized", "CQ_EXECUTION_ERROR"),
    ],
)
def test_one_failure_does_not_stop_other_questions(code, expected):
    error = RuntimeError("do not expose diagnostics")
    error.code = code
    driver = Driver(error={QUESTIONS["CQ-01"].cypher: error})
    summary, rows, lines = run(driver)
    assert rows["CQ-01"]["code"] == expected
    assert not rows["CQ-01"]["success"] and rows["CQ-02"]["success"]
    assert summary["hop_compliant"] == len(QUESTIONS) - 2
    assert "do not expose" not in str(lines)


def test_coverage_deduplicates_answer_ids_and_only_counts_promoted_answers():
    scope = [
        {"creative_id": "youtube:a", "linked": True},
        {"creative_id": "youtube:b", "linked": False},
        {"creative_id": "youtube:c", "linked": True},
    ]
    driver = Driver(
        scope=scope,
        answers={
            QUESTIONS["CQ-04"].cypher: [
                {"creative_ids": ["youtube:a", "youtube:b", "youtube:a"]},
                {"creative_ids": ["youtube:a"]},
            ]
        },
    )
    _, rows, _ = run(driver)
    assert rows["CQ-04"]["connected_creatives"] == 1
    assert rows["CQ-04"]["scope_product_creatives"] == 3
    assert rows["CQ-04"]["promotes_coverage"] == pytest.approx(1 / 3)
    driver.scope = [{"creative_id": "youtube:a", "linked": False}]
    _, rows, _ = run(driver)
    assert rows["CQ-04"]["connected_creatives"] == 0
    assert rows["CQ-04"]["success"]


@pytest.mark.parametrize(
    "brand, retailer", [(29, 30), (30, 29), (29, 31), (30, 30), (31, 31)]
)
def test_warning_boundary(brand, retailer):
    assert bool(
        sample_warning({"brand_direct": brand, "retailer": retailer, "unknown": 99})
    ) == (min(brand, retailer) < 30)


def test_advertiser_failure_only_skips_cq09(tmp_path):
    out = io.StringIO()
    driver = Driver()
    summary = run_verification(
        GraphConnection(driver),
        as_of=date(2026, 11, 15),
        out=out,
        advertiser_path=tmp_path / "missing",
    )
    rows = [json.loads(line) for line in out.getvalue().splitlines()]
    assert (
        next(r for r in rows if r.get("id") == "CQ-09")["code"]
        == "ADVERTISER_CLASSES_UNREADABLE"
    )
    assert summary["hop_compliant"] == len(QUESTIONS) - 2
    assert QUESTIONS["CQ-09"].cypher not in [q for q, _ in driver.calls]


def test_all_frozen_limit_bullets_are_preserved_verbatim():
    document = Path("docs/COMPETENCY_QUESTIONS.md").read_text()
    bullets = [
        line[2:]
        for line in document.split("한계와 조건", 1)[1].splitlines()
        if line.startswith("- ")
    ]
    assert set(bullets) <= {text for limits in LIMITATIONS.values() for text in limits}


@pytest.mark.parametrize(
    "env,docker,tcp,code",
    [
        ({}, True, True, "ENV_MISSING:NEO4J_PASSWORD"),
        ({"NEO4J_PASSWORD": "test-placeholder"}, False, True, "DOCKER_DOWN"),
        ({"NEO4J_PASSWORD": "test-placeholder"}, True, False, "NEO4J_UNREACHABLE"),
    ],
)
def test_preflight_failure_never_creates_driver(env, docker, tcp, code):
    calls = []
    out = io.StringIO()
    assert (
        main(
            environ=env,
            out=out,
            docker_check=lambda: docker,
            tcp_check=lambda *args: tcp,
            graph_factory=lambda: calls.append(1),
        )
        == 2
    )
    assert code in out.getvalue() and calls == []


def test_empty_graph_and_close():
    driver = Driver(count=0)
    out = io.StringIO()
    assert (
        main(
            environ={"NEO4J_PASSWORD": "test-placeholder"},
            out=out,
            docker_check=lambda: True,
            tcp_check=lambda *args: True,
            graph_factory=lambda: GraphConnection(driver),
        )
        == 2
    )
    assert "GRAPH_EMPTY" in out.getvalue() and "make sync" in out.getvalue()
    assert driver.closed


def test_live_target_keeps_verify_offline():
    text = Path("Makefile").read_text()
    assert "\nlive-cq:\n\tuv run python -m beautyads.eval.cq_verify\n" in text
    assert "live-cq" in text.splitlines()[0]
    assert "live-" not in text.split("verify:\n", 1)[1].split("\n\n", 1)[0]


@pytest.mark.parametrize("brand,retailer", [(29, 31), (30, 30), (31, 29), (31, 31)])
def test_runner_counts_classified_creatives_and_warns_at_boundary(
    tmp_path, brand, retailer
):
    path = tmp_path / "classes.yaml"
    path.write_text(
        "advertisers: [{name: Brand, class: brand_direct}, {name: Shop, class: retailer}]"
    )
    answers = [
        {
            "creative_id": f"tiktok:b{i}",
            "advertiser_name": "ＢＲＡＮＤ ",
            "hook": "question",
        }
        for i in range(brand)
    ]
    answers += [
        {"creative_id": f"tiktok:r{i}", "advertiser_name": "SHOP ", "hook": "problem"}
        for i in range(retailer)
    ]
    answers += [
        {"creative_id": "tiktok:u", "advertiser_name": "absent", "hook": "problem"}
    ]
    driver = Driver(answers={QUESTIONS["CQ-09"].cypher: answers})
    out = io.StringIO()
    summary = run_verification(
        GraphConnection(driver), as_of=date(2026, 11, 15), out=out, advertiser_path=path
    )
    rows = [json.loads(line) for line in out.getvalue().splitlines()]
    row = next(row for row in rows if row.get("id") == "CQ-09")
    assert summary["advertiser_classes"] == {
        "brand_direct": brand,
        "retailer": retailer,
        "unknown": 1,
    }
    assert ("sample_warning" in summary) == (min(brand, retailer) < 30)
    assert ("sample_warning" in row) == (min(brand, retailer) < 30)
    params = next(p for q, p in driver.calls if q == QUESTIONS["CQ-09"].cypher)
    assert params["source"] == "tiktok"


def test_feedback_uses_only_trusted_context_and_is_read_only():
    context = {"tenant_id": "synthetic-tenant"}
    driver = Driver(feedback=1)
    _, rows, _ = run(driver, context=context)
    assert rows["CQ-12"]["success"]
    query, params = next(
        (q, p) for q, p in driver.calls if q == QUESTIONS["CQ-12"].cypher
    )
    assert params["context"] == context
    assert "synthetic-tenant" not in query
    assert all(
        not any(word in q for word in ("MERGE ", "CREATE ", "DELETE ", "SET "))
        for q, _ in driver.calls
    )
    _, rows, _ = run(Driver(feedback=1))
    assert rows["CQ-12"]["code"] == "CQ_CONTEXT_MISSING"


def test_missing_views_are_excluded_and_sources_rank_separately():
    scope = [
        {
            "creative_id": f"{source}:{i}",
            "source": source,
            "channel_brand": "synthetic",
            "views": value,
            "linked": True,
            "published_at": "2026-10-01T00:00:00Z",
        }
        for source, values in [
            ("youtube", [1, 2, 3, 4, None]),
            ("instagram", [100, 200, 300, 400]),
        ]
        for i, value in enumerate(values)
    ]
    answers = [
        dict(
            row,
            category="mask_pack"
            if row["creative_id"].startswith("youtube:")
            else "serum_ampoule",
            hook="question",
        )
        for row in scope
        if row["views"] is not None
    ]
    _, rows, _ = run(Driver(scope=scope, answers={QUESTIONS["CQ-06"].cypher: answers}))
    result = rows["CQ-06"]
    assert result["excluded_missing_views"] == 1
    distribution = result["hook_distribution"]
    assert {(row["source"], row["band"], row["creatives"]) for row in distribution} == {
        ("youtube", "top", 1),
        ("youtube", "bottom", 1),
        ("instagram", "top", 1),
        ("instagram", "bottom", 1),
    }
    assert result["cross_category_hooks"]["question"] == ["mask_pack", "serum_ampoule"]


def test_recent_month_windows_and_leap_year_are_calendar_months():
    from beautyads.graph.queries import months_before

    assert months_before(date(2024, 5, 31), 3) == date(2024, 2, 29)
    records = [
        {"creative_id": "youtube:a", "published_at": "2026-08-15T00:00:00Z"},
        {"creative_id": "youtube:b", "published_at": "2026-08-14T23:59:59Z"},
    ]
    _, rows, _ = run(Driver(answers={QUESTIONS["CQ-15"].cypher: records}))
    assert rows["CQ-15"]["trend"] == {
        "recent_3_months": 1,
        "previous_3_months": 1,
        "change": 0,
    }


@pytest.mark.parametrize("content", ["[", "advertisers: [{name: x, class: invalid}]"])
def test_invalid_advertiser_file_does_not_stop_next_question(tmp_path, content):
    path = tmp_path / "invalid.yaml"
    path.write_text(content)
    out = io.StringIO()
    run_verification(
        GraphConnection(Driver()),
        as_of=date(2026, 11, 15),
        out=out,
        advertiser_path=path,
    )
    lines = [json.loads(line) for line in out.getvalue().splitlines()]
    assert (
        next(r for r in lines if r.get("id") == "CQ-09")["code"]
        == "ADVERTISER_CLASSES_INVALID"
    )
    assert next(r for r in lines if r.get("id") == "CQ-10")["success"]


def test_driver_temporal_values_and_offset_boundaries_are_supported():
    from datetime import UTC, datetime

    from beautyads.eval.cq_verify import _datetime

    class Temporal:
        def to_native(self):
            return datetime(2026, 8, 15, tzinfo=UTC)

    assert _datetime(Temporal()) == datetime(2026, 8, 15, tzinfo=UTC)
    assert _datetime("2026-08-15T08:59:59+09:00") == datetime(
        2026, 8, 14, 23, 59, 59, tzinfo=UTC
    )


def test_multi_product_links_are_counted_separately_in_the_coverage():
    scope = [
        {"creative_id": "youtube:a", "linked": True, "multi_linked": True},
        {"creative_id": "youtube:b", "linked": True, "multi_linked": False},
        {"creative_id": "youtube:c", "linked": False},
    ]
    driver = Driver(
        scope=scope,
        answers={
            QUESTIONS["CQ-04"].cypher: [
                {"creative_ids": ["youtube:a", "youtube:b", "youtube:c"]}
            ]
        },
    )
    _, rows, _ = run(driver)
    row = rows["CQ-04"]
    assert row["connected_creatives"] == 2
    assert row["multi_product_connected_creatives"] == 1
    # Questions without any multi-product link report zero, never a missing key.
    assert rows["CQ-01"]["multi_product_connected_creatives"] == 0


def test_the_scope_query_reads_the_multi_product_relationship_property():
    from beautyads.eval.cq_verify import CREATIVE_SCOPE

    assert "r.multi_product = true" in CREATIVE_SCOPE
