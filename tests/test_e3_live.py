"""Synthetic E3 arms, split isolation, scoring and pre-dispatch guards."""

import inspect
import json
from dataclasses import asdict
from types import SimpleNamespace
from typing import get_type_hints

import pytest
from test_evalset import workspaces_path as workspace_config  # noqa: F401 -- shared synthetic fixture

from beautyads.domain.tools import ToolContext
from beautyads.eval import e3_live as e3
from beautyads.eval.evalset import AnswerItem, QuestionItem, write_jsonl
from beautyads.eval.freeze_guard import RunIdentity
from beautyads.eval.vector_baseline import CorpusDoc

IDENTITY = RunIdentity("code", "prereg", None, "hash")


def question(i=0, split="dev", kind="graph", axes=None):
    return QuestionItem(
        id=f"q{i}",
        split=split,
        tenant_id=f"{split}-brand",
        source_cq="CQ-01",
        axes_used=axes or ["category"],
        needs_human_review=False,
        reviewed=True,
        kind=kind,
        text="synthetic question",
        cq_inputs={},
        answer_type="count",
    )


def truth(i=0):
    return AnswerItem(
        question_id=f"q{i}",
        answer_type="count",
        value=2,
        tolerance_abs=0.0,
        evidence_ids=["youtube:a"],
        confirmed=True,
    )


class Structured:
    model = "gpt-6-luna"

    def __init__(self):
        self.calls = []

    def generate(self, spec, **kw):
        self.calls.append((spec, kw))
        return SimpleNamespace(
            ok=True, value={"count": 2, "items": [], "evidence_ids": ["youtube:a"]}
        )


def arm_options():
    from datetime import date

    generator, calls = Structured(), []

    def chat(**kw):
        calls.append(kw)
        return SimpleNamespace(tool_calls=[])

    def embed(texts, **kw):
        calls.append(dict(texts=texts, **kw))
        return SimpleNamespace(
            vectors=[[1.0, 0.0] for _ in texts],
            input_tokens=1,
            cost_usd=0.01,
            response_shape={"data": []},
        )

    options = {
        "identity": IDENTITY,
        "mode": "dev",
        "arms": ("graph", "vector"),
        "embedding_model": "text-embedding-3-small",
        "docs": [CorpusDoc("youtube:a", "external document instruction")],
        "doc_vecs": [[1.0, 0.0]],
        "embed": embed,
        "chat": chat,
        "structured": generator,
        "tool_runner": lambda *a: pytest.fail("unexpected tool"),
        "context_factory": lambda tenant: ToolContext(
            tenant_id=tenant, as_of=date(2026, 11, 19)
        ),
    }
    return options, generator, calls


def test_run_signature_and_common_spec_prompt_inputs():
    signature = inspect.signature(e3.run)
    assert not any(
        "answer" in n or "path" in n or "truth" in n for n in signature.parameters
    )
    assert get_type_hints(e3.run)["identity"] is RunIdentity
    options, generator, calls = arm_options()
    rows = e3.run([question()], **options)
    assert {r["arm"] for r in rows} == {"graph", "vector"}
    assert all(r["identity"] == asdict(IDENTITY) for r in rows)
    assert len(generator.calls) == 2
    left, right = [kw for _, kw in generator.calls]
    assert left["messages"][0] == right["messages"][0]
    assert left["reasoning_effort"] == right["reasoning_effort"] == "none"
    assert json.loads(left["messages"][1]["content"])["evidence"] == []
    assert "external document instruction" in right["messages"][1]["content"]
    assert "external document instruction" not in right["messages"][0]["content"]
    assert calls[0]["model"] == generator.model


