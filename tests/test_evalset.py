"""Synthetic evaluation sets and the read-only E1 axis policy."""

import hashlib
import re
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from beautyads.eval import evalset as sets


@pytest.fixture
def workspaces_path(tmp_path):
    path = tmp_path / "workspaces.yaml"
    path.write_text(
        "\n".join(
            f"- tenant_id: {group}-synthetic\n"
            "  display_name: Synthetic\n"
            "  brand: synthetic\n"
            "  own_product_url: https://example.invalid/product\n"
            "  tone: synthetic\n"
            "  forbidden_terms: []\n"
            f"  group: {group}"
            for group in ("dev", "test")
        ),
        encoding="utf-8",
    )
    return path


def synthetic_set():
    requests, questions, answers = [], [], []
    for split, request_count, question_count in (("dev", 10, 10), ("test", 20, 40)):
        for index in range(request_count):
            requests.append(
                {
                    "id": f"req-{split}-{index:02}",
                    "split": split,
                    "tenant_id": f"{split}-synthetic",
                    "message": "SENTINEL_MESSAGE 합성 요청",
                    "source_cq": "CQ-06",
                    "axes_used": ["category"],
                    "needs_human_review": False,
                    "reviewed": True,
                }
            )
        for index in range(question_count):
            question_id = f"q-{split}-{index:02}"
            questions.append(
                {
                    "id": question_id,
                    "split": split,
                    "kind": "simple_search"
                    if split == "test" and index < 10
                    else "graph",
                    "tenant_id": f"{split}-synthetic",
                    "text": "SENTINEL_QUESTION 합성 질문",
                    "source_cq": "CQ-06",
                    "cq_inputs": {"category": "sun_care"},
                    "answer_type": "count",
                    "axes_used": ["graph_structure"],
                    "needs_human_review": False,
                    "reviewed": True,
                }
            )
            answers.append(
                {
                    "question_id": question_id,
                    "answer_type": "count",
                    "value": index,
                    "tolerance_abs": 0.0,
                    "evidence_ids": ["SENTINEL_EVIDENCE"],
                    "confirmed": True,
                }
            )
    return requests, questions, answers


def test_axis_partition_and_strata():
    assert isinstance(sets.AXIS_NAMES, tuple)
    assert isinstance(sets.E1_RELIABLE_AXES, frozenset)
    assert isinstance(sets.E1_UNMET_AXES, frozenset)
    assert not sets.E1_RELIABLE_AXES & sets.E1_UNMET_AXES
    assert sets.E1_RELIABLE_AXES | sets.E1_UNMET_AXES == set(sets.AXIS_NAMES)
    assert len(sets.AXIS_NAMES) == len(set(sets.AXIS_NAMES)) == 17
    assert sets.stratum([]) == "reliable"
    assert sets.stratum(sets.E1_RELIABLE_AXES) == "reliable"
    checked = 0
    for axis in sets.E1_UNMET_AXES:
        assert sets.stratum(["category", axis]) == "unreliable"
        checked += 1
    assert checked > 0
    with pytest.raises(sets.EvalsetError, match="^AXIS_UNKNOWN$"):
        sets.stratum(["claims", "SENTINEL_UNKNOWN_AXIS"])


def test_axis_policy_matches_e1_section_two():
    text = Path("docs/results/2026-11-19-e1-scoring.md").read_text(encoding="utf-8")
    section = re.search(
        r"^## 2\..*?\n(.*?)(?=^### |^## |\Z)", text, re.MULTILINE | re.DOTALL
    )
    assert section is not None
    assert "| 축 | n | 일치율 | κ | 충족 |" in section.group(1)
    reliable, unmet = set(), set()
    checked = 0
    for line in section.group(1).splitlines():
        if not line.startswith("|"):
            continue
        cells = [
            re.sub(r"\([^)]*\)", "", cell.replace("**", "")).strip()
            for cell in line.strip("|").split("|")
        ]
        if (
            len(cells) != 5
            or not cells[1].isdigit()
            or cells[-1] not in {"충족", "미충족"}
        ):
            continue
        (reliable if cells[-1] == "충족" else unmet).add(cells[0])
        checked += 1
    assert checked == 14
    assert unmet == sets.E1_UNMET_AXES - {"claims"}
    assert reliable <= sets.E1_RELIABLE_AXES


@pytest.mark.parametrize(
    "model,index", [(sets.RequestItem, 0), (sets.QuestionItem, 1), (sets.AnswerItem, 2)]
)
def test_item_models_are_frozen_and_forbid_extra(model, index):
    row = synthetic_set()[index][0]
    item = model.model_validate(row)
    assert item.model_dump(mode="json") == row
    field = "value" if index == 2 else "id"
    with pytest.raises(ValidationError):
        setattr(item, field, "SENTINEL_CHANGED")
    with pytest.raises(ValidationError):
        model.model_validate({**row, "SENTINEL_EXTRA": True})


