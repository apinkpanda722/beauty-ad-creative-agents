"""Closed request routing and pure budgets for 텍스트 모델 비용, 이미지 제외."""

import math
import re
from collections.abc import Mapping
from copy import deepcopy
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from beautyads.domain.labels import Angle, Category, Claim, Format, HookType
from beautyads.domain.skin import SkinConcern

AGGREGATE_UNVERIFIED_PREFIX = "aggregate:"
AGGREGATES_LABEL = "모델 작성값, 검증되지 않음"
OUT_OF_SCOPE_TEXT = "지원 범위 밖이거나 요청 조건을 판단할 수 없다."
NO_EVIDENCE_TEXT = "조건에 맞는 근거가 없다. 근거를 지어내지 않는다."
LIMIT_REACHED_TEXT = "요청 한도에 도달해 현재까지의 결과를 미완료로 반환한다."
# 잠정값, 사용자 승인 전. 이유·날짜는 docs/PROMPT_CHANGELOG.md
MIN_DOMINANT_SHARE = 0.4
THIN_POOL_MAX = 10
THIN_POOL_NOTE = "근거 소재가 {n}건으로 얇아 차별성 판단에 한계가 있다"
DESIGN_IMAGE_DISCLAIMER = "생성 시안은 참고용이며 라벨 글자가 부정확할 수 있다"
CLARIFY_REQUESTED_TEXT = "요청하신 '{requested}' 효능은 이 제품의 성분·인증으로 근거가 확인되지 않았습니다. 확인된 효능은 {available}입니다. 어떻게 진행할까요?"
CLARIFY_REQUESTED_NO_CONFIRMED_TEXT = "요청하신 '{requested}' 효능은 이 제품의 성분·인증으로 근거가 확인되지 않았습니다. 이 제품에서 근거가 확인된 효능이 없습니다. 어떻게 진행할까요?"
CLARIFY_UNSPECIFIED_TEXT = "효능을 지정하지 않으셨습니다. 이 제품에서 근거가 확인된 효능은 {available}입니다. 어떤 효능을 강조할까요?"
OPTION_KEEP_REQUESTED = (
    "요청하신 '{requested}'로 진행 (효능을 단정하는 표현은 제한됩니다)"
)
OPTION_SELECT_CONFIRMED = "확인된 효능 중에서 선택"
OPTION_SELECT_ONE = "한 가지 효능 선택"
OPTION_SELECT_MANY = "여러 효능 선택"
OPTION_NONE = "효능 강조 없이 제품 홍보"
EFFICACY_NOTICE_TEXT = {
    "lookup_unconfirmed": "효능 근거를 확인하지 못해 효능 강조 없이 작성했습니다.",
    "none_confirmed": "이 제품에서 근거가 확인된 효능이 없어 효능 강조 없이 작성했습니다.",
}


class ClarifyReason(StrEnum):
    requested_not_confirmed = "requested_not_confirmed"
    no_claim_requested = "no_claim_requested"


class ClarifyOption(StrEnum):
    keep_requested = "keep_requested"
    select_confirmed = "select_confirmed"
    select_one = "select_one"
    select_many = "select_many"
    none = "none"


class ClaimChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["selected", "keep_requested", "none"]
    claims: list[Claim] = Field(default_factory=list)
    requested_claim: Claim | None = None

    @model_validator(mode="after")
    def validate_choice(self) -> "ClaimChoice":
        if Claim.other in self.claims or self.requested_claim == Claim.other:
            raise ValueError("CLAIM_CHOICE_OTHER")
        if len(self.claims) != len(set(self.claims)):
            raise ValueError("CLAIM_CHOICE_DUPLICATE")
        if self.mode == "selected" and not self.claims:
            raise ValueError("CLAIM_CHOICE_SELECTION_EMPTY")
        if self.mode == "keep_requested" and self.requested_claim is None:
            raise ValueError("CLAIM_CHOICE_REQUESTED_MISSING")
        if self.mode != "selected" and self.claims:
            raise ValueError("CLAIM_CHOICE_CLAIMS_UNEXPECTED")
        return self


def resolve_claim_policy(
    *, requested: str | None, available: list[str], status: str, choice: dict | None
) -> dict:
    """Resolve confirmed efficacy and an optional marketer choice without I/O."""
    if requested == Claim.other:
        requested = None
    result = {
        "action": "proceed",
        "claim": None,
        "claim_choice": {},
        "notice": None,
        "clarification": {},
    }
    no_claim = {"mode": "none", "claims": [], "requested_claim": None}
    if status != "ok":
        result.update(
            claim=requested,
            claim_choice={
                "mode": "keep_requested",
                "claims": [],
                "requested_claim": requested,
            }
            if requested
            else no_claim,
            notice="lookup_unconfirmed",
        )
    elif choice is not None:
        mode = choice["mode"]
        if mode == "selected":
            if not all(claim in available for claim in choice["claims"]):
                result["action"] = "invalid"
            else:
                result.update(claim=choice["claims"][0], claim_choice=deepcopy(choice))
        elif mode == "keep_requested":
            if requested is None:
                result["action"] = "invalid"
            else:
                result.update(claim=requested, claim_choice=deepcopy(choice))
        else:
            result["claim_choice"] = no_claim
    elif requested is not None and requested in available:
        result.update(
            claim=requested,
            claim_choice={
                "mode": "selected",
                "claims": [requested],
                "requested_claim": requested,
            },
        )
    elif requested is not None or available:
        options = (
            [ClarifyOption.keep_requested]
            + ([ClarifyOption.select_confirmed] if available else [])
            + [ClarifyOption.none]
            if requested is not None
            else [
                ClarifyOption.select_one,
                ClarifyOption.select_many,
                ClarifyOption.none,
            ]
        )
        result.update(
            action="clarify",
            clarification={
                "reason": (
                    ClarifyReason.requested_not_confirmed
                    if requested is not None
                    else ClarifyReason.no_claim_requested
                ).value,
                "requested_claim": requested,
                "available_efficacy": list(available),
                "available_status": "ok",
                "options": [option.value for option in options],
            },
        )
    else:
        result.update(claim_choice=no_claim, notice="none_confirmed")
    return result


