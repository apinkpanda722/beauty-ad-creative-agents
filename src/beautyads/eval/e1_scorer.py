"""Score completed E1 human labels against saved @v1 jobs, on explicit invocation."""

import argparse
import csv
import json
import re
import sys
from collections import Counter
from collections.abc import Mapping
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from pathlib import Path

from beautyads.domain import CreativeKey, JobStatus
from beautyads.domain.labels import ContentType
from beautyads.eval import pilot_compare as pilot
from beautyads.eval.e1_sampling import (
    CONFIG_PATH,
    DEFAULT_OUT_DIR,
    PREREGISTRATION_PATH,
    STAGE1_COLUMNS,
    E1Error,
    load_e1_config,
)
from beautyads.eval.e1_stage2 import StopPoint, read_stage1_labels, stop_point
from beautyads.eval.sheets import SheetError, label_columns
from beautyads.pipeline.preflight import docker_running, tcp_reachable
from beautyads.settings import DEFAULT_ENV_FILE, get_setting
from beautyads.store import (
    PostgresCreativeStore,
    StoreConnectError,
    connect,
    postgres_dsn,
)

# EVAL.md E1, frozen: these are criteria, never CLI parameters.
THRESHOLDS = {"human_retest": 0.7, "human_model": 0.6, "content_type": 0.9}
PRODUCT = ContentType.product_creative.value
STAGE2_AXES = tuple(a for a in label_columns() if a not in {"content_type", "category"})
MISSING = "model_missing"


def meets_threshold(value: float | None, comparison: str) -> bool | None:
    return None if value is None else value >= THRESHOLDS[comparison]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    for option, filename in (
        ("stage1-labels", "e1_stage1_sheet_labeled.csv"),
        ("stage2-labels", "e1_stage2_sheet_labeled.csv"),
        ("retest-labels", "e1_stage2_sheet_retest.csv"),
        ("stage1-key", "e1_stage1_key.json"),
        ("stage2-key", "e1_stage2_key.json"),
    ):
        parser.add_argument(
            f"--{option}", type=Path, default=DEFAULT_OUT_DIR / filename
        )
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--preregistration", type=Path, default=PREREGISTRATION_PATH)
    return parser


def read_label_file(path: Path, *, stage: int) -> dict[str, dict]:
    """Validate a sheet without opening any key; discard link/text immediately."""
    axes = STAGE1_COLUMNS[3:] if stage == 1 else STAGE2_AXES
    fields = ["item_id", "link", "text", *axes]
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream, strict=True)
            if reader.fieldnames != fields:
                raise ValueError
            result = {}
            blank_seen = False
            for index, row in enumerate(reader, 1):
                item_id = f"{'E' if stage == 1 else 'F'}{index:03}"
                if (
                    set(row) != set(fields)
                    or any(v is None for v in row.values())
                    or row.get("item_id") != item_id
                ):
                    raise ValueError
                if stage == 1 and row["content_type"] == row["category"] == "":
                    blank_seen = True
                    continue
                if blank_seen:
                    raise ValueError
                values = {
                    a: pilot._human_value(a, row[a], non_product=False) for a in axes
                }
                if (
                    stage == 2
                    and values.get("has_cta") is not None
                    and values["has_cta"] != (values["cta_type"] != "none")
                ):
                    raise ValueError
                result[item_id] = values
            if not result:
                raise ValueError
            return result
    except (OSError, UnicodeError, ValueError, csv.Error):
        raise E1Error("LABEL_FILE_INVALID") from None