@pytest.mark.parametrize("message", ["", "   ", "x" * 2001])
def test_request_message_bounds(message):
    row = synthetic_set()[0][0]
    with pytest.raises(ValidationError):
        sets.RequestItem.model_validate({**row, "message": message})
    assert sets.RequestItem.model_validate({**row, "message": "x" * 2000})


@pytest.mark.parametrize(
    "answer_type,value",
    [
        ("count", True),
        ("count", 1.5),
        ("count", "1"),
        ("count", []),
        ("set", 1),
        ("set", [1]),
    ],
)
def test_answer_type_is_strict(answer_type, value):
    row = synthetic_set()[2][0]
    with pytest.raises(ValidationError):
        sets.AnswerItem.model_validate(
            {**row, "answer_type": answer_type, "value": value}
        )


def test_set_answers_and_default_tolerance():
    row = synthetic_set()[2][0]
    row.pop("tolerance_abs")
    answer = sets.AnswerItem.model_validate(
        {**row, "answer_type": "set", "value": ["synthetic"]}
    )
    assert answer.tolerance_abs == 0.0
    assert answer.value == ["synthetic"]


@pytest.mark.parametrize(
    "inputs",
    [
        {"category": "SENTINEL_CATEGORY"},
        {"claim": "SENTINEL_CLAIM"},
        {"concern": "SENTINEL_CONCERN"},
        {"skin_type": "SENTINEL_SKIN"},
        {"tenant_id": "SENTINEL_TENANT"},
        {"as_of": "SENTINEL_DATE"},
        {"SENTINEL_KEY": "SENTINEL_VALUE"},
    ],
)
def test_question_inputs_are_closed_classifications(inputs):
    row = synthetic_set()[1][0]
    with pytest.raises(ValidationError):
        sets.QuestionItem.model_validate({**row, "cq_inputs": inputs})


def test_question_inputs_accept_existing_cq_vocabulary():
    from beautyads.domain.labels import Category, Claim
    from beautyads.domain.skin import SkinConcern, SkinType

    row = synthetic_set()[1][0]
    inputs = {
        "category": next(value.value for value in Category if value != Category.other),
        "claim": next(iter(Claim)).value,
        "concern": next(iter(SkinConcern)).value,
        "skin_type": next(iter(SkinType)).value,
    }
    assert (
        sets.QuestionItem.model_validate({**row, "cq_inputs": inputs}).cq_inputs
        == inputs
    )


def test_jsonl_and_canonical_are_deterministic(tmp_path):
    rows = [{"id": "b", "message": "합성"}, {"message": "둘", "id": "a"}]
    path = tmp_path / "rows.jsonl"
    sets.write_jsonl(path, rows)
    assert sets.read_jsonl(path) == list(reversed(rows))
    output = path.read_text(encoding="utf-8")
    assert "합성" in output and output.endswith("\n")
    assert len(output.splitlines()) == 2
    assert sets.canonical(rows[0]) == '{"id":"b","message":"합성"}'
    sets.write_jsonl(path, reversed(rows))
    assert path.read_text(encoding="utf-8") == output
    assert sets.REQUESTS_PATH == sets.EVALSET_DIR / "requests.jsonl"
    assert sets.QUESTIONS_PATH == sets.EVALSET_DIR / "questions.jsonl"
    assert sets.ANSWERS_PATH == sets.EVALSET_DIR / "answers.jsonl"
    assert sets.QUESTIONS_PATH != sets.ANSWERS_PATH


@pytest.mark.parametrize(
    "content", ['{"SENTINEL_FIELD":', '["SENTINEL_ROW"]', '"SENTINEL_ROW"']
)
def test_invalid_jsonl_has_safe_error(tmp_path, content):
    path = tmp_path / "invalid.jsonl"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(sets.EvalsetError, match="^EVALSET_READ_INVALID$"):
        sets.read_jsonl(path)


def test_hashes_are_order_independent_and_include_answers():
    requests, questions, answers = synthetic_set()
    request_hash = sets.request_set_hash(requests)
    question_hash = sets.question_set_hash(questions, answers)
    request_text = "\n".join(
        sets.canonical(row) for row in sorted(requests, key=lambda r: r["id"])
    )
    question_text = "\n".join(
        [
            *(sets.canonical(row) for row in sorted(questions, key=lambda r: r["id"])),
            "--answers--",
            *(
                sets.canonical(row)
                for row in sorted(answers, key=lambda r: r["question_id"])
            ),
        ]
    )
    assert request_hash == hashlib.sha256(request_text.encode()).hexdigest()
    assert question_hash == hashlib.sha256(question_text.encode()).hexdigest()
    assert re.fullmatch(r"[0-9a-f]{64}", request_hash)
    assert sets.request_set_hash(list(reversed(requests))) == request_hash
    assert (
        sets.question_set_hash(list(reversed(questions)), list(reversed(answers)))
        == question_hash
    )
    assert (
        sets.request_set_hash(
            [sets.RequestItem.model_validate(row) for row in requests]
        )
        == request_hash
    )
    answers[0]["value"] += 1
    assert sets.question_set_hash(questions, answers) != question_hash
    assert sets.request_set_hash(requests) == request_hash