def test_score_count_set_and_evidence():
    assert (
        e3.score_answer(
            e3.E3Answer(count=2, items=[], evidence_ids=["youtube:a", "wrong"]), truth()
        )["evidence_hit_rate"]
        == 0.5
    )
    assert (
        e3.score_answer(e3.E3Answer(count=3, items=[], evidence_ids=[]), truth())[
            "correct"
        ]
        is False
    )
    t = truth().model_copy(
        update={"answer_type": "set", "value": ["a", "b"], "evidence_ids": []}
    )
    assert e3.score_answer(
        e3.E3Answer(count=None, items=[" b ", "a", "a"], evidence_ids=[]), t
    ) == {"correct": True, "evidence_hit_rate": None}


def test_answer_loader_split_before_validation_and_measure_no_leaks(
    tmp_path, monkeypatch, capsys
):
    qs = [question(), question(1, "test")]
    path = tmp_path / "answers"
    write_jsonl(
        path,
        [
            truth(),
            {
                **truth(1).model_dump(),
                "value": "SENTINEL_TEST",
                "evidence_ids": ["SENTINEL_EVIDENCE"],
            },
        ],
    )
    options, generator, calls = arm_options()
    result = e3.measure(
        options["docs"],
        qs,
        answers_path=path,
        models=[options["embedding_model"]],
        embed=options["embed"],
        cache_dir=tmp_path,
    )
    assert result["models"][0]["hit_at_k"] == 1.0
    assert "SENTINEL" not in json.dumps([result, calls, capsys.readouterr().out])
    assert generator.calls == []
    with pytest.raises(Exception, match="^ANSWER_SPLIT_FORBIDDEN$"):
        e3.measure(
            [],
            qs,
            answers_path=path,
            models=[],
            embed=options["embed"],
            split="test",
            cache_dir=tmp_path,
        )


def test_truth_never_enters_run_calls_records_logs_or_exceptions(tmp_path, capsys):
    path = tmp_path / "answers"
    write_jsonl(
        path,
        [
            truth().model_copy(
                update={"value": ["SENTINEL_TRUTH"], "answer_type": "set"}
            )
        ],
    )
    options, generator, calls = arm_options()
    rows = e3.run([question()], **options)
    output = tmp_path / "results"
    write_jsonl(output, rows)
    assert "SENTINEL" not in json.dumps(calls)
    assert "SENTINEL" not in json.dumps([kw for _, kw in generator.calls])
    assert "SENTINEL" not in output.read_text() + capsys.readouterr().out

    def fail(**kw):
        raise RuntimeError("SENTINEL_DIAGNOSTIC")

    options["chat"] = fail
    with pytest.raises(Exception) as caught:
        e3.run([question()], **options)
    assert "SENTINEL" not in str(caught.value)


def test_measure_dry_run_is_free_and_reports_assumption(tmp_path):
    result = e3.measure(
        [CorpusDoc("a", "x" * 2000)],
        [question()],
        answers_path=tmp_path / "absent",
        models=["text-embedding-3-small"],
        embed=lambda *a, **kw: pytest.fail(),
        dry_run=True,
        cache_dir=tmp_path,
    )
    assert result["documents"] == 1 and result["estimated_tokens"] > 0
    assert result["assumption"] == "가정(미실측)"


def test_paired_report_subsets_and_strata(tmp_path):
    qs = [
        question(
            i,
            "test",
            "simple_search" if i < 10 else "graph",
            ["hook_type"] if i < 3 else ["category"],
        )
        for i in range(40)
    ]
    path = tmp_path / "answers"
    write_jsonl(path, [truth(i) for i in range(40)])
    rows = [
        {
            "question_id": q.id,
            "arm": arm,
            "answer": {
                "count": 2 if arm == "graph" else 0,
                "items": [],
                "evidence_ids": [],
            },
            "identity": asdict(IDENTITY),
        }
        for q in qs
        for arm in ("graph", "vector")
    ]
    result = e3.report(rows, qs, answers_path=path, split="test")
    assert result["overall"]["n"] == 40
    assert result["overall"]["decision"] == "graph_adopted"
    assert result["simple_search"]["n"] == 10
    assert result["simple_search"]["decision"] == "undecidable"
    assert result["strata"]["unreliable"]["status"] == "undecidable"
    assert result["strata"]["reliable"]["status"] == "descriptive_only"
    assert result["overall"]["difference_ci"] == [1.0, 1.0]


