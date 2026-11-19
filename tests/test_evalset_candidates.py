"""Offline candidate generation and human review using only synthetic answers."""

import ast
import csv
import io
import json
import math
from collections import Counter
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from beautyads.domain.labels import Category
from beautyads.eval import evalset as sets
from beautyads.eval import evalset_candidates as candidates
from beautyads.graph.queries import Question
from beautyads.sources.workspaces import load_workspaces

DAY = date(2026, 11, 19)


@pytest.fixture
def synthetic(monkeypatch):
    specs = {
        "CQ-01": Question(
            "SYNTHETIC_GRAPH", ("category", "claim"), 2, ("category", "claim")
        ),
        "CQ-04": Question(
            "SYNTHETIC_COUNT", ("category", "claim"), 3, ("category", "claim")
        ),
        "CQ-11": Question(
            "SYNTHETIC_SIMPLE",
            ("category", "claim", "concern"),
            1,
            ("category", "claim", "concern"),
        ),
        "CQ-12": Question("SYNTHETIC_CONTEXT", ("context",), 1),
    }
    monkeypatch.setattr(candidates, "QUESTIONS", specs)
    rows = candidates.parse_cq_table(
        "\n".join(
            f"| {qid} | 합성 질문 | 1+2 | 합성 경로 | 리서치, 기획 |" for qid in specs
        )
    )
    workspaces = load_workspaces(Path("config/workspaces.yaml"))
    return rows, workspaces


class FakeGraph:
    def __init__(self, rows=None, fail=None):
        self.rows = (
            rows
            if rows is not None
            else [
                {
                    "product": "synthetic-b",
                    "creative_ids": ["synthetic:2", "synthetic:1"],
                },
                {"product": "synthetic-a", "creative_id": "synthetic:1"},
                {"product": "synthetic-b"},
                {"absent": None},
            ]
        )
        self.fail = fail
        self.calls = []
        self.closed = False

    def run(self, cypher, params):
        self.calls.append((cypher, params))
        if self.fail:
            raise self.fail
        return SimpleNamespace(records=self.rows)

    def close(self):
        self.closed = True


def combined(synthetic, graph=None):
    rows, workspaces = synthetic
    requests = candidates.build_request_candidates(rows, workspaces)
    questions = candidates.build_question_candidates(
        rows, workspaces, graph=graph or FakeGraph(), as_of=DAY
    )
    return candidates.Candidates(
        requests=requests.requests,
        questions=questions.questions,
        answers=questions.answers,
    )


def review_rows(bundle):
    rows = candidates.review_rows(bundle)
    return [
        {
            **row,
            "decision": "O",
            "edited_text": "-",
            "answer_confirmed": "Y",
            "note": "합성 확인",
        }
        for row in rows
    ]


def test_parse_only_document_table_ids():
    rows = candidates.parse_cq_table("""
| ID | 질문 | 쓰는 층 | 경로 | 쓰이는 곳 |
|---|---|---|---|---|
| CQ-42 | 합성 질문 | 1 | 경로 | 리서치 |
CQ-01 is prose
| CQ-42 | 답 | 0 | 0 | 상태 | extra |
""")
    assert len(rows) == 1
    assert rows[0]["id"] == "CQ-42"
    assert set(rows[0]) == {"id", "question", "layers", "path", "usage"}


def test_workspace_category_matches_configuration():
    workspaces = load_workspaces(Path("config/workspaces.yaml"))
    assert set(candidates.WORKSPACE_CATEGORY) == {
        w.tenant_id for w in workspaces if w.group in {"dev", "test"}
    }
    assert set(candidates.WORKSPACE_CATEGORY.values()) <= {v.value for v in Category}


def test_request_counts_strata_split_and_determinism(synthetic):
    rows, workspaces = synthetic
    result = candidates.build_request_candidates(rows, workspaces)
    assert result == candidates.build_request_candidates(rows, workspaces)
    assert candidates.CANDIDATE_FACTOR == 1.5
    assert candidates.CANDIDATE_DIR == Path("data/interim/evalset")
    assert Counter(r.split for r in result.requests) == {
        "dev": math.ceil(10 * 1.5),
        "test": math.ceil(20 * 1.5),
    }
    for split, reliable, unreliable in (("dev", 10, 5), ("test", 20, 10)):
        items = [r for r in result.requests if r.split == split]
        assert Counter(sets.stratum(r.axes_used) for r in items) == {
            "reliable": reliable,
            "unreliable": unreliable,
        }
        assert all(r.tenant_id.startswith(split + "-") for r in items)
    for r in result.requests:
        assert "기획안 1안" in r.message
        assert r.needs_human_review and not r.reviewed
        assert set(r.axes_used) <= set(sets.AXIS_NAMES)
        assert r.source_cq != "CQ-12"
    assert not any(result.shortages.values())


