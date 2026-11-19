"""Preregistration rendering and CLI use temporary, synthetic inputs only."""

import io
import json
import re
from datetime import date
from pathlib import Path

import pytest
from test_evalset import synthetic_set
from test_evalset import workspaces_path as workspace_config  # noqa: F401 -- shared fixture
from test_freeze_guard import FakeGit

from beautyads.eval import e2_scoring, e2e5_live, e3_live, prereg
from beautyads.eval import evalset as sets
from beautyads.eval import freeze_guard as guard
from beautyads.eval.single_agent import SINGLE_AGENT_PROMPT_VERSION


@pytest.fixture
def render_inputs():
    requests, questions, answers = synthetic_set()
    embedding = "SENTINEL_EMBEDDING"
    return {
        "request_hash": sets.request_set_hash(requests),
        "question_hash": sets.question_set_hash(questions, answers),
        "extra": {**e2e5_live._extra_frozen(), **e3_live.extra_frozen(embedding)},
        "embedding": embedding,
        "isolation_hash": sets.request_set_hash(
            [{"id": "isolation-synthetic", "message": "SENTINEL_ISOLATION"}]
        ),
        "today": date(2026, 11, 26),
    }


def test_all_fourteen_required_procedures_are_present(render_inputs):
    text = prereg.render_preregistration(**render_inputs)
    sentences = prereg.REQUIRED_SENTENCES
    assert len(sentences) == len(set(sentences)) == 17
    checked = 0
    for sentence in sentences:
        assert sentence.strip()
        assert sentence in text
        checked += 1
    assert checked > 0
    assert "변경 규칙" in sentences[12]
    assert "재등록" in sentences[12]
    assert "커밋 절차" in sentences[13]
    assert "함께" in sentences[13]


def test_e3_reporting_procedure_is_appended(render_inputs):
    sentence = prereg.REQUIRED_SENTENCES[15]
    for phrase in (
        str(e3_live.SIZE_STRATUM_THRESHOLD),
        "F1",
        "참고용",
        "사전 등록 전에 확정",
        "완전 일치",
        "TOP_K",
        "MAX_DOC_CHARS",
        "evidence_ids",
        "대상이 없는 질문 수",
        "효능",
        "카테고리",
        "test 결과",
    ):
        assert phrase in sentence
    assert sentence in prereg.render_preregistration(**render_inputs)
    assert "표현 규칙 ID" not in sentence


def test_rule_corpus_procedure_is_seventeenth(render_inputs):
    sentence = prereg.REQUIRED_SENTENCES[16]
    for phrase in (
        "규칙",
        "APPLIES_TO",
        "상속",
        "참고용",
        "전체 질문 기준",
        "reachable_subset",
        "graph_adopted",
        "advisor_approved",
        "confirmed",
        "효능",
        "카테고리",
        "도달 가능 질문 수",
    ):
        assert phrase in sentence
    assert f"17. {sentence}" in prereg.render_preregistration(**render_inputs)


def test_approved_limitations_are_not_weakened(render_inputs):
    text = prereg.render_preregistration(**render_inputs)
    for phrase in (
        "그대로 보고한다",
        "1인 라벨링",
        "단일 팔은 보조 값(pattern_context, available_efficacy)을 받지 않는다",
        "대화 압축 요약 경로는 미구현",
        "재작업 경로(max_reworks=0)는 실행되지 않는다",
        "재검사 κ는 재현성 증거로 쓰지 않는다",
        "정정은 기존 문장을 고치지 않고 정정 기록으로만 쌓는다",
    ):
        assert phrase in text
    assert not re.search(r"κ\s*[=≥]?\s*\d", text)


def test_renderer_roundtrips_through_final_guard(tmp_path, request, render_inputs):
    rows = synthetic_set()
    paths = [tmp_path / name for name in ("r.jsonl", "q.jsonl", "a.jsonl")]
    for path, collection in zip(paths, rows, strict=True):
        sets.write_jsonl(path, collection)
    path = tmp_path / "prereg.md"
    text = prereg.render_preregistration(**render_inputs)
    path.write_text(text, encoding="utf-8")
    parsed = guard.parse_preregistration(text)
    expected = {
        guard.REQUEST_HASH_LABEL: render_inputs["request_hash"],
        guard.QUESTION_HASH_LABEL: render_inputs["question_hash"],
        **guard.frozen_values(),
        **render_inputs["extra"],
    }
    assert {label: parsed.get(label) for label in expected} == expected
    assert render_inputs["isolation_hash"] in parsed.values()
    checked_paths = []

    def committed(path):
        checked_paths.append(path)
        return True

    identity = guard.check_run(
        mode="final",
        groups={"test"},
        requests_path=paths[0],
        questions_path=paths[1],
        answers_path=paths[2],
        workspaces_path=request.getfixturevalue("workspace_config"),
        prereg_path=path,
        extra=render_inputs["extra"],
        committed_fn=committed,
        run=FakeGit(),
    )
    assert checked_paths == [path]
    assert identity.request_hash == render_inputs["request_hash"]
    assert identity.question_hash == render_inputs["question_hash"]


