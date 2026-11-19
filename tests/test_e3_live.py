"""Synthetic E3 arms, split isolation, scoring and pre-dispatch guards."""

import inspect
import json
from dataclasses import asdict
from types import SimpleNamespace
from typing import get_type_hints

import pytest
from test_evalset import workspaces_path as workspace_config  # noqa: F401 -- shared synthetic fixture
from test_evalset_candidates import synthetic as candidate_synthetic  # noqa: F401 -- shared synthetic fixture

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


@pytest.mark.parametrize("command", ["measure", "run", "report"])
@pytest.mark.parametrize(
    "flags",
    [
        ["--questions", "SENTINEL_PATH"],
        ["--answers", "SENTINEL_PATH"],
        ["--questions", "SENTINEL_Q", "--answers", "SENTINEL_A"],
    ],
)
def test_final_path_options_rejected_before_any_work(
    monkeypatch, capsys, command, flags
):
    from pathlib import Path

    def forbidden(*args, **kwargs):
        pytest.fail("path option must be rejected before I/O or dispatch")

    monkeypatch.setattr(Path, "open", forbidden)
    assert (
        e3.main(
            [command, "--mode", "final", *flags],
            check_fn=forbidden,
            corpus_loader=forbidden,
            runtime_factory=forbidden,
            settings_fn=forbidden,
        )
        == 1
    )
    assert json.loads(capsys.readouterr().out) == {"code": "E3_PATH_OPTION_FORBIDDEN"}


def fake_cli_options(tmp_path):
    from contextlib import contextmanager

    from beautyads.settings import Settings

    options, generator, calls = arm_options()
    guards = []

    def guard(**kwargs):
        guards.append(kwargs)
        return IDENTITY

    @contextmanager
    def runtime(*args, **kwargs):
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

    return (
        {
            "output_dir": tmp_path / "output",
            "check_fn": guard,
            "corpus_loader": lambda: options["docs"],
            "runtime_factory": runtime,
            "settings_fn": lambda: Settings(ledger_path=tmp_path / "ledger"),
        },
        options,
        generator,
        calls,
        guards,
    )


def test_final_default_paths_only_with_synthetic_file_routing(tmp_path, monkeypatch):
    from pathlib import Path

    paths = {
        e3.QUESTIONS_PATH: tmp_path / "questions",
        e3.ANSWERS_PATH: tmp_path / "answers",
    }
    write_jsonl(
        paths[e3.QUESTIONS_PATH],
        [
            question(i, "test", "simple_search" if i < 10 else "graph")
            for i in range(40)
        ],
    )
    write_jsonl(paths[e3.ANSWERS_PATH], [truth(i) for i in range(40)])
    injected, _, _, _, guards = fake_cli_options(tmp_path)
    original = Path.open
    opened = []

    def routed(path, *args, **kwargs):
        if path in paths:
            opened.append(path)
            return original(paths[path], *args, **kwargs)
        assert "data/" not in str(path)
        return original(path, *args, **kwargs)

    def guard(**kwargs):
        guards.append(kwargs)
        # Stand in for check_run's final answer read, without any real data.
        with kwargs["answers_path"].open() as source:
            assert source.read()
        return IDENTITY

    injected["check_fn"] = guard
    monkeypatch.setattr(Path, "open", routed)
    assert e3.main(["run", "--mode", "final"], **injected) == 0
    assert opened == [e3.QUESTIONS_PATH, e3.ANSWERS_PATH]
    assert guards[0]["questions_path"] == e3.QUESTIONS_PATH
    assert guards[0]["answers_path"] == e3.ANSWERS_PATH


@pytest.mark.parametrize("selected", ["questions", "answers", "both"])
def test_dev_cli_uses_optional_paths_and_keeps_injected_defaults(
    tmp_path, monkeypatch, capsys, selected
):
    from pathlib import Path

    from beautyads.eval.evalset import question_set_hash

    injected, _, _, _, guards = fake_cli_options(tmp_path)
    flags = []
    expected = {}
    for name, rows in (("questions", [question()]), ("answers", [truth()])):
        path = tmp_path / name
        write_jsonl(path, rows)
        expected[name + "_path"] = path
        if selected in (name, "both"):
            flags.extend(["--" + name, str(path)])
            injected[name + "_path"] = tmp_path / ("unused_" + name)
        else:
            injected[name + "_path"] = path
    original = Path.open
    opened = []

    def watched(path, *args, **kwargs):
        assert path not in {e3.QUESTIONS_PATH, e3.ANSWERS_PATH}
        assert not path.name.startswith("unused_")
        if path in expected.values():
            opened.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", watched)
    assert e3.main(["measure", *flags], **injected) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["dev_question_hash"] == question_set_hash([question()], [truth()])
    assert opened == [expected["questions_path"], expected["answers_path"]]
    assert all(guards[0][key] == value for key, value in expected.items())
    measurement = json.loads((tmp_path / "output" / "measurement.json").read_text())
    assert measurement == result


