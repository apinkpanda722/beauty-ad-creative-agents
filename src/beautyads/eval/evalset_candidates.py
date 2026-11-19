"""Deterministic CQ candidates and user-run, read-only graph answer collection."""

import argparse
import csv
import json
import math
import random
import re
import sys
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import product
from pathlib import Path
from typing import NamedTuple

from pydantic import ValidationError

from beautyads.domain.labels import Angle, Category, Claim, Format, HookType
from beautyads.domain.skin import SkinConcern, SkinType
from beautyads.eval.cq_verify import cq_preflight, error_code
from beautyads.eval.evalset import (
    EVALSET_DIR,
    WORKSPACES_PATH,
    AnswerItem,
    EvalsetError,
    QuestionItem,
    RequestItem,
    question_set_hash,
    read_jsonl,
    request_set_hash,
    stratum,
    validate_set,
    write_jsonl,
)
from beautyads.eval.p5_compare import BRIEFS
from beautyads.graph.connection import connect_graph
from beautyads.graph.queries import QUESTIONS, question_parameters
from beautyads.graph.values import to_json_safe
from beautyads.pipeline.preflight import docker_running, tcp_reachable
from beautyads.settings import DEFAULT_ENV_FILE
from beautyads.sources.workspaces import load_workspaces

CANDIDATE_FACTOR = 1.5
MAX_ANSWER_SET = 50
CANDIDATE_DIR = Path("data/interim/evalset")
DEV_SPLIT_DIR = CANDIDATE_DIR / "dev"
DEV_SPLIT_CHANGED = "DEV_SPLIT_CHANGED"
WORKSPACE_CATEGORY = {
    "dev-mixsoon": "serum_ampoule",
    "dev-cosrx": "sun_care",
    "test-isntree": "serum_ampoule",
    "test-bojoseon": "sun_care",
}
REVIEW_COLUMNS = (
    "item_id",
    "kind",
    "split",
    "text",
    "source_cq",
    "axes_used",
    "answer_summary",
    "decision",
    "edited_text",
    "answer_confirmed",
    "note",
)

# Korean display names are deliberately local, closed, and independent of models.
_LABELS = {
    "category": {
        "mask_pack": "마스크팩",
        "serum_ampoule": "세럼·앰플",
        "sun_care": "선케어",
    },
    "claim": {
        "hydration": "보습",
        "soothing": "진정",
        "brightening": "미백",
        "firming_elasticity": "탄력",
        "pore_sebum": "모공·피지",
        "acne_trouble": "트러블",
        "barrier": "장벽",
        "anti_aging": "주름 개선",
        "sun_protection": "자외선 차단",
        "texture_finish": "사용감·마무리",
        "other": "기타 효능",
    },
    "format": {
        "ugc_style": "일반인 후기형",
        "studio_film": "스튜디오 촬영",
        "demo": "시연",
        "text_motion": "문자 모션",
        "static_image": "정지 이미지",
        "other": "기타 포맷",
    },
    "hook_type": {
        "question": "질문형",
        "problem": "문제 제기형",
        "result_first": "결과 선공개형",
        "bold_claim": "강한 주장형",
        "product_first": "제품 먼저 제시형",
        "person_first": "인물 먼저 제시형",
        "other": "기타 훅",
    },
    "angle": {
        "problem_solution": "문제 해결",
        "desire": "욕구",
        "social_proof": "사회적 증거",
        "comparison": "비교",
        "ingredient_science": "성분 과학",
        "how_to": "사용법",
        "other": "기타 각도",
    },
    "concern": {v.value: v.value for v in SkinConcern},
    "skin_type": {v.value: v.value for v in SkinType},
}
_INPUTS = {
    "category": tuple(v.value for v in Category if v != Category.other),
    "claim": tuple(v.value for v in Claim),
    "concern": tuple(v.value for v in SkinConcern),
    "skin_type": tuple(v.value for v in SkinType),
}
_REQUEST_AXES = {
    "basic": ["category"],
    "format": ["category", "format"],
    "hook_type": ["hook_type"],
    "angle": ["angle"],
}
_CQ_AXES = {
    "CQ-01": ["category", "claims"],
    "CQ-02": ["category"],
    "CQ-03": ["graph_structure"],
    "CQ-04": ["category", "claims"],
    "CQ-05": ["claims"],
    "CQ-06": ["category", "hook_type"],
    "CQ-08": ["angle", "format"],
    "CQ-09": ["hook_type", "format"],
    "CQ-10": ["claims"],
    "CQ-11": ["category", "claims"],
    "CQ-13": ["claims"],
    "CQ-14": ["claims"],
    "CQ-15": ["graph_structure"],
}
# Each set question asks for the first string-valued column of the frozen query.
# Count questions explicitly ask for result rows, not an aggregate cell's value.
_QUESTION_TEXT = {
    "CQ-01": "{claim} 효능 근거 성분이 든 {category} 제품 링크 집합은 무엇인가?",
    "CQ-02": "{concern} 고민에 맞는 {category} 제품 링크 집합은 무엇인가?",
    "CQ-03": "미백 기능성 인증에 연결된 제품 링크 집합은 무엇인가?",
    "CQ-04": "{claim} 근거 성분이 든 {category} 제품 광고의 고정 질의 결과 행은 몇 개인가?",
    "CQ-05": "병풀 별칭 성분 제품의 광고가 앞세우는 효능 집합은 무엇인가?",
    "CQ-06": "게시 후 14일이 지난 조회수 보유 소재의 훅에 연결된 제품 카테고리 집합은 무엇인가?",
    "CQ-08": "{skin_type} 피부용 제품 광고의 앵글·포맷 값 집합은 무엇인가?",
    "CQ-09": "훅과 포맷이 연결된 틱톡 제품 광고의 소재 ID 집합은 무엇인가?",
    "CQ-10": "{claim} 효능 근거 성분 또는 기능성 인증이 연결된 제품 링크 집합은 무엇인가?",
    "CQ-11": "{category}, {claim}, {concern} 조건에 적용되는 표현 규칙 ID 집합은 무엇인가?",
    "CQ-13": "핵심 성분을 공유하는 경쟁 제품 광고와 연결된 공개 기준 제품 링크 집합은 무엇인가?",
    "CQ-14": "독점 성분·인증의 효능을 경쟁 광고가 앞세우지 않는 공개 기준 제품 링크 집합은 무엇인가?",
    "CQ-15": "최근 6개월 병풀 별칭을 언급한 연결 광고의 소재 ID 집합은 무엇인가?",
}
_FINAL_TARGETS = {
    "requests_dev": 10,
    "requests_test": 20,
    "questions_dev": 10,
    "questions_test_graph": 30,
    "questions_test_simple_search": 10,
}
DEV_TARGETS = {key: _FINAL_TARGETS[key] for key in ("requests_dev", "questions_dev")}
_REQUEST_HASH = "후보 요청 sha256"
_QUESTION_HASH = "후보 질문 sha256"


