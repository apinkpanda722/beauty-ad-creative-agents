"""Preregistration rendering and CLI use temporary, synthetic inputs only."""

import hashlib
import io
import json
import re
from copy import deepcopy
from datetime import date
from itertools import product
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
    assert len(sentences) == len(set(sentences)) == 25
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


def test_test_question_count_change_is_twenty_first_procedure(render_inputs):
    sentence = prereg.REQUIRED_SENTENCES[20]
    for phrase in (
        "EVAL.md 대비 변경",
        "40→37",
        "관계 30→27",
        "CQ-04",
        "정답이 항상 1",
        "판정 불가 하한",
        "단순 검색 10",
        "요청 20건·dev 구성은 불변",
    ):
        assert phrase in sentence
    assert "질문 37건" in prereg.REQUIRED_SENTENCES[5]
    assert f"21. {sentence}" in prereg.render_preregistration(**render_inputs)


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


def test_e5_supplement_procedure_is_eighteenth(render_inputs):
    sentence = prereg.REQUIRED_SENTENCES[17]
    for phrase in (
        "30%",
        "참고용",
        "리서치",
        "토큰 기준 미달",
        "그대로",
        "-0.05",
        "95%",
        "70%",
    ):
        assert phrase in sentence
    assert f"18. {sentence}" in prereg.render_preregistration(**render_inputs)
    assert sentence in prereg.render_results_template()


def test_first_seventeen_procedures_remain_byte_identical():
    original = json.dumps(prereg.REQUIRED_SENTENCES[:17], ensure_ascii=False)
    assert hashlib.sha256(original.encode()).hexdigest() == (
        "8511f0d460d4e074f0fc61ca4263af5716616fd98597d187ac589da2eea532c0"
    )


def test_failure_as_worst_procedure_is_nineteenth(render_inputs):
    sentence = prereg.REQUIRED_SENTENCES[18]
    for phrase in (
        "E2",
        "E5",
        "최저점",
        "실행되지 않은",
        "민감도",
        "실패율",
        "채점 실패",
        "근거 없음",
        "실패",
        "한도",
        "범위 밖",
        "기록 없음",
        "요청 적합성 1점",
        "차별성 1점",
        "근거 유효율 0",
        "두 판정이 다르면 그대로",
        "out_of_scope",
    ):
        assert phrase in sentence
    assert f"19. {sentence}" in prereg.render_preregistration(**render_inputs)
    original = json.dumps(prereg.REQUIRED_SENTENCES[:18], ensure_ascii=False)
    assert hashlib.sha256(original.encode()).hexdigest() == (
        "8e0a75bfa9e8363815950108a523829853ed88b80734ce5049247d2909b6fba2"
    )


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
def dev_measurement():
    """Invented metrics, prices and candidates, unrelated to live measurements."""
    models = [
        {
            "embedding_model": model,
            "price_per_million": price,
            "hit_at_k": hit,
            "recall_at_k": recall,
            "n_with_target": 7,
            "n_no_target": 2,
            "hit_at_k_all_questions": old_hit,
        }
        for model, price, hit, recall, old_hit in (
            ("text-embedding-3-large", 0.37, None, None, None),
            ("text-embedding-3-small", 0.11, 0.625, 0.375, 0.25),
        )
    ]
    return {
        "selected_model": models[1]["embedding_model"],
        "dev_question_hash": "abcdef01" * 8,
        "selection_rule": "synthetic_selection_rule",
        "truncated_document_ratio": 0.125,
        "truncated_dev_evidence_ratio": None,
        "n_set_questions_values_not_in_corpus": 4,
        "models": models,
        "combinations": [
            {**model, "top_k": k, "max_doc_chars": length}
            for model, k, length in product(models, (3, 17), (47, 83))
        ]
        + [
            {
                **models[1],
                "top_k": e3_live.TOP_K,
                "max_doc_chars": e3_live.MAX_DOC_CHARS,
            }
        ],
    }


@pytest.fixture
def cli_inputs(tmp_path, monkeypatch, request, dev_measurement):
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
    measurement.write_text(json.dumps(dev_measurement), encoding="utf-8")
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
    for section, label in (
        ("E2", "지정 축 준수(코드 판정, 참고용)"),
        ("E5", "목적별 입력 토큰(기획 포함, 참고용)"),
    ):
        content = text.split(f"## {section}\n", 1)[1].split("\n## ", 1)[0]
        assert f"| {label} |  |  |  |  |" in content
    for section in ("E2", "E5"):
        content = text.split(f"## {section}\n", 1)[1].split("\n## ", 1)[0]
        for label in (
            "팔별 기획 실패율",
            "완전 사례 민감도 판정",
            "실행되지 않은 항목 수",
        ):
            assert f"| {label} |  |  |  |  |" in content


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


