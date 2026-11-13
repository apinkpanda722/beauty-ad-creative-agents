"""Compare completed human pilot labels with two saved runs, using files only."""

import argparse
import csv
import json
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, TextIO

from beautyads.domain import ContentTypeResult, FullResult, HookResult, JobStatus
from beautyads.domain.labels import Category, ContentType
from beautyads.eval.sheets import SheetError, _label_axes, label_columns

DEFAULT_LABELS = Path("data/interim/pilot/pilot_sheet_labeled.csv")
DEFAULT_KEY = DEFAULT_LABELS.with_name("pilot_key.json")

# Preregistration §4: content_type uses all retained items; every other axis
# uses human/product-model intersection, separately for each comparison.
RUN_TAGS = ("minimal", "default")
CONTENT_AXIS = "content_type"
PRODUCT = ContentType.product_creative.value
INTERSECTION_AXES = tuple(axis for axis in label_columns() if axis != CONTENT_AXIS)
NOT_ANALYZED_REASON = "category_other로 분석 제외"
UNSETTLED_AXES = frozenset({"has_cta", "has_hook_segment"})
UNSETTLED_NOTE = "정의 미확정, 참고용"
TASK_MODELS = {
    "content_type": ContentTypeResult,
    "hook": HookResult,
    "full": FullResult,
}
AXIS_TASKS = {
    axis: task for task, model in TASK_MODELS.items() for axis, _ in _label_axes(model)
}
AXIS_TYPES = {
    axis: annotation
    for model in TASK_MODELS.values()
    for axis, annotation in _label_axes(model)
}


@dataclass(frozen=True)
class AgreementResult:
    """Exact matches over n pairs; rate is a fraction in [0, 1]."""

    n: int
    matches: int
    rate: float


def agreement(pairs: Iterable[tuple[Any, Any]]) -> AgreementResult:
    """Pure exact agreement, with multi-valued labels compared as sets.

    Callers select the population and remove missing values first. Empty input
    raises ValueError, so an absent population cannot be mistaken for 0%.
    """

    def normalized(value):
        return frozenset(value) if isinstance(value, (list, set, frozenset)) else value

    n = matches = 0
    for left, right in pairs:
        n += 1
        matches += normalized(left) == normalized(right)
    if not n:
        raise ValueError("COMPARE_EMPTY_SET")
    return AgreementResult(n=n, matches=matches, rate=matches / n)


def _human_value(axis: str, value: str, *, non_product: bool) -> Any:
    annotation = AXIS_TYPES[axis]
    if value == "":
        if axis in {CONTENT_AXIS, "category"} or (
            annotation is not bool and axis != "claims" and not non_product
        ):
            raise ValueError
        return frozenset() if axis == "claims" else None
    if annotation is bool:
        if value not in {"true", "false"}:
            raise ValueError
        return value == "true"
    if axis == "claims":
        return frozenset(annotation(part.strip()).value for part in value.split(","))
    return annotation(value).value


def read_labels(path: Path) -> dict[str, dict[str, Any]]:
    """Validate the entire CSV before any key or supplement is opened."""
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream, strict=True)
            fields = ["item_id", "link", "text", *label_columns()]
            if (
                reader.fieldnames is None
                or len(reader.fieldnames) != len(fields)
                or set(reader.fieldnames) != set(fields)
            ):
                raise ValueError
            rows = {}
            for row in reader:
                item_id = row.get("item_id")
                if (
                    not item_id
                    or not item_id.strip()
                    or item_id in rows
                    or None in row
                    or any(value is None for value in row.values())
                ):
                    raise ValueError
                rows[item_id] = {
                    axis: _human_value(
                        axis, row[axis], non_product=row[CONTENT_AXIS] != PRODUCT
                    )
                    for axis in label_columns()
                }
            if not rows:
                raise ValueError
            return rows
    except FileNotFoundError:
        raise SheetError("LABEL_FILE_MISSING") from None
    except (OSError, UnicodeError, ValueError, csv.Error):
        raise SheetError("LABEL_FILE_INVALID") from None


def _read_items(path: Path) -> tuple[dict, dict]:
    document = json.loads(path.read_text(encoding="utf-8"))
    items = document.get("items")
    if not isinstance(items, dict) or not all(
        isinstance(item, dict) and isinstance(item.get("runs"), dict)
        for item in items.values()
    ):
        raise ValueError
    return document, items


