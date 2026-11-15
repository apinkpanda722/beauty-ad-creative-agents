"""Select E1 stage two exclusively from contiguous first-stage human labels."""

import argparse
import csv
import json
import random
import sys
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple

from beautyads.eval.e1_sampling import (
    DEFAULT_OUT_DIR,
    STAGE1_COLUMNS,
    E1Config,
    E1Error,
    e1_codebook,
    ensure_new_outputs,
    output_paths,
    provenance_files,
    round_robin,
    sha256_of,
    stratum_shortfall,
    write_artifacts,
)
from beautyads.eval.sheets import label_columns


@dataclass(frozen=True)
class HumanItem:
    item_id: str
    source: str
    source_id: str
    brand: str | None
    account: str | None
    url: str | None
    link: str
    text: str
    content_type: str
    category: str


class Stage1Labels(NamedTuple):
    items: list[HumanItem]
    provenance: dict


def read_stage1_labels(path: Path, key: Path, config: E1Config) -> Stage1Labels:
    """Accept a labeled prefix, optionally followed by entirely unlabeled rows.

    Validate even labels past the stop point, but never use them for selection.
    Key order and CSV order must both match the original E001... sequence.
    """
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream, strict=True)
            if reader.fieldnames != STAGE1_COLUMNS:
                raise E1Error("LABEL_FILE_INVALID")
            rows = list(reader)
    except FileNotFoundError:
        raise E1Error("LABEL_FILE_MISSING") from None
    except (OSError, UnicodeError, csv.Error):
        raise E1Error("LABEL_FILE_INVALID") from None

    try:
        document = json.loads(key.read_text(encoding="utf-8"))
        key_items = document["items"]
        if not isinstance(key_items, dict) or not key_items:
            raise ValueError
        expected_ids = [f"E{i:03}" for i in range(1, len(key_items) + 1)]
        if list(key_items) != expected_ids or len(rows) > len(key_items):
            raise ValueError
        values = defaultdict(set)
        for row in e1_codebook(("content_type", "category"), 1):
            values[row["axis"]].add(row["value"])
        items = []
        blank_seen = False
        for index, row in enumerate(rows):
            if set(row) != set(STAGE1_COLUMNS) or any(
                value is None for value in row.values()
            ):
                raise ValueError
            item_id = row["item_id"]
            if item_id != expected_ids[index]:
                raise ValueError
            content_type, category = row["content_type"], row["category"]
            if content_type == category == "":
                blank_seen = True
                continue
            if (
                blank_seen
                or content_type not in values["content_type"]
                or category not in values["category"]
            ):
                raise ValueError
            identity = key_items[item_id]
            if (
                not isinstance(identity, dict)
                or identity.get("source") not in config.sources
                or not isinstance(identity.get("source_id"), str)
                or not identity["source_id"]
            ):
                raise ValueError
            for field in ("brand", "account", "url"):
                if field not in identity or (
                    identity[field] is not None and not isinstance(identity[field], str)
                ):
                    raise ValueError
            items.append(
                HumanItem(
                    item_id=item_id,
                    source=identity["source"],
                    source_id=identity["source_id"],
                    brand=identity["brand"],
                    account=identity["account"],
                    url=identity["url"],
                    link=identity["url"] or "",
                    text=row["text"],
                    content_type=content_type,
                    category=category,
                )
            )
        if not items:
            raise ValueError
        return Stage1Labels(items, {k: v for k, v in document.items() if k != "items"})
    except (
        OSError,
        UnicodeError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        IndexError,
    ):
        raise E1Error("LABEL_FILE_INVALID") from None


class StopPoint(NamedTuple):
    items: list[HumanItem]
    position: int
    product_count: int
    unused_count: int


def stop_point(labels: Stage1Labels, config: E1Config) -> StopPoint:
    products = 0
    scope = []
    for item in labels.items[: config.stage1.max_labeled]:
        scope.append(item)
        products += item.content_type == "product_creative"
        if (
            not config.stage1.use_all_labeled
            and len(scope) >= config.stage1.min_labeled
            and products >= config.stage1.target_product
        ):
            break
    return StopPoint(scope, len(scope), products, len(labels.items) - len(scope))


SHORTFALL_CENSUS_NOTE = "전수 모드라 참고용"


class Stage2Selection(NamedTuple):
    items: list[HumanItem]
    shortfall: dict
    mode: str = "sample"  # "census" when every eligible item fits within size
    eligible_count: int = 0
    not_eligible_product_count: int = 0  # human products outside stage2.categories