def test_rendering_is_deterministic_including_mapping_order(render_inputs):
    first = prereg.render_preregistration(**render_inputs)
    second = prereg.render_preregistration(**render_inputs)
    assert first == second
    assert first == prereg.render_preregistration(
        **{**render_inputs, "extra": dict(reversed(render_inputs["extra"].items()))}
    )
    assert render_inputs["today"].isoformat() in first
    assert render_inputs["embedding"] in first


def test_rendered_procedure_values_follow_code(monkeypatch, render_inputs):
    monkeypatch.setattr(prereg, "frozen_values", lambda: {"SENTINEL_FROZEN": "value"})
    text = prereg.render_preregistration(**render_inputs)
    assert guard.parse_preregistration(text)["SENTINEL_FROZEN"] == "value"
    for value in (
        SINGLE_AGENT_PROMPT_VERSION,
        e2_scoring.E2_SCORING_PROMPT_VERSION,
        str(e2_scoring.SCORING_SEED),
        str(e2_scoring.BOOTSTRAP_RESAMPLES),
        str(e2_scoring.E2_SCORE_PURPOSE_CAP),
        str(e2_scoring.MIN_STRATUM_N),
        str(e2_scoring.E5_MIN_TOKEN_REDUCTION),
        str(e2_scoring.E5_MIN_VALIDITY_LOWER),
        str(e3_live.EMBED_PURPOSE_CAP),
    ):
        assert value in text


@pytest.fixture
def cli_inputs(tmp_path, monkeypatch, request):
    monkeypatch.chdir(tmp_path)
    rows = synthetic_set()
    for name, collection in zip(
        ("REQUESTS_PATH", "QUESTIONS_PATH", "ANSWERS_PATH"), rows, strict=True
    ):
        path = tmp_path / (name.lower() + ".jsonl")
        sets.write_jsonl(path, collection)
        monkeypatch.setattr(prereg, name, path)
    monkeypatch.setattr(
        prereg, "WORKSPACES_PATH", request.getfixturevalue("workspace_config")
    )
    measurement = tmp_path / "measurement.json"
    measurement.write_text(
        json.dumps({"selected_model": "text-embedding-3-small"}), encoding="utf-8"
    )
    isolation = tmp_path / "isolation.jsonl"
    sets.write_jsonl(
        isolation,
        [{"id": f"iso-{i}", "message": "SENTINEL_ISOLATION"} for i in range(200)],
    )
    monkeypatch.setattr(prereg, "EMBEDDING_MEASUREMENT_PATH", measurement)
    monkeypatch.setattr(prereg, "ISOLATION_REQUESTS_PATH", isolation)
    return rows


def test_cli_print_is_read_only_and_matches_current_inputs(cli_inputs, tmp_path):
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    out = io.StringIO()
    assert prereg.main(["--print"], out=out) == 0
    values = guard.parse_preregistration(out.getvalue())
    assert values[guard.REQUEST_HASH_LABEL] == sets.request_set_hash(cli_inputs[0])
    assert values[guard.QUESTION_HASH_LABEL] == sets.question_set_hash(*cli_inputs[1:])
    for label, value in {
        **guard.frozen_values(),
        **e2e5_live._extra_frozen(),
        **e3_live.extra_frozen("text-embedding-3-small"),
    }.items():
        assert values[label] == value
    assert {
        path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()
    } == before


def test_cli_defaults_to_print(cli_inputs):
    out = io.StringIO()
    assert prereg.main([], out=out) == 0
    assert all(sentence in out.getvalue() for sentence in prereg.REQUIRED_SENTENCES)


def test_cli_write_only_creates_requested_path_and_reports_commit_rule(
    cli_inputs, tmp_path
):
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    target = tmp_path / "prereg.md"
    out = io.StringIO()
    assert prereg.main(["--write", str(target)], out=out) == 0
    assert target.is_file()
    assert all(sentence in target.read_text() for sentence in prereg.REQUIRED_SENTENCES)
    assert out.getvalue().strip() == (
        "사전 등록 커밋은 `data/evalset/`와 이 문서를 함께 커밋한다"
    )
    after = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert set(after) - set(before) == {target}
    assert {path: after[path] for path in before} == before


@pytest.mark.parametrize("kind", ["file", "directory", "dangling_symlink"])
def test_cli_never_overwrites_existing_target(tmp_path, monkeypatch, kind):
    target = tmp_path / "existing"
    if kind == "file":
        target.write_bytes(b"SENTINEL_EXISTING")
    elif kind == "directory":
        target.mkdir()
    else:
        target.symlink_to(tmp_path / "absent")
    monkeypatch.setattr(
        prereg, "read_jsonl", lambda *a: pytest.fail("existing target must stop first")
    )
    out = io.StringIO()
    assert prereg.main(["--write", str(target)], out=out) != 0
    assert out.getvalue().strip() == "PREREG_FILE_EXISTS"
    if kind == "file":
        assert target.read_bytes() == b"SENTINEL_EXISTING"
    elif kind == "directory":
        assert target.is_dir()
    else:
        assert target.is_symlink()
        assert not target.resolve().exists()


