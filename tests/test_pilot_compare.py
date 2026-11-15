"""Pilot comparison uses only synthetic CSV/JSON files in temporary directories."""

import csv
import json
from copy import deepcopy
from io import StringIO
from pathlib import Path
from unittest.mock import Mock

import pytest

from beautyads.analysis.axes import is_product_target
from beautyads.domain.labels import (
    Category,
    Claim,
    ContentType,
    ContentTypeResult,
    FullResult,
    HookResult,
)
from beautyads.eval import pilot_compare as compare
from beautyads.eval.sheets import _label_axes, label_columns

PRODUCT = ContentType.product_creative.value
NON_PRODUCT = ContentType.event_place.value
TAGS = ("minimal", "default")
MODELS = {"content_type": ContentTypeResult, "hook": HookResult, "full": FullResult}
SENTINEL = "PRIVATE_TITLE_CAPTION_SENTINEL"


def labels_for(model):
    result = {}
    for name, field in model.model_fields.items():
        annotation = field.annotation
        if name == "ingredients":
            result[name] = []
        elif name == "claims":
            result[name] = [next(iter(Claim)).value]
        elif annotation is bool:
            result[name] = True
        elif hasattr(annotation, "model_fields"):
            result[name] = labels_for(annotation)
        else:
            result[name] = next(iter(annotation)).value
    return result


def run(content=PRODUCT):
    tasks = {
        task: {"status": "done", "labels": labels_for(model), "error_code": None}
        for task, model in MODELS.items()
    }
    tasks["content_type"]["labels"]["content_type"] = content
    if content != PRODUCT:
        tasks.update(hook=None, full=None)
    return tasks


def run_unanalyzed():
    """Model says product but category other: hook/full are never created."""
    tasks = run(PRODUCT)
    tasks["content_type"]["labels"]["category"] = Category.other.value
    tasks.update(hook=None, full=None)
    return tasks


def item(minimal=PRODUCT, default=PRODUCT):
    return {"runs": {"minimal": run(minimal), "default": run(default)}}


def human(item_id, content=PRODUCT):
    row = {"item_id": item_id, "link": "https://example.invalid", "text": SENTINEL}
    for model in MODELS.values():
        for axis, annotation in _label_axes(model):
            row[axis] = "true" if annotation is bool else next(iter(annotation)).value
    row["content_type"] = content
    if content != PRODUCT:
        for axis in label_columns():
            if axis not in {"content_type", "category"}:
                row[axis] = ""
        row["category"] = Category.other.value
    return row


def files(tmp_path, rows=None, items=None, supplement=None):
    labels = tmp_path / "labeled.csv"
    key = tmp_path / "custom_key.json"
    rows = [human("P001")] if rows is None else rows
    with labels.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=["item_id", "link", "text", *label_columns()]
        )
        writer.writeheader()
        writer.writerows(rows)
    key.write_text(json.dumps({"items": {"P001": item()} if items is None else items}))
    if supplement is not None:
        (tmp_path / "pilot_key_supplement.json").write_text(json.dumps(supplement))
    return labels, key


def cli(labels, key):
    out = StringIO()
    code = compare.main(["--labels", str(labels), "--key", str(key)], out=out)
    output = out.getvalue()
    return code, output, json.loads(output.splitlines()[-1])


def metric(report, axis, tag):
    return next(
        row for row in report["metrics"] if row["axis"] == axis and row["run"] == tag
    )


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "header",
        "enum",
        "blank_enum",
        "boolean",
        "claims",
        "short_row",
        "duplicate_id",
    ],
)
def test_invalid_labels_never_read_key(tmp_path, monkeypatch, damage):
    labels, key = files(tmp_path)
    if damage == "missing":
        labels.unlink()
    elif damage == "header":
        labels.write_text(labels.read_text().replace("item_id", "wrong", 1))
    elif damage == "short_row":
        labels.write_text(
            ",".join(["item_id", "link", "text", *label_columns()]) + "\nP001\n"
        )
    else:
        row = human("P001")
        if damage == "duplicate_id":
            files(tmp_path, [row, row])
        else:
            row[
                {
                    "enum": "angle",
                    "blank_enum": "angle",
                    "boolean": "has_cta",
                    "claims": "claims",
                }[damage]
            ] = "" if damage == "blank_enum" else SENTINEL
            files(tmp_path, [row])
    reader = Mock(side_effect=AssertionError("key must remain unread"))
    monkeypatch.setattr(compare, "read_model_items", reader)
    code, output, report = cli(labels, key)
    expected = "LABEL_FILE_MISSING" if damage == "missing" else "LABEL_FILE_INVALID"
    assert code == 2 and report["errors"] == [expected]
    assert expected in output and SENTINEL not in output
    reader.assert_not_called()


