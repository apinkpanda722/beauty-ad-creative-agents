"""E1 scoring uses only synthetic labels, keys and an in-memory repository."""

import csv
import json
from copy import deepcopy
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml

from beautyads.domain import CreativeKey, JobStatus
from beautyads.domain.labels import Category, Claim, ContentType
from beautyads.eval import e1_sampling
from beautyads.eval import e1_scorer as scorer
from beautyads.eval import pilot_compare as pilot
from beautyads.eval.e1_sampling import STAGE1_COLUMNS
from beautyads.eval.sheets import label_columns

SENTINEL = "PRIVATE_TITLE_CAPTION_LABEL_SENTINEL"
PRODUCT = ContentType.product_creative.value
NON_PRODUCT = ContentType.event_place.value
STAGE2_AXES = [a for a in label_columns() if a not in {"content_type", "category"}]


def write_csv(path, fields, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def model_labels(model, alternate=False):
    result = {}
    for name, field in model.model_fields.items():
        kind = field.annotation
        if name == "ingredients":
            result[name] = [SENTINEL]
        elif name == "claims":
            result[name] = [list(Claim)[int(alternate)].value]
        elif kind is bool:
            result[name] = alternate
        elif hasattr(kind, "model_fields"):
            result[name] = model_labels(kind, alternate)
        else:
            values = list(kind)
            result[name] = values[int(alternate)].value
    # Respect frozen CTA equivalence for synthetic v1 outputs.
    if "cta_type" in result:
        result["structure"]["has_cta"] = result["cta_type"] != "none"
    return result


def tasks(alternate=False, content=PRODUCT, category=None):
    result = {
        name: {"status": "done", "labels": model_labels(model, alternate)}
        for name, model in pilot.TASK_MODELS.items()
    }
    result["content_type"]["labels"].update(
        content_type=content, category=category or list(Category)[int(alternate)].value
    )
    if content != PRODUCT or category == "other":
        result.pop("hook")
        result.pop("full")
    return result


def human(alternate=False):
    saved = tasks(alternate)
    return {axis: pilot._model_value(saved, axis) for axis in label_columns()}


def csv_row(item_id, values, axes):
    return {
        "item_id": item_id,
        "link": "https://example.invalid",
        "text": SENTINEL,
        **{
            a: ""
            if values[a] is None
            else (
                str(values[a]).lower()
                if isinstance(values[a], bool)
                else ",".join(sorted(values[a]))
                if a == "claims"
                else values[a]
            )
            for a in axes
        },
    }


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(
        e1_sampling,
        "TAXONOMY_PATH",
        Path(__file__).resolve().parents[1] / "docs/TAXONOMY.md",
    )
    monkeypatch.chdir(tmp_path)
    config = {
        "seed": 1,
        "stage1": {
            "min_labeled": 4,
            "max_labeled": 8,
            "target_product": 3,
            "use_all_labeled": False,
        },
        "stage2": {
            "size": 4,
            "categories": [c.value for c in Category if c.value != "other"],
        },
        "accepted_stage1_provenance": {},
        "sources": ["youtube", "instagram"],
        "dedupe": {
            "youtube": ["source", "account", "title", "caption"],
            "instagram": ["source", "account", "caption"],
        },
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config))
    prereg = tmp_path / "prereg.md"
    prereg.write_text(
        "## 5. E1 채점 분모 규칙\n"
        "축별 일치율·Cohen's κ와 합격 판정은 사람과 모델이 모두 `product_creative`로 본 교집합.\n"
        "커버리지 = 교집합 건수 ÷ 사람이 제품으로 본 건수.\n"
        "사람 재검사 κ는 2단계 표본 전체. 소구점도 같은 교집합.\n"
        "## 6. 분류 동결\n전체 v1 동결: 2026-11-13\n"
    )
    stage1 = tmp_path / "e1_stage1_sheet_labeled.csv"
    first = tmp_path / "e1_stage2_sheet_labeled.csv"
    retest = tmp_path / "e1_stage2_sheet_retest.csv"
    key1, key2 = tmp_path / "e1_stage1_key.json", tmp_path / "e1_stage2_key.json"
    humans = [human(i % 2 == 1) for i in range(6)]
    write_csv(
        stage1,
        STAGE1_COLUMNS,
        [
            csv_row(f"E{i + 1:03}", row, STAGE1_COLUMNS[3:])
            for i, row in enumerate(humans)
        ],
    )
    stage2_rows = [
        csv_row(f"F{i + 1:03}", row, STAGE2_AXES) for i, row in enumerate(humans[:4])
    ]
    write_csv(first, ["item_id", "link", "text", *STAGE2_AXES], stage2_rows)
    write_csv(retest, ["item_id", "link", "text", *STAGE2_AXES], stage2_rows)
    identities = [
        {
            "source": "youtube",
            "source_id": str(i),
            "brand": "synthetic",
            "account": "synthetic",
            "url": None,
        }
        for i in range(6)
    ]
    key1.write_text(
        json.dumps(
            {"items": {f"E{i + 1:03}": item for i, item in enumerate(identities)}}
        )
    )
    key2.write_text(
        json.dumps(
            {
                "items": {
                    f"F{i + 1:03}": {
                        **identities[i],
                        "stage1_human_labels": {
                            a: humans[i][a] for a in ("content_type", "category")
                        },
                    }
                    for i in range(4)
                }
            }
        )
    )
    saved = {str(i): tasks(i % 2 == 1) for i in range(6)}
    store = Mock()

    def get_jobs(kind, keys):
        task = kind.removesuffix("@v1")
        return [
            SimpleNamespace(key=key, kind=kind, **saved[key.source_id][task])
            for key in keys
            if task in saved[key.source_id]
        ]

    store.get_job_results.side_effect = get_jobs
    factory = Mock(return_value=store)
    args = [
        "--stage1-labels",
        str(stage1),
        "--stage2-labels",
        str(first),
        "--retest-labels",
        str(retest),
        "--stage1-key",
        str(key1),
        "--stage2-key",
        str(key2),
        "--config",
        str(config_path),
        "--preregistration",
        str(prereg),
    ]
    return SimpleNamespace(**locals())


