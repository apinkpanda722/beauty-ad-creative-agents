"""Reviewed evaluation records, separate answers, and reproducible set hashes."""

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    ValidationError,
    field_validator,
    model_validator,
)

from beautyads.domain.labels import Category, Claim
from beautyads.domain.skin import SkinConcern, SkinType
from beautyads.sources.workspaces import load_workspaces

EVALSET_DIR = Path("data/evalset")
REQUESTS_PATH = EVALSET_DIR / "requests.jsonl"
QUESTIONS_PATH = EVALSET_DIR / "questions.jsonl"
ANSWERS_PATH = EVALSET_DIR / "answers.jsonl"
WORKSPACES_PATH = Path("config/workspaces.yaml")

AXIS_NAMES = (
    "category",
    "content_type",
    "hook_type",
    "angle",
    "format",
    "talent",
    "has_demo_segment",
    "has_proof_segment",
    "has_cta",
    "is_vertical",
    "has_text_overlay",
    "has_voice",
    "has_music_only",
    "has_subtitles",
    "cta_type",
    "claims",
    "graph_structure",
)
E1_RELIABLE_AXES = frozenset(
    {
        "category",
        "content_type",
        "format",
        "has_demo_segment",
        "has_cta",
        "has_voice",
        "has_music_only",
        "has_subtitles",
        "graph_structure",
    }
)
E1_UNMET_AXES = frozenset(
    {
        "hook_type",
        "angle",
        "talent",
        "has_proof_segment",
        "is_vertical",
        "has_text_overlay",
        "cta_type",
        "claims",
    }
)


class EvalsetError(Exception):
    """Set failures contain a fixed code, never record contents."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def stratum(axes_used) -> str:
    axes = set(axes_used)
    if not axes <= set(AXIS_NAMES):
        raise EvalsetError("AXIS_UNKNOWN")
    return "unreliable" if axes & E1_UNMET_AXES else "reliable"


class _ReviewedItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: str = Field(min_length=1)
    split: Literal["dev", "test"]
    tenant_id: str = Field(min_length=1)
    source_cq: str = Field(min_length=1)
    # Assigned by the dataset construction code, never inferred by a model.
    axes_used: list[str]
    needs_human_review: bool
    reviewed: bool

    @field_validator("axes_used")
    @classmethod
    def known_axes(cls, value: list[str]) -> list[str]:
        stratum(value)
        return value


class RequestItem(_ReviewedItem):
    message: str = Field(min_length=1, max_length=2000)

    @field_validator("message")
    @classmethod
    def nonblank_message(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("EVALSET_ITEM_INVALID")
        return value


class QuestionItem(_ReviewedItem):
    kind: Literal["graph", "simple_search"]
    text: str = Field(min_length=1)
    cq_inputs: dict[str, str]
    answer_type: Literal["count", "set"]

    @field_validator("cq_inputs")
    @classmethod
    def closed_inputs(cls, value: dict[str, str]) -> dict[str, str]:
        # Same classification vocabulary as graph.queries.question_parameters;
        # tenant identity and the reference date come from execution context.
        allowed = {
            "category": {item.value for item in Category if item != Category.other},
            "claim": {item.value for item in Claim},
            "concern": {item.value for item in SkinConcern},
            "skin_type": {item.value for item in SkinType},
        }
        if any(item not in allowed.get(key, ()) for key, item in value.items()):
            raise ValueError("EVALSET_ITEM_INVALID")
        return value


class AnswerItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    question_id: str = Field(min_length=1)
    answer_type: Literal["count", "set"]
    value: StrictInt | list[str]
    tolerance_abs: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    evidence_ids: list[str]
    confirmed: bool

    @model_validator(mode="after")
    def value_matches_type(self) -> "AnswerItem":
        if (self.answer_type == "count" and type(self.value) is not int) or (
            self.answer_type == "set" and not isinstance(self.value, list)
        ):
            raise ValueError("EVALSET_ANSWER_INVALID")
        return self


def _record(item) -> dict:
    return item.model_dump(mode="json") if isinstance(item, BaseModel) else item


def canonical(item) -> str:
    return json.dumps(
        _record(item), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )


def read_jsonl(path: Path) -> list[dict]:
    try:
        rows = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if any(not isinstance(row, dict) for row in rows):
            raise EvalsetError("EVALSET_READ_INVALID")
        return rows
    except (OSError, UnicodeError, ValueError):
        raise EvalsetError("EVALSET_READ_INVALID") from None


def write_jsonl(path: Path, rows):
    records = [_record(row) for row in rows]
    records.sort(
        key=lambda row: (row.get("id", row.get("question_id", "")), canonical(row))
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(canonical(row) + "\n" for row in records), encoding="utf-8")


def _canonical_rows(items, key: str) -> list[str]:
    return [
        canonical(item) for item in sorted(items, key=lambda row: _record(row)[key])
    ]


def request_set_hash(items) -> str:
    text = "\n".join(_canonical_rows(items, "id"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def question_set_hash(questions, answers) -> str:
    text = "\n".join(
        [
            *_canonical_rows(questions, "id"),
            "--answers--",
            *_canonical_rows(answers, "question_id"),
        ]
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _validated(model, rows):
    try:
        # Dump instances as well: frozen models still contain mutable lists/dicts.
        return [model.model_validate(_record(row)) for row in rows]
    except ValidationError as error:
        code = (
            "EVALSET_SPLIT_INVALID"
            if any(item.get("loc") == ("split",) for item in error.errors())
            else "EVALSET_ITEM_INVALID"
        )
        raise EvalsetError(code) from None


def validate_set(
    requests,
    questions,
    answers,
    *,
    final: bool,
    workspaces_path: Path = WORKSPACES_PATH,
):
    requests = _validated(RequestItem, requests)
    questions = _validated(QuestionItem, questions)
    answers = _validated(AnswerItem, answers)
    for rows, key in (
        (requests, "id"),
        (questions, "id"),
        (answers, "question_id"),
    ):
        ids = [getattr(row, key) for row in rows]
        if len(ids) != len(set(ids)):
            raise EvalsetError("EVALSET_ID_DUPLICATE")
    try:
        groups = {row.tenant_id: row.group for row in load_workspaces(workspaces_path)}
    except ValueError:
        raise EvalsetError("EVALSET_SPLIT_INVALID") from None
    for row in [*requests, *questions]:
        if groups.get(row.tenant_id) != row.split or not row.tenant_id.startswith(
            row.split + "-"
        ):
            raise EvalsetError("EVALSET_SPLIT_INVALID")
    by_question = {row.question_id: row for row in answers}
    if set(by_question) != {row.id for row in questions} or any(
        by_question[row.id].answer_type != row.answer_type for row in questions
    ):
        raise EvalsetError("EVALSET_ANSWER_INVALID")
    if not final:
        return
    if (
        Counter(row.split for row in requests) != {"dev": 10, "test": 20}
        or Counter(row.split for row in questions) != {"dev": 10, "test": 40}
        or sum(row.split == "test" and row.kind == "simple_search" for row in questions)
        != 10
    ):
        raise EvalsetError("EVALSET_COUNT_INVALID")
    if any(
        not row.reviewed or row.needs_human_review for row in [*requests, *questions]
    ) or any(not row.confirmed for row in answers):
        raise EvalsetError("EVALSET_NOT_REVIEWED")