def read_model_items(path: Path) -> dict[str, dict]:
    """Read an arbitrary key path, then replace only supplemented item/tag runs.

    read_key_items() returns creative IDs, not labels, and restricts directories
    to data/interim; this reader instead supports --key and synthetic tmp files.
    SheetError and its existing key reason codes are shared with sheets.py.
    """
    try:
        _, items = _read_items(path)
    except FileNotFoundError:
        raise SheetError("PILOT_KEY_MISSING") from None
    except (OSError, UnicodeError, ValueError, TypeError, AttributeError):
        raise SheetError("PILOT_KEY_INVALID") from None
    try:
        supplement = path.with_name("pilot_key_supplement.json")
        if supplement.exists():
            document, additions = _read_items(supplement)
            tag = document.get("run_tag")
            if tag not in RUN_TAGS:
                raise ValueError
            for item_id, addition in additions.items():
                if item_id in items and tag in addition["runs"]:
                    items[item_id]["runs"][tag] = addition["runs"][tag]
    except (OSError, UnicodeError, ValueError, TypeError, AttributeError):
        raise SheetError("PILOT_KEY_INVALID") from None
    return items


def _tasks(item: Mapping, tag: str) -> Mapping:
    run = item["runs"].get(tag)
    if run is None:
        return {}
    if not isinstance(run, dict):
        raise SheetError("PILOT_KEY_INVALID")
    return run


def _flatten(model, labels: Mapping) -> dict[str, Any]:
    values = {}
    for name, field in model.model_fields.items():
        if name == "ingredients":
            continue
        annotation = field.annotation
        value = labels.get(name)
        if hasattr(annotation, "model_fields"):
            values.update(
                _flatten(annotation, value if isinstance(value, dict) else {})
            )
        else:
            values[name] = value
    return values


def _model_value(tasks: Mapping, axis: str) -> Any:
    task = AXIS_TASKS[axis]
    result = tasks.get(task)
    labels = result.get("labels") if isinstance(result, dict) else None
    if not isinstance(labels, dict):
        raise SheetError("PILOT_KEY_INVALID")
    value = _flatten(TASK_MODELS[task], labels).get(axis)
    annotation = AXIS_TYPES[axis]
    try:
        if annotation is bool:
            if not isinstance(value, bool):
                raise ValueError
            return value
        if axis == "claims":
            if not isinstance(value, list):
                raise ValueError
            return frozenset(annotation(part).value for part in value)
        return annotation(value).value
    except (ValueError, TypeError):
        raise SheetError("PILOT_KEY_INVALID") from None


def _is_analysis_target(tasks: Mapping) -> bool:
    """Mirror `analysis.axes.is_product_target`: hook/full exist only for these items.

    The model calls an item a product but with category `other` is excluded from
    hook/full analysis by design, so its missing downstream tasks are not failures.
    """
    return (
        _model_value(tasks, CONTENT_AXIS) == PRODUCT
        and _model_value(tasks, "category") != Category.other.value
    )


def _exclusions(item_id: str, item: Mapping) -> list[dict]:
    """Exclude on (a) an existing task that is not done, (b) a missing hook/full
    for an item that must have them (`is_product_target`). Nothing else."""
    failures = []
    for tag in RUN_TAGS:
        tasks = _tasks(item, tag)

        def fail(task, result, tasks=tasks, tag=tag):
            failures.append(
                {
                    "item_id": item_id,
                    "run_tag": tag,
                    "task": task,
                    "error_code": result.get("error_code")
                    if isinstance(result, dict)
                    else None,
                }
            )

        def usable(task, result):
            if not isinstance(result, dict) and result is not None:
                raise SheetError("PILOT_KEY_INVALID")
            if result is None or result.get("status") != JobStatus.done:
                fail(task, result)
                return False
            return True

        content = tasks.get("content_type")
        if not usable("content_type", content):
            continue
        required = _is_analysis_target(tasks)
        for task in ("hook", "full"):
            result = tasks.get(task)
            if result is None:
                if required:
                    fail(task, None)
            else:
                usable(task, result)
    return failures