def cli(ws, **kwargs):
    out = StringIO()
    code = scorer.main(
        ws.args,
        out=out,
        environ={"POSTGRES_PASSWORD": "synthetic"},
        docker_check=lambda: True,
        tcp_check=lambda *args: True,
        store_factory=ws.factory,
        **kwargs,
    )
    return code, out.getvalue()


def report(ws):
    code, output = cli(ws)
    return code, output, json.loads(output.splitlines()[-1])


def metric(data, axis, comparison="human_model"):
    return next(
        r
        for r in data["metrics"]
        if r["axis"] == axis and r["comparison"] == comparison
    )


@pytest.mark.parametrize("missing", ["stage1", "first", "retest"])
def test_not_ready_opens_nothing(workspace, monkeypatch, missing):
    ws = workspace
    path = getattr(ws, missing)
    path.unlink()
    open_file = Mock(side_effect=AssertionError("must not open any file"))
    key_reader = Mock(side_effect=AssertionError("must not read keys"))
    monkeypatch.setattr(Path, "open", open_file)
    monkeypatch.setattr(scorer, "read_keys", key_reader)
    code, output = cli(ws)
    assert code == 2 and output.strip() == f"NOT_READY:{path.name}"
    open_file.assert_not_called()
    key_reader.assert_not_called()
    ws.factory.assert_not_called()
    assert not any(word in output for word in ("score", "rate", "κ", "일치율"))


@pytest.mark.parametrize("file", ["stage1", "first", "retest"])
@pytest.mark.parametrize(
    "damage", ["header", "value", "empty", "duplicate", "short", "cta"]
)
def test_invalid_label_precedes_keys_and_database(workspace, monkeypatch, file, damage):
    ws = workspace
    path = getattr(ws, file)
    if damage == "cta" and file == "stage1":
        return
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        fields, rows = reader.fieldnames, list(reader)
    if damage == "header":
        fields = [SENTINEL, *fields[1:]]
        path.write_text(",".join(fields))
    elif damage == "empty":
        write_csv(path, fields, [])
    elif damage == "short":
        path.write_text(",".join(fields) + "\nE001\n")
    else:
        if damage == "duplicate":
            rows[1]["item_id"] = rows[0]["item_id"]
        elif damage == "cta":
            rows[0]["has_cta"] = "true"  # first synthetic row has cta_type none
        else:
            rows[0]["content_type" if file == "stage1" else "angle"] = SENTINEL
        write_csv(path, fields, rows)
    reader = Mock(side_effect=AssertionError("keys must remain unread"))
    monkeypatch.setattr(scorer, "read_keys", reader)
    code, output = cli(ws)
    assert code == 2 and output.strip() == "LABEL_FILE_INVALID"
    reader.assert_not_called()
    ws.factory.assert_not_called()
    assert SENTINEL not in output