def test_membership_checked_after_key_read(tmp_path, monkeypatch):
    labels, key = files(tmp_path, items={"P002": item()})
    reader = Mock(wraps=compare.read_model_items)
    monkeypatch.setattr(compare, "read_model_items", reader)
    code, _, report = cli(labels, key)
    assert code == 2 and report["errors"] == ["LABEL_FILE_INVALID"]
    reader.assert_called_once_with(key)


def test_missing_key(tmp_path):
    labels, key = files(tmp_path)
    key.unlink()
    code, _, report = cli(labels, key)
    assert code == 2 and report["errors"] == ["PILOT_KEY_MISSING"]


@pytest.mark.parametrize("task", ["content_type", "hook", "full"])
@pytest.mark.parametrize("status", ["failed", "held", "pending", None, "absent"])
def test_failure_excludes_whole_item_from_both_runs(tmp_path, task, status):
    bad = item()
    tasks = bad["runs"]["default"]
    if status == "absent":
        del tasks[task]
    else:
        tasks[task] = (
            None if status is None else {"status": status, "error_code": "TEST_FAILURE"}
        )
    labels, key = files(
        tmp_path,
        [human("P001"), human("P002")],
        {"P001": item(), "P002": bad},
    )
    code, _, report = cli(labels, key)
    assert code == 0
    assert report["included"] == 1
    assert report["excluded"] == [
        {
            "item_id": "P002",
            "run_tag": "default",
            "task": task,
            "error_code": None if status in {None, "absent"} else "TEST_FAILURE",
        }
    ]
    assert all(row["n"] == 1 for row in report["metrics"])
    for matrix in report["confusion_matrices"].values():
        assert sum(sum(row.values()) for row in matrix.values()) == 1


def test_non_product_missing_downstream_is_normal(tmp_path):
    labels, key = files(tmp_path, items={"P001": item(NON_PRODUCT, NON_PRODUCT)})
    code, _, report = cli(labels, key)
    assert code == 3 and report["excluded"] == [] and report["included"] == 1


def test_supplement_overrides_only_same_item_and_run(tmp_path):
    a, b = item(), item()
    a["runs"]["default"]["content_type"] = {"status": "failed"}
    b["runs"]["minimal"]["content_type"] = {"status": "held"}
    original = {"P001": a, "P002": b, "P003": item()}
    supplement = {
        "run_tag": "default",
        "items": {"P001": {"runs": {"default": run()}}},
    }
    labels, key = files(
        tmp_path, [human(name) for name in original], original, supplement
    )
    merged = compare.read_model_items(key)
    assert merged["P001"]["runs"]["minimal"] == original["P001"]["runs"]["minimal"]
    assert merged["P002"] == original["P002"]
    assert merged["P003"] == original["P003"]
    assert json.loads(key.read_text())["items"] == original
    code, _, report = cli(labels, key)
    assert code == 0 and report["included"] == 2
    assert [(r["item_id"], r["run_tag"], r["task"]) for r in report["excluded"]] == [
        ("P002", "minimal", "content_type")
    ]


def test_intersections_and_confusion_matrices(tmp_path):
    rows = [human("P001"), human("P002"), human("P003", NON_PRODUCT), human("P004")]
    items = {
        "P001": item(),
        "P002": item(PRODUCT, NON_PRODUCT),
        "P003": item(PRODUCT, NON_PRODUCT),
        "P004": item(NON_PRODUCT, PRODUCT),
    }
    # category belongs to content_type; decoys in other jobs must not be used.
    alternate = list(Category)[1].value
    items["P002"]["runs"]["minimal"]["content_type"]["labels"]["category"] = alternate
    items["P002"]["runs"]["minimal"]["full"]["labels"]["category"] = rows[1]["category"]
    labels, key = files(tmp_path, rows, items)
    code, _, report = cli(labels, key)
    assert code == 0
    for tag, n in [("minimal", 2), ("default", 2), ("minimal_vs_default", 1)]:
        row = metric(report, "category", tag)
        assert row["n"] == row["intersection_size"] == n
    assert metric(report, "category", "minimal")["rate"] == 0.5
    expected = {
        "minimal": {
            (PRODUCT, PRODUCT): 2,
            (PRODUCT, NON_PRODUCT): 1,
            (NON_PRODUCT, PRODUCT): 1,
        },
        "default": {
            (PRODUCT, PRODUCT): 2,
            (PRODUCT, NON_PRODUCT): 1,
            (NON_PRODUCT, NON_PRODUCT): 1,
        },
    }
    for tag, counts in expected.items():
        matrix = report["confusion_matrices"][tag]
        assert {
            (h, m): count
            for h, columns in matrix.items()
            for m, count in columns.items()
            if count
        } == counts
        assert metric(report, "content_type", tag)["n"] == 4