def test_request_unknown_values_and_ineligible_rows_are_not_invented(synthetic):
    rows, workspaces = synthetic
    for selected, briefs in (
        ([], None),
        (rows, [{"category": "unknown", "claim": "unknown"}]),
    ):
        kwargs = {} if briefs is None else {"briefs": briefs}
        result = candidates.build_request_candidates(selected, workspaces, **kwargs)
        assert not result.requests
        assert result.shortages == {"requests_dev": 15, "requests_test": 30}
    result = candidates.build_request_candidates(
        rows, workspaces, briefs=[{"category": "sun_care", "claim": "soothing"}]
    )
    assert len({(r.tenant_id, r.message) for r in result.requests}) == len(
        result.requests
    )


def test_questions_counts_round_robin_and_disjoint_combinations(synthetic):
    rows, workspaces = synthetic
    graph = FakeGraph()
    result = candidates.build_question_candidates(
        rows, workspaces, graph=graph, as_of=DAY
    )
    again = candidates.build_question_candidates(
        rows, workspaces, graph=FakeGraph(), as_of=DAY
    )
    assert result == again
    assert Counter(q.split for q in result.questions) == {"dev": 15, "test": 60}
    assert (
        sum(q.split == "test" and q.kind == "simple_search" for q in result.questions)
        == 15
    )
    assert len(graph.calls) == result.query_count == len(result.questions)
    assert len(result.answers) == len(result.questions)
    signatures = {
        (q.source_cq, json.dumps(q.cq_inputs, sort_keys=True)) for q in result.questions
    }
    assert len(signatures) == len(result.questions)
    for split in ("dev", "test"):
        graph_counts = Counter(
            q.source_cq
            for q in result.questions
            if q.split == split and q.kind == "graph"
        )
        assert max(graph_counts.values()) - min(graph_counts.values()) <= 1
    for q in result.questions:
        assert q.source_cq != "CQ-12"
        assert q.kind == (
            "simple_search" if candidates.QUESTIONS[q.source_cq].hops <= 1 else "graph"
        )
        assert set(q.axes_used) <= set(sets.AXIS_NAMES)
        assert q.tenant_id.startswith(q.split + "-")
    assert not any(result.shortages.values())


def test_missing_pool_reports_shortages_without_duplicates(synthetic, monkeypatch):
    rows, workspaces = synthetic
    monkeypatch.setattr(
        candidates, "QUESTIONS", {"CQ-01": Question("SYNTHETIC", (), 2)}
    )
    result = candidates.build_question_candidates(
        rows, workspaces, graph=FakeGraph(), as_of=DAY
    )
    assert len(result.questions) == 1
    assert result.shortages == {
        "questions_dev": 14,
        "questions_test_graph": 45,
        "questions_test_simple_search": 15,
    }


@pytest.mark.parametrize(
    "failure,code",
    [
        (ValueError("CQ_INPUT_INVALID"), "CQ_INPUT_INVALID"),
        (TimeoutError("PRIVATE_DIAGNOSTIC"), "NEO4J_UNREACHABLE"),
        (RuntimeError("PRIVATE_DIAGNOSTIC"), "CQ_EXECUTION_ERROR"),
    ],
)
def test_failed_candidates_are_excluded_and_counted(
    synthetic, monkeypatch, failure, code
):
    rows, workspaces = synthetic
    if code == "CQ_INPUT_INVALID":

        def invalid(*args, **kwargs):
            raise failure

        monkeypatch.setattr(candidates, "question_parameters", invalid)
        graph = FakeGraph()
    else:
        graph = FakeGraph(fail=failure)
    result = candidates.build_question_candidates(
        rows, workspaces, graph=graph, as_of=DAY
    )
    assert not result.questions and not result.answers
    assert set(result.errors) == {code}
    assert result.errors[code] > 0
    assert result.query_count == len(graph.calls)
    assert result.shortages["questions_dev"] == 15