def test_dev_rejects_test_question_before_calls():
    options, _, calls = arm_options()
    with pytest.raises(Exception, match="WORKSPACE_GROUP_INVALID"):
        e3.run([question(split="test")], **options)
    assert calls == []


def test_wrapped_boundaries_honor_provider_and_purpose_caps(tmp_path):
    from beautyads.settings import Settings

    settings = Settings(
        ledger_path=tmp_path / "ledger", provider_caps_usd={"openai": 0.0}
    )
    calls = []
    boundary = e3.build_calls(
        settings,
        api_key="synthetic",
        embed_fn=lambda *a, **kw: calls.append(kw),
        chat_fn=lambda **kw: calls.append(kw),
        structured_factory=lambda m: SimpleNamespace(
            model=m, generate=lambda *a, **kw: calls.append(kw)
        ),
    )
    for invoke in (
        lambda: boundary.embed(["x"], model="text-embedding-3-small"),
        lambda: boundary.chat(model=e3.ANSWER_MODEL),
        lambda: boundary.structured.generate(None),
    ):
        with pytest.raises(Exception, match="COST_CAP:openai"):
            invoke()
    assert calls == []
    settings = settings.model_copy(update={"provider_caps_usd": {"openai": 100.0}})
    boundary = e3.build_calls(
        settings, api_key="synthetic", embed_fn=lambda *a, **kw: calls.append(kw)
    )
    with pytest.raises(Exception, match="COST_CAP:purpose:embed"):
        boundary.embed(["x" * 8_000_000], model="text-embedding-3-large")
    assert calls == []


def test_final_check_reads_answers_once_run_never_opens_them(
    tmp_path, monkeypatch, request
):
    from functools import partial
    from pathlib import Path

    from test_evalset import synthetic_set
    from test_freeze_guard import FakeGit

    from beautyads.eval import freeze_guard as guard
    from beautyads.eval.evalset import question_set_hash, request_set_hash
    from beautyads.eval.p5_compare import preregistration_committed

    rows = synthetic_set()
    paths = [tmp_path / name for name in ("requests", "questions", "answers")]
    for path, collection in zip(paths, rows, strict=True):
        write_jsonl(path, collection)
    config = request.getfixturevalue("workspace_config")
    prereg = tmp_path / "prereg"
    values = {
        guard.REQUEST_HASH_LABEL: request_set_hash(rows[0]),
        guard.QUESTION_HASH_LABEL: question_set_hash(rows[1], rows[2]),
        **guard.frozen_values(),
        **e3.extra_frozen("text-embedding-3-small"),
    }
    prereg.write_text("\n".join(f"{k}: {v}" for k, v in values.items()))
    git = FakeGit()
    original_open = Path.open
    answer_opens = []

    def watched(path, *a, **kw):
        if path == paths[2]:
            answer_opens.append(inspect.stack()[1].function)
        return original_open(path, *a, **kw)

    monkeypatch.setattr(Path, "open", watched)
    identity = guard.check_run(
        mode="final",
        groups={"test"},
        requests_path=paths[0],
        questions_path=paths[1],
        answers_path=paths[2],
        workspaces_path=config,
        prereg_path=prereg,
        extra=e3.extra_frozen("text-embedding-3-small"),
        run=git,
        committed_fn=partial(preregistration_committed, run=git),
    )
    assert len(answer_opens) == 1
    options, _, _ = arm_options()
    options.update(identity=identity, mode="final")
    questions = [
        QuestionItem.model_validate(q) for q in rows[1] if q["split"] == "test"
    ]
    e3.run(questions, **options)
    assert len(answer_opens) == 1