def test_run_intersections_can_have_different_sizes(tmp_path):
    labels, key = files(
        tmp_path,
        [human("P001"), human("P002")],
        {"P001": item(), "P002": item(PRODUCT, NON_PRODUCT)},
    )
    code, _, report = cli(labels, key)
    assert code == 0
    assert metric(report, "angle", "minimal")["n"] == 2
    assert metric(report, "angle", "default")["n"] == 1


def test_agreement_is_pure_and_claims_are_sets():
    pairs = [(1, 1), (True, False), (["a", "b"], ["b", "a", "a"])]
    original = deepcopy(pairs)
    result = compare.agreement(iter(pairs))
    assert result.n == 3 and result.matches == 2 and result.rate == pytest.approx(2 / 3)
    assert pairs == original
    assert compare.agreement([({"a"}, {"b"})]).rate == 0
    with pytest.raises(ValueError):
        compare.agreement([])


def test_empty_axis_continues_other_axes_and_notes_are_scoped(tmp_path):
    row = human("P001")
    row["is_vertical"] = ""
    labels, key = files(tmp_path, [row])
    code, output, report = cli(labels, key)
    assert code == 3 and "COMPARE_EMPTY_SET:is_vertical" in output
    assert report["errors"] == ["COMPARE_EMPTY_SET:is_vertical"]
    for tag in TAGS:
        empty = metric(report, "is_vertical", tag)
        assert empty["n"] == 0 and empty["rate"] is None
        assert empty["intersection_size"] == 1
        assert metric(report, "angle", tag)["n"] == 1
    for result in report["metrics"]:
        if result["axis"] in {"has_cta", "has_hook_segment"}:
            assert result["note"] == "정의 미확정, 참고용"
        else:
            assert "note" not in result
    assert SENTINEL not in output
    assert "note: 정의 미확정, 참고용" in output


def test_empty_all_intersections_is_not_zero_percent(tmp_path):
    labels, key = files(tmp_path, [human("P001", NON_PRODUCT)])
    code, _, report = cli(labels, key)
    assert code == 3
    assert set(report["errors"]) == {
        f"COMPARE_EMPTY_SET:{axis}"
        for axis in label_columns()
        if axis != "content_type"
    }
    assert all(
        row["rate"] is None
        for row in report["metrics"]
        if row["axis"] != "content_type"
    )


def test_success_output_has_no_raw_labels_or_text(tmp_path):
    model_item = item()
    for tag in TAGS:
        model_item["runs"][tag]["full"]["labels"]["ingredients"] = [SENTINEL]
        model_item["runs"][tag]["full"]["raw_output"] = SENTINEL
    labels, key = files(tmp_path, items={"P001": model_item})
    code, output, report = cli(labels, key)
    assert code == 0 and report["errors"] == []
    assert SENTINEL not in output and '"labels"' not in output
    assert "교집합" in output and "일치율" in output


def test_make_target_is_manual_only():
    makefile = (Path(__file__).resolve().parents[1] / "Makefile").read_text()
    assert "pilot-compare" in makefile.splitlines()[0].split()
    assert (
        "pilot-compare:\n\tuv run python -m beautyads.eval.pilot_compare\n" in makefile
    )
    verify = makefile.split("verify:\n", 1)[1].split("\n\n", 1)[0]
    assert "pilot-compare" not in verify