def test_stop_recall_matrix_missing_denominator(workspace):
    ws = workspace
    ws.saved["1"] = tasks(content=NON_PRODUCT)
    ws.saved["2"]["content_type"]["status"] = JobStatus.held
    code, output, data = report(ws)
    recall = data["content_type"]
    assert code == 0 and SENTINEL not in output
    assert data["stop_position"] == 4 and data["unused_count"] == 2
    assert recall["human_product"] == 4 and recall["model_missing"] == 1
    assert recall["recall"] == 2 / 4 and recall["meets_threshold"] is False
    assert recall["confusion_matrix"][PRODUCT][PRODUCT] == 2
    assert recall["confusion_matrix"][PRODUCT][NON_PRODUCT] == 1
    assert recall["confusion_matrix"][PRODUCT]["model_missing"] == 1
    assert metric(data, "hook_type")["n"] == 2
    assert metric(data, "hook_type")["coverage"] == 2 / 4


def test_intersection_coverage_and_pass_do_not_use_missed_items(workspace):
    ws = workspace
    ws.saved["3"] = tasks(content=NON_PRODUCT)
    _, _, data = report(ws)
    row = metric(data, "hook_type")
    assert row["n"] == 3 and row["human_product"] == 4
    assert row["coverage"] == 3 / 4
    assert row["rate"] == row["kappa"] == 1 and row["meets_threshold"] is True
    assert data["content_type"]["recall"] == 3 / 4
    assert metric(data, "hook_type", "human_retest")["n"] == 4


@pytest.mark.parametrize(
    "pairs, rate, kappa",
    [
        ([(0, 0), (0, 1), (1, 1), (1, 1)], 3 / 4, 1 / 2),
        ([(0, 1), (0, 1), (1, 0), (1, 0)], 0, -1),
        ([(False, False), (False, True), (True, True), (True, False)], 1 / 2, 0),
    ],
)
def test_hand_calculated_agreement_and_kappa(pairs, rate, kappa):
    result = scorer.axis_score(
        "synthetic", pairs, comparison="human_model", human_product=4
    )
    assert result["rate"] == pytest.approx(rate)
    assert result["kappa"] == pytest.approx(kappa)


@pytest.mark.parametrize("pairs", [[(0, 0)], [(0, 0), (0, 1)], [(0, 1), (1, 1)]])
def test_constant_marginal_is_undefined(pairs):
    row = scorer.axis_score(
        "synthetic", pairs, comparison="human_model", human_product=2
    )
    assert row["kappa"] is None and row["meets_threshold"] is None
    assert row["reason"] == "KAPPA_UNDEFINED:synthetic"


def test_empty_score_is_not_zero():
    row = scorer.axis_score("synthetic", [], comparison="human_model", human_product=0)
    assert row["n"] == 0 and row["rate"] is row["kappa"] is None
    assert row["reason"] == "SCORE_EMPTY_SET:synthetic"


def test_retest_kappa_hand_calculated(workspace):
    ws = workspace
    rows = deepcopy(ws.stage2_rows)
    rows[2]["hook_type"] = rows[1]["hook_type"]
    write_csv(ws.retest, ["item_id", "link", "text", *STAGE2_AXES], rows)
    _, _, data = report(ws)
    row = metric(data, "hook_type", "human_retest")
    assert row["n"] == 4 and row["rate"] == 3 / 4 and row["kappa"] == 1 / 2
    assert row["meets_threshold"] is False and row["ambiguous_definition"] is True


