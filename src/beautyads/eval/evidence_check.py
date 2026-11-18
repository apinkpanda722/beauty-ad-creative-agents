"""User-run read-only CQ-06 parity and evidence-scope counts, with zero model cost."""

import argparse
import json
import sys
from datetime import UTC, date, datetime
from typing import TextIO

from beautyads.domain.evidence import CertificationKind
from beautyads.domain.labels import Category
from beautyads.domain.tools import GraphReader
from beautyads.eval.cq_verify import cq_preflight, error_code
from beautyads.graph.connection import connect_graph
from beautyads.graph.evidence_queries import (
    axis_rows_query,
    certification_parameters,
    certified_by_kind_query,
    evidence_parameters,
)
from beautyads.graph.queries import QUESTIONS, question_parameters
from beautyads.pipeline.preflight import docker_running, tcp_reachable
from beautyads.settings import DEFAULT_ENV_FILE


def _pairs(rows):
    return {(row.get("creative_id"), row.get("hook")) for row in rows}


def run_check(graph: GraphReader, *, as_of: date, out: TextIO) -> int:
    """Count both differences without assuming category sources agree."""
    frozen = QUESTIONS["CQ-06"]
    cq_params = question_parameters(frozen, as_of=as_of)
    cq_rows = graph.run(frozen.cypher, cq_params).records
    for category in Category:
        if category == Category.other:
            continue
        params = evidence_parameters(category=category, as_of=as_of)
        params["sources"] = cq_params["sources"]
        linked_rows = graph.run(
            axis_rows_query("hook_type", "product_link"), params
        ).records
        expected = _pairs([r for r in cq_rows if r.get("category") == category])
        linked = _pairs(linked_rows)
        report = {"category": category.value, "cost_usd": 0}
        if linked != expected:
            report.update(
                code="CQ06_MISMATCH",
                cq_only_count=len(expected - linked),
                query_only_count=len(linked - expected),
            )
            print(json.dumps(report, ensure_ascii=False), file=out)
            return 3
        label_rows = graph.run(
            axis_rows_query("hook_type", "creative_label"), params
        ).records
        label_ids = {r.get("creative_id") for r in label_rows}
        linked_ids = {r.get("creative_id") for r in linked_rows}
        report.update(
            code="OK",
            creative_label_count=len(label_rows),
            product_link_count=len(linked_rows),
            intersection_count=len(label_ids & linked_ids),
            creative_label_only_count=len(label_ids - linked_ids),
            product_link_only_count=len(linked_ids - label_ids),
        )
        print(json.dumps(report, ensure_ascii=False), file=out)
    return 0


def run_certification_check(graph: GraphReader, *, out: TextIO) -> int:
    """Compare product/certification sets; never print product data or diagnostics."""
    for kind in CertificationKind:
        params = certification_parameters(cert=kind)
        cq_rows = graph.run(QUESTIONS["CQ-03"].cypher, params).records
        rows = graph.run(certified_by_kind_query(), params).records
        expected = {(row.get("product"), row.get("certification")) for row in cq_rows}
        actual = {(row.get("product"), row.get("certification")) for row in rows}
        mismatch = expected != actual
        report = {
            "certification": kind.value,
            "code": "CQ03_MISMATCH" if mismatch else "OK",
            "cost_usd": 0,
            "cq_count": len(expected),
            "query_count": len(actual),
            "cq_only_count": len(expected - actual),
            "query_only_count": len(actual - expected),
        }
        print(json.dumps(report, ensure_ascii=False), file=out)
        if mismatch:
            return 3
    return 0


def main(
    argv=None,
    *,
    environ=None,
    out=None,
    docker_check=docker_running,
    tcp_check=tcp_reachable,
    graph_factory=None,
    as_of=None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--certifications",
        action="store_true",
        help="기존 점검 뒤 세 인증 종류의 CQ-03 제품 집합 일치를 추가 점검",
    )
    args = parser.parse_args(argv)
    out = sys.stdout if out is None else out
    env_file = DEFAULT_ENV_FILE if environ is None else None
    problem = cq_preflight(
        environ=environ,
        env_file=env_file,
        docker_check=docker_check,
        tcp_check=tcp_check,
    )
    if problem:
        print(f"PREFLIGHT_FAILED {problem}", file=out)
        return 2
    graph = None
    try:
        graph = (
            graph_factory()
            if graph_factory
            else connect_graph(environ=environ, env_file=env_file)
        )
        code = run_check(graph, as_of=as_of or datetime.now(UTC).date(), out=out)
        if code == 0 and args.certifications:
            return run_certification_check(graph, out=out)
        return code
    except Exception as error:  # noqa: BLE001 -- never print connection diagnostics
        print(f"PREFLIGHT_FAILED {error_code(error)}", file=out)
        return 2
    finally:
        if graph is not None:
            try:
                graph.close()
            except Exception:  # noqa: BLE001, S110 -- close diagnostics may include secrets
                pass


if __name__ == "__main__":
    raise SystemExit(main())