def clarification_texts(clarification: dict, display: Mapping[str, str]) -> dict:
    """Render centralized copy using caller-owned efficacy display names."""
    requested = clarification.get("requested_claim")
    requested_name = display.get(requested, requested)
    available = clarification.get("available_efficacy", [])
    template = (
        CLARIFY_UNSPECIFIED_TEXT
        if clarification.get("reason") == ClarifyReason.no_claim_requested
        else CLARIFY_REQUESTED_TEXT
        if available
        else CLARIFY_REQUESTED_NO_CONFIRMED_TEXT
    )
    labels = {
        ClarifyOption.keep_requested.value: OPTION_KEEP_REQUESTED,
        ClarifyOption.select_confirmed.value: OPTION_SELECT_CONFIRMED,
        ClarifyOption.select_one.value: OPTION_SELECT_ONE,
        ClarifyOption.select_many.value: OPTION_SELECT_MANY,
        ClarifyOption.none.value: OPTION_NONE,
    }
    return {
        "text": template.format(
            requested=requested_name,
            available=", ".join(display.get(value, value) for value in available),
        ),
        "options": [
            {"id": option, "label": labels[option].format(requested=requested_name)}
            for option in clarification.get("options", [])
        ],
    }


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


def pattern_context(
    tool_outputs: list[dict], evidence_ids: list[str], *, fixed_axes=()
) -> dict:
    """Describe observed populations and dominant axes without judging a plan.

    Axis inference, additive counts and repeated totals follow pattern_alignment.
    Tied values all rank first; the second share is the next distinct rank.
    Distribution is observation only, independent of the provisional threshold.
    Brief-fixed axes remain observable but are excluded from classification.
    """
    closed = {
        "hook_type": {item.value for item in HookType},
        "angle": {item.value for item in Angle},
        "format": {item.value for item in Format},
    }
    fixed_axes = set(fixed_axes)
    if fixed_axes.difference(closed):
        raise ValueError("PATTERN_FIXED_AXES_INVALID")
    counts = {axis: {} for axis in closed}
    totals = dict.fromkeys(closed, None)
    populations = []
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
            continue
        values = {row.get("value") for row in rows}
        matches = [axis for axis, allowed in closed.items() if values <= allowed]
        if len(matches) != 1 or not all(
            type(row.get("creatives")) is int and row.get("creatives") >= 0
            for row in rows
        ):
            continue
        axis = matches[0]
        for row in rows:
            value = row.get("value")
            counts[axis][value] = counts[axis].get(value, 0) + row.get("creatives")
        total = rows[0].get("total")
        if type(total) is int and total >= 0:
            totals[axis] = (totals[axis] or 0) + total
            populations.append(total)
    dominant_axes, weak_axes, distribution = [], [], []
    for axis, observed in counts.items():
        if not observed:
            continue
        ranks = sorted(set(observed.values()), reverse=True)
        dominant = sorted(
            value for value, count in observed.items() if count == ranks[0]
        )
        total = totals[axis]
        top_share = ranks[0] / total if total else None
        share = sum(observed[value] for value in dominant) / total if total else None
        if axis not in fixed_axes:
            if share is not None and share >= MIN_DOMINANT_SHARE:
                dominant_axes.append({"axis": axis, "values": dominant, "share": share})
            else:
                weak_axes.append(axis)
        distribution.append(
            {
                "axis": axis,
                "total": total,
                "top_share": top_share,
                "second_share": ranks[1] / total if len(ranks) > 1 and total else None,
                "top_value": dominant[0],
            }
        )
    compared = any(counts.values())
    pool_size = (
        max(populations)
        if populations
        else None
        if compared
        else len(set(evidence_ids))
    )
    context = {
        "pool_size": pool_size,
        "pool_basis": "axis_total" if compared else "evidence_ids",
        "thin_pool": pool_size is not None and pool_size < THIN_POOL_MAX,
        "min_dominant_share": MIN_DOMINANT_SHARE,
        "thin_pool_max": THIN_POOL_MAX,
        "dominant_axes": dominant_axes,
        "weak_axes": weak_axes,
        "distribution": distribution,
    }
    if fixed_axes:
        context["fixed_axes"] = sorted(fixed_axes)
    return context


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