def test_validate_draft_and_final(workspaces_path):
    rows = synthetic_set()
    assert sets.validate_set(*rows, final=True, workspaces_path=workspaces_path) is None
    draft = tuple(group[:1] for group in rows)
    draft[0][0].update(reviewed=False, needs_human_review=True)
    draft[1][0].update(reviewed=False, needs_human_review=True)
    draft[2][0]["confirmed"] = False
    assert (
        sets.validate_set(*draft, final=False, workspaces_path=workspaces_path) is None
    )


@pytest.mark.parametrize("collection", [0, 1, 2])
def test_duplicate_ids(collection, workspaces_path):
    rows = synthetic_set()
    rows[collection].append(deepcopy(rows[collection][0]))
    with pytest.raises(sets.EvalsetError, match="^EVALSET_ID_DUPLICATE$"):
        sets.validate_set(*rows, final=False, workspaces_path=workspaces_path)


@pytest.mark.parametrize("collection", [0, 1])
@pytest.mark.parametrize("tenant", ["test-synthetic", "SENTINEL_UNKNOWN_TENANT"])
def test_workspace_membership_and_split(collection, tenant, workspaces_path):
    rows = synthetic_set()
    rows[collection][0]["tenant_id"] = tenant
    with pytest.raises(sets.EvalsetError, match="^EVALSET_SPLIT_INVALID$"):
        sets.validate_set(*rows, final=False, workspaces_path=workspaces_path)


@pytest.mark.parametrize("collection", [0, 1])
def test_unknown_axes_and_split(collection, workspaces_path):
    rows = synthetic_set()
    rows[collection][0]["axes_used"] = ["SENTINEL_AXIS"]
    with pytest.raises(sets.EvalsetError, match="^AXIS_UNKNOWN$"):
        sets.validate_set(*rows, final=False, workspaces_path=workspaces_path)
    rows[collection][0]["axes_used"] = []
    rows[collection][0]["split"] = "SENTINEL_SPLIT"
    with pytest.raises(sets.EvalsetError, match="^EVALSET_SPLIT_INVALID$"):
        sets.validate_set(*rows, final=False, workspaces_path=workspaces_path)


@pytest.mark.parametrize("change", ["missing", "orphan", "type"])
def test_answer_correspondence(change, workspaces_path):
    rows = synthetic_set()
    if change == "missing":
        rows[2].pop()
    elif change == "orphan":
        rows[2][0]["question_id"] = "SENTINEL_ORPHAN"
    else:
        rows[2][0].update(answer_type="set", value=[])
    with pytest.raises(sets.EvalsetError, match="^EVALSET_ANSWER_INVALID$"):
        sets.validate_set(*rows, final=False, workspaces_path=workspaces_path)


@pytest.mark.parametrize(
    "collection,split",
    [(0, "dev"), (0, "test"), (1, "dev"), (1, "test"), (1, "simple_search")],
)
def test_final_counts(collection, split, workspaces_path):
    rows = synthetic_set()
    if split == "simple_search":
        next(row for row in rows[1] if row["kind"] == split)["kind"] = "graph"
    else:
        row = next(row for row in rows[collection] if row["split"] == split)
        rows[collection].remove(row)
        if collection == 1:
            rows[2][:] = [
                answer for answer in rows[2] if answer["question_id"] != row["id"]
            ]
    with pytest.raises(sets.EvalsetError, match="^EVALSET_COUNT_INVALID$"):
        sets.validate_set(*rows, final=True, workspaces_path=workspaces_path)


@pytest.mark.parametrize(
    "collection,field,value",
    [
        (0, "reviewed", False),
        (1, "reviewed", False),
        (0, "needs_human_review", True),
        (1, "needs_human_review", True),
        (2, "confirmed", False),
    ],
)
def test_final_review_required(collection, field, value, workspaces_path):
    rows = synthetic_set()
    rows[collection][0][field] = value
    with pytest.raises(sets.EvalsetError, match="^EVALSET_NOT_REVIEWED$"):
        sets.validate_set(*rows, final=True, workspaces_path=workspaces_path)


def test_schema_and_workspace_errors_are_safe(workspaces_path):
    rows = synthetic_set()
    rows[0][0]["SENTINEL_EXTRA"] = "SENTINEL_VALUE"
    with pytest.raises(sets.EvalsetError, match="^EVALSET_ITEM_INVALID$"):
        sets.validate_set(*rows, final=False, workspaces_path=workspaces_path)
    rows[0][0].pop("SENTINEL_EXTRA")
    workspaces_path.write_text("SENTINEL_INVALID", encoding="utf-8")
    with pytest.raises(sets.EvalsetError, match="^EVALSET_SPLIT_INVALID$"):
        sets.validate_set(*rows, final=False, workspaces_path=workspaces_path)