MEASUREMENT_KEYS = {
    "root": (
        "selected_model",
        "dev_question_hash",
        "selection_rule",
        "truncated_document_ratio",
        "truncated_dev_evidence_ratio",
        "n_set_questions_values_not_in_corpus",
        "models",
        "combinations",
    ),
    "models": (
        "embedding_model",
        "price_per_million",
        "hit_at_k",
        "recall_at_k",
        "n_with_target",
        "n_no_target",
        "hit_at_k_all_questions",
    ),
    "combinations": (
        "embedding_model",
        "top_k",
        "max_doc_chars",
        "hit_at_k",
        "recall_at_k",
        "n_with_target",
        "n_no_target",
    ),
}


def test_none_measurement_preserves_original_bytes(render_inputs):
    text = prereg.render_preregistration(**render_inputs, dev_measurement=None)
    assert text == prereg.render_preregistration(**render_inputs)
    assert "E3 dev 측정 근거" not in text
    # 이 step에서 동결 줄과 25번째 문장 추가로 갱신.
    # 2026-11-20 6b-clarify step 3: 프롬프트 동결 줄 변경으로 갱신
    assert hashlib.sha256(text.encode()).hexdigest() == (
        "27e8ba2d58a4730d7ef02abad30f24e12968e21c6f56c3d99cfcee9545b3d040"
    )


def test_dev_measurement_tables_preserve_every_cell_and_order(
    render_inputs, dev_measurement
):
    before = deepcopy(dev_measurement)
    text = prereg.render_preregistration(
        **render_inputs, dev_measurement=dev_measurement
    )
    section = text.split("## E3 dev 측정 근거\n", 1)[1].split("## 절차와 한계", 1)[0]
    tables = [
        block.splitlines() for block in section.split("\n\n") if block.startswith("| ")
    ]
    assert len(tables) == 3
    for table, name in zip(tables, ("models", "combinations")):
        assert len(table[2:]) == len(dev_measurement[name])
        for line, row in zip(table[2:], dev_measurement[name], strict=True):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            assert cells == [
                "해당 없음" if row[key] is None else str(row[key])
                for key in MEASUREMENT_KEYS[name]
            ]
    value_rows = [
        [cell.strip() for cell in line.strip("|").split("|")] for line in tables[2][2:]
    ]
    assert [row[0] for row in value_rows] == [
        "선택 모델",
        "선택 규칙",
        "dev 질문 세트 해시",
        "잘린 문서 비율",
        "정답 근거 소재 문서 중 잘린 비율",
        "정답 값이 코퍼스에 없는 집합 질문 수",
        "측정 파일 기본 TOP_K",
        "동결 TOP_K",
        "동결 MAX_DOC_CHARS",
    ]
    assert [row[1] for row in value_rows] == [
        str(dev_measurement[key]) if dev_measurement[key] is not None else "해당 없음"
        for key in (
            "selected_model",
            "selection_rule",
            "dev_question_hash",
            "truncated_document_ratio",
            "truncated_dev_evidence_ratio",
            "n_set_questions_values_not_in_corpus",
        )
    ] + ["해당 없음", str(e3_live.TOP_K), str(e3_live.MAX_DOC_CHARS)]
    assert all(":" not in line for line in section.splitlines())
    assert guard.parse_preregistration(text) == guard.parse_preregistration(
        prereg.render_preregistration(**render_inputs)
    )
    assert text == prereg.render_preregistration(
        **render_inputs, dev_measurement=dev_measurement
    )
    assert dev_measurement == before


@pytest.mark.parametrize("measurement_k", [None, 7])
def test_dev_evidence_records_measurement_and_frozen_parameters(
    render_inputs, dev_measurement, measurement_k
):
    if measurement_k is not None:
        dev_measurement["top_k"] = measurement_k
    text = prereg.render_preregistration(
        **render_inputs, dev_measurement=dev_measurement
    )
    section = text.split("## E3 dev 측정 근거\n", 1)[1].split("## 절차와 한계", 1)[0]
    assert (
        f"| 측정 파일 기본 TOP_K | {measurement_k if measurement_k is not None else '해당 없음'} |"
        in section
    )
    assert f"| 동결 TOP_K | {e3_live.TOP_K} |" in section
    assert f"| 동결 MAX_DOC_CHARS | {e3_live.MAX_DOC_CHARS} |" in section
    assert all(":" not in line for line in section.splitlines())
    parsed = guard.parse_preregistration(text)
    assert parsed == guard.parse_preregistration(
        prereg.render_preregistration(**render_inputs)
    )
    assert parsed["동결 E3 TOP_K"] == "50"