def test_claims_delegate_item_and_micro_scores(workspace, monkeypatch):
    ws = workspace
    a, b, c = [v.value for v in list(Claim)[:3]]
    # First two humans claim a / b. Model first invents c and misses a.
    ws.saved["0"]["full"]["labels"]["claims"] = [c]
    spy = Mock(wraps=pilot.claim_scores)
    monkeypatch.setattr(pilot, "claim_scores", spy)
    _, output, data = report(ws)
    assert spy.call_count == 2
    assert all(r["axis"] != "claims" for r in data["metrics"])
    entry = data["claims"]["human_model"]
    scores = {r["claim"]: r for r in entry["items"]}
    assert scores[a]["precision"] == 1 and scores[a]["recall"] == 1 / 2
    assert scores[b]["precision"] == scores[b]["recall"] == 1
    assert scores[c]["precision"] == 0 and scores[c]["recall"] is None
    assert entry["micro_precision"] == entry["micro_recall"] == 3 / 4
    assert "rate" not in entry and "kappa" not in entry and SENTINEL not in output


def test_thresholds_frozen_and_not_parser_options():
    assert scorer.THRESHOLDS == {
        "human_retest": 0.7,
        "human_model": 0.6,
        "content_type": 0.9,
    }
    for name, value in scorer.THRESHOLDS.items():
        assert scorer.meets_threshold(value, name) is True
        assert scorer.meets_threshold(value - 0.00001, name) is False
        assert scorer.meets_threshold(None, name) is None
    options = scorer.build_parser()._option_string_actions
    assert set(options) == {
        "-h",
        "--help",
        "--stage1-labels",
        "--stage2-labels",
        "--retest-labels",
        "--stage1-key",
        "--stage2-key",
        "--config",
        "--preregistration",
    }


@pytest.mark.parametrize(
    "text", ["", "## 4. 比較\nproduct_creative 交集", "## 5. E1\n交集"]
)
def test_missing_registered_rule_prevents_database(workspace, text):
    workspace.prereg.write_text(text)
    code, output = cli(workspace)
    assert code == 2 and output.strip() == "PREREGISTRATION_RULE_MISSING"
    workspace.factory.assert_not_called()


def test_category_other_is_separate_analysis_gap(workspace):
    ws = workspace
    ws.saved["0"] = tasks(category="other")
    _, _, data = report(ws)
    assert data["content_type"]["recall"] == 1
    assert metric(data, "category")["n"] == 4
    row = metric(data, "hook_type")
    assert row["n"] == 3 and row["coverage"] == 3 / 4 and row["not_analyzed"] == 1
    assert row["not_analyzed_reason"] == pilot.NOT_ANALYZED_REASON


@pytest.mark.parametrize("task", ["hook", "full"])
@pytest.mark.parametrize("status", ["absent", "pending", "failed", "held"])
def test_item_level_exclusions_match_pilot(workspace, task, status):
    ws = workspace
    if status == "absent":
        ws.saved["0"].pop(task)
    else:
        ws.saved["0"][task]["status"] = status
    _, _, data = report(ws)
    assert data["excluded"] == [{"item_id": "F001", "task": task}]
    assert metric(data, "category")["n"] == 3
    assert metric(data, "category")["coverage"] == 3 / 4
    assert data["content_type"]["recall"] == 1


def test_undefined_and_empty_axes_exit_three_without_fabrication(workspace):
    ws = workspace
    for saved in ws.saved.values():
        saved["hook"]["labels"] = model_labels(pilot.TASK_MODELS["hook"])
    rows = deepcopy(ws.stage2_rows)
    for row in rows:
        row["is_vertical"] = ""
    write_csv(ws.first, ["item_id", "link", "text", *STAGE2_AXES], rows)
    code, output, data = report(ws)
    assert code == 3
    assert metric(data, "hook_type")["kappa"] is None
    assert "KAPPA_UNDEFINED:hook_type" in output
    assert "SCORE_EMPTY_SET:is_vertical" in output
    assert metric(data, "is_vertical")["rate"] is None


def test_only_v1_repository_reads_after_validation(workspace):
    ws = workspace
    _, _, data = report(ws)
    calls = ws.store.get_job_results.call_args_list
    assert [c.args[0] for c in calls] == ["content_type@v1", "hook@v1", "full@v1"]
    assert all(isinstance(k, CreativeKey) for c in calls for k in c.args[1])
    assert {k.source_id for c in calls for k in c.args[1]} == {"0", "1", "2", "3"}
    assert data["thresholds"] == scorer.THRESHOLDS