def read_registration(path: Path) -> None:
    """Fail closed unless §5 records both the population and its coverage.

    v1's active axes come from the frozen domain schema. §4's historical pilot
    notes are not exceptions to §6's subsequently frozen definitions.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise E1Error("PREREGISTRATION_RULE_MISSING") from None
    section = re.search(
        r"^## 5\.[^\n]*\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL
    )
    if section is None or not all(
        token in section.group(1)
        for token in (
            "사람",
            "모델",
            "모두",
            "product_creative",
            "교집합",
            "커버리지",
            "÷",
            "사람이 제품",
            "판정",
        )
    ):
        raise E1Error("PREREGISTRATION_RULE_MISSING")
    frozen = re.search(
        r"^## 6\.[^\n]*\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL
    )
    if frozen is None or not re.search(
        r"전체 v1 동결:\s*\d{4}-\d{2}-\d{2}", frozen.group(1)
    ):
        raise E1Error("PREREGISTRATION_DEFINITIONS_MISSING")


@dataclass(frozen=True)
class Inputs:
    stop: StopPoint
    stage1: dict[str, dict]
    first: dict[str, dict]
    retest: dict[str, dict]
    stage1_keys: dict[str, CreativeKey]
    stage2_keys: dict[str, CreativeKey]


def read_keys(args, first, retest, config) -> Inputs:
    """Join the two blind IDs through identities and checked stage-one labels."""
    labels = read_stage1_labels(args.stage1_labels, args.stage1_key, config)
    scope = stop_point(labels, config)
    by_key = {
        CreativeKey(source=i.source, source_id=i.source_id): i for i in scope.items
    }
    if len(by_key) != len(scope.items):
        raise E1Error("LABEL_FILE_INVALID")
    try:
        document = json.loads(args.stage2_key.read_text(encoding="utf-8"))
        items = document.get("items")
        if (
            not isinstance(items, dict)
            or list(items) != list(first)
            or list(first) != list(retest)
        ):
            raise ValueError
        keys, combined = {}, {}
        for item_id, item in items.items():
            if not isinstance(item, dict):
                raise TypeError
            key = CreativeKey(
                source=item.get("source"), source_id=item.get("source_id")
            )
            original = by_key.get(key)
            if original is None or key in keys.values():
                raise ValueError
            human_labels = {
                "content_type": original.content_type,
                "category": original.category,
            }
            if (
                item.get("stage1_human_labels") != human_labels
                or original.content_type != PRODUCT
                or original.category not in config.stage2.categories
            ):
                raise ValueError
            keys[item_id] = key
            combined[item_id] = {**first[item_id], **human_labels}
        return Inputs(
            scope,
            {
                i.item_id: {"content_type": i.content_type, "category": i.category}
                for i in scope.items
            },
            combined,
            retest,
            {
                i.item_id: CreativeKey(source=i.source, source_id=i.source_id)
                for i in scope.items
            },
            keys,
        )
    except (OSError, UnicodeError, ValueError, TypeError, AttributeError):
        raise E1Error("LABEL_FILE_INVALID") from None


def read_model_results(store, inputs: Inputs) -> dict[CreativeKey, dict]:
    keys = list(
        dict.fromkeys([*inputs.stage1_keys.values(), *inputs.stage2_keys.values()])
    )
    results = {key: {} for key in keys}
    try:
        for task in pilot.TASK_MODELS:
            kind = f"{task}@v1"
            for job in store.get_job_results(kind, keys):
                if (
                    job.key not in results
                    or job.kind != kind
                    or task in results[job.key]
                ):
                    raise E1Error("MODEL_RESULT_INVALID")
                # Never carry model prose, raw outputs or provider diagnostics to reports.
                results[job.key][task] = {"status": job.status, "labels": job.labels}
    except E1Error:
        raise
    except Exception:  # noqa: BLE001 — SDK diagnostics must never escape this boundary.
        # Driver errors can include SQL, inputs or secrets; keep diagnostics stable.
        raise E1Error("MODEL_READ_FAILED") from None
    return results


def axis_score(axis, pairs, *, comparison, human_product, **metadata) -> dict:
    pairs = [(a, b) for a, b in pairs if a is not None and b is not None]
    row = {
        "axis": axis,
        "comparison": comparison,
        "n": len(pairs),
        "human_product": human_product,
        "coverage": len(pairs) / human_product if human_product else None,
        "rate": None,
        "kappa": None,
        "threshold": THRESHOLDS[comparison],
        "meets_threshold": None,
        **metadata,
    }
    if not pairs:
        row["reason"] = f"SCORE_EMPTY_SET:{axis}"
        return row
    row.update(asdict(pilot.agreement(pairs)))
    left, right = (Counter(values) for values in zip(*pairs, strict=True))
    n = row["n"]
    expected_count = sum(count * right.get(value, 0) for value, count in left.items())
    if len(left) == 1 or len(right) == 1 or expected_count == n**2:
        row["reason"] = f"KAPPA_UNDEFINED:{axis}"
    else:
        # Integer counts avoid cancellation that can flip a boundary decision.
        row["kappa"] = (row["matches"] * n - expected_count) / (n**2 - expected_count)
        row["meets_threshold"] = meets_threshold(row["kappa"], comparison)
    if comparison == "human_retest":
        row["ambiguous_definition"] = (
            None if row["kappa"] is None else not row["meets_threshold"]
        )
    return row


def _claims(pairs, *, human_product, **metadata) -> dict:
    pairs = list(pairs)
    row = {
        "n": len(pairs),
        "human_product": human_product,
        "coverage": len(pairs) / human_product if human_product else None,
        **metadata,
    }
    if pairs:
        row.update(asdict(pilot.claim_scores(pairs)))
    else:
        row.update(
            items=[],
            micro_precision=None,
            micro_recall=None,
            reason="SCORE_EMPTY_SET:claims",
        )
    return row


def score(inputs: Inputs, results: Mapping[CreativeKey, dict]) -> dict:
    """Pure scoring: no reads, printing or logging, including on failure."""
    matrix = {c.value: dict.fromkeys([*ContentType, MISSING], 0) for c in ContentType}
    products = missing = found = 0
    for item_id, human in inputs.stage1.items():
        content = results[inputs.stage1_keys[item_id]].get("content_type")
        model = MISSING
        if content and content.get("status") == JobStatus.done:
            model = pilot._model_value({"content_type": content}, "content_type")
        else:
            missing += 1
        matrix[human["content_type"]][model] += 1
        if human["content_type"] == PRODUCT:
            products += 1
            found += model == PRODUCT
    recall = found / products if products else None
    content_report = {
        "n": len(inputs.stage1),
        "human_product": products,
        "model_missing": missing,
        "model_missing_human_product": matrix[PRODUCT][MISSING],
        "true_positive": found,
        "recall": recall,
        "threshold": THRESHOLDS["content_type"],
        "meets_threshold": meets_threshold(recall, "content_type"),
        "confusion_matrix": matrix,
    }
    if not products:
        content_report["reason"] = "SCORE_EMPTY_SET:content_type"
    excluded, intersection, analyzed = [], [], []
    for item_id, human in inputs.first.items():
        tasks = results[inputs.stage2_keys[item_id]]
        failures = pilot.single_run_exclusions(tasks)
        excluded.extend({"item_id": item_id, "task": task} for task in failures)
        if failures:
            continue
        if (
            human["content_type"]
            == pilot._model_value(tasks, "content_type")
            == PRODUCT
        ):
            intersection.append(item_id)
            if pilot._is_analysis_target(tasks):
                analyzed.append(item_id)
    human_product = sum(h["content_type"] == PRODUCT for h in inputs.first.values())
    metrics = []
    for axis in pilot.AGREEMENT_AXES:
        downstream = pilot.AXIS_TASKS[axis] != "content_type"
        population = analyzed if downstream else intersection
        unanalyzed = len(intersection) - len(population)
        metadata = {"intersection_size": len(intersection), "not_analyzed": unanalyzed}
        if unanalyzed:
            metadata["not_analyzed_reason"] = pilot.NOT_ANALYZED_REASON
        metrics.append(
            axis_score(
                axis,
                (
                    (
                        inputs.first[i][axis],
                        pilot._model_value(results[inputs.stage2_keys[i]], axis),
                    )
                    for i in population
                ),
                comparison="human_model",
                human_product=human_product,
                **metadata,
            )
        )
    # The second-stage sheets have no independent category/content_type labels:
    # reusing the stage-one label here would fabricate perfect repeatability.
    for axis in STAGE2_AXES:
        if axis == "claims":
            continue
        metrics.append(
            axis_score(
                axis,
                ((inputs.first[i][axis], inputs.retest[i][axis]) for i in inputs.first),
                comparison="human_retest",
                human_product=len(inputs.first),
            )
        )
    claims = {
        "human_model": _claims(
            (
                (
                    inputs.first[i]["claims"],
                    pilot._model_value(results[inputs.stage2_keys[i]], "claims"),
                )
                for i in analyzed
            ),
            human_product=human_product,
            intersection_size=len(intersection),
            not_analyzed=len(intersection) - len(analyzed),
        ),
        "human_retest": _claims(
            (
                (inputs.first[i]["claims"], inputs.retest[i]["claims"])
                for i in inputs.first
            ),
            human_product=len(inputs.first),
        ),
    }
    if claims["human_model"]["not_analyzed"]:
        claims["human_model"]["not_analyzed_reason"] = pilot.NOT_ANALYZED_REASON
    errors = list(
        dict.fromkeys(
            r["reason"]
            for r in [content_report, *metrics, *claims.values()]
            if "reason" in r
        )
    )
    return {
        "thresholds": THRESHOLDS.copy(),
        "stop_position": inputs.stop.position,
        "unused_count": inputs.stop.unused_count,
        "content_type": content_report,
        "excluded": excluded,
        "metrics": metrics,
        "claims": claims,
        "errors": errors,
    }


def print_report(report, out) -> None:
    def value(number):
        return "—" if number is None else f"{number:.4f}"

    def decision(passed):
        return "판정 불가" if passed is None else "충족" if passed else "미충족"

    print(
        "축\t비교\tn\t사람 제품 수\t교집합\t분석 제외\t커버리지\t일치율\tκ\t기준 충족 여부",
        file=out,
    )
    for row in report["metrics"]:
        print(
            "\t".join(
                [
                    row["axis"],
                    row["comparison"],
                    str(row["n"]),
                    str(row["human_product"]),
                    str(row.get("intersection_size", "—")),
                    str(row.get("not_analyzed", 0)),
                    value(row["coverage"]),
                    value(row["rate"]),
                    value(row["kappa"]),
                    decision(row["meets_threshold"]),
                    "정의 모호 후보" if row.get("ambiguous_definition") else "",
                ]
            ),
            file=out,
        )
    content = report["content_type"]
    print(
        f"content_type 재현율\t{value(content['recall'])}\t"
        f"사람 제품 수 {content['human_product']}\t모델 결과 없음 {content['model_missing']}\t"
        f"{decision(content['meets_threshold'])}",
        file=out,
    )
    print("content_type 혼동 행렬 (행=사람, 열=모델)", file=out)
    print("사람/모델\t" + "\t".join([*ContentType, MISSING]), file=out)
    for human, counts in content["confusion_matrix"].items():
        print(human + "\t" + "\t".join(map(str, counts.values())), file=out)
    for comparison, entry in report["claims"].items():
        print(
            f"claims {comparison} 항목별 정밀도·재현율 n={entry['n']} "
            f"커버리지={value(entry['coverage'])}",
            file=out,
        )
        for item in entry["items"]:
            print(
                f"{item['claim']}\t{value(item['precision'])}\t{value(item['recall'])}",
                file=out,
            )
        print(
            f"micro\t{value(entry['micro_precision'])}\t{value(entry['micro_recall'])}",
            file=out,
        )
    for entry in report["excluded"]:
        print(f"EXCLUDED:{entry['item_id']}:{entry['task']}", file=out)
    for error in report["errors"]:
        print(error, file=out)
    print(json.dumps(report, ensure_ascii=False, allow_nan=False), file=out)


def _live_store(*, environ, env_file, stack):
    connection = connect(postgres_dsn(environ=environ, env_file=env_file))
    stack.callback(connection.close)
    return PostgresCreativeStore(connection)


def main(
    argv=None,
    *,
    out=None,
    environ=None,
    docker_check=docker_running,
    tcp_check=tcp_reachable,
    store_factory=None,
) -> int:
    out = sys.stdout if out is None else out
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    try:
        # Check ALL names before opening even the first existing file.
        for path in (args.stage1_labels, args.stage2_labels, args.retest_labels):
            if not path.is_file():
                raise E1Error(f"NOT_READY:{path.name}")
        read_label_file(args.stage1_labels, stage=1)
        first = read_label_file(args.stage2_labels, stage=2)
        retest = read_label_file(args.retest_labels, stage=2)
        read_registration(args.preregistration)
        config = load_e1_config(args.config)
        inputs = read_keys(args, first, retest, config)
        env_file = DEFAULT_ENV_FILE if environ is None else None
        if get_setting("POSTGRES_PASSWORD", environ=environ, env_file=env_file) is None:
            raise E1Error("ENV_MISSING:POSTGRES_PASSWORD")
        if not docker_check():
            raise E1Error("DOCKER_DOWN")
        try:
            port = int(
                get_setting(
                    "BEAUTYADS_POSTGRES_PORT",
                    "5433",
                    environ=environ,
                    env_file=env_file,
                )
            )
            reachable = 1 <= port <= 65535 and tcp_check("127.0.0.1", port, 1.0)
        except (ValueError, TypeError, OSError):
            reachable = False
        if not reachable:
            raise E1Error("POSTGRES_UNREACHABLE")
        with ExitStack() as stack:
            store = (
                _live_store(environ=environ, env_file=env_file, stack=stack)
                if store_factory is None
                else store_factory()
            )
            results = read_model_results(store, inputs)
        try:
            report = score(inputs, results)
        except SheetError:
            raise E1Error("MODEL_RESULT_INVALID") from None
    except (E1Error, StoreConnectError) as exc:
        print(exc.code, file=out)
        return 2
    print_report(report, out)
    return 3 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