def test_product_with_category_other_is_analysis_exclusion_not_failure(tmp_path):
    rows = [human("P001"), human("P002")]
    items = {
        "P001": item(),
        "P002": {"runs": {tag: run_unanalyzed() for tag in TAGS}},
    }
    labels, key = files(tmp_path, rows, items)
    code, output, report = cli(labels, key)
    assert code == 0 and report["errors"] == []
    assert report["included"] == 2 and report["excluded"] == []
    assert report["human_product"] == 2
    # content_type and category are compared for every retained product item.
    for tag in TAGS:
        assert metric(report, "content_type", tag)["n"] == 2
        assert metric(report, "content_type", tag)["coverage"] is None
        category = metric(report, "category", tag)
        assert category["n"] == category["intersection_size"] == 2
        assert category["not_analyzed"] == 0
        # the model's category other against a supported human category shows up here
        assert category["rate"] == 0.5
    # hook/full-derived axes count the item separately, with the reason.
    for tag in (*TAGS, "minimal_vs_default"):
        row = metric(report, "hook_type", tag)
        assert row["n"] == 1 and row["intersection_size"] == 2
        assert row["not_analyzed"] == 1
        assert row["not_analyzed_reason"] == compare.NOT_ANALYZED_REASON
        assert row["coverage"] == 0.5 and row["human_product"] == 2
    assert {(g["item_id"], g["run_tag"]) for g in report["not_analyzed"]} == {
        ("P002", "minimal"),
        ("P002", "default"),
    }
    assert "NOT_ANALYZED P002 minimal" in output
    assert SENTINEL not in output


def test_existing_downstream_task_that_is_not_done_still_excludes(tmp_path):
    bad = {"runs": {tag: run_unanalyzed() for tag in TAGS}}
    bad["runs"]["minimal"]["hook"] = {"status": "failed", "error_code": "TEST_FAILURE"}
    labels, key = files(
        tmp_path,
        [human("P001"), human("P002")],
        {
            "P001": item(),
            "P002": bad,
        },
    )
    code, _, report = cli(labels, key)
    assert code == 0 and report["included"] == 1
    assert report["excluded"] == [
        {
            "item_id": "P002",
            "run_tag": "minimal",
            "task": "hook",
            "error_code": "TEST_FAILURE",
        }
    ]


def test_analysis_target_rule_matches_the_pipeline_rule():
    for content in ContentType:
        for category in Category:
            labels = labels_for(ContentTypeResult)
            labels.update(content_type=content.value, category=category.value)
            tasks = {"content_type": {"status": "done", "labels": labels}}
            assert compare._is_analysis_target(tasks) == is_product_target(
                ContentTypeResult.model_validate(labels)
            )


def test_claim_scores_are_per_item_precision_and_recall():
    first, second, third = (claim.value for claim in list(Claim)[:3])
    scores = compare.claim_scores(
        [
            ({first, second}, {first, third}),
            ({first}, {first}),
            (set(), {second}),
        ]
    )
    by_claim = {row.claim: row for row in scores.items}
    assert scores.n == 3
    assert (by_claim[first].human_n, by_claim[first].model_n, by_claim[first].tp) == (
        2,
        2,
        2,
    )
    assert by_claim[first].precision == 1 and by_claim[first].recall == 1
    assert by_claim[second].precision == 0 and by_claim[second].recall == 0
    assert by_claim[third].precision == 0 and by_claim[third].recall is None
    assert scores.micro_precision == pytest.approx(2 / 4)
    assert scores.micro_recall == pytest.approx(2 / 3)
    # nobody predicted anything: no precision is made up
    silent = compare.claim_scores([({first}, set())])
    assert silent.items[0].precision is None and silent.items[0].recall == 0
    assert silent.micro_precision is None
    with pytest.raises(ValueError):
        compare.claim_scores([])


def test_claims_report_uses_precision_recall_not_exact_sets(tmp_path):
    first, second = (claim.value for claim in list(Claim)[:2])
    rows = [human("P001"), human("P002")]
    items = {"P001": item(), "P002": item()}
    for tag in TAGS:
        items["P001"]["runs"][tag]["full"]["labels"]["claims"] = [first]
        items["P002"]["runs"][tag]["full"]["labels"]["claims"] = [second]
    labels, key = files(tmp_path, rows, items)
    code, output, report = cli(labels, key)
    assert code == 0
    # the exact-set agreement row is gone; the dedicated section replaces it
    assert all(row["axis"] != "claims" for row in report["metrics"])
    for tag in TAGS:
        entry = report["claims"][tag]
        assert entry["n"] == 2 and entry["intersection_size"] == 2
        assert entry["micro_precision"] == 0.5 and entry["micro_recall"] == 0.5
        by_claim = {row["claim"]: row for row in entry["items"]}
        assert by_claim[first]["precision"] == 1 and by_claim[first]["recall"] == 0.5
        assert by_claim[second]["precision"] == 0
        assert by_claim[second]["recall"] is None
    assert "항목별 정밀도·재현율" in output
    assert SENTINEL not in output