def test_cli_final_guard_failure_means_no_service_or_model_calls(tmp_path):
    questions = tmp_path / "questions"
    write_jsonl(
        questions,
        [
            question(i, "test", "simple_search" if i < 10 else "graph")
            for i in range(40)
        ],
    )
    calls = []

    def refused(**kw):
        calls.append(kw)
        raise RuntimeError("SENTINEL_GUARD")

    assert (
        e3.main(
            ["run", "--mode", "final"],
            questions_path=questions,
            output_dir=tmp_path,
            check_fn=refused,
            corpus_loader=lambda: pytest.fail("corpus before guard"),
            runtime_factory=lambda *a, **kw: pytest.fail("runtime before guard"),
        )
        == 1
    )
    assert len(calls) == 1
    assert calls[0]["groups"] == {"test"}
    assert calls[0]["extra"] == e3.extra_frozen("text-embedding-3-small")


def test_graph_observations_reach_structured_as_json_data():
    from test_research_agent import Chat, call, reply, result

    options, generator, _ = arm_options()
    options["chat"] = Chat([reply([call()]), reply()])
    options["tool_runner"] = lambda *args: result()
    e3.run([question()], **options)
    graph_messages = generator.calls[0][1]["messages"]
    payload = json.loads(graph_messages[1]["content"])
    assert payload["evidence"]
    assert payload["evidence"][0]["tool"]
    assert "observations" not in graph_messages[0]["content"]
    assert generator.calls[0][0].schema == generator.calls[1][0].schema


def test_measure_selection_truncation_costs_and_first_shape(tmp_path):
    from beautyads.llm.embed import EmbedResult

    docs = [CorpusDoc("youtube:a", "x" * 1600), CorpusDoc("youtube:b", "other")]
    path = tmp_path / "answers"
    write_jsonl(path, [truth()])
    calls = []

    def embed(texts, **kw):
        calls.append((texts, kw))
        return EmbedResult(
            [[1.0, 0.0] for _ in texts],
            10,
            0.01,
            {"data": [{"embedding": [0.1, 0.2, 0.3]}]},
        )

    result = e3.measure(
        docs,
        [question()],
        answers_path=path,
        models=["text-embedding-3-large", "text-embedding-3-small"],
        embed=embed,
        cache_dir=tmp_path,
    )
    assert result["selected_model"] == "text-embedding-3-small"
    assert result["truncated_document_ratio"] == 0.5
    assert result["truncated_dev_evidence_ratio"] == 1.0
    assert all(len(text) <= 1500 for texts, _ in calls for text in texts)
    assert all(
        m["input_tokens"] == 20 and m["cost_usd"] == 0.02 for m in result["models"]
    )
    assert json.loads((tmp_path / "embedding_response_shape.json").read_text())["data"]


def test_evidence_ratio_counts_submitted_ids_and_count_tolerance():
    answer = e3.E3Answer(
        count=3, items=[], evidence_ids=["youtube:a", "youtube:a", "wrong"]
    )
    t = truth().model_copy(update={"tolerance_abs": 1.0})
    score = e3.score_answer(answer, t)
    assert score["correct"] is True
    assert score["evidence_hit_rate"] == pytest.approx(2 / 3)


def test_run_unpriced_model_and_wrong_structured_model_refused_before_calls():
    options, generator, calls = arm_options()
    options["embedding_model"] = "unpriced"
    with pytest.raises(Exception, match="EMBED_MODEL_UNPRICED"):
        e3.run([question()], **options)
    assert calls == [] and generator.calls == []
    options["embedding_model"] = "text-embedding-3-small"
    generator.model = "other"
    with pytest.raises(Exception, match="E3_ANSWER_MODEL_INVALID"):
        e3.run([question()], **options)
    assert calls == [] and generator.calls == []