@pytest.mark.parametrize("invalid", ["unreviewed", "unconfirmed", "count", "split"])
def test_cli_validates_final_set_before_any_hash_or_write(
    cli_inputs, tmp_path, monkeypatch, invalid
):
    if invalid == "unreviewed":
        cli_inputs[0][0]["reviewed"] = False
        code = "EVALSET_NOT_REVIEWED"
    elif invalid == "unconfirmed":
        cli_inputs[2][0]["confirmed"] = False
        code = "EVALSET_NOT_REVIEWED"
    elif invalid == "count":
        cli_inputs[0].pop()
        code = "EVALSET_COUNT_INVALID"
    else:
        cli_inputs[0][0]["tenant_id"] = "test-synthetic"
        code = "EVALSET_SPLIT_INVALID"
    for path, rows in zip(
        (prereg.REQUESTS_PATH, prereg.QUESTIONS_PATH, prereg.ANSWERS_PATH),
        cli_inputs,
        strict=True,
    ):
        sets.write_jsonl(path, rows)
    for name in ("request_set_hash", "question_set_hash"):
        monkeypatch.setattr(
            prereg, name, lambda *a: pytest.fail("hash before validation")
        )
    target = tmp_path / "prereg.md"
    out = io.StringIO()
    assert prereg.main(["--write", str(target)], out=out) != 0
    assert out.getvalue().strip() == code
    assert not target.exists()


@pytest.mark.parametrize("source", ["measurement", "isolation", "evalset"])
def test_missing_cli_inputs_fail_with_fixed_codes(cli_inputs, tmp_path, source):
    path = {
        "measurement": prereg.EMBEDDING_MEASUREMENT_PATH,
        "isolation": prereg.ISOLATION_REQUESTS_PATH,
        "evalset": prereg.REQUESTS_PATH,
    }[source]
    path.unlink()
    out = io.StringIO()
    target = tmp_path / "prereg.md"
    assert prereg.main(["--write", str(target)], out=out) != 0
    assert out.getvalue().strip() in {"PREREG_INPUT_INVALID", "EVALSET_READ_INVALID"}
    assert not target.exists()


@pytest.mark.parametrize("contents", ["{", "{}", "[]", '{"selected_model":""}'])
def test_invalid_embedding_selection_is_not_guessed(cli_inputs, contents):
    prereg.EMBEDDING_MEASUREMENT_PATH.write_text(contents)
    out = io.StringIO()
    assert prereg.main(["--print"], out=out) != 0
    assert out.getvalue().strip() == "PREREG_INPUT_INVALID"


def test_results_template_leaves_every_measurement_cell_empty():
    text = prereg.render_results_template()
    assert text == prereg.render_results_template()
    for experiment in ("E2", "E3", "E4", "E5", "격리"):
        assert f"## {experiment}" in text
    for field in (
        "건수",
        "기준일",
        "조건",
        "코드 커밋",
        "사전 등록 커밋",
        "모델 ID",
        "판정 코드",
        "기준 미달 항목",
        "층화 보조",
        "한계",
        "미수행",
        "이유",
    ):
        assert field in text
    measured_rows = 0
    for line in text.splitlines():
        if line.startswith("| ") and not line.startswith("| ---"):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if cells[0] in {"항목", "지표", "층", "경로", "축"}:
                continue
            assert cells[0]
            assert all(cell == "" for cell in cells[1:])
            measured_rows += 1
    assert measured_rows > 0
    assert "한 에이전트 대 한 시스템" in text
    assert "대화 압축 요약 경로는 미구현" in text
    assert "1인 라벨링" in text


def test_results_cli_needs_no_input_files_and_performs_no_writes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        prereg, "read_jsonl", lambda *a: pytest.fail("template does not read a set")
    )
    out = io.StringIO()
    assert prereg.main(["--results-template"], out=out) == 0
    assert out.getvalue() == prereg.render_results_template()
    assert list(tmp_path.iterdir()) == []


def test_render_functions_perform_no_file_io(tmp_path, monkeypatch, render_inputs):
    monkeypatch.chdir(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("pure renderers must not open files")

    monkeypatch.setattr(Path, "open", forbidden)
    assert prereg.render_preregistration(**render_inputs)
    assert prereg.render_results_template()
    assert list(tmp_path.iterdir()) == []


def test_candidate_validity_limitations_are_appended(render_inputs):
    from beautyads.eval import evalset_candidates

    sentence = prereg.REQUIRED_SENTENCES[14]
    text = prereg.render_preregistration(**render_inputs)
    assert f"15. {sentence}" in text
    for phrase in (
        str(evalset_candidates.MAX_ANSWER_SET),
        "정답",
        "비었",
        "넘는",
        "CQ-08",
        "CQ-13",
        "CQ-14",
        "데이터 부재",
        "독립",
        "템플릿 범위에 한정",
    ):
        assert phrase in sentence
    assert "층화" not in sentence