def test_dev_finalize_and_measure_hash_match_without_model_input_leaks(
    request, tmp_path, capsys
):
    import io

    from test_evalset_candidates import (
        generate_files,
        split_review_rows,
        write_review_csv,
    )

    from beautyads.eval import evalset as sets
    from beautyads.eval import evalset_candidates as candidates

    candidate_dir = tmp_path / "candidates"
    generate_files(request.getfixturevalue("candidate_synthetic"), candidate_dir)
    bundle = candidates.load_candidates(candidate_dir)
    bundle.questions = [
        q.model_copy(update={"answer_type": "set"}) if q.split == "dev" else q
        for q in bundle.questions
    ]
    dev_ids = {q.id for q in bundle.questions if q.split == "dev"}
    bundle.answers = [
        a.model_copy(
            update={
                "answer_type": "set",
                "value": ["SENTINEL_DEV_TRUTH"],
                "evidence_ids": ["SENTINEL_DEV_EVIDENCE"],
            }
        )
        if a.question_id in dev_ids
        else a
        for a in bundle.answers
    ]
    for name, rows in (
        ("requests", bundle.requests),
        ("questions", bundle.questions),
        ("answers", bundle.answers),
    ):
        write_jsonl(candidate_dir / f"{name}_candidates.jsonl", rows)
    candidates.write_review_sheet(bundle, candidate_dir)
    write_review_csv(
        candidate_dir / "review_sheet.csv", split_review_rows(bundle, dev_only=True)
    )
    out = io.StringIO()
    assert (
        candidates.main(
            ["finalize", "--split", "dev"],
            candidate_dir=candidate_dir,
            final_dir=tmp_path / "final",
            out=out,
        )
        == 0
    )
    hashes = json.loads(out.getvalue().splitlines()[1])
    dev_dir = candidate_dir / "dev"
    qs = [
        QuestionItem.model_validate(r)
        for r in sets.read_jsonl(dev_dir / "questions.jsonl")
    ]
    answers = [
        AnswerItem.model_validate(r) for r in sets.read_jsonl(dev_dir / "answers.jsonl")
    ]
    injected, options, generator, calls, _ = fake_cli_options(tmp_path)
    assert (
        e3.main(
            [
                "measure",
                "--questions",
                str(dev_dir / "questions.jsonl"),
                "--answers",
                str(dev_dir / "answers.jsonl"),
            ],
            **injected,
        )
        == 0
    )
    measured = json.loads(capsys.readouterr().out)
    assert (
        measured["dev_question_hash"]
        == hashes["dev_question_hash"]
        == sets.question_set_hash(qs, answers)
    )
    e3.run(qs, **options)
    inputs = json.dumps([calls, [kw for _, kw in generator.calls]])
    assert "SENTINEL_DEV" not in inputs
    assert all(value not in inputs for value in hashes.values())