def test_report_rejects_unpaired_duplicate_or_mixed_identity(tmp_path):
    options, _, _ = arm_options()
    rows = e3.run([question()], **options)
    path = tmp_path / "answers"
    write_jsonl(path, [truth()])
    for bad in (
        rows[:1],
        rows + rows[:1],
        [rows[0], {**rows[1], "identity": {"code_commit": "other"}}],
    ):
        with pytest.raises(Exception, match="^E3_RECORDS_INVALID$"):
            e3.report(bad, [question()], answers_path=path, split="dev")
    result = e3.report(rows, [question()], answers_path=path, split="dev")
    assert result["overall"]["decision"] == "undecidable"


def test_cli_measure_run_report_and_dry_run_with_fake_runtime(tmp_path, capsys):
    from contextlib import contextmanager

    from beautyads.settings import Settings

    questions_path = tmp_path / "questions"
    answers_path = tmp_path / "answers"
    write_jsonl(questions_path, [question()])
    write_jsonl(answers_path, [truth()])
    options, generator, calls = arm_options()
    guards = []

    @contextmanager
    def runtime(settings, **kwargs):
        assert settings.ledger_path == tmp_path / "ledger"
        yield SimpleNamespace(
            **{
                name: options[name]
                for name in (
                    "embed",
                    "chat",
                    "structured",
                    "tool_runner",
                    "context_factory",
                )
            }
        )

    def guard(**kwargs):
        guards.append(kwargs)
        return IDENTITY

    injected = {
        "questions_path": questions_path,
        "answers_path": answers_path,
        "output_dir": tmp_path / "output",
        "check_fn": guard,
        "corpus_loader": lambda: options["docs"],
        "runtime_factory": runtime,
        "settings_fn": lambda: Settings(ledger_path=tmp_path / "ledger"),
    }
    assert e3.main(["measure", "--dry-run"], **injected) == 0
    assert calls == [] and generator.calls == []
    assert "가정(미실측)" in capsys.readouterr().out
    assert e3.main(["measure"], **injected) == 0
    assert (tmp_path / "output" / "measurement.json").exists()
    assert e3.main(["run"], **injected) == 0
    assert e3.main(["report"], **injected) == 0
    assert (tmp_path / "output" / "dev_report.json").exists()
    assert len(guards) == 3
    assert all(g["mode"] == "dev" and g["groups"] == {"dev"} for g in guards)


def test_measure_projects_id_before_deserializing_test_values(tmp_path, monkeypatch):
    path = tmp_path / "answers"
    test_record = {
        **truth(1).model_dump(),
        "value": {"question_id": "q0", "nested": ["SENTINEL_TEST"]},
    }
    write_jsonl(path, [test_record, truth()])
    original = AnswerItem.model_validate_json
    validated = []

    def validate(line):
        assert "SENTINEL" not in line
        validated.append(line)
        return original(line)

    monkeypatch.setattr(AnswerItem, "model_validate_json", validate)
    loaded = e3.read_answers(
        path,
        questions=[question(), question(1, "test")],
        split="dev",
        purpose="measure",
    )
    assert set(loaded) == {"q0"} and len(validated) == 1


def test_stratified_description_never_makes_adoption_decision(tmp_path):
    questions = [question(i, axes=["hook_type"]) for i in range(20)]
    path = tmp_path / "answers"
    write_jsonl(path, [truth(i) for i in range(20)])
    rows = [
        {
            "question_id": q.id,
            "arm": arm,
            "answer": {
                "count": 2 if arm == "graph" else 0,
                "items": [],
                "evidence_ids": [],
            },
            "identity": asdict(IDENTITY),
        }
        for q in questions
        for arm in ("graph", "vector")
    ]
    result = e3.report(rows, questions, answers_path=path, split="dev")
    assert result["overall"]["decision"] == "graph_adopted"
    assert result["strata"]["unreliable"]["status"] == "descriptive_only"
    assert result["strata"]["unreliable"]["decision"] == "undecidable"