@dataclass
class Candidates:
    requests: list[RequestItem] = field(default_factory=list)
    questions: list[QuestionItem] = field(default_factory=list)
    answers: list[AnswerItem] = field(default_factory=list)
    shortages: dict[str, int] = field(default_factory=dict)
    errors: dict[str, int] = field(default_factory=dict)
    query_count: int = 0
    excluded: dict[str, int] = field(default_factory=dict)
    valid_pool: dict[str, int] = field(default_factory=dict)
    answer_sizes: dict[str, dict[str, int]] = field(default_factory=dict)
    composition: dict[str, dict[str, int]] = field(default_factory=dict)
    final_shortages: dict[str, int] = field(default_factory=dict)


class ReviewedSet(NamedTuple):
    requests: list[RequestItem]
    questions: list[QuestionItem]
    answers: list[AnswerItem]

    @property
    def shortages(self):
        return _shortages(self.requests, self.questions, _FINAL_TARGETS)


def _shortages(requests, questions, targets):
    counts = Counter(f"requests_{r.split}" for r in requests)
    counts.update(
        "questions_dev" if q.split == "dev" else f"questions_test_{q.kind}"
        for q in questions
    )
    return {key: max(0, target - counts[key]) for key, target in targets.items()}


def parse_cq_table(text) -> list[dict]:
    """Read the five-column source table, ignoring prose and result tables."""
    rows, seen = [], set()
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if (
            len(cells) != 5
            or not re.fullmatch(r"CQ-\d{2}", cells[0])
            or cells[0] in seen
        ):
            continue
        seen.add(cells[0])
        rows.append(
            dict(zip(("id", "question", "layers", "path", "usage"), cells, strict=True))
        )
    return rows


def _eligible(rows):
    return [
        row
        for row in rows
        if row["id"] in QUESTIONS and "context" not in QUESTIONS[row["id"]].parameters
    ]


def _workspaces(workspaces, split):
    return sorted(
        (
            w
            for w in workspaces
            if w.group == split and w.tenant_id.startswith(split + "-")
        ),
        key=lambda w: w.tenant_id,
    )


def _round_robin(groups, rng):
    queues = []
    for key in sorted(groups):
        items = list(groups[key])
        rng.shuffle(items)
        queues.append(deque(items))
    while any(queues):
        for queue in queues:
            if queue:
                yield queue.popleft()