def compare_labels(humans: Mapping[str, dict], items: Mapping[str, dict]) -> dict:
    """Apply item-level exclusions before building any comparison population."""
    if any(item_id not in items for item_id in humans):
        raise SheetError("LABEL_FILE_INVALID")
    excluded = []
    retained = []
    for item_id in humans:
        failures = _exclusions(item_id, items[item_id])
        excluded.extend(failures)
        if not failures:
            retained.append(item_id)
    human_product = sum(1 for i in retained if humans[i][CONTENT_AXIS] == PRODUCT)
    report = {
        "included": len(retained),
        "human_product": human_product,
        "excluded": excluded,
        "not_analyzed": [],
        "confusion_matrices": {},
        "metrics": [],
        "errors": [],
    }

    def add_metric(axis, tag, population, pairs, unanalyzed=0):
        pairs = [(a, b) for a, b in pairs if a is not None and b is not None]
        row = {
            "axis": axis,
            "run": tag,
            "intersection_size": len(population) + unanalyzed,
        }
        try:
            row.update(asdict(agreement(pairs)))
        except ValueError:
            row.update(n=0, matches=0, rate=None)
            code = f"COMPARE_EMPTY_SET:{axis}"
            if code not in report["errors"]:
                report["errors"].append(code)
        row["human_product"] = human_product
        row["not_analyzed"] = unanalyzed
        # Coverage is about hook/full-derived and category axes; content_type is the
        # confusion matrix over every retained item, so it has no coverage.
        row["coverage"] = (
            row["n"] / human_product if human_product and axis != CONTENT_AXIS else None
        )
        if unanalyzed:
            row["not_analyzed_reason"] = NOT_ANALYZED_REASON
        if axis in UNSETTLED_AXES:
            row["note"] = UNSETTLED_NOTE
        report["metrics"].append(row)

    intersections = {}
    analyzed = {}
    for tag in RUN_TAGS:
        matrix = {human.value: dict.fromkeys(ContentType, 0) for human in ContentType}
        content_pairs = []
        intersection = []
        for item_id in retained:
            human = humans[item_id][CONTENT_AXIS]
            model = _model_value(_tasks(items[item_id], tag), CONTENT_AXIS)
            matrix[human][model] += 1
            content_pairs.append((human, model))
            if human == model == PRODUCT:
                intersection.append(item_id)
        report["confusion_matrices"][tag] = matrix
        add_metric(CONTENT_AXIS, tag, retained, content_pairs)
        intersections[tag] = intersection
        analyzed[tag] = [
            i for i in intersection if _is_analysis_target(_tasks(items[i], tag))
        ]
        for item_id in intersection:
            if item_id not in analyzed[tag]:
                report["not_analyzed"].append(
                    {"item_id": item_id, "run_tag": tag, "reason": NOT_ANALYZED_REASON}
                )
        for axis in INTERSECTION_AXES:
            # category comes from content_type; hook/full axes need the later tasks.
            downstream = AXIS_TASKS[axis] != "content_type"
            population = analyzed[tag] if downstream else intersection
            add_metric(
                axis,
                tag,
                population,
                (
                    (humans[i][axis], _model_value(_tasks(items[i], tag), axis))
                    for i in population
                ),
                len(intersection) - len(population),
            )
    shared = [i for i in intersections[RUN_TAGS[0]] if i in intersections[RUN_TAGS[1]]]
    shared_analyzed = [i for i in shared if all(i in analyzed[tag] for tag in RUN_TAGS)]
    for axis in INTERSECTION_AXES:
        downstream = AXIS_TASKS[axis] != "content_type"
        population = shared_analyzed if downstream else shared
        add_metric(
            axis,
            "minimal_vs_default",
            population,
            (
                tuple(_model_value(_tasks(items[i], tag), axis) for tag in RUN_TAGS)
                for i in population
            ),
            len(shared) - len(population),
        )
    return report


def _print_report(report: dict, out: TextIO) -> None:
    for failure in report.get("excluded", []):
        print(
            "EXCLUDED {item_id} {run_tag} {task} {error_code}".format(**failure),
            file=out,
        )
    for gap in report.get("not_analyzed", []):
        print(
            "NOT_ANALYZED {item_id} {run_tag} {reason}".format(**gap),
            file=out,
        )
    for tag, matrix in report.get("confusion_matrices", {}).items():
        print(f"content_type {tag} 혼동 행렬 (행=사람, 열=모델)", file=out)
        print("사람/모델\t" + "\t".join(ContentType), file=out)
        for human, counts in matrix.items():
            print(human + "\t" + "\t".join(str(n) for n in counts.values()), file=out)
    if report.get("metrics"):
        print(
            "축\t실행\tn\t교집합 크기\t사람 제품 수\t분석 제외\t커버리지\t"
            "일치율 (content_type은 참고용)",
            file=out,
        )
    for row in report.get("metrics", []):
        rate = "—" if row["rate"] is None else f"{row['rate']:.1%}"
        note = f" note: {row['note']}" if "note" in row else ""
        coverage = "—" if row.get("coverage") is None else f"{row['coverage']:.1%}"
        reason = f" ({row['not_analyzed_reason']})" if row.get("not_analyzed") else ""
        print(
            f"{row['axis']}\t{row['run']}\t{row['n']}\t"
            f"{row['intersection_size']}\t{row['human_product']}\t"
            f"{row['not_analyzed']}{reason}\t{coverage}\t{rate}{note}",
            file=out,
        )
    for error in report["errors"]:
        print(error, file=out)
    print(json.dumps(report, ensure_ascii=False), file=out)


def main(argv: Sequence[str] | None = None, *, out: TextIO | None = None) -> int:
    out = sys.stdout if out is None else out
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--key", type=Path, default=DEFAULT_KEY)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    try:
        humans = read_labels(args.labels)
        items = read_model_items(args.key)
        report = compare_labels(humans, items)
    except SheetError as exc:
        _print_report({"errors": [exc.code]}, out)
        return 2
    _print_report(report, out)
    return 3 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