def select_stage2(
    labels_in_scope: Sequence[HumanItem], config: E1Config, seed: int
) -> Stage2Selection:
    """Human-product items in the supported categories; `other` is not eligible.

    At most `size` items: a census when the eligible pool fits, otherwise the
    (source, category) round-robin used before.
    """
    allowed = set(config.stage2.categories)
    products = [i for i in labels_in_scope if i.content_type == "product_creative"]
    eligible = [i for i in products if i.category in allowed]
    size = config.stage2.size
    if len(eligible) <= size:
        mode = "census"
        selected = sorted(eligible, key=lambda item: item.source_id)
    else:
        mode = "sample"
        grouped = defaultdict(list)
        for item in eligible:
            grouped[item.source, item.category].append(item)
        selected = round_robin(
            grouped, size=size, seed=seed, identity=lambda item: item.source_id
        )
    counts = Counter((item.source, item.category) for item in eligible)
    shortfall = stratum_shortfall(
        counts,
        [(source, category) for source in config.sources for category in allowed],
        size,
        len(selected),
    )
    if mode == "census":
        shortfall["note"] = SHORTFALL_CENSUS_NOTE
    # The second-stage labeling order is blind and independently shuffled.
    random.Random(seed).shuffle(selected)
    return Stage2Selection(
        selected, shortfall, mode, len(eligible), len(products) - len(eligible)
    )


def provenance_accepted(recorded: dict, current: dict, config: E1Config) -> bool:
    """Recorded hashes must be current or explicitly listed as the stage-1 hashes."""
    if recorded.get("seed") != config.seed:
        return False
    for name, value in current.items():
        got = recorded.get(name)
        if got != value and got not in config.accepted_stage1_provenance.get(name, []):
            return False
    return True


def main(argv=None, *, out=None) -> int:
    out = sys.stdout if out is None else out
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--labels", type=Path, default=DEFAULT_OUT_DIR / "e1_stage1_sheet_labeled.csv"
    )
    parser.add_argument(
        "--key", type=Path, default=DEFAULT_OUT_DIR / "e1_stage1_key.json"
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    try:
        config, provenance = provenance_files()
        paths = output_paths(args.out_dir, 2)
        labels = read_stage1_labels(args.labels, args.key, config)
        if not provenance_accepted(labels.provenance, provenance, config):
            raise E1Error("LABEL_FILE_INVALID")
        ensure_new_outputs(paths)
        stop = stop_point(labels, config)
        selection = select_stage2(stop.items, config, config.seed)
        axes = [
            axis for axis in label_columns() if axis not in ("content_type", "category")
        ]
        rows, items = [], {}
        for index, item in enumerate(selection.items, 1):
            item_id = f"F{index:03}"
            rows.append(
                {
                    "item_id": item_id,
                    "link": item.link,
                    "text": item.text,
                    **dict.fromkeys(axes, ""),
                }
            )
            items[item_id] = {
                "source": item.source,
                "source_id": item.source_id,
                "brand": item.brand,
                "account": item.account,
                "url": item.url,
                "stage1_human_labels": {
                    "content_type": item.content_type,
                    "category": item.category,
                },
            }
        document = {
            **provenance,
            "seed": config.seed,
            "stage1_key_sha256": sha256_of(args.key),
            "stop_position": stop.position,
            "product_count": stop.product_count,
            "unused_count": stop.unused_count,
            "shortfall": selection.shortfall,
            "mode": selection.mode,
            "eligible_count": selection.eligible_count,
            "not_eligible_product_count": selection.not_eligible_product_count,
            "stage1_recorded_provenance": {
                name: labels.provenance.get(name) for name in provenance
            },
            "generated_at": datetime.now(UTC).isoformat(),
            "items": items,
        }
        instructions = (
            "# E1 2단계 라벨링\n\n영상·제목·캡션에서 관찰되는 사실을 코드북에 따라 라벨링한다.\n\n"
            "claims는 쉼표 구분 여럿 선택이다. 나머지는 하나만 고르고 불리언은 true/false로 쓴다. "
            "훅은 첫 3초, 다른 축은 전체 영상 기준이다. ingredients는 제외한다.\n\n"
            "첫 라벨은 e1_stage2_sheet_labeled.csv에 따로 저장한다. "
            "7일 뒤 같은 시트를 다시 라벨링한다. 원래의 빈 e1_stage2_sheet.csv를 복사해 "
            "첫 라벨과 키 파일을 가리고 e1_stage2_sheet_retest.csv에 저장한다. "
            "항목 번호와 순서는 유지한다. 키 파일(e1_stage2_key.json)은 라벨링 뒤에만 연다."
        )
        write_artifacts(
            paths,
            fields=["item_id", "link", "text", *axes],
            rows=rows,
            document=document,
            instructions=instructions,
            stage=2,
        )
        if stop.product_count < config.stage1.target_product:
            print(
                f"E1_PRODUCT_SHORTFALL {config.stage1.target_product - stop.product_count}",
                file=out,
            )
        if selection.mode == "census":
            print(f"SHORTFALL_NOTE {SHORTFALL_CENSUS_NOTE}(층별 shortfall)", file=out)
        print(
            json.dumps(
                {
                    "stop_position": stop.position,
                    "product_count": stop.product_count,
                    "unused_count": stop.unused_count,
                    "shortfall": selection.shortfall,
                    "mode": selection.mode,
                    "eligible_count": selection.eligible_count,
                    "not_eligible_product_count": selection.not_eligible_product_count,
                    "selected": len(selection.items),
                    "files": {k: str(v) for k, v in paths.items()},
                },
                ensure_ascii=False,
            ),
            file=out,
        )
        print("키 파일(e1_stage2_key.json)은 라벨링 뒤에만 여세요.", file=out)
    except E1Error as exc:
        print(f"PREFLIGHT_FAILED {exc.code}", file=out)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