def _apportion(weights: dict[str, int], total: int) -> dict[str, int]:
    """Allocate capped integer quotas by largest remainder, breaking ties by key."""
    available = sum(weights.values())
    total = min(total, available)
    if not available:
        return dict.fromkeys(sorted(weights), 0)
    quotas = {key: total * weight // available for key, weight in weights.items()}
    order = sorted(weights, key=lambda key: (-(total * weights[key] % available), key))
    for key in order[: total - sum(quotas.values())]:
        quotas[key] += 1
    return quotas


def _object_particle(word) -> str:
    """Choose the Korean object particle from the final Hangul syllable."""
    if word and "가" <= word[-1] <= "힣":
        return "을" if (ord(word[-1]) - ord("가")) % 28 else "를"
    return "을"


def build_request_candidates(cq_rows, workspaces, *, briefs=None) -> Candidates:
    briefs = BRIEFS if briefs is None else briefs
    cqs = [
        row
        for row in _eligible(cq_rows)
        if "기획" in row["usage"] or "리서치" in row["usage"]
    ]
    targets = {
        key: math.ceil(value * CANDIDATE_FACTOR)
        for key, value in _FINAL_TARGETS.items()
        if key.startswith("requests_")
    }
    result = Candidates()
    rng = random.Random(20261119)
    enums = {"format": Format, "hook_type": HookType, "angle": Angle}
    for split in ("dev", "test"):
        pools = {"reliable": {}, "unreliable": {}}
        seen = set()
        for workspace, cq, brief, template in product(
            _workspaces(workspaces, split), cqs, briefs, _REQUEST_AXES
        ):
            category, claim = brief.get("category"), brief.get("claim")
            if (
                category != WORKSPACE_CATEGORY.get(workspace.tenant_id)
                or category not in _LABELS["category"]
                or claim not in _LABELS["claim"]
            ):
                continue
            values = (
                (None,)
                if template == "basic"
                else tuple(v.value for v in enums[template])
            )
            for value in values:
                if value == "other":
                    continue
                if value is not None and value not in _LABELS[template]:
                    continue
                condition = ""
                if value is not None:
                    noun = {"format": "포맷", "hook_type": "훅 유형", "angle": "각도"}[
                        template
                    ]
                    label = _LABELS[template][value]
                    phrase = label if label.endswith(noun) else f"{label} {noun}"
                    condition = f" {phrase}{_object_particle(phrase)} 지정해"
                message = f"역량 질문 {cq['id']}의 근거를 바탕으로 {_LABELS['category'][category]} 제품의 {_LABELS['claim'][claim]} 광고를{condition} 기획안 1안으로 작성해 주세요."
                signature = (workspace.tenant_id, message)
                if signature in seen:
                    continue
                seen.add(signature)
                axes = list(_REQUEST_AXES[template])
                item = RequestItem(
                    id=f"req-{split}-{len(seen):04d}",
                    split=split,
                    tenant_id=workspace.tenant_id,
                    source_cq=cq["id"],
                    axes_used=axes,
                    needs_human_review=True,
                    reviewed=False,
                    message=message,
                )
                pools[stratum(axes)].setdefault(cq["id"], []).append(item)
        limit = targets[f"requests_{split}"]
        reliable = list(_round_robin(pools["reliable"], rng))
        unreliable = list(_round_robin(pools["unreliable"], rng))
        reliable_count = math.ceil(limit * 2 / 3)
        selected = reliable[:reliable_count] + unreliable[: limit - reliable_count]
        # Exhaust available strata before reporting a deficit; never fabricate rows.
        selected += (reliable[reliable_count:] + unreliable[limit - reliable_count :])[
            : limit - len(selected)
        ]
        result.requests.extend(selected)
    result.shortages = _shortages(result.requests, [], targets)
    return result


class _CountingGraph:
    def __init__(self, graph):
        self.graph, self.count = graph, 0

    def run(self, cypher, params):
        self.count += 1
        return self.graph.run(cypher, params)


def _failure_code(error):
    if isinstance(error, ValueError) and error.args == ("CQ_INPUT_INVALID",):
        return "CQ_INPUT_INVALID"
    code = error_code(error)
    return (
        code
        if code
        in {
            "CQ_SYNTAX_ERROR",
            "NEO4J_UNREACHABLE",
            "NEO4J_AUTH_VOLUME_STALE",
            "NEO4J_CONSTRAINT_VIOLATION",
        }
        else "CQ_EXECUTION_ERROR"
    )


def build_question_candidates(cq_rows, workspaces, *, graph=None, as_of) -> Candidates:
    """Select disjoint input combinations; graph=None is an offline estimate."""
    groups = {"graph": {}, "simple_search": {}}
    rng = random.Random(20261119)
    for cq in _eligible(cq_rows):
        qid = cq["id"]
        spec = QUESTIONS[qid]
        # A new CQ needs an explicit display template and axis declaration.
        if qid not in _CQ_AXES or qid not in _QUESTION_TEXT:
            continue
        combinations = product(*(_INPUTS.get(name, ()) for name in spec.inputs))
        for values in combinations:
            inputs = dict(zip(spec.inputs, values, strict=True))
            if any(
                value not in _LABELS.get(name, {}) for name, value in inputs.items()
            ):
                continue
            labels = {name: _LABELS[name][value] for name, value in inputs.items()}
            # Closed defaults agree with question_parameters when inputs omit a key.
            for name, default in (
                ("category", "serum_ampoule"),
                ("claim", "soothing"),
                ("concern", SkinConcern.acne_trouble.value),
                ("skin_type", SkinType.dry.value),
            ):
                labels.setdefault(name, _LABELS[name][default])
            kind = "simple_search" if spec.hops <= 1 else "graph"
            groups[kind].setdefault(qid, []).append(
                (qid, inputs, _QUESTION_TEXT[qid].format(**labels))
            )
    result = Candidates(
        excluded={"empty": 0, "oversize": 0, "duplicate_answers": 0},
        valid_pool={qid: 0 for group in groups.values() for qid in sorted(group)},
        answer_sizes={
            qid: {"le10": 0, "gt10": 0, "count": 0}
            for group in groups.values()
            for qid in sorted(group)
        },
    )
    reader = _CountingGraph(graph) if graph is not None else None
    errors = Counter()
    targets = {
        key: math.ceil(value * CANDIDATE_FACTOR)
        for key, value in _FINAL_TARGETS.items()
        if key.startswith("questions_")
    }
    seen_answers = {qid: set() for qid in result.valid_pool}
    sequence = 0

    def evaluate(entry, kind):
        nonlocal sequence
        qid, inputs, text = entry
        sequence += 1
        # Fixed queries read public data; split/tenant and final IDs are assigned
        # only after answer validation and proportional allocation.
        question = QuestionItem(
            id=f"q-pending-{sequence:04d}",
            split="dev",
            tenant_id="dev-pending",
            source_cq=qid,
            axes_used=list(_CQ_AXES[qid]),
            needs_human_review=True,
            reviewed=False,
            kind=kind,
            text=text,
            cq_inputs=inputs,
            answer_type="count" if qid == "CQ-04" else "set",
        )
        answer = None
        if reader is not None:
            try:
                answer = compute_answer(reader, question, as_of=as_of)
            except Exception as error:  # noqa: BLE001 -- isolate failed candidates
                errors[_failure_code(error)] += 1
                return None
            size = len(answer.value) if answer.answer_type == "set" else answer.value
            if size == 0:
                result.excluded["empty"] += 1
                return None
            if answer.answer_type == "set" and size > MAX_ANSWER_SET:
                result.excluded["oversize"] += 1
                return None
            bucket = (
                "count"
                if answer.answer_type == "count"
                else "le10"
                if size <= 10
                else "gt10"
            )
            result.answer_sizes[qid][bucket] += 1
            signature = (
                tuple(answer.value) if answer.answer_type == "set" else answer.value
            )
            if signature in seen_answers[qid]:
                result.excluded["duplicate_answers"] += 1
            seen_answers[qid].add(signature)
        result.valid_pool[qid] += 1
        return question, answer

    # Evaluate every closed graph combination before capping or splitting.
    valid_graph = {qid: [] for qid in sorted(groups["graph"])}
    for entry in _round_robin(groups["graph"], rng):
        candidate = evaluate(entry, "graph")
        if candidate is not None:
            valid_graph[entry[0]].append(candidate)
    quotas = _apportion(
        {qid: len(items) for qid, items in valid_graph.items()},
        targets["questions_dev"] + targets["questions_test_graph"],
    )
    valid_graph = {qid: items[: quotas[qid]] for qid, items in valid_graph.items()}
    pool_size = sum(quotas.values())
    dev_share = min(
        targets["questions_dev"],
        round(
            pool_size
            * _FINAL_TARGETS["questions_dev"]
            / (_FINAL_TARGETS["questions_dev"] + _FINAL_TARGETS["questions_test_graph"])
        ),
    )
    dev_quotas = _apportion(quotas, dev_share)
    selected = {"dev": [], "test": []}
    for qid, items in valid_graph.items():
        selected["dev"].extend(items[: dev_quotas[qid]])
        selected["test"].extend(items[dev_quotas[qid] :])

    # Reserve test simple searches first, then fill only the dev deficit. This
    # iterator stops once both quotas are met, leaving remaining inputs unqueried.
    simple_pool = iter(_round_robin(groups["simple_search"], rng))
    for split, limit in (
        ("test", targets["questions_test_simple_search"]),
        ("dev", targets["questions_dev"] - len(selected["dev"])),
    ):
        if not _workspaces(workspaces, split):
            continue
        accepted = 0
        while accepted < limit:
            entry = next(simple_pool, None)
            if entry is None:
                break
            candidate = evaluate(entry, "simple_search")
            if candidate is not None:
                selected[split].append(candidate)
                accepted += 1

    for split in ("dev", "test"):
        tenants = _workspaces(workspaces, split)
        if not tenants:
            continue
        for index, (question, answer) in enumerate(selected[split], 1):
            question = QuestionItem.model_validate(
                {
                    **question.model_dump(),
                    "id": f"q-{split}-{index:04d}",
                    "split": split,
                    "tenant_id": tenants[(index - 1) % len(tenants)].tenant_id,
                }
            )
            result.questions.append(question)
            if answer is not None:
                result.answers.append(
                    AnswerItem.model_validate(
                        {**answer.model_dump(), "question_id": question.id}
                    )
                )
    result.query_count = reader.count if reader is not None else len(result.questions)
    result.errors = dict(errors)
    result.shortages = _shortages([], result.questions, targets)
    result.final_shortages = _shortages(
        [], result.questions, {key: _FINAL_TARGETS[key] for key in targets}
    )
    result.composition = {
        split: dict(Counter(q.source_cq for q in result.questions if q.split == split))
        for split in ("dev", "test")
    }
    return result


def compute_answer(graph, question, *, as_of) -> AnswerItem:
    spec = QUESTIONS[question.source_cq]
    if "context" in spec.parameters:
        raise ValueError("CQ_INPUT_INVALID")
    params = question_parameters(spec, as_of=as_of, inputs=question.cq_inputs)
    records = to_json_safe(graph.run(spec.cypher, params).records)
    values, evidence = set(), set()
    for row in records:
        if not isinstance(row, dict):
            continue
        first = next((value for value in row.values() if isinstance(value, str)), None)
        if first is not None:
            values.add(first)
        creative_id = row.get("creative_id")
        if isinstance(creative_id, str):
            evidence.add(creative_id)
        creative_ids = row.get("creative_ids")
        if isinstance(creative_ids, list):
            evidence.update(value for value in creative_ids if isinstance(value, str))
    return AnswerItem(
        question_id=question.id,
        answer_type=question.answer_type,
        value=len(records) if question.answer_type == "count" else sorted(values),
        evidence_ids=sorted(evidence),
        confirmed=False,
    )


def review_rows(candidates):
    answers = {a.question_id: a for a in candidates.answers}
    rows = []
    for item in [*candidates.requests, *candidates.questions]:
        answer = answers.get(item.id)
        summary = (
            "-"
            if answer is None
            else json.dumps(
                {
                    "answer_type": answer.answer_type,
                    "value": answer.value,
                    "evidence_ids": answer.evidence_ids,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        rows.append(
            dict(
                zip(
                    REVIEW_COLUMNS,
                    (
                        item.id,
                        "request" if isinstance(item, RequestItem) else item.kind,
                        item.split,
                        item.message if isinstance(item, RequestItem) else item.text,
                        item.source_cq,
                        json.dumps(item.axes_used, ensure_ascii=False),
                        summary,
                        "",
                        "",
                        "",
                        "",
                    ),
                    strict=True,
                )
            )
        )
    return rows


def write_review_sheet(candidates, out_dir=CANDIDATE_DIR):
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "review_sheet.csv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=REVIEW_COLUMNS)
        writer.writeheader()
        writer.writerows(review_rows(candidates))
    instructions = """# 평가셋 후보 검수 (1인 라벨링)

## 칸의 뜻과 칸별 기준
- item_id: 후보 ID. kind: request(요청), graph(관계 질문), simple_search(단순 검색).
- split: dev는 기준 조정용, test는 최종 측정용. 작업 공간·카테고리 대응의 사실을 확인한다.
- text: CQ와 맞고 명확한 한국어인지 확인한다. 요청은 기획안 1안이어야 한다.
- source_cq: 근거 CQ. axes_used: 코드가 정한 축. 두 칸은 수정하지 않는다.
- answer_summary: 고정 질의 정답의 유형·값·근거 소재 ID. count는 결과 행 수,
  set은 각 행 첫 문자열 열의 중복 제거·정렬 집합이다. 집계 셀의 숫자가 아니다.
  그래프 질의 요약과 대조해 정답을 확인한다. 요청은 해당 없음(-).
- decision: O(그대로 채택), X(제외), 수정(edited_text에 고친 문장).
- edited_text: 수정일 때만 새 문장을 쓴다. 의미·축·입력 조건을 바꾸지 않는다.
  수정하지 않으면 -를 적는다. 축·정답·source_cq 변경이 필요하면 X로 제외한다.
- answer_confirmed: 정답이 맞으면 Y, 틀리거나 모호하면 N. 요청은 N(해당 없음).
  N인 질문은 채택되지 않는다. 모호한 사유는 note에 적는다.
- note: 판단 사유. 사유가 없으면 -를 적는다.

## 예시 1개
item_id=q-dev-0001, decision=수정, edited_text=조건에 맞는 제품 링크 집합은 무엇인가?,
answer_confirmed=Y, note=표현만 명료화 (나머지 칸은 원본 유지).

## 기록 방법
CSV를 UTF-8로 저장한다. 생성 시 비어 있는 decision·edited_text·answer_confirmed·note를
모든 행에서 채운다. 빈 칸 금지이며 해당 없는 칸에는 위 기준대로 - 또는 N을 기록한다.
이 네 칸만 편집하고 나머지는 원본을 유지한다. 질문은 Y로 확인한 O·수정만 채택한다.
요청 dev 10/test 20, 질문 dev 10/test 관계 30·단순 검색 10을 골라 나머지는 X로 둔다.
충족 축만 쓴 reliable 후보를 우선하되 미충족 축 후보도 층화 분석용으로 유지한다.
카테고리 대응·효능 문구의 사실은 사람이 확인한다. 부족하면 확정 파일을 쓰지 않는다.
검수 후 python -m beautyads.eval.evalset_candidates finalize (또는 --finalize)를 실행한다.
--dry-run은 접속·파일 쓰기 없이 건수와 부족 건수만 확인한다.

## dev 먼저 확정
dev 행만 먼저 기록하고 finalize --split dev로 dev만 별도로 확정할 수 있다.
X로 제외하는 행도 포함해 모든 dev 행의 네 칸(decision·edited_text·answer_confirmed·note)을
채워야 한다. 빈 칸 금지이며 test 행은 비워 둬도 된다.
dev만 확정한 파일은 최종 사전 등록 세트가 아니다.
test까지 검수를 끝낸 뒤 finalize로 전체를 확정한다.

"""
    instructions += f"""## 질문 후보 유효성과 부족 건수
정답이 비었거나 정답 집합 크기가 {MAX_ANSWER_SET} 초과인 질문은 후보에서 이미 제외했다.
count 정답은 결과 행 수가 0일 때 제외하며 집합 크기 상한은 적용하지 않는다.
CQ-08·CQ-13·CQ-14는 데이터 부재로 항상 빈 정답이라 후보가 없다.
후보가 부족하면 생성 출력의 final_shortages를 확인한다.

"""
    instructions += f"{_REQUEST_HASH}: {request_set_hash(candidates.requests)}\n"
    instructions += f"{_QUESTION_HASH}: {question_set_hash(candidates.questions, candidates.answers)}\n"
    (out_dir / "review_instructions.md").write_text(instructions, encoding="utf-8")


def apply_review(candidates, sheet_rows, *, split=None) -> ReviewedSet:
    items = [*candidates.requests, *candidates.questions]
    known_ids = {item.id for item in items}
    expected = {
        row["item_id"]: row
        for row in review_rows(candidates)
        if split is None or row["split"] == split
    }
    reviews = {}
    editable = {"decision", "edited_text", "answer_confirmed", "note"}
    for row in sheet_rows:
        item_id = row.get("item_id")
        if item_id not in known_ids:
            raise EvalsetError("REVIEW_INVALID")
        if item_id not in expected:
            continue
        if item_id in reviews or set(row) != set(REVIEW_COLUMNS):
            raise EvalsetError("REVIEW_INVALID")
        if any(
            row.get(key) != expected[item_id][key]
            for key in REVIEW_COLUMNS
            if key not in editable
        ):
            raise EvalsetError("REVIEW_IMMUTABLE_MISMATCH")
        if any(
            not isinstance(row.get(key), str) or not row[key].strip()
            for key in editable
        ):
            raise EvalsetError("REVIEW_INCOMPLETE")
        if row["decision"] not in {"O", "X", "수정"} or row["answer_confirmed"] not in {
            "Y",
            "N",
        }:
            raise EvalsetError("REVIEW_INVALID")
        if row["decision"] == "수정" and row["edited_text"].strip() == "-":
            raise EvalsetError("REVIEW_INVALID")
        reviews[item_id] = row
    if set(reviews) != set(expected):
        raise EvalsetError("REVIEW_INCOMPLETE")
    requests, questions, answers = [], [], []
    by_question = {a.question_id: a for a in candidates.answers}
    for item in items:
        if split is not None and item.split != split:
            continue
        row = reviews[item.id]
        if row["decision"] == "X":
            continue
        is_request = isinstance(item, RequestItem)
        if not is_request and row["answer_confirmed"] != "Y":
            continue
        record = item.model_dump()
        record.update(reviewed=True, needs_human_review=False)
        if row["decision"] == "수정":
            record["message" if is_request else "text"] = row["edited_text"]
        try:
            if is_request:
                requests.append(RequestItem.model_validate(record))
            else:
                answer = by_question.get(item.id)
                if answer is None:
                    raise EvalsetError("EVALSET_ANSWER_INVALID")
                questions.append(QuestionItem.model_validate(record))
                answers.append(
                    AnswerItem.model_validate(
                        {**answer.model_dump(), "confirmed": True}
                    )
                )
        except ValidationError:
            raise EvalsetError("EVALSET_ITEM_INVALID") from None
    return ReviewedSet(requests, questions, answers)


def load_candidates(out_dir=CANDIDATE_DIR):
    try:
        result = Candidates(
            requests=[
                RequestItem.model_validate(row)
                for row in read_jsonl(out_dir / "requests_candidates.jsonl")
            ],
            questions=[
                QuestionItem.model_validate(row)
                for row in read_jsonl(out_dir / "questions_candidates.jsonl")
            ],
            answers=[
                AnswerItem.model_validate(row)
                for row in read_jsonl(out_dir / "answers_candidates.jsonl")
            ],
        )
    except ValidationError:
        raise EvalsetError("EVALSET_ITEM_INVALID") from None
    return result


def _verify_hashes(bundle, out_dir):
    try:
        text = (out_dir / "review_instructions.md").read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise EvalsetError("EVALSET_READ_INVALID") from None
    for label, expected in (
        (_REQUEST_HASH, request_set_hash(bundle.requests)),
        (_QUESTION_HASH, question_set_hash(bundle.questions, bundle.answers)),
    ):
        values = re.findall(
            rf"^{re.escape(label)}: ([a-f0-9]{{64}})$", text, re.MULTILINE
        )
        if values != [expected]:
            raise EvalsetError("EVALSET_HASH_MISMATCH")


def _read_review(bundle, candidate_dir, *, split=None):
    try:
        with (candidate_dir / "review_sheet.csv").open(
            encoding="utf-8", newline=""
        ) as stream:
            reader = csv.DictReader(stream)
            if tuple(reader.fieldnames or ()) != REVIEW_COLUMNS:
                raise EvalsetError("REVIEW_INVALID")
            return apply_review(bundle, list(reader), split=split)
    except (OSError, UnicodeError, csv.Error):
        raise EvalsetError("EVALSET_READ_INVALID") from None


def _dev_hashes(reviewed):
    requests = [r for r in reviewed.requests if r.split == "dev"]
    questions = [q for q in reviewed.questions if q.split == "dev"]
    ids = {q.id for q in questions}
    answers = [a for a in reviewed.answers if a.question_id in ids]
    return {
        "dev_request_hash": request_set_hash(requests),
        "dev_question_hash": question_set_hash(questions, answers),
    }


def _dev_split_changed(dev_dir, reviewed):
    try:
        paths = [
            dev_dir / name
            for name in ("requests.jsonl", "questions.jsonl", "answers.jsonl")
        ]
        if not all(path.is_file() for path in paths):
            return False
        saved = ReviewedSet(
            *(
                [model.model_validate(row) for row in read_jsonl(path)]
                for model, path in zip(
                    (RequestItem, QuestionItem, AnswerItem), paths, strict=True
                )
            )
        )
        return _dev_hashes(saved) != _dev_hashes(reviewed)
    except (EvalsetError, OSError, UnicodeError, ValueError):
        return False


def _finalize_dev(candidate_dir, dev_dir, *, dry_run, out):
    bundle = load_candidates(candidate_dir)
    validate_set(bundle.requests, bundle.questions, bundle.answers, final=False)
    _verify_hashes(bundle, candidate_dir)
    reviewed = _read_review(bundle, candidate_dir, split="dev")
    if any(item.split != "dev" for item in [*reviewed.requests, *reviewed.questions]):
        raise EvalsetError("EVALSET_SPLIT_INVALID")
    shortages = _shortages(reviewed.requests, reviewed.questions, DEV_TARGETS)
    print(
        json.dumps(
            {
                "requests": len(reviewed.requests),
                "questions": len(reviewed.questions),
                "shortages": shortages,
            }
        ),
        file=out,
    )
    if dry_run:
        return 0
    if any(shortages.values()):
        return 3
    validate_set(*reviewed, final=False)
    for filename, items in zip(
        ("requests.jsonl", "questions.jsonl", "answers.jsonl"), reviewed, strict=True
    ):
        write_jsonl(dev_dir / filename, items)
    print(json.dumps(_dev_hashes(reviewed)), file=out)
    return 0


def _finalize(candidate_dir, final_dir, *, dry_run, out):
    bundle = load_candidates(candidate_dir)
    validate_set(bundle.requests, bundle.questions, bundle.answers, final=False)
    _verify_hashes(bundle, candidate_dir)
    reviewed = _read_review(bundle, candidate_dir)
    if not dry_run and not any(reviewed.shortages.values()):
        validate_set(*reviewed, final=True)
    print(
        json.dumps(
            {
                "requests": len(reviewed.requests),
                "questions": len(reviewed.questions),
                "shortages": reviewed.shortages,
            },
            ensure_ascii=False,
        ),
        file=out,
    )
    if dry_run:
        print("모델 호출 0건, 그래프 읽기 전용 질의 0건(가정, 미실측)", file=out)
        return 0
    if any(reviewed.shortages.values()):
        return 3
    if _dev_split_changed(candidate_dir / "dev", reviewed):
        print(DEV_SPLIT_CHANGED, file=out)
    for filename, items in zip(
        ("requests.jsonl", "questions.jsonl", "answers.jsonl"), reviewed, strict=True
    ):
        write_jsonl(final_dir / filename, items)
    print(
        json.dumps(
            {
                "request_hash": request_set_hash(reviewed.requests),
                "question_hash": question_set_hash(
                    reviewed.questions, reviewed.answers
                ),
            }
        ),
        file=out,
    )
    return 0


class _ArgumentError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise _ArgumentError


def main(
    argv=None,
    *,
    out=None,
    cq_rows=None,
    workspaces=None,
    graph_factory=None,
    check=None,
    candidate_dir=CANDIDATE_DIR,
    final_dir=EVALSET_DIR,
    as_of=None,
    environ=None,
):
    out = sys.stdout if out is None else out
    parser = _Parser(description=__doc__, allow_abbrev=False)
    parser.add_argument(
        "command", choices=("generate", "finalize"), nargs="?", default="generate"
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--finalize", action="store_true")
    parser.add_argument("--split", choices=("dev",))
    graph = None
    try:
        args = parser.parse_args(argv)
        if args.command == "finalize" or args.finalize:
            if args.split == "dev":
                return _finalize_dev(
                    candidate_dir, candidate_dir / "dev", dry_run=args.dry_run, out=out
                )
            return _finalize(candidate_dir, final_dir, dry_run=args.dry_run, out=out)
        if args.split is not None:
            raise _ArgumentError
        rows = (
            parse_cq_table(
                Path("docs/COMPETENCY_QUESTIONS.md").read_text(encoding="utf-8")
            )
            if cq_rows is None
            else cq_rows
        )
        workspaces = (
            load_workspaces(WORKSPACES_PATH) if workspaces is None else workspaces
        )
        as_of = datetime.now(UTC).date() if as_of is None else as_of
        requests = build_request_candidates(rows, workspaces)
        if not args.dry_run:
            env_file = DEFAULT_ENV_FILE if environ is None else None
            problem = (
                check()
                if check is not None
                else cq_preflight(
                    environ=environ,
                    env_file=env_file,
                    docker_check=docker_running,
                    tcp_check=tcp_reachable,
                )
            )
            if problem:
                print(f"PREFLIGHT_FAILED {problem}", file=out)
                return 2
            graph = (
                graph_factory()
                if graph_factory is not None
                else connect_graph(environ=environ, env_file=env_file)
            )
        questions = build_question_candidates(
            rows, workspaces, graph=graph, as_of=as_of
        )
        bundle = Candidates(
            requests=requests.requests,
            questions=questions.questions,
            answers=questions.answers,
            shortages={**requests.shortages, **questions.shortages},
            errors=questions.errors,
            query_count=questions.query_count,
            excluded=questions.excluded,
            valid_pool=questions.valid_pool,
            answer_sizes=questions.answer_sizes,
            composition=questions.composition,
            final_shortages=_shortages(
                requests.requests, questions.questions, _FINAL_TARGETS
            ),
        )
        print(
            json.dumps(
                {
                    "requests": len(bundle.requests),
                    "questions": len(bundle.questions),
                    "shortages": bundle.shortages,
                    "errors": bundle.errors,
                    "excluded": bundle.excluded,
                    "valid_pool": bundle.valid_pool,
                    "answer_sizes": bundle.answer_sizes,
                    "composition": bundle.composition,
                    "final_shortages": bundle.final_shortages,
                },
                ensure_ascii=False,
            ),
            file=out,
        )
        qualifier = "(가정, 미실측)" if args.dry_run else "(실측)"
        print(
            f"모델 호출 0건, 그래프 읽기 전용 질의 {bundle.query_count}건{qualifier}",
            file=out,
        )
        if args.dry_run:
            return 0
        validate_set(bundle.requests, bundle.questions, bundle.answers, final=False)
        for filename, items in (
            ("requests_candidates.jsonl", bundle.requests),
            ("questions_candidates.jsonl", bundle.questions),
            ("answers_candidates.jsonl", bundle.answers),
        ):
            write_jsonl(candidate_dir / filename, items)
        write_review_sheet(bundle, candidate_dir)
        return 0
    except _ArgumentError:
        print("ARGUMENT_ERROR", file=out)
        return 2
    except EvalsetError as error:
        print(error.code, file=out)
        return 2
    except (OSError, UnicodeError):
        print("EVALSET_IO_ERROR", file=out)
        return 2
    except ValueError:
        print("EVALSET_ITEM_INVALID", file=out)
        return 2
    except Exception as error:  # noqa: BLE001 -- fixed codes, never external diagnostics
        print(_failure_code(error), file=out)
        return 2
    finally:
        if graph is not None:
            try:
                graph.close()
            except Exception:  # noqa: BLE001, S110 -- never expose driver diagnostics
                pass


if __name__ == "__main__":
    raise SystemExit(main())