def test_answers_use_fixed_query_parameters_and_safe_rows(synthetic, monkeypatch):
    bundle = combined(synthetic)
    question = bundle.questions[0]
    calls = []

    def parameters(spec, **kwargs):
        calls.append((spec, kwargs))
        return {"SYNTHETIC_PARAM": True}

    monkeypatch.setattr(candidates, "question_parameters", parameters)
    graph = FakeGraph()
    answer = candidates.compute_answer(
        graph, replace_question(question, answer_type="set"), as_of=DAY
    )
    assert answer.value == ["synthetic-a", "synthetic-b"]
    assert answer.evidence_ids == ["synthetic:1", "synthetic:2"]
    assert not answer.confirmed
    assert graph.calls == [
        (candidates.QUESTIONS[question.source_cq].cypher, {"SYNTHETIC_PARAM": True})
    ]
    assert calls[0][1] == {"as_of": DAY, "inputs": question.cq_inputs}
    count = candidates.compute_answer(
        graph, replace_question(question, answer_type="count"), as_of=DAY
    )
    assert count.value == len(graph.rows)


def replace_question(q, **updates):
    return sets.QuestionItem.model_validate({**q.model_dump(), **updates})


def test_no_model_imports_or_new_cypher():
    tree = ast.parse(Path(candidates.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = (
                [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else [a.name for a in node.names]
            )
            assert all(
                not any(
                    part in name.split(".")
                    for part in ("llm", "litellm", "openai", "anthropic", "google")
                )
                for name in names
            )
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert "MATCH (" not in node.value and "RETURN " not in node.value


def test_review_preserves_frozen_fields_excludes_x_and_n(synthetic):
    bundle = combined(synthetic)
    original = bundle.questions[0]
    rows = review_rows(bundle)
    by_id = {r["item_id"]: r for r in rows}
    by_id[original.id].update(decision="수정", edited_text="합성 수정 질문")
    by_id[bundle.requests[0].id].update(
        decision="수정", edited_text="합성 수정 기획안 1안"
    )
    by_id[bundle.questions[1].id]["decision"] = "X"
    by_id[bundle.questions[2].id]["answer_confirmed"] = "N"
    result = candidates.apply_review(bundle, rows)
    requests, questions, answers = result
    changed = next(q for q in questions if q.id == original.id)
    assert changed.text == by_id[original.id]["edited_text"]
    assert (
        changed.axes_used == original.axes_used
        and changed.source_cq == original.source_cq
    )
    assert {q.id for q in questions}.isdisjoint(
        {bundle.questions[1].id, bundle.questions[2].id}
    )
    assert all(a.confirmed for a in answers)
    assert (
        next(a for a in answers if a.question_id == original.id).value
        == bundle.answers[0].value
    )
    assert all(r.reviewed and not r.needs_human_review for r in [*requests, *questions])
    assert requests[0].message == by_id[bundle.requests[0].id]["edited_text"]
    assert set(result.shortages) == {
        "requests_dev",
        "requests_test",
        "questions_dev",
        "questions_test_graph",
        "questions_test_simple_search",
    }


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("axes_used", "angle", "REVIEW_IMMUTABLE_MISMATCH"),
        ("source_cq", "CQ-999", "REVIEW_IMMUTABLE_MISMATCH"),
        ("answer_summary", "altered", "REVIEW_IMMUTABLE_MISMATCH"),
        ("decision", "", "REVIEW_INCOMPLETE"),
        ("decision", "yes", "REVIEW_INVALID"),
        ("answer_confirmed", "", "REVIEW_INCOMPLETE"),
        ("note", "", "REVIEW_INCOMPLETE"),
    ],
)
def test_review_rejects_invalid_or_altered_sheet(synthetic, field, value, code):
    bundle = combined(synthetic)
    rows = review_rows(bundle)
    rows[0][field] = value
    with pytest.raises(sets.EvalsetError, match=f"^{code}$"):
        candidates.apply_review(bundle, rows)


def test_sheet_columns_instructions_and_hash_guard(synthetic, tmp_path):
    bundle = combined(synthetic)
    candidates.write_review_sheet(bundle, tmp_path)
    with (tmp_path / "review_sheet.csv").open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        assert tuple(reader.fieldnames) == candidates.REVIEW_COLUMNS
        assert len(list(reader)) == len(bundle.requests) + len(bundle.questions)
    instructions = (tmp_path / "review_instructions.md").read_text(encoding="utf-8")
    assert all(
        term in instructions for term in ("칸의 뜻", "기준", "예시", "기록 방법")
    )
    assert sets.request_set_hash(bundle.requests) in instructions
    assert sets.question_set_hash(bundle.questions, bundle.answers) in instructions


def test_dry_run_never_checks_or_connects(synthetic, tmp_path):
    rows, workspaces = synthetic

    def forbidden():
        pytest.fail("dry-run must not check services or connect")

    out = io.StringIO()
    assert (
        candidates.main(
            ["generate", "--dry-run"],
            out=out,
            cq_rows=rows,
            workspaces=workspaces,
            check=forbidden,
            graph_factory=forbidden,
            candidate_dir=tmp_path,
        )
        == 0
    )
    assert "모델 호출 0건" in out.getvalue()
    assert "그래프 읽기 전용 질의 75건(가정, 미실측)" in out.getvalue()
    assert not list(tmp_path.iterdir())


def generate_files(synthetic, tmp_path):
    rows, workspaces = synthetic
    graph = FakeGraph()
    assert (
        candidates.main(
            ["generate"],
            cq_rows=rows,
            workspaces=workspaces,
            graph_factory=lambda: graph,
            check=lambda: None,
            candidate_dir=tmp_path,
            as_of=DAY,
            out=io.StringIO(),
        )
        == 0
    )
    assert graph.closed
    return graph


def test_generate_writes_only_five_candidate_files(synthetic, tmp_path):
    generate_files(synthetic, tmp_path)
    assert {p.name for p in tmp_path.iterdir()} == {
        "requests_candidates.jsonl",
        "questions_candidates.jsonl",
        "answers_candidates.jsonl",
        "review_sheet.csv",
        "review_instructions.md",
    }
    requests = sets.read_jsonl(tmp_path / "requests_candidates.jsonl")
    questions = sets.read_jsonl(tmp_path / "questions_candidates.jsonl")
    answers = sets.read_jsonl(tmp_path / "answers_candidates.jsonl")
    sets.validate_set(requests, questions, answers, final=False)


@pytest.mark.parametrize(
    "tamper,expected",
    [("hash", "EVALSET_HASH_MISMATCH"), ("validation", "EVALSET_ITEM_INVALID")],
)
def test_finalize_errors_are_fixed_and_do_not_write(
    synthetic, tmp_path, tamper, expected
):
    generate_files(synthetic, tmp_path)
    path = tmp_path / "requests_candidates.jsonl"
    rows = sets.read_jsonl(path)
    rows[0]["message"] = "PRIVATE_DIAGNOSTIC" if tamper == "hash" else ""
    sets.write_jsonl(path, rows)
    out = io.StringIO()
    destination = tmp_path / "final"
    assert (
        candidates.main(
            ["finalize"], candidate_dir=tmp_path, final_dir=destination, out=out
        )
        == 2
    )
    assert out.getvalue().strip() == expected
    assert not destination.exists()


def test_finalize_shortage_does_not_call_final_validation(
    synthetic, tmp_path, monkeypatch
):
    generate_files(synthetic, tmp_path)
    bundle = candidates.load_candidates(tmp_path)
    rows = review_rows(bundle)
    for row in rows:
        row["decision"] = "X"
    with (tmp_path / "review_sheet.csv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=candidates.REVIEW_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    real_validate = candidates.validate_set

    def validate(*args, **kwargs):
        assert kwargs["final"] is False
        return real_validate(*args, **kwargs)

    monkeypatch.setattr(candidates, "validate_set", validate)
    destination = tmp_path / "final"
    out = io.StringIO()
    assert (
        candidates.main(
            ["finalize"], candidate_dir=tmp_path, final_dir=destination, out=out
        )
        == 3
    )
    assert "shortages" in out.getvalue()
    assert not destination.exists()


def write_review_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=candidates.REVIEW_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def test_finalize_validates_exact_reviewed_set_before_writing(
    synthetic, tmp_path, monkeypatch
):
    generate_files(synthetic, tmp_path)
    bundle = candidates.load_candidates(tmp_path)
    rows = review_rows(bundle)
    limits = {
        ("request", "dev"): 10,
        ("request", "test"): 20,
        ("graph", "dev"): 10,
        ("graph", "test"): 30,
        ("simple_search", "test"): 10,
    }
    counts = Counter()
    for row in rows:
        key = (row["kind"], row["split"])
        counts[key] += 1
        if counts[key] > limits.get(key, 0):
            row["decision"] = "X"
    write_review_csv(tmp_path / "review_sheet.csv", rows)
    real_validate = candidates.validate_set
    validations = []

    def validate(*args, **kwargs):
        validations.append(kwargs["final"])
        return real_validate(*args, **kwargs)

    monkeypatch.setattr(candidates, "validate_set", validate)

    def forbidden():
        pytest.fail("finalize must not access graph services")

    destination = tmp_path / "final"
    out = io.StringIO()
    assert (
        candidates.main(
            ["--finalize"],
            candidate_dir=tmp_path,
            final_dir=destination,
            out=out,
            check=forbidden,
            graph_factory=forbidden,
        )
        == 0
    )
    assert validations == [False, True]
    requests, questions, answers = (
        sets.read_jsonl(destination / name)
        for name in ("requests.jsonl", "questions.jsonl", "answers.jsonl")
    )
    real_validate(requests, questions, answers, final=True)
    assert sets.request_set_hash(requests) in out.getvalue()
    assert sets.question_set_hash(questions, answers) in out.getvalue()


def test_finalize_overcount_returns_only_fixed_validation_code(synthetic, tmp_path):
    generate_files(synthetic, tmp_path)
    write_review_csv(
        tmp_path / "review_sheet.csv", review_rows(candidates.load_candidates(tmp_path))
    )
    destination = tmp_path / "final"
    out = io.StringIO()
    assert (
        candidates.main(
            ["finalize"], candidate_dir=tmp_path, final_dir=destination, out=out
        )
        == 2
    )
    assert out.getvalue().strip() == "EVALSET_COUNT_INVALID"
    assert not destination.exists()


@pytest.mark.parametrize("change", ["duplicate", "missing", "unknown", "blank_edit"])
def test_review_rejects_incomplete_mapping(synthetic, change):
    bundle = combined(synthetic)
    rows = review_rows(bundle)
    if change == "duplicate":
        rows.append(dict(rows[0]))
    elif change == "missing":
        rows.pop()
    elif change == "unknown":
        rows[0]["item_id"] = "SYNTHETIC_UNKNOWN"
    else:
        rows[0].update(decision="수정", edited_text="-")
    with pytest.raises(sets.EvalsetError, match="^REVIEW_(INVALID|INCOMPLETE)$"):
        candidates.apply_review(bundle, rows)


def test_preflight_failure_does_not_connect_or_write(synthetic, tmp_path):
    rows, workspaces = synthetic

    def forbidden():
        pytest.fail("failed preflight must not connect")

    out = io.StringIO()
    assert (
        candidates.main(
            ["generate"],
            cq_rows=rows,
            workspaces=workspaces,
            check=lambda: "DOCKER_DOWN",
            graph_factory=forbidden,
            candidate_dir=tmp_path,
            out=out,
        )
        == 2
    )
    assert out.getvalue().strip() == "PREFLIGHT_FAILED DOCKER_DOWN"
    assert not list(tmp_path.iterdir())


def test_partial_request_pool_reports_actual_deficit(synthetic, monkeypatch):
    rows, workspaces = synthetic
    monkeypatch.setattr(candidates, "_REQUEST_AXES", {"basic": ["category"]})
    result = candidates.build_request_candidates(
        rows[:1], workspaces, briefs=[{"category": "sun_care", "claim": "soothing"}]
    )
    assert Counter(r.split for r in result.requests) == {"dev": 1, "test": 1}
    assert result.shortages == {"requests_dev": 14, "requests_test": 29}


def test_only_documented_questions_and_json_safe_answers(synthetic, monkeypatch):
    rows, workspaces = synthetic
    result = candidates.build_question_candidates(
        rows[:1], workspaces, graph=FakeGraph(), as_of=DAY
    )
    assert {q.source_cq for q in result.questions} == {rows[0]["id"]}
    seen = []

    def safe(value):
        seen.append(value)
        return [{"number": 9, "name": "synthetic-value", "creative_id": None}]

    monkeypatch.setattr(candidates, "to_json_safe", safe)
    graph = FakeGraph()
    answer = candidates.compute_answer(graph, result.questions[0], as_of=DAY)
    assert seen == [graph.rows]
    assert answer.value == ["synthetic-value"] and not answer.evidence_ids