@pytest.mark.parametrize("problem", ["env", "docker", "tcp", "port"])
def test_preflight_never_connects_or_emits_scores(workspace, problem):
    ws = workspace
    environ = {} if problem == "env" else {"POSTGRES_PASSWORD": "synthetic"}
    if problem == "port":
        environ["BEAUTYADS_POSTGRES_PORT"] = "invalid"
    out = StringIO()
    code = scorer.main(
        ws.args,
        out=out,
        environ=environ,
        docker_check=lambda: problem != "docker",
        tcp_check=lambda *args: problem != "tcp",
        store_factory=ws.factory,
    )
    expected = {
        "env": "ENV_MISSING:POSTGRES_PASSWORD",
        "docker": "DOCKER_DOWN",
        "tcp": "POSTGRES_UNREACHABLE",
        "port": "POSTGRES_UNREACHABLE",
    }[problem]
    assert code == 2 and out.getvalue().strip() == expected
    ws.factory.assert_not_called()


def test_make_target_manual_only():
    makefile = (Path(__file__).resolve().parents[1] / "Makefile").read_text()
    assert "e1-score" in makefile.splitlines()[0].split()
    assert (
        "e1-score:\n\tuv run python -m beautyads.eval.e1_scorer $(ARGS)\n" in makefile
    )
    assert "e1-score" not in makefile.split("verify:\n", 1)[1].split("\n\n", 1)[0]


def test_agreement_is_reused_and_helpers_do_not_print(workspace, monkeypatch, capsys):
    ws = workspace
    args = scorer.build_parser().parse_args(ws.args)
    config = scorer.load_e1_config(args.config)
    inputs = scorer.read_keys(
        args,
        scorer.read_label_file(ws.first, stage=2),
        scorer.read_label_file(ws.retest, stage=2),
        config,
    )
    spy = Mock(wraps=pilot.agreement)
    monkeypatch.setattr(pilot, "agreement", spy)
    saved = scorer.read_model_results(ws.store, inputs)
    scorer.score(inputs, saved)
    assert spy.call_count == len(pilot.AGREEMENT_AXES) + len(STAGE2_AXES) - 1
    assert capsys.readouterr().out == capsys.readouterr().err == ""


@pytest.mark.parametrize("status", ["absent", "pending", "failed", "held"])
def test_missing_content_results_remain_in_recall(workspace, status):
    ws = workspace
    if status == "absent":
        ws.saved["0"].pop("content_type")
    else:
        ws.saved["0"]["content_type"]["status"] = status
    _, _, data = report(ws)
    content = data["content_type"]
    assert content["human_product"] == 4 and content["model_missing_human_product"] == 1
    assert content["recall"] == 3 / 4
    assert metric(data, "category")["coverage"] == 3 / 4


def test_non_products_and_missing_are_separate_matrix_cells(workspace):
    ws = workspace
    # Stage-two keys remain products. Add two stage-one-only non-products.
    rows = [
        csv_row(f"E{i + 1:03}", row, STAGE1_COLUMNS[3:])
        for i, row in enumerate(ws.humans)
    ]
    for row in rows[4:]:
        row.update(content_type=NON_PRODUCT, category="other")
    write_csv(ws.stage1, STAGE1_COLUMNS, rows)
    cfg = yaml.safe_load(ws.config_path.read_text())
    cfg["stage1"]["use_all_labeled"] = True
    ws.config_path.write_text(yaml.safe_dump(cfg))
    ws.saved["4"] = tasks(content=NON_PRODUCT)
    ws.saved["5"] = {}
    _, _, data = report(ws)
    content = data["content_type"]
    assert content["n"] == 6 and content["human_product"] == 4
    assert content["recall"] == 1
    assert content["model_missing"] == 1 and content["model_missing_human_product"] == 0
    assert content["confusion_matrix"][NON_PRODUCT][NON_PRODUCT] == 1
    assert content["confusion_matrix"][NON_PRODUCT]["model_missing"] == 1


