"""Build human-first pilot sheets and keep model results in a separate key."""

import csv
import hashlib
import json
import random
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, NamedTuple, get_args, get_origin

from pydantic import BaseModel

from beautyads.domain import (
    ContentTypeResult,
    Creative,
    CreativeKey,
    FullResult,
    HookResult,
    JobResult,
)

_NON_PRODUCT = (
    "content_type이 product_creative가 아니면 나머지 열(category 제외)은 비워 둔다. "
    "category는 other로 둔다."
)
_CLAIMS = "claims는 여럿 선택이며 쉼표로 구분한다(예: hydration,soothing)."
_OBSERVATION = (
    "영상과 제목·캡션에서 관찰되는 것만 적는다. "
    "자막·음성에 명시된 효능만 쓰고 분위기에서 추정하지 않는다. 확신이 없으면 other."
)
_KEY_RULE = "키 파일(pilot_key.json)은 라벨링을 마친 뒤에만 연다."
_INGREDIENTS = "성분(ingredients)은 이 시범 시트의 라벨링 대상이 아니다."
_PROVENANCE = ("split_sha256", "selection_seed", "sheet_seed", "generated_at")
_RESULT_FIELDS = {
    "status",
    "labels",
    "error_code",
    "model",
    "thinking_level",
    "prompt_version",
}


class BlindSheet(NamedTuple):
    rows: list[dict[str, str]]
    # Each key row carries provenance; the writer hoists it into the JSON header.
    key_rows: list[dict[str, Any]]


class SheetError(Exception):
    """A sheet cannot be built or safely written, identified by a stable code."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _label_axes(model: type[BaseModel]) -> list[tuple[str, type]]:
    axes = []
    for name, field in model.model_fields.items():
        if name == "ingredients":
            continue
        annotation = field.annotation
        if get_origin(annotation) is list:
            annotation = get_args(annotation)[0]
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            axes.extend(_label_axes(annotation))
        else:
            axes.append((name, annotation))
    return axes


def label_columns() -> list[str]:
    """Flatten the v0 result axes, excluding the non-E1 ingredients field."""
    return [
        axis
        for model in (ContentTypeResult, HookResult, FullResult)
        for axis, _ in _label_axes(model)
    ]


def codebook_rows() -> list[dict[str, str]]:
    """Enumerate domain values rather than maintaining a second value list."""
    rows = []
    for model in (ContentTypeResult, HookResult, FullResult):
        for axis, annotation in _label_axes(model):
            if annotation is bool:
                values = ("true", "false")
                note = "불리언 열은 true/false로 적는다."
            elif issubclass(annotation, Enum):
                values = tuple(member.value for member in annotation)
                note = _CLAIMS if axis == "claims" else "하나만 고른다."
            else:
                raise TypeError(f"Unsupported label axis: {axis}")
            note = f"{note} {_NON_PRODUCT} {_OBSERVATION} {_KEY_RULE} {_INGREDIENTS}"
            if axis == "hook_type":
                note += " 훅은 첫 3초 기준이며 둘 이상 해당하면 코드북의 위쪽 값을 우선한다."
            for value in values:
                rows.append({"axis": axis, "value": value, "note": note})
    return rows


def instructions_text() -> str:
    return (
        "\n\n".join(
            (
                "# 시범 20건 블라인드 라벨링 안내",
                "모델 결과를 보기 전에 영상 링크와 제목·캡션을 보고 사람이 먼저 라벨링한다.",
                _NON_PRODUCT,
                f"{_CLAIMS} 나머지 축은 하나만 고른다. 불리언 열은 true/false로 적는다.",
                _OBSERVATION,
                (
                    "훅은 첫 3초, 다른 축은 전체 영상을 기준으로 판정한다. "
                    "훅이 둘 이상 해당하면 코드북의 위쪽 값을 우선한다."
                ),
                _KEY_RULE,
                _INGREDIENTS,
            )
        )
        + "\n"
    )


def build_blind_sheet(
    items: Sequence[Creative],
    *,
    seed: int,
    job_results: Mapping[tuple[str, CreativeKey], JobResult],
    run_tags: Sequence[str],
    split_sha256: str,
    selection_seed: int,
) -> BlindSheet:
    if not items:
        raise SheetError("EMPTY_SELECTION")
    shuffled = list(items)
    random.Random(seed).shuffle(shuffled)
    metadata = {
        "split_sha256": split_sha256,
        "selection_seed": selection_seed,
        "sheet_seed": seed,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    rows = []
    key_rows = []
    for index, creative in enumerate(shuffled, start=1):
        item_id = f"P{index:03}"
        rows.append(
            {
                "item_id": item_id,
                "link": creative.url or "",
                "text": "\n".join(
                    text for text in (creative.title, creative.caption) if text
                ),
                **dict.fromkeys(label_columns(), ""),
            }
        )
        runs = {}
        for tag in run_tags:
            results = {}
            for axis in ("content_type", "hook", "full"):
                result = job_results.get((f"{axis}@{tag}", creative.key))
                results[axis] = (
                    result.model_dump(mode="json", include=_RESULT_FIELDS)
                    if result is not None
                    else None
                )
            runs[tag] = (
                results
                if any(value is not None for value in results.values())
                else None
            )
        key_rows.append(
            {
                **metadata,
                "item_id": item_id,
                "source": creative.source.value,
                "source_id": creative.source_id,
                "brand": creative.brand,
                "account": creative.account,
                "url": creative.url,
                "published_at": creative.published_at.isoformat()
                if creative.published_at
                else None,
                "metrics": creative.metrics.model_dump(mode="json"),
                "runs": runs,
            }
        )
    return BlindSheet(rows, key_rows)


def _output_paths(out_dir: Path) -> dict[str, Path]:
    """Resolve traversal and symlinks before creating any output."""
    resolved = out_dir.resolve()
    root = next(
        (
            path
            for path in (resolved, *resolved.parents)
            if path.name == "interim" and path.parent.name == "data"
        ),
        None,
    )
    paths = {
        "sheet": out_dir / "pilot_sheet.csv",
        "codebook": out_dir / "pilot_codebook.csv",
        "instructions": out_dir / "pilot_instructions.md",
        "key": out_dir / "pilot_key.json",
    }
    if root is None or any(
        not path.resolve().is_relative_to(root) for path in paths.values()
    ):
        raise SheetError("OUTPUT_NOT_IGNORED")
    return paths


def _write_csv(
    path: Path, fields: Sequence[str], rows: Sequence[dict[str, str]]
) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_sheet_files(
    out_dir: Path,
    sheet: BlindSheet,
    codebook: Sequence[dict[str, str]],
    instructions: str,
) -> dict[str, Path]:
    """Write four artifacts; only the JSON key receives provenance and results.

    JSON uses a top-level ``items`` mapping from item_id to creative and run data.
    A missing run is null; a partial run retains null for each missing axis.
    """
    paths = _output_paths(out_dir)
    if not sheet.rows or not sheet.key_rows:
        raise SheetError("EMPTY_SELECTION")
    document = {field: sheet.key_rows[0][field] for field in _PROVENANCE}
    document["items"] = {
        row["item_id"]: {
            key: value
            for key, value in row.items()
            if key not in (*_PROVENANCE, "item_id")
        }
        for row in sheet.key_rows
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(
        paths["sheet"], ["item_id", "link", "text", *label_columns()], sheet.rows
    )
    _write_csv(paths["codebook"], ["axis", "value", "note"], codebook)
    paths["instructions"].write_text(instructions, encoding="utf-8")
    paths["key"].write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return paths


def sha256_of(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()
