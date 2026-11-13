"""Build human-first pilot sheets and keep model results in a separate key."""

import csv
import hashlib
import json
import random
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
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

TAXONOMY_PATH = Path(__file__).resolve().parents[3] / "docs" / "TAXONOMY.md"
_NO_DEFINITION = "정의 없음(위 값 어느 것에도 맞지 않을 때만 고른다)."
_TOKEN = re.compile(r"`([a-z_]+)`(?:\(([^)]*)\))?")

_NON_PRODUCT = (
    "content_type이 product_creative가 아니면 나머지 열(category 제외)은 비워 둔다. "
    "category는 other로 둔다."
)
_CLAIMS = "claims는 여럿 선택이며 쉼표로 구분한다(예: hydration,soothing)."
_OBSERVATION = (
    "영상과 제목·캡션에서 관찰되는 것만 적는다. "
    "영상 자막·음성 또는 캡션 본문 문장에 명시된 효능만 쓰고 "
    "해시태그만 있는 경우는 제외한다. 분위기에서 추정하지 않는다. 확신이 없으면 other."
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
    """Flatten the v1 result axes, excluding the non-E1 ingredients field."""
    return [
        axis
        for model in (ContentTypeResult, HookResult, FullResult)
        for axis, _ in _label_axes(model)
    ]


@dataclass
class AxisGuide:
    """Definitions parsed from one `### ... `axis`` section of TAXONOMY.md."""

    definitions: dict[str, str]
    order: list[str]
    ordered: bool
    bullets: list[str]
    # 3열 이상 표의 셋째 열 이후: 값 -> "열 제목: 내용"
    extras: dict[str, str] = dataclass_field(default_factory=dict)
    headers: list[str] = dataclass_field(default_factory=list)


def parse_taxonomy(text: str) -> dict[str, AxisGuide]:
    """Read value definitions from the taxonomy document instead of copying them."""
    guides: dict[str, AxisGuide] = {}
    current: AxisGuide | None = None
    for line in text.splitlines():
        if line.startswith("### "):
            axis = _TOKEN.search(line)
            current = AxisGuide({}, [], False, [])
            if axis:
                guides[axis.group(1)] = current
            else:
                current = None
            continue
        if line.startswith("## "):
            current = None
            continue
        if current is None:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if line.startswith("|") and len(cells) >= 2:
            token = re.fullmatch(r"`([a-z_]+)`", cells[0])
            if token:
                value = token.group(1)
                current.definitions[value] = cells[1]
                current.order.append(value)
                extra = " ".join(cell for cell in cells[2:] if cell)
                if extra:
                    header = current.headers[2] if len(current.headers) > 2 else "참고"
                    current.extras[value] = f"{header}: {extra}"
            elif not current.headers and not set(cells[0]) <= {"-", ":", " "}:
                current.headers = cells
            continue
        if "위쪽 값을 우선" in line:
            current.ordered = True
        elif line.startswith("- "):
            current.bullets.append(line[2:].strip())
            definition = re.fullmatch(r"- `([a-z_]+)`:\s*(.+)", line)
            if definition:
                current.definitions[definition.group(1)] = definition.group(
                    2
                ).removesuffix(".")
        elif line and not line.startswith(("|", ">")):
            for token, description in _TOKEN.findall(line):
                if description:
                    current.definitions.setdefault(token, description)
    return guides


def _guide_for(guides: Mapping[str, AxisGuide], axis: str) -> AxisGuide | None:
    """Section by axis name, or the table section that lists this column."""
    return guides.get(axis) or next(
        (guide for guide in guides.values() if axis in guide.definitions), None
    )


def _value_note(
    guide: AxisGuide | None, value: str, *, flag_value: str | None = None
) -> str:
    """Note for one value; for a boolean column ``flag_value`` is "true" or "false"."""
    if guide is None:
        return ""
    parts = []
    definition = guide.definitions.get(value, "")
    if flag_value == "false" and definition:
        return "위 true 조건에 해당하지 않으면 false."
    if definition:
        label = "true인 경우" if flag_value == "true" else "정의"
        parts.append(f"{label}: {definition}.")
    elif value in guide.order:
        parts.append(_NO_DEFINITION)
    if value in guide.extras:
        parts.append(f"{guide.extras[value]}.")
    if guide.ordered and value in guide.order:
        parts.append(
            f"우선순위 {guide.order.index(value) + 1}/{len(guide.order)}"
            "(둘 이상 해당하면 숫자가 작은 값)."
        )
    for bullet in guide.bullets:
        # 미확정 쟁점은 값 이름이 없으면 그 절의 모든 값에 보여 준다.
        unresolved = bullet.startswith("**미확정")
        names_section_value = any(f"`{name}`" in bullet for name in guide.order)
        shared_rule = not _TOKEN.search(bullet) or "고정 우선순위" in bullet
        if (
            f"`{value}`" in bullet
            or shared_rule
            or (unresolved and not names_section_value)
        ):
            parts.append(bullet)
    return " ".join(parts)


def codebook_rows(taxonomy_text: str | None = None) -> list[dict[str, str]]:
    """Enumerate domain values rather than maintaining a second value list.

    Per-value definitions and priorities come from docs/TAXONOMY.md.
    """
    if taxonomy_text is None:
        taxonomy_text = TAXONOMY_PATH.read_text(encoding="utf-8")
    guides = parse_taxonomy(taxonomy_text)
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
                guide = _guide_for(guides, axis)
                # 불리언 열은 값(true/false)이 아니라 열 이름으로 정의를 찾는다.
                detail = (
                    _value_note(guide, axis, flag_value=value)
                    if annotation is bool
                    else _value_note(guide, value)
                )
                rows.append(
                    {
                        "axis": axis,
                        "value": value,
                        "note": f"{detail} {note}" if detail else note,
                    }
                )
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


def write_docs_files(
    out_dir: Path, codebook: Sequence[dict[str, str]], instructions: str
) -> dict[str, Path]:
    """Rewrite only the codebook and instructions; sheet and key stay untouched."""
    paths = _output_paths(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(paths["codebook"], ["axis", "value", "note"], codebook)
    paths["instructions"].write_text(instructions, encoding="utf-8")
    return {name: paths[name] for name in ("codebook", "instructions")}


def write_key_supplement(out_dir: Path, document: Mapping[str, Any]) -> Path:
    """Write retry results beside, never into, the already-generated key file."""
    _output_paths(out_dir)
    path = out_dir / "pilot_key_supplement.json"
    if not path.resolve().is_relative_to(out_dir.resolve()):
        raise SheetError("OUTPUT_NOT_IGNORED")
    out_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path


def read_key_items(out_dir: Path) -> dict[str, CreativeKey]:
    """item_id -> creative key from the existing key file (read-only)."""
    path = _output_paths(out_dir)["key"]
    try:
        items = json.loads(path.read_text(encoding="utf-8"))["items"]
        return {
            item_id: CreativeKey(source=value["source"], source_id=value["source_id"])
            for item_id, value in items.items()
        }
    except FileNotFoundError:
        raise SheetError("PILOT_KEY_MISSING") from None
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise SheetError("PILOT_KEY_INVALID") from None


def sha256_of(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()