@pytest.mark.parametrize(
    "damage", ["missing", "json", "shape", "identity", "labels", "outside", "duplicate"]
)
def test_invalid_keys_never_connect(workspace, damage):
    ws = workspace
    if damage == "missing":
        ws.key2.unlink()
    elif damage == "json":
        ws.key2.write_text(SENTINEL)
    elif damage == "shape":
        ws.key2.write_text("[]")
    else:
        doc = json.loads(ws.key2.read_text())
        item = doc["items"]["F001"]
        if damage == "identity":
            item["source"] = SENTINEL
        elif damage == "labels":
            item["stage1_human_labels"]["category"] = "other"
        elif damage == "outside":
            item["source_id"] = "5"
        else:
            doc["items"]["F002"] = item
        ws.key2.write_text(json.dumps(doc))
    code, output = cli(ws)
    assert code == 2 and output.strip() == "LABEL_FILE_INVALID"
    ws.factory.assert_not_called()
    assert SENTINEL not in output


@pytest.mark.parametrize("task", ["content_type", "hook", "full"])
def test_bad_completed_model_labels_emit_no_partial_scores(workspace, task, caplog):
    ws = workspace
    ws.saved["0"][task]["labels"] = {"invalid": SENTINEL}
    code, output = cli(ws)
    assert code == 2 and output.strip() == "MODEL_RESULT_INVALID"
    assert SENTINEL not in output + caplog.text


def test_database_error_diagnostics_are_private(workspace, caplog):
    ws = workspace
    ws.store.get_job_results.side_effect = RuntimeError(SENTINEL)
    code, output = cli(ws)
    assert code == 2 and output.strip() == "MODEL_READ_FAILED"
    assert SENTINEL not in output + caplog.text


def test_empty_intersection_is_not_zero_and_retest_is_independent(workspace):
    ws = workspace
    for key in ws.saved:
        ws.saved[key] = tasks(content=NON_PRODUCT)
    code, output, data = report(ws)
    assert code == 3 and "SCORE_EMPTY_SET:claims" in output
    assert data["claims"]["human_model"]["micro_precision"] is None
    assert data["claims"]["human_model"]["n"] == 0
    assert metric(data, "hook_type")["rate"] is None
    assert metric(data, "hook_type")["coverage"] == 0
    assert metric(data, "hook_type", "human_retest")["kappa"] == 1


@pytest.mark.parametrize(
    "comparison, cells, expected",
    [
        ("human_model", (4, 1, 1, 4), 0.6),
        ("human_retest", (17, 3, 3, 17), 0.7),
    ],
)
def test_computed_kappa_at_frozen_boundary(comparison, cells, expected):
    a, b, c, d = cells
    pairs = [(0, 0)] * a + [(0, 1)] * b + [(1, 0)] * c + [(1, 1)] * d
    row = scorer.axis_score(
        "synthetic", pairs, comparison=comparison, human_product=len(pairs)
    )
    assert row["kappa"] == expected and row["meets_threshold"] is True


def test_coverage_rule_cannot_be_borrowed_from_another_section(workspace):
    ws = workspace
    ws.prereg.write_text(
        ws.prereg.read_text().replace("커버리지", "unregistered") + "\n커버리지"
    )
    code, output = cli(ws)
    assert code == 2 and output.strip() == "PREREGISTRATION_RULE_MISSING"
    ws.factory.assert_not_called()


def test_frozen_definition_record_required(workspace):
    ws = workspace
    ws.prereg.write_text(ws.prereg.read_text().split("## 6.")[0])
    code, output = cli(ws)
    assert code == 2 and output.strip() == "PREREGISTRATION_DEFINITIONS_MISSING"
    ws.factory.assert_not_called()


def test_new_exclusion_adapter_matches_unchanged_pilot():
    samples = [tasks(), tasks(content=NON_PRODUCT), tasks(category="other"), {}]
    for task in pilot.TASK_MODELS:
        for status in ("pending", "held", "failed"):
            saved = tasks()
            saved[task]["status"] = status
            samples.append(saved)
        saved = tasks()
        saved.pop(task)
        samples.append(saved)
    for saved in samples:
        original = deepcopy(saved)
        failures = pilot._exclusions(
            "synthetic", {"runs": {tag: saved for tag in pilot.RUN_TAGS}}
        )
        assert pilot.single_run_exclusions(saved) == [
            f["task"] for f in failures if f["run_tag"] == pilot.RUN_TAGS[0]
        ]
        assert saved == original
