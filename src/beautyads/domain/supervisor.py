"""Closed request routing and pure budgets for 텍스트 모델 비용, 이미지 제외."""

import math
import re
from copy import deepcopy
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from beautyads.domain.labels import Angle, Category, Claim, Format, HookType
from beautyads.domain.skin import SkinConcern

AGGREGATE_UNVERIFIED_PREFIX = "aggregate:"
AGGREGATES_LABEL = "모델 작성값, 검증되지 않음"
OUT_OF_SCOPE_TEXT = "지원 범위 밖이거나 요청 조건을 판단할 수 없다."
NO_EVIDENCE_TEXT = "조건에 맞는 근거가 없다. 근거를 지어내지 않는다."
LIMIT_REACHED_TEXT = "요청 한도에 도달해 현재까지의 결과를 미완료로 반환한다."


class Intent(StrEnum):
    pattern = "pattern"
    relation = "relation"
    plan = "plan"
    boundary = "boundary"


class SupervisorDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Intent
    category: (
        Literal[Category.mask_pack, Category.serum_ampoule, Category.sun_care] | None
    )
    claim: Claim | None
    hook_type: HookType | None
    angle: Angle | None
    format: Format | None
    skin_concern: SkinConcern | None
    plan_count: Literal[1, 2, 3]
    goal: str


class RequestLimits(BaseModel):
    """Request cap: 텍스트 모델 비용, 이미지 제외; image purpose cap stays separate.

    6d preregistration §8: terra low $0.0048/call, sonnet $0.0063–0.0102/
    attempt. $0.30 accommodates up to three plans with three evaluations each.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_text_cost_usd: float = Field(default=0.30, ge=0, allow_inf_nan=False)
    max_plans: int = Field(default=3, ge=1, le=3)
    max_reworks: int = Field(default=2, ge=0, le=2)
    decide_max_chars: int = Field(default=2000, ge=0)
    handoff_max_evidence_ids: int = Field(default=30, ge=0)
    handoff_max_aggregates: int = Field(default=20, ge=0)
    # Node execution budget; recursion_limit is only a larger safety net.
    max_steps: int = Field(default=8, ge=0)


def cost_exceeded(text_spent_usd: float, limits: RequestLimits) -> bool:
    """Compare only 텍스트 모델 비용, 이미지 제외, failing closed on nonfinite cost."""
    return (
        not math.isfinite(text_spent_usd) or text_spent_usd >= limits.max_text_cost_usd
    )


def trim_message(message: str, limits: RequestLimits) -> tuple[str, bool]:
    return message[: limits.decide_max_chars], len(message) > limits.decide_max_chars


def trim_handoff(handoff: dict, limits: RequestLimits) -> tuple[dict, list[dict]]:
    bounded, trims = deepcopy(handoff), []
    for field, cap in (
        ("evidence_ids", limits.handoff_max_evidence_ids),
        ("aggregates", limits.handoff_max_aggregates),
    ):
        value = bounded.get(field, {} if field == "aggregates" else [])
        total = len(value)
        if total > cap:
            bounded[field] = (
                dict(list(value.items())[:cap])
                if isinstance(value, dict)
                else value[:cap]
            )
            trims.append({"field": field, "kept": cap, "total": total})
    return bounded, trims


# Accept grouped thousands as one token, then remove grouping commas.
_NUMBER = re.compile(r"-?\d+(?:,\d{3})*(?:[.,]\d+)?")


def _number(token: str) -> float:
    return float(token.replace(",", ""))


def numbers_in_results(values) -> set[float]:
    """Collect observed counts/row numbers, never prose, dates, IDs or UI data."""
    allowed = set()

    def collect(value):
        if type(value) in (int, float):
            try:
                number = float(value)
            except OverflowError:
                return
            if math.isfinite(number):
                allowed.add(number)
        elif isinstance(value, str) and _NUMBER.fullmatch(value.strip()):
            number = _number(value.strip())
            if math.isfinite(number):
                allowed.add(number)
        elif isinstance(value, dict):
            for item in value.values():
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    for result in values:
        if not isinstance(result, dict):
            continue
        collect(result.get("row_count"))
        collect(result.get("shown_count"))
        ids = result.get("evidence_ids")
        if isinstance(ids, list):
            collect(len(ids))
        collect(result.get("top_rows"))
    return allowed


def verify_aggregates(
    aggregates: dict[str, str], allowed: set[float]
) -> tuple[dict[str, str], list[str]]:
    """Set membership only: do not derive sums, ratios or other new numbers."""
    verified, unresolved = {}, []
    for name, value in aggregates.items():
        tokens = _NUMBER.findall(value)
        if any(
            not any(
                math.isclose(_number(token), number, rel_tol=0, abs_tol=1e-9)
                for number in allowed
            )
            for token in tokens
        ):
            unresolved.append(
                f"{AGGREGATE_UNVERIFIED_PREFIX}{name}: 도구 출력에 없는 수치"
            )
        else:
            verified[name] = value
    return verified, unresolved


def pattern_alignment(plan: dict, tool_outputs: list[dict]) -> dict:
    """Report agreement with observed dominant patterns; never decide plan quality.

    Infer the axis from every value in one output, including shared ``other``.
    A query repeats its population total on each row, so count it once per
    output. Separate outputs contribute their counts and populations additively.
    """
    closed = {
        "hook_type": {item.value for item in HookType},
        "angle": {item.value for item in Angle},
        "format": {item.value for item in Format},
    }
    counts = {axis: {} for axis in closed}
    totals = dict.fromkeys(closed, 0)
    skipped = 0
    for output in tool_outputs:
        if (
            not isinstance(output, dict)
            or output.get("tool") != "compare_axis_by_category"
        ):
            continue
        rows = output.get("rows")
        if (
            not isinstance(rows, list)
            or not rows
            or not all(
                isinstance(row, dict) and isinstance(row.get("value"), str)
                for row in rows
            )
        ):
            skipped += 1
            continue
        values = {row.get("value") for row in rows}
        matches = [axis for axis, allowed in closed.items() if values <= allowed]
        if len(matches) != 1 or not all(
            type(row.get("creatives")) is int and row.get("creatives") >= 0
            for row in rows
        ):
            skipped += 1
            continue
        axis = matches[0]
        for row in rows:
            value = row.get("value")
            counts[axis][value] = counts[axis].get(value, 0) + row.get("creatives")
        total = rows[0].get("total")
        if type(total) is int and total >= 0:
            totals[axis] += total
    axes = {}
    for axis, observed in counts.items():
        value = plan.get(axis)
        value = value if isinstance(value, str) else None
        dominant = sorted(
            key for key, count in observed.items() if count == max(observed.values())
        )
        axes[axis] = {
            "plan": value,
            "dominant": dominant,
            "same": value in dominant if observed else None,
            "share": observed[value] / totals[axis]
            if value in observed and totals[axis] > 0
            else None,
        }
    return {
        "axes": axes,
        "compared": sum(item["same"] is not None for item in axes.values()),
        "same_count": sum(item["same"] is True for item in axes.values()),
        "skipped": skipped,
    }