@pytest.mark.parametrize("missing", ["absent", "other_model_only", "different_length"])
def test_prereg_requires_selected_models_frozen_combination(
    render_inputs, dev_measurement, missing
):
    frozen = dev_measurement["combinations"].pop()
    if missing == "other_model_only":
        frozen["embedding_model"] = dev_measurement["models"][0]["embedding_model"]
        dev_measurement["combinations"].append(frozen)
    elif missing == "different_length":
        frozen["max_doc_chars"] += 1
        dev_measurement["combinations"].append(frozen)
    assert prereg.validate_dev_measurement(dev_measurement) is None
    with pytest.raises(ValueError, match="^PREREG_INPUT_INVALID$"):
        prereg.render_preregistration(**render_inputs, dev_measurement=dev_measurement)


@pytest.mark.parametrize(
    "scope,key",
    [(scope, key) for scope, keys in MEASUREMENT_KEYS.items() for key in keys],
)
def test_dev_measurement_requires_every_key(dev_measurement, scope, key):
    row = dev_measurement if scope == "root" else dev_measurement[scope][-1]
    del row[key]
    with pytest.raises(ValueError, match="^PREREG_INPUT_INVALID$"):
        prereg.validate_dev_measurement(dev_measurement)


@pytest.mark.parametrize("measurement", [None, [], "invalid", 7, True])
def test_dev_measurement_requires_dict(measurement):
    with pytest.raises(ValueError, match="^PREREG_INPUT_INVALID$"):
        prereg.validate_dev_measurement(measurement)


INVALID_MEASUREMENT_VALUES = (
    [
        ("root", "selected_model", value)
        for value in ("unknown", [], None, "model:invalid")
    ]
    + [
        ("root", key, value)
        for key in ("models", "combinations")
        for value in ([], {}, None, "invalid", [None], [[]])
    ]
    + [
        ("root", "dev_question_hash", value)
        for value in ("a" * 63, "a" * 65, "A" * 64, "g" * 64, "a" * 64 + "\n", None, 64)
    ]
    + [("root", "selection_rule", value) for value in ("rule:invalid", None, [])]
    + [("models", "embedding_model", value) for value in ("unknown", None, [], "x:y")]
    + [("combinations", "embedding_model", value) for value in (None, [], "x:y")]
    + [
        ("combinations", key, value)
        for key in ("top_k", "max_doc_chars")
        for value in (0, -1, "3", True, 1.5, None)
    ]
    + [
        (scope, key, value)
        for scope, key in (
            ("root", "n_set_questions_values_not_in_corpus"),
            ("models", "n_with_target"),
            ("models", "n_no_target"),
            ("combinations", "n_with_target"),
            ("combinations", "n_no_target"),
        )
        for value in (-1, "2", True, 1.5, None)
    ]
    + [
        (scope, key, value)
        for scope, keys in (
            ("root", ("truncated_document_ratio", "truncated_dev_evidence_ratio")),
            (
                "models",
                (
                    "price_per_million",
                    "hit_at_k",
                    "recall_at_k",
                    "hit_at_k_all_questions",
                ),
            ),
            ("combinations", ("hit_at_k", "recall_at_k")),
        )
        for key in keys
        for value in (True, "0.5", [], {})
    ]
)


@pytest.mark.parametrize("scope,key,value", INVALID_MEASUREMENT_VALUES)
def test_invalid_dev_measurement_values_are_fixed_errors(
    render_inputs, dev_measurement, scope, key, value
):
    row = dev_measurement if scope == "root" else dev_measurement[scope][-1]
    row[key] = value
    with pytest.raises(ValueError, match="^PREREG_INPUT_INVALID$"):
        prereg.validate_dev_measurement(dev_measurement)
    with pytest.raises(ValueError, match="^PREREG_INPUT_INVALID$"):
        prereg.render_preregistration(**render_inputs, dev_measurement=dev_measurement)


def test_selected_model_must_be_measured(dev_measurement):
    dev_measurement["models"] = dev_measurement["models"][:1]
    with pytest.raises(ValueError, match="^PREREG_INPUT_INVALID$"):
        prereg.validate_dev_measurement(dev_measurement)


