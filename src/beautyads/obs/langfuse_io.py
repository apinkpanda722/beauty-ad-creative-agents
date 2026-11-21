"""Ephemeral Langfuse-only IO; never part of the local trace schema."""

import json
import re
from dataclasses import dataclass
from datetime import datetime

REDACTED = "[가림]"
OMITTED = "(생략됨)"
CLIP_CHARS = 4000
_IMAGE_OMITTED = "(이미지 데이터 생략)"
_DATA_URL = re.compile(r"data:[^\s;,]+;base64,[A-Za-z0-9+/=_-]*", re.IGNORECASE)
_BASE64 = re.compile(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/=]{200,}(?![A-Za-z0-9+/=])")
_CREDENTIALS = re.compile(
    r"Authorization:[^\r\n]*|Bearer\s+\S+|sk-[A-Za-z0-9_-]{8,}"
    r"|AIza[0-9A-Za-z_-]{20,}|\beyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+",
    re.IGNORECASE,
)
_ASSIGNMENT = re.compile(
    r"\b(?=[A-Za-z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD))"
    r"([A-Za-z_][A-Za-z0-9_]*\s*=\s*)"
    r"""(?:\\".*?\\"|"[^"\r\n]*"|'[^'\r\n]*'|[^\s,;"']+)""",
    re.IGNORECASE,
)


def redact(text: str) -> str:
    text = _DATA_URL.sub(_IMAGE_OMITTED, text)
    text = _ASSIGNMENT.sub(lambda match: match.group(1) + REDACTED, text)
    text = _CREDENTIALS.sub(REDACTED, text)
    return _BASE64.sub(_IMAGE_OMITTED, text)


def clip(text: str, limit: int = CLIP_CHARS) -> str:
    return text if len(text) <= limit else text[:limit] + "\n" + OMITTED


def to_text(value) -> str:
    try:
        return (
            value
            if isinstance(value, str)
            else json.dumps(value, ensure_ascii=False, default=str)
        )
    except Exception:  # noqa: BLE001 -- never expose serialization diagnostics
        return "(직렬화 불가)"


@dataclass(frozen=True)
class Capture:
    purpose: str
    ended_at: datetime
    input: str
    output: str


@dataclass(frozen=True)
class RequestIO:
    message: str
    claim_choice: dict | None
    result: dict | None
    captures: tuple[Capture, ...]


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _rows(value):
    return value if isinstance(value, (list, tuple)) else []


def _select(value, names):
    source = _mapping(value)
    return {label: source.get(key) for key, label in names if key in source}


def _plan_summary(plan):
    return _select(
        plan,
        (
            ("title", "제목"),
            ("hook_text", "훅"),
            ("copy_lines", "카피"),
            ("claimed_efficacy", "주장 효능"),
            ("evidence_ids", "근거 ID"),
        ),
    )


def trace_input(io: RequestIO) -> dict:
    incoming = {"요청": io.message}
    if io.claim_choice is not None:
        incoming["효능 선택"] = _select(
            io.claim_choice,
            ((name, name) for name in ("mode", "claims", "requested_claim")),
        )
    return incoming


def trace_output(io: RequestIO) -> dict:
    result = _mapping(io.result)
    outgoing = _select(result, (("kind", "결과"),))
    if "plans" in result:
        outgoing["기획안"] = [
            _plan_summary(_mapping(item).get("plan"))
            for item in _rows(result.get("plans"))
            if isinstance(_mapping(item).get("plan"), dict)
        ]
    return outgoing


def stage_io(io: RequestIO) -> dict:
    result = _mapping(io.result)
    stages = {}
    supervisor = {
        **_select(result, (("intent", "의도"),)),
        **_select(
            result.get("brief"),
            (
                ("claim", "효능"),
                ("hook_type", "훅 유형"),
                ("angle", "소구"),
                ("format", "형식"),
            ),
        ),
    }
    if supervisor:
        stages["supervisor"] = {"output": supervisor}
    handoff = _mapping(result.get("handoff"))
    research = _select(handoff, (("conclusion", "결론"),))
    if "result_counts" in handoff:
        counts = [
            _select(
                row, ((name, name) for name in ("tool", "row_count", "shown_count"))
            )
            for row in _rows(handoff.get("result_counts"))
        ]
        research.update(
            {
                "도구": [row.get("tool") for row in counts if "tool" in row],
                "결과 건수": counts,
            }
        )
    if research:
        stages["research"] = {"output": research}
    ordinal = 0
    image_briefs = []
    for item in _rows(result.get("plans")):
        item = _mapping(item)
        plan = _mapping(item.get("plan"))
        attempts = _rows(item.get("attempts"))
        for index, attempt in enumerate(attempts):
            ordinal += 1
            if index == len(attempts) - 1 and plan:
                stages[f"planning #{ordinal}"] = {"output": _plan_summary(plan)}
            attempt = _mapping(attempt)
            evaluation = _select(
                attempt, (("final_passed", "통과"), ("checks_passed", "코드 검사"))
            )
            if "scores" in attempt:
                scores = _mapping(attempt.get("scores"))
                evaluation["점수"] = (
                    {
                        name: scores.get(name)
                        for name in ("differentiation", "fit")
                        if type(scores.get(name)) is int
                    }
                    if scores
                    else None
                )
            if "low_items" in attempt:
                evaluation["재검토 항목"] = [
                    name
                    for name in _rows(attempt.get("low_items"))
                    if name in ("differentiation", "fit")
                ]
            if evaluation:
                stages[f"evaluation #{ordinal}"] = {"output": evaluation}
        if "image_brief" in plan:
            image_briefs.append(plan.get("image_brief"))
    if image_briefs:
        stages["image"] = {"input": image_briefs[0]}
        for index, brief in enumerate(image_briefs, 1):
            stages[f"image #{index}"] = {"input": brief}
    return stages


def match_captures(calls, captures) -> dict[int, Capture]:
    matches, used = {}, set()
    for index, call in enumerate(calls):
        if call.ended_at is None:
            continue
        nearest, distance = None, None
        for position, capture in enumerate(captures):
            if position in used or capture.purpose != call.purpose:
                continue
            delta = abs((capture.ended_at - call.ended_at).total_seconds())
            if delta <= 5 and (distance is None or delta < distance):
                nearest, distance = position, delta
        if nearest is not None:
            used.add(nearest)
            matches[index] = captures[nearest]
    return matches