def test_measure_dry_run_never_reads_answers_or_emits_hash(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("dry-run must not read answers")

    monkeypatch.setattr(e3, "read_answers", forbidden)
    result = e3.measure(
        [],
        [question()],
        answers_path=tmp_path / "absent",
        models=["text-embedding-3-small"],
        embed=forbidden,
        dry_run=True,
        cache_dir=tmp_path,
    )
    assert "dev_question_hash" not in result


@pytest.mark.parametrize(
    "items,expected",
    [
        (["a", "b"], (1, 1, 1)),
        (["a", "c"], (0.5, 0.5, 0.5)),
        (["a"], (1, 0.5, 2 / 3)),
        (["c"], (0, 0, 0)),
        ([], (0, 0, 0)),
        ([" a ", "a", " b "], (1, 1, 1)),
    ],
)
def test_set_f1_normalizes_and_counts_only_sets(items, expected):
    t = truth().model_copy(update={"answer_type": "set", "value": [" a ", "b", "b"]})
    answer = e3.E3Answer(count=None, items=items, evidence_ids=[])
    assert e3.set_f1(answer, t) == dict(
        zip(("precision", "recall", "f1"), expected, strict=True)
    )
    assert e3.set_f1(answer, truth()) is None


def report_rows(qs, truths, *, partial=False):
    return [
        {
            "question_id": q.id,
            "arm": arm,
            "identity": asdict(IDENTITY),
            "answer": {
                "count": t.value
                if t.answer_type == "count" and arm == "graph"
                else None,
                "items": t.value
                if t.answer_type == "set" and arm == "graph"
                else t.value[:1]
                if partial and t.answer_type == "set"
                else [],
                "evidence_ids": [],
            },
        }
        for q, t in zip(qs, truths, strict=True)
        for arm in ("graph", "vector")
    ]


def test_report_size_strata_boundaries_f1_and_unchanged_decisions(
    tmp_path, monkeypatch
):
    from beautyads.eval import vector_baseline

    monkeypatch.setattr(vector_baseline, "TOP_K", 3)
    sizes = [3] * e3.MIN_STRATUM_N + [4, 10, 11, None]
    qs = [
        question(i).model_copy(update={"answer_type": "set" if size else "count"})
        for i, size in enumerate(sizes)
    ]
    truths = [
        truth(i).model_copy(
            update={"answer_type": "set", "value": [f"v{j}" for j in range(size)]}
        )
        if size
        else truth(i)
        for i, size in enumerate(sizes)
    ]
    path = tmp_path / "answers"
    write_jsonl(path, truths)
    rows = report_rows(qs, truths)
    result = e3.report(rows, qs, answers_path=path, split="dev")
    expected = {"size_le10": len(sizes) - 2, "size_gt10": 1, "size_count": 1}
    assert {key: value["n"] for key, value in result["size_strata"].items()} == expected
    assert {key: value["n"] for key, value in result["size_vs_top_k"].items()} == {
        "size_le_top_k": e3.MIN_STRATUM_N,
        "size_gt_top_k": 3,
    }
    for layer in (*result["size_strata"].values(), *result["size_vs_top_k"].values()):
        assert layer["status"] == (
            "undecidable" if layer["n"] < e3.MIN_STRATUM_N else "descriptive_only"
        )
        assert layer["decision"] == "undecidable"
    assert result["overall"]["arms"]["graph"]["set_f1"] == {
        "f1": 1.0,
        "n": len(sizes) - 1,
    }
    assert result["size_strata"]["size_count"]["arms"]["vector"]["set_f1"] == {
        "f1": None,
        "n": 0,
    }
    # Original summaries are exactly the original score computation plus the new F1 key.
    scores = {
        (row["question_id"], row["arm"]): e3.score_answer(
            e3.E3Answer.model_validate(row["answer"]),
            truths[int(row["question_id"][1:])],
        )
        for row in rows
    }
    old = e3._summary(qs, scores)
    for key in ("n", "difference", "difference_ci", "decision"):
        assert result["overall"][key] == old[key]
    for arm in ("graph", "vector"):
        for key in ("accuracy", "accuracy_ci", "evidence_hit_rate"):
            assert result["overall"]["arms"][arm][key] == old["arms"][arm][key]
    assert result["strata"]["reliable"]["n"] == len(qs)
    assert result["strata"]["unreliable"]["n"] == 0
    assert "v0" not in json.dumps(result)


def test_partial_f1_cannot_change_adoption(tmp_path):
    qs = [question(i).model_copy(update={"answer_type": "set"}) for i in range(20)]
    truths = [
        truth(i).model_copy(update={"answer_type": "set", "value": ["a", "b"]})
        for i in range(20)
    ]
    path = tmp_path / "answers"
    write_jsonl(path, truths)
    reports = [
        e3.report(
            report_rows(qs, truths, partial=p), qs, answers_path=path, split="dev"
        )
        for p in (False, True)
    ]
    assert {r["overall"]["decision"] for r in reports} == {"graph_adopted"}
    assert [r["overall"]["arms"]["vector"]["set_f1"]["f1"] for r in reports] == [
        0,
        2 / 3,
    ]
    assert (
        reports[0]["overall"]["difference_ci"] == reports[1]["overall"]["difference_ci"]
    )


@pytest.mark.parametrize(
    "values,evidence,expected",
    [
        (2, ["youtube:a", "absent"], {"youtube:a"}),
        (
            ["https://example.invalid/p:1"],
            [],
            {"product:brand:https://example.invalid/p:1"},
        ),
        (["youtube:a"], [], {"youtube:a"}),
        (["rule-id", "SENTINEL_TRUTH"], [], set()),
        (
            ["youtube:a", "https://example.invalid/p:1"],
            ["youtube:a"],
            {"youtube:a", "product:brand:https://example.invalid/p:1"},
        ),
        (2, [], set()),
    ],
)
def test_target_ids_maps_only_corpus_ids(values, evidence, expected):
    t = truth().model_copy(
        update={
            "answer_type": "set" if isinstance(values, list) else "count",
            "value": values,
            "evidence_ids": evidence,
        }
    )
    assert (
        e3.target_ids(
            t,
            {
                "youtube:a",
                "product:brand:https://example.invalid/p:1",
                "product:malformed",
            },
        )
        == expected
    )


def measurement_inputs(tmp_path, *, no_target=False):
    docs = [
        CorpusDoc("youtube:a", "abcdef"),
        CorpusDoc("product:brand:https://example.invalid/p", "ghijkl"),
    ]
    qs = [
        question(i).model_copy(update={"answer_type": "set" if i != 2 else "count"})
        for i in range(4)
    ]
    truths = [
        truth(0).model_copy(
            update={
                "answer_type": "set",
                "value": ["https://example.invalid/p"],
                "evidence_ids": [],
            }
        ),
        truth(1).model_copy(
            update={
                "answer_type": "set",
                "value": ["youtube:a", "https://example.invalid/p"],
                "evidence_ids": [],
            }
        ),
        truth(2),
        truth(3).model_copy(
            update={
                "answer_type": "set",
                "value": ["SENTINEL_TRUTH"],
                "evidence_ids": [],
            }
        ),
    ]
    if no_target:
        truths = [
            t.model_copy(
                update={
                    "value": ["SENTINEL_TRUTH"] if t.answer_type == "set" else 2,
                    "evidence_ids": [],
                }
            )
            for t in truths
        ]
    path = tmp_path / "answers"
    write_jsonl(path, truths)
    calls = []

    def embed(texts, **kw):
        from beautyads.llm.embed import EmbedResult

        calls.append((texts, kw))
        return EmbedResult([[1.0, 0.0] for _ in texts], 5, 0.01)

    return docs, qs, path, embed, calls


def test_measure_targets_recall_combinations_and_no_leaks(tmp_path, capsys):
    docs, qs, path, embed, calls = measurement_inputs(tmp_path)
    result = e3.measure(
        docs,
        qs,
        answers_path=path,
        models=["text-embedding-3-small"],
        embed=embed,
        cache_dir=tmp_path / "cache",
        top_ks=[1, 2],
    )
    assert len(calls) == 2
    assert result["n_set_questions_values_not_in_corpus"] == 1
    baseline = result["models"][0]
    assert baseline["hit_at_k"] == baseline["recall_at_k"] == 1
    assert baseline["n_with_target"] == 3 and baseline["n_no_target"] == 1
    assert baseline["hit_at_k_all_questions"] == 0.25
    by_k = {r["top_k"]: r for r in result["combinations"]}
    assert by_k[1]["hit_at_k"] == pytest.approx(2 / 3)
    assert by_k[1]["recall_at_k"] == 0.5
    assert by_k[1]["hit_at_k_all_questions"] == 0.0
    assert by_k[2]["recall_at_k"] == 1
    assert all(r["n_with_target"] == 3 and r["n_no_target"] == 1 for r in by_k.values())
    output = tmp_path / "measurement.json"
    e3._write_json(output, result)
    assert (
        "SENTINEL"
        not in json.dumps(calls) + output.read_text() + capsys.readouterr().out
    )
    for p in (tmp_path / "cache").glob("*.json"):
        assert "SENTINEL" not in p.read_text()


def test_measure_no_targets_null_metrics_and_price_tie_break(tmp_path):
    docs, qs, path, embed, _ = measurement_inputs(tmp_path, no_target=True)
    result = e3.measure(
        docs,
        qs,
        answers_path=path,
        models=list(reversed(e3.EMBEDDING_PRICES)),
        embed=embed,
        cache_dir=tmp_path / "cache",
    )
    assert all(
        m["hit_at_k"] is None
        and m["recall_at_k"] is None
        and m["n_with_target"] == 0
        and m["n_no_target"] == len(qs)
        for m in result["models"]
    )
    assert result["selected_model"] == min(
        e3.EMBEDDING_PRICES, key=e3.EMBEDDING_PRICES.get
    )


def test_measure_length_candidates_share_queries_and_isolate_caches(tmp_path):
    docs, qs, path, embed, calls = measurement_inputs(tmp_path)
    kwargs = {
        "answers_path": path,
        "models": ["text-embedding-3-small"],
        "embed": embed,
        "cache_dir": tmp_path / "cache",
    }
    baseline = e3.measure(docs, qs, **kwargs)
    calls.clear()
    expanded = e3.measure(docs, qs, **kwargs, top_ks=[1, 2], max_doc_chars=[2, 3])
    assert len(calls) == 3  # two new corpus lengths, one shared question batch
    assert sum(texts == [q.text for q in qs] for texts, _ in calls) == 1
    assert {len(texts[0]) for texts, _ in calls if len(texts) == len(docs)} == {2, 3}
    assert len(list((tmp_path / "cache").glob("*.bin"))) == 3
    # Cached corpus costs differ, but primary retrieval and truncation remain at defaults.
    assert expanded["models"][0]["hit_at_k"] == baseline["models"][0]["hit_at_k"]
    for key in (
        "selected_model",
        "truncated_document_ratio",
        "truncated_dev_evidence_ratio",
        "top_k",
        "max_doc_chars",
    ):
        assert expanded[key] == baseline[key]
    assert len(expanded["combinations"]) == 9
    calls.clear()
    e3.measure(docs, qs, **kwargs, top_ks=[1, 2], max_doc_chars=[2, 3])
    assert len(calls) == 1


@pytest.mark.parametrize("no_target", [False, True])
def test_measure_candidate_output_matches_prereg_consumer(tmp_path, no_target):
    from beautyads.eval import prereg

    docs, qs, path, embed, _ = measurement_inputs(tmp_path, no_target=no_target)
    result = e3.measure(
        docs,
        qs,
        answers_path=path,
        models=list(e3.EMBEDDING_PRICES),
        embed=embed,
        cache_dir=tmp_path / "cache",
        top_ks=[1, 2],
        max_doc_chars=[2, 3],
    )
    assert len({row["top_k"] for row in result["combinations"]}) >= 2
    assert len({row["max_doc_chars"] for row in result["combinations"]}) >= 2
    assert prereg.validate_dev_measurement(result) is None


@pytest.mark.parametrize(
    "command,mode",
    [
        ("run", "dev"),
        ("report", "dev"),
        ("run", "final"),
        ("report", "final"),
        ("measure", "final"),
    ],
)
@pytest.mark.parametrize("flag", ["--top-ks", "--max-doc-chars"])
def test_measure_options_rejected_before_io(command, mode, flag, monkeypatch, capsys):
    from pathlib import Path

    def forbidden(*a, **kw):
        pytest.fail("invalid arguments must precede I/O")

    monkeypatch.setattr(Path, "open", forbidden)
    assert (
        e3.main(
            [command, "--mode", mode, flag, "1,2"],
            check_fn=forbidden,
            corpus_loader=forbidden,
            settings_fn=forbidden,
        )
        == 1
    )
    assert json.loads(capsys.readouterr().out) == {"code": "E3_ARGUMENTS_INVALID"}


@pytest.mark.parametrize("value", ["0", "-1", "1,,2", "a", "1.5", ""])
@pytest.mark.parametrize("flag", ["--top-ks", "--max-doc-chars"])
def test_measure_options_require_positive_integer_lists(value, flag, capsys):
    assert e3.main(["measure", flag, value]) == 1
    assert json.loads(capsys.readouterr().out) == {"code": "E3_ARGUMENTS_INVALID"}


def test_cli_measure_candidates_and_dry_run_never_reads_truth(
    tmp_path, monkeypatch, capsys
):
    injected, _, _, calls, _ = fake_cli_options(tmp_path)
    qs = tmp_path / "questions"
    answers = tmp_path / "answers"
    write_jsonl(qs, [question()])
    write_jsonl(answers, [truth()])
    injected.update(questions_path=qs, answers_path=answers)
    flags = [
        "measure",
        "--models",
        "text-embedding-3-small",
        "--top-ks",
        "1,2",
        "--max-doc-chars",
        "2,3",
    ]
    assert e3.main(flags, **injected) == 0
    result = json.loads(capsys.readouterr().out)
    assert len(result["combinations"]) == 9 and len(calls) == 4
    assert result == json.loads(
        (injected["output_dir"] / "measurement.json").read_text()
    )
    calls.clear()
    monkeypatch.setattr(
        e3, "read_answers", lambda *a, **kw: pytest.fail("dry-run answers")
    )
    assert e3.main([*flags, "--dry-run"], **injected) == 0
    dry = json.loads(capsys.readouterr().out)
    assert {r["max_doc_chars"] for r in dry["lengths"]} == {2, 3, e3.MAX_DOC_CHARS}
    assert all(
        r["documents"] == 1 and r["estimated_tokens"] > 0 for r in dry["lengths"]
    )
    assert "가정" in dry["assumption"] and "미실측" in dry["assumption"]
    assert "dev_question_hash" not in dry and "models" not in dry and not calls


def test_model_selection_uses_default_k_and_length_even_when_candidates_tie(tmp_path):
    from beautyads.llm.embed import EmbedResult

    docs = [CorpusDoc(f"youtube:{i:03}", f"document {i}") for i in range(e3.TOP_K)]
    docs.append(CorpusDoc("youtube:zz", "target document"))
    path = tmp_path / "answers"
    write_jsonl(path, [truth().model_copy(update={"evidence_ids": ["youtube:zz"]})])
    cheap, expensive = sorted(e3.EMBEDDING_PRICES, key=e3.EMBEDDING_PRICES.get)

    def embed(texts, *, model):
        if texts == [question().text]:
            vectors = [[1.0, 0.0]]
        elif model == expensive and len(texts[0]) > 1:
            vectors = [[0.0, 1.0] for _ in docs[:-1]] + [[1.0, 0.0]]
        else:
            vectors = [[1.0, 0.0] for _ in texts]
        return EmbedResult(vectors, 1, 0.0)

    result = e3.measure(
        docs,
        [question()],
        answers_path=path,
        models=[cheap, expensive],
        embed=embed,
        cache_dir=tmp_path / "cache",
        top_ks=[len(docs)],
        max_doc_chars=[1],
    )
    assert result["selected_model"] == expensive
    assert [m["hit_at_k"] for m in result["models"]] == [0.0, 1.0]
    larger_k = [m for m in result["combinations"] if m["top_k"] == len(docs)]
    assert all(m["hit_at_k"] == 1 for m in larger_k)
    shorter = [
        m
        for m in result["combinations"]
        if m["max_doc_chars"] == 1 and m["top_k"] == e3.TOP_K
    ]
    assert all(m["hit_at_k"] == 0 for m in shorter)


def test_measure_invalid_truth_never_exposes_answer_in_exception(tmp_path, capsys):
    path = tmp_path / "answers"
    write_jsonl(path, [{**truth().model_dump(), "value": "SENTINEL_TRUTH"}])
    with pytest.raises(e3.E3Error, match="^E3_ANSWERS_INVALID$") as caught:
        e3.measure(
            [CorpusDoc("a", "document")],
            [question()],
            answers_path=path,
            models=["text-embedding-3-small"],
            embed=lambda *a, **kw: pytest.fail("invalid truth before embedding"),
            cache_dir=tmp_path / "cache",
        )
    assert caught.value.__suppress_context__
    assert "SENTINEL" not in str(caught.value) + capsys.readouterr().out
    assert not (tmp_path / "cache").exists()


@pytest.mark.parametrize(
    "values,evidence,expected",
    [
        (["CR-011", "CR-012"], [], True),
        (["https://example.invalid/p:1"], [], True),
        (["youtube:a"], [], True),
        (["CR-011"], ["youtube:a"], True),
        (["hydration"], [], False),
        (["sun_care"], [], False),
        (["CR-011", "absent"], [], False),
        (["CR-011"], ["youtube:a", "absent"], False),
        (["https://example.invalid/p:1", "absent"], [], False),
        (["absent"], ["youtube:a"], False),
        (2, [], False),
        (2, ["youtube:a"], True),
        (2, ["youtube:a", "absent"], False),
    ],
)
def test_reachability_requires_every_value_and_evidence_id(values, evidence, expected):
    t = truth().model_copy(
        update={
            "answer_type": "set" if isinstance(values, list) else "count",
            "value": values,
            "evidence_ids": evidence,
        }
    )
    ids = [
        "CR-011",
        "CR-012",
        "youtube:a",
        "product:brand:https://example.invalid/p:1",
        "product:other:https://example.invalid/p:1",
        "product:malformed",
    ]
    assert e3.is_reachable(t, ids) is expected
    assert not e3.is_reachable(t.model_copy(update={"answer_type": "unknown"}), ids)


def test_rule_id_targets_and_measurement_metrics_without_truth_leaks(tmp_path, capsys):
    from test_vector_baseline import synthetic_rule

    from beautyads.eval.vector_baseline import build_corpus

    source = SimpleNamespace(read_changed=lambda **kw: [])
    docs = build_corpus(
        source, source, rules=[synthetic_rule("CR-012"), synthetic_rule("CR-011")]
    )
    qs = [question(i).model_copy(update={"answer_type": "set"}) for i in range(3)]
    truths = [
        truth(i).model_copy(
            update={"answer_type": "set", "value": values, "evidence_ids": []}
        )
        for i, values in enumerate(
            (["CR-011", "CR-012"], ["CR-012"], ["SENTINEL_TRUTH"])
        )
    ]
    assert e3.target_ids(truths[0], [d.id for d in docs]) == {d.id for d in docs}
    path = tmp_path / "answers"
    write_jsonl(path, truths)
    options, generator, calls = arm_options()
    result = e3.measure(
        docs,
        qs,
        answers_path=path,
        models=[options["embedding_model"]],
        embed=options["embed"],
        cache_dir=tmp_path / "output",
        top_ks=[1],
    )
    at_one = next(row for row in result["combinations"] if row["top_k"] == 1)
    assert at_one["hit_at_k"] == 0.5
    assert at_one["recall_at_k"] == 0.25
    assert at_one["n_with_target"] == 2 and at_one["n_no_target"] == 1
    assert result["models"][0]["hit_at_k"] == 1.0
    assert result["models"][0]["recall_at_k"] == 1.0
    assert result["n_set_questions_values_not_in_corpus"] == 1
    e3._write_json(tmp_path / "output" / "measurement.json", result)
    with pytest.raises(e3.E3Error, match="^ANSWER_SPLIT_FORBIDDEN$") as caught:
        e3.measure(
            docs,
            qs,
            answers_path=path,
            models=[options["embedding_model"]],
            embed=options["embed"],
            split="test",
            cache_dir=tmp_path / "output",
        )
    assert generator.calls == []
    public = json.dumps(calls) + capsys.readouterr().out + str(caught.value)
    public += "".join(p.read_text() for p in (tmp_path / "output").glob("*.json"))
    assert "SENTINEL_TRUTH" not in public


@pytest.mark.parametrize("n", [0, e3.MIN_STRATUM_N - 1, e3.MIN_STRATUM_N, 20])
def test_reachable_report_is_descriptive_and_preserves_existing_summaries(tmp_path, n):
    total = 24
    qs = [
        question(
            i,
            kind="simple_search" if i < 10 else "graph",
            axes=["hook_type"] if i % 2 else ["category"],
        ).model_copy(update={"answer_type": "set"})
        for i in range(total)
    ]
    truths = [
        truth(i).model_copy(
            update={
                "answer_type": "set",
                "value": ["CR-011"] if i < n else ["hydration"],
                "evidence_ids": [],
            }
        )
        for i in range(total)
    ]
    path = tmp_path / "answers"
    write_jsonl(path, truths)
    rows = report_rows(qs, truths)
    baseline = e3.report(rows, qs, answers_path=path, split="dev")
    assert baseline["reachable_subset"] == {"status": "corpus_ids_missing"}
    result = e3.report(
        rows,
        [*qs, question(100, "test")],
        answers_path=path,
        split="dev",
        corpus_doc_ids=["CR-011"],
    )
    for key in (
        "overall",
        "graph_questions",
        "simple_search",
        "strata",
        "size_strata",
        "size_vs_top_k",
    ):
        assert result[key] == baseline[key]
    scores = {
        (row["question_id"], row["arm"]): {
            **e3.score_answer(e3.E3Answer.model_validate(row["answer"]), t),
            "set_f1": e3.set_f1(e3.E3Answer.model_validate(row["answer"]), t),
        }
        for q, t in zip(qs, truths, strict=True)
        for row in rows
        if row["question_id"] == q.id
    }
    assert result["reachable_subset"] == {
        **e3._summary(qs[:n], scores),
        "n_reachable": n,
        "n_total": total,
        "status": "undecidable" if n < e3.MIN_STRATUM_N else "descriptive_only",
        "decision": "undecidable",
    }
    assert result["overall"]["decision"] == "graph_adopted"
    empty = e3.report(rows, qs, answers_path=path, split="dev", corpus_doc_ids=[])
    assert empty["reachable_subset"]["n_reachable"] == 0


@pytest.mark.parametrize("mode", ["dev", "final"])
@pytest.mark.parametrize("arms", ["graph", "vector", "graph,vector"])
def test_cli_corpus_ids_only_for_loaded_corpus_and_report_forwarding(
    tmp_path, monkeypatch, capsys, mode, arms
):
    from pathlib import Path

    injected, options, generator, calls, _ = fake_cli_options(tmp_path)
    options["docs"] += [CorpusDoc("CR-011", "SENTINEL_PUBLIC_DOCUMENT")]
    qs = [
        question(
            i,
            "dev" if mode == "dev" else "test",
            "simple_search" if i < 10 else "graph",
        ).model_copy(update={"answer_type": "set"})
        for i in range(1 if mode == "dev" else 40)
    ]
    questions_path, answers_path = tmp_path / "questions", tmp_path / "answers"
    write_jsonl(questions_path, qs)
    write_jsonl(
        answers_path,
        [
            truth(i).model_copy(
                update={"answer_type": "set", "value": ["SENTINEL_TRUTH"]}
            )
            for i in range(len(qs))
        ],
    )
    injected.update(questions_path=questions_path, answers_path=answers_path)
    original_open, original_report, original_read = (
        Path.open,
        e3.report,
        e3.read_answers,
    )
    answer_opens, forwarded, reads, loaded = [], [], [], []

    def watched(path, *a, **kw):
        if path == answers_path:
            answer_opens.append(path)
        return original_open(path, *a, **kw)

    def report_spy(*a, **kw):
        forwarded.append(kw["corpus_doc_ids"])
        return original_report(*a, **kw)

    def answers_spy(*a, **kw):
        reads.append(kw["purpose"])
        return original_read(*a, **kw)

    def corpus_loader():
        loaded.append(True)
        return options["docs"]

    injected["corpus_loader"] = corpus_loader
    monkeypatch.setattr(Path, "open", watched)
    monkeypatch.setattr(e3, "report", report_spy)
    monkeypatch.setattr(e3, "read_answers", answers_spy)
    assert e3.main(["run", "--mode", mode, "--arms", arms], **injected) == 0
    assert not answer_opens and not reads
    ids_path = injected["output_dir"] / f"{mode}_corpus_ids.json"
    if "vector" in arms:
        expected_ids = sorted(d.id for d in options["docs"])
        assert json.loads(ids_path.read_text()) == {"ids": expected_ids}
        assert loaded == [True]
        if arms == "vector":
            # Reports require paired arms; supply a synthetic graph counterpart.
            result_path = injected["output_dir"] / f"{mode}_results.jsonl"
            rows = e3.read_jsonl(result_path)
            write_jsonl(result_path, [*rows, *({**r, "arm": "graph"} for r in rows)])
        assert e3.main(["report", "--mode", mode], **injected) == 0
        assert forwarded == [expected_ids]
        assert reads == ["report"] and len(answer_opens) == 1
        # The missing-file report remains usable for older runs.
        ids_path.unlink()
        assert e3.main(["report", "--mode", mode], **injected) == 0
        assert forwarded[-1] is None
    else:
        assert not ids_path.exists() and not loaded
    public = json.dumps(calls) + json.dumps([kw for _, kw in generator.calls])
    public += capsys.readouterr().out
    public += "".join(p.read_text() for p in injected["output_dir"].glob("*.json*"))
    assert "SENTINEL_TRUTH" not in public
    if ids_path.exists():
        assert "SENTINEL_PUBLIC_DOCUMENT" not in ids_path.read_text()


@pytest.mark.parametrize("invalid", [False, True])
def test_load_corpus_reuses_claim_rule_reader_and_sanitizes_failure(
    monkeypatch, invalid
):
    from pathlib import Path

    from test_vector_baseline import synthetic_rule

    from beautyads.sources.config import ConfigError

    closed, reads, builds = [], [], []
    conn = SimpleNamespace(close=lambda: closed.append(True))
    creative_source, product_source = object(), object()
    rules = [synthetic_rule()]

    def load(path):
        reads.append(path)
        if invalid:
            raise ConfigError("/SENTINEL_PRIVATE_PATH/SENTINEL_TRUTH")
        return rules

    def build(creative, product, **kw):
        builds.append((creative, product, kw))
        return [CorpusDoc(rules[0].rule_id, "synthetic")]

    monkeypatch.setattr(e3, "postgres_dsn", lambda: "synthetic")
    monkeypatch.setattr(e3, "connect", lambda dsn: conn)
    monkeypatch.setattr(e3, "PostgresGraphSyncSource", lambda c: creative_source)
    monkeypatch.setattr(e3, "PostgresLayer1Source", lambda c: product_source)
    monkeypatch.setattr(e3, "load_claim_rules", load)
    monkeypatch.setattr(e3, "build_corpus", build)
    if invalid:
        with pytest.raises(e3.E3Error, match="^E3_CORPUS_RULES_INVALID$") as caught:
            e3.load_corpus()
        assert caught.value.__suppress_context__
        assert "SENTINEL" not in str(caught.value)
        assert builds == []
    else:
        assert [d.id for d in e3.load_corpus()] == [r.rule_id for r in rules]
        assert builds == [(creative_source, product_source, {"rules": rules})]
    assert reads == [Path("config/claim_rules.yaml")]
    assert closed == [True]


def test_corpus_runner_imports_only_closed_public_store_sources():
    import ast
    from pathlib import Path

    tree = ast.parse(Path(e3.__file__).read_text(encoding="utf-8"))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0 and node.module is not None
            imports.update(f"{node.module}.{alias.name}" for alias in node.names)
    store_modules = {
        ".".join(name.split(".")[:3])
        for name in imports
        if name == "beautyads.store" or name.startswith("beautyads.store.")
    }
    assert store_modules == {
        "beautyads.store.connection",
        "beautyads.store.layer1_source",
        "beautyads.store.repository",
        "beautyads.store.sync_source",
    }
    forbidden = {
        "beautyads.store.tenant_repository",
        "beautyads.store.feedback_source",
        "beautyads.store.links_source",
        "beautyads.store.product_repository",
        "beautyads.api",
        "beautyads.eval.isolation_live",
    }
    assert {
        name
        for name in imports
        if any(name == path or name.startswith(path + ".") for path in forbidden)
    } == set()


def test_load_corpus_excludes_tenant_data_and_uses_only_public_document_ids(
    monkeypatch,
):
    import re
    from datetime import UTC, datetime
    from pathlib import Path

    from test_vector_baseline import synthetic_rule

    from beautyads.domain.sync import SyncCreative, SyncLabel
    from beautyads.eval.isolation_live import ISOLATION_TENANTS
    from beautyads.store import tenant_repository

    class ForbiddenTenantRepository:
        def __getattribute__(self, name):
            pytest.fail("E3 corpus must not access the tenant repository")

        def __call__(self, *args, **kwargs):
            pytest.fail("E3 corpus must not construct the tenant repository")

    monkeypatch.setattr(
        tenant_repository, "PostgresTenantRepository", ForbiddenTenantRepository()
    )
    private = {
        "plan": "SENTINEL_TENANT_PLAN",
        "feedback": "SENTINEL_TENANT_FEEDBACK",
        "tenant_id": ISOLATION_TENANTS[0],
        "other_tenant_id": ISOLATION_TENANTS[1],
    }
    closed, calls = [], []
    conn = SimpleNamespace(close=lambda: closed.append(True))

    class CreativeSource:
        def __init__(self, connection):
            assert connection is conn
            calls.append("creative_source")

        def read_changed(self, **kwargs):
            assert kwargs == {"since": None, "limit": None, "run_tag": "v1"}
            calls.append("creatives")
            return [
                SyncCreative(
                    {
                        "source": "youtube",
                        "source_id": "public-creative",
                        "brand": "synthetic-public-brand",
                        **private,
                    },
                    datetime(2026, 11, 19, tzinfo=UTC),
                )
            ]

        def read_labels(self, key, **kwargs):
            assert (key.source.value, key.source_id) == ("youtube", "public-creative")
            assert kwargs == {"run_tag": "v1"}
            calls.append("labels")
            return [SyncLabel("full@v1", "done", {"angle": "comparison", **private})]

    product = SimpleNamespace(
        brand="synthetic-public-brand",
        source_url="https://example.invalid/public-product",
        name_ko="synthetic public product",
        **private,
    )

    class ProductSource:
        def __init__(self, connection):
            assert connection is conn
            calls.append("product_source")

        def read_changed(self, **kwargs):
            assert kwargs == {"since": None, "limit": None}
            calls.append("products")
            return [SimpleNamespace(product=product, ingredients=[], certs=[])]

    rule = synthetic_rule().model_copy(
        update={"law_basis": json.dumps(private), "exception_note": json.dumps(private)}
    )

    def load_rules(path):
        assert path == Path("config/claim_rules.yaml")
        calls.append("rules")
        return [rule]

    def connect(dsn):
        assert dsn == "synthetic"
        calls.append("connect")
        return conn

    monkeypatch.setattr(e3, "postgres_dsn", lambda: "synthetic")
    monkeypatch.setattr(e3, "connect", connect)
    monkeypatch.setattr(e3, "PostgresGraphSyncSource", CreativeSource)
    monkeypatch.setattr(e3, "PostgresLayer1Source", ProductSource)
    monkeypatch.setattr(e3, "load_claim_rules", load_rules)
    docs = e3.load_corpus()
    assert calls == [
        "connect",
        "rules",
        "creative_source",
        "product_source",
        "creatives",
        "labels",
        "products",
    ]
    assert closed == [True]
    assert {doc.id for doc in docs} == {
        "youtube:public-creative",
        f"product:{product.brand}:{product.source_url}",
        rule.rule_id,
    }
    assert all(
        re.fullmatch(r"(?:youtube:[^:]+|product:[^:]+:.+|CR-\d{3})", doc.id)
        for doc in docs
    )
    assert all(
        marker not in doc.id + doc.text for doc in docs for marker in private.values()
    )