def test_measurement_model_list_is_not_expanded_or_filtered(
    render_inputs, dev_measurement
):
    dev_measurement["models"] = dev_measurement["models"][1:]
    dev_measurement["combinations"] = dev_measurement["combinations"][-1:]
    prereg.validate_dev_measurement(dev_measurement)
    text = prereg.render_preregistration(
        **render_inputs, dev_measurement=dev_measurement
    )
    section = text.split("## E3 dev 측정 근거", 1)[1].split("## 절차와 한계", 1)[0]
    assert "text-embedding-3-large" not in section


def test_cli_measurement_override_reads_once_and_prints_evidence(
    cli_inputs, tmp_path, monkeypatch, dev_measurement
):
    path = prereg.EMBEDDING_MEASUREMENT_PATH
    monkeypatch.setattr(prereg, "EMBEDDING_MEASUREMENT_PATH", tmp_path / "absent.json")
    original_read = Path.read_text
    reads = []

    def read(path_, *args, **kwargs):
        if path_ == path:
            reads.append(path_)
        return original_read(path_, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    out = io.StringIO()
    assert prereg.main(["--print", "--dev-measurement", str(path)], out=out) == 0
    assert reads == [path]
    assert "## E3 dev 측정 근거" in out.getvalue()
    assert dev_measurement["dev_question_hash"] in out.getvalue()


def test_cli_print_adds_evidence_without_writing(cli_inputs, tmp_path):
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    out = io.StringIO()
    assert prereg.main(["--print"], out=out) == 0
    assert "## E3 dev 측정 근거" in out.getvalue()
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("override", [False, True])
def test_cli_incomplete_measurement_never_creates_document(
    cli_inputs, tmp_path, dev_measurement, override
):
    del dev_measurement["models"][-1]["recall_at_k"]
    path = prereg.EMBEDDING_MEASUREMENT_PATH
    path.write_text(json.dumps(dev_measurement), encoding="utf-8")
    target = tmp_path / "prereg.md"
    args = ["--write", str(target)]
    if override:
        args.extend(["--dev-measurement", str(path)])
    out = io.StringIO()
    assert prereg.main(args, out=out) == 1
    assert out.getvalue() == "PREREG_INPUT_INVALID\n"
    assert not target.exists()


def test_repeat_procedures_and_empty_distribution_template(render_inputs):
    sentences = prereg.REQUIRED_SENTENCES
    assert len(sentences) == 25
    for phrase in (
        "2회",
        "요청 20건 × 2회",
        "요청별로 평균",
        "단위는 요청",
        "10,000회",
        "모델 비결정성",
        "docs/EVAL.md",
    ):
        assert phrase in sentences[2]
    for phrase in ("반복 1", "근거 소재마다 한 행", "200행", "고정 시드"):
        assert phrase in sentences[3]
    for phrase in ("우리 요청은 전부 지원 범위 안", "out_of_scope", "실패로 센다"):
        assert phrase in sentences[18]
    for phrase in (
        "반복마다 따로 채점",
        "팔 이름 숨김",
        "순서 섞기",
        "고정 시드",
        "숨김 id",
        "최저점",
        "반복 단위",
        "일부만 없으면",
        "하나도 없으면",
        "요청별 반복 평균",
        "두 반복을 모두 재사용",
        "같은 코드 커밋",
        "세트 해시",
        "채점 실행",
        "E3와 격리는 반복하지 않는다",
    ):
        assert phrase in sentences[19]
    assert f"20. {sentences[19]}" in prereg.render_preregistration(**render_inputs)
    section = (
        prereg.render_results_template().split("## E2\n", 1)[1].split("\n## ", 1)[0]
    )
    assert "| 요청당 반복 수(팔별 분포) |  |  |  |  |" in section


def test_interpretation_change_and_limit_are_appended_and_frozen(render_inputs):
    from beautyads.agents.supervisor import SUPERVISOR_PROMPT_VERSION

    changed, limitation = prereg.REQUIRED_SENTENCES[21:23]
    for phrase in (
        "P5 이후",
        "dev 스모크",
        "동결",
        "pattern_context",
        SUPERVISOR_PROMPT_VERSION,
        "대응표",
        "payload",
        "기획·평가 프롬프트",
        "기획 단계",
    ):
        assert phrase in changed
    for phrase in ("자유 표현", "단일 팔은 원문", "표시 이름", "UGC", "후기 영상"):
        assert phrase in limitation
    rendered = prereg.render_preregistration(**render_inputs)
    assert changed in rendered and limitation in rendered
    parsed = guard.parse_preregistration(rendered)
    for label in (
        "동결 해석 프롬프트 버전",
        "동결 해석 _SYSTEM sha256",
        "동결 해석 대응표 sha256",
    ):
        assert parsed[label] == guard.frozen_values()[label]
    content = (
        prereg.render_results_template().split("## E2\n", 1)[1].split("\n## ", 1)[0]
    )
    assert "| 요청에 없는 축 채움(과채움, 코드 판정, 참고용) |  |  |  |  |" in content


def test_axis_adherence_supplement_is_twenty_fourth_procedure(render_inputs):
    sentence = prereg.REQUIRED_SENTENCES[23]
    for phrase in (
        "정지 이미지",
        "불안정",
        "지정 축 준수율",
        "해석 채움",
        "최종 기획안 준수",
        "요청에 없는 축 채움",
        "과채움",
        "코드 판정 보조 지표",
        "판정에 쓰지 않",
        "graph_adopted",
        "verdict_e2",
        "verdict_e5",
        "dev 재스모크",
        "지정 축 요청 8건 중 해석 채움 6건",
        "과채움 0건",
        "최종 기획안 준수 8건",
        "해석 누락 2건은 모두 정지 이미지 포맷",
        "dev 관찰이며 test 결과가 아니다",
    ):
        assert phrase in sentence
    assert f"24. {sentence}\n" in prereg.render_preregistration(**render_inputs)


def test_first_twenty_three_procedures_remain_byte_identical():
    original = json.dumps(prereg.REQUIRED_SENTENCES[:23], ensure_ascii=False)
    assert hashlib.sha256(original.encode()).hexdigest() == (
        "786632ffa3d03b04bb13afb70951ed6fd58b022e7996e8fc85c6fcb0834cec6e"
    )


def test_first_twenty_four_procedures_remain_byte_identical():
    original = json.dumps(prereg.REQUIRED_SENTENCES[:24], ensure_ascii=False)
    assert hashlib.sha256(original.encode()).hexdigest() == (
        "fa0a73058096fa36463fd43e04a174efe04a2d435057f5464b77e51f13730908"
    )


def test_evaluation_model_explanation_is_twenty_fifth_procedure(render_inputs):
    sentence = prereg.REQUIRED_SENTENCES[24]
    for phrase in (
        '문장 2의 "생성 모델이 같다"',
        "기획 생성 모델(gpt-6.1-terra, reasoning_effort low)",
        "도구 집합·한도",
        "Supervisor의 요청 해석·리서치는 gpt-6-luna",
        f"루프 내 평가는 {e2e5_live._EVALUATION_MODEL}(최종 실행)",
        "단일 팔의 도구 루프와 기획은 gpt-6.1-terra(reasoning_effort low) 하나다",
        "격리 실험은 표식 노출만",
        "루프 내 평가 모델은 claude-haiku-5-5",
        "결과 해석에 영향 없음",
    ):
        assert phrase in sentence
    assert ":" not in sentence and "\n" not in sentence
    assert f"25. {sentence}\n" in prereg.render_preregistration(**render_inputs)


@pytest.mark.parametrize("change", [None, "value", "missing"])
def test_loop_evaluation_model_label_roundtrips_and_is_enforced(
    tmp_path, request, render_inputs, change
):
    paths = [tmp_path / name for name in ("r.jsonl", "q.jsonl", "a.jsonl")]
    for path, collection in zip(paths, synthetic_set(), strict=True):
        sets.write_jsonl(path, collection)
    label = "동결 Supervisor 루프 내 평가 모델"
    rendered = prereg.render_preregistration(**render_inputs)
    assert guard.parse_preregistration(rendered)[label] == "claude-sonnet-5-5"
    line = guard.PREREG_LINE_FORMAT.format(label=label, value="claude-sonnet-5-5")
    if change == "value":
        rendered = rendered.replace(line, line.replace("sonnet", "haiku"))
    elif change == "missing":
        rendered = rendered.replace(line + "\n", "")
    path = tmp_path / "prereg.md"
    path.write_text(rendered, encoding="utf-8")
    options = {
        "mode": "final",
        "groups": {"test"},
        "requests_path": paths[0],
        "questions_path": paths[1],
        "answers_path": paths[2],
        "workspaces_path": request.getfixturevalue("workspace_config"),
        "prereg_path": path,
        "extra": render_inputs["extra"],
        "committed_fn": lambda path: True,
        "run": FakeGit(),
    }
    if change is None:
        assert guard.check_run(**options).request_hash == render_inputs["request_hash"]
    else:
        with pytest.raises(guard.FreezeError, match="^FROZEN_VALUE_MISMATCH$"):
            guard.check_run(**options)
