"""Request-local metadata only: no prompts, generated prose or diagnostics."""

import re
from collections import defaultdict
from datetime import UTC, datetime
from math import fsum, isfinite
from pathlib import Path
from threading import Lock
from typing import Annotated, Literal, NamedTuple
from uuid import uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
)

from beautyads.obs.ledger import LedgerEntry

_trace_lock = Lock()
# Supervisor's default decide budget. Custom budgets also appear in input_trims.
_DECIDE_MAX_CHARS = 2000
Token = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")]
DetailKey = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.*:|-]{1,120}$")]
Count = Annotated[int, Field(strict=True, ge=0)]


class _TraceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class TraceStep(_TraceModel):
    agent: Token
    phase: Token
    status: Token
    at: datetime | None = Field(default=None, exclude_if=lambda value: value is None)

    @field_validator("at")
    @classmethod
    def utc_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.utcoffset() is None:
            raise ValueError("at must include a timezone")
        return value.astimezone(UTC)


class TraceTool(_TraceModel):
    tool: Token
    row_count: Count = 0
    shown_count: Count = 0


class TraceAttempt(_TraceModel):
    attempt: Count = 0
    checks_passed: bool | None = None
    final_passed: bool | None = None
    scores: dict[Token, Annotated[int, Field(strict=True)]] | None = None
    failed_check_codes: list[Token] = Field(default_factory=list)
    cost_usd: float | None = None


class TraceAlignment(_TraceModel):
    compared: Count = 0
    same_count: Count = 0
    skipped: Count = 0


class TracePatternDistribution(_TraceModel):
    axis: Literal["hook_type", "angle", "format"]
    total: Count | None = None
    top_share: Annotated[float, Field(ge=0)] | None = None
    second_share: Annotated[float, Field(ge=0)] | None = None


class TraceComposedContrast(_TraceModel):
    contrast_adjusted: Annotated[bool, Field(strict=True)]
    min_contrast: Annotated[float, Field(strict=True, ge=0)] | None


class TracePlan(_TraceModel):
    status: Token | None = None
    rework_count: Count = 0
    unknown_count: Count = 0
    efficacy_status: dict[Token, Token] = Field(default_factory=dict)
    attempts: list[TraceAttempt] = Field(default_factory=list)
    alignment: TraceAlignment = Field(default_factory=TraceAlignment)
    composed_contrast: TraceComposedContrast | None = None


class TraceInputTrim(_TraceModel):
    field: Literal["message", "evidence_ids", "aggregates"]
    kept: Count
    total: Count


class TraceLimitDetail(_TraceModel):
    kind: Token
    cap: Token

    @field_validator("cap", mode="before")
    @classmethod
    def safe_cap(cls, value):
        return (
            value
            if isinstance(value, str)
            and re.fullmatch(
                r"(?:provider|purpose):[a-z_]{1,32}|request:(?:text|steps|plans)|unknown",
                value,
            )
            else "unknown"
        )


class TraceCall(_TraceModel):
    purpose: Token
    model: Token
    reasoning_effort: Token | None = None
    input_tokens: Count = 0
    output_tokens: Count = 0
    thought_tokens: Count = 0
    cached_tokens: Count = 0
    cost_usd: float
    cost_source: Literal["response_cost", "computed", "missing", "price_table"]
    duration_ms: Count | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    ended_at: datetime | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @field_validator("ended_at")
    @classmethod
    def utc_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.utcoffset() is None:
            raise ValueError("ended_at must include a timezone")
        return value.astimezone(UTC)


class TraceStructured(_TraceModel):
    calls: Count = 0
    failed_after_retry: Count = 0
    first_attempt_failures: dict[Token, Count] = Field(default_factory=dict)
    # Keep legacy successful/empty trace serialization unchanged.
    first_attempt_failure_details: dict[DetailKey, Count] = Field(
        default_factory=dict, exclude_if=lambda value: not value
    )


class TraceEfficacyUnavailable(_TraceModel):
    reason: Literal["failed", "no_product"]
    brand: Annotated[str, StringConstraints(max_length=200)] | None
    product_name: Annotated[str, StringConstraints(max_length=200)] | None


class TraceRecord(_TraceModel):
    trace_id: str = Field(
        default_factory=lambda: uuid4().hex, pattern=r"^[0-9a-f]{32}$"
    )
    tenant_id: Token
    started_at: datetime
    duration_ms: Count
    outcome: Literal["ok", "error"]
    error_class: str | None = None
    error_code: str | None = None
    kind: (
        Literal[
            "research",
            "plan",
            "out_of_scope",
            "no_evidence",
            "failed",
            "needs_clarification",
            "claim_choice_invalid",
            "efficacy_unavailable",
        ]
        | None
    ) = None
    intent: Literal["pattern", "relation", "plan", "boundary"] | None = None
    efficacy_unavailable: TraceEfficacyUnavailable | None = None
    message_chars: Count
    message_trimmed: bool = False
    steps: list[TraceStep] = Field(default_factory=list)
    tools: list[TraceTool] = Field(default_factory=list)
    plans: list[TracePlan] = Field(default_factory=list)
    pattern_distribution: list[TracePatternDistribution] = Field(default_factory=list)
    prompt_versions: dict[Literal["planning", "evaluation"], str] = Field(
        default_factory=dict
    )
    limit_hit: bool = False
    limit_kinds: list[Token] = Field(default_factory=list)
    limit_detail: list[TraceLimitDetail] = Field(default_factory=list)
    input_trims: list[TraceInputTrim] = Field(default_factory=list)
    aggregates_removed_count: Count = 0
    text_spent_usd: float | None = None
    calls: list[TraceCall] = Field(default_factory=list)
    cost_total_usd: float = 0.0
    cost_by_purpose: dict[Token, float] = Field(default_factory=dict)
    structured: dict[Token, TraceStructured] = Field(default_factory=dict)

    @field_validator("prompt_versions", mode="before")
    @classmethod
    def safe_prompt_versions(cls, value):
        return (
            {
                key: version
                for key, version in value.items()
                if key in {"planning", "evaluation"}
                and isinstance(version, str)
                and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{1,6}", version)
            }
            if isinstance(value, dict)
            else {}
        )

    @field_validator("error_class", "error_code", mode="before")
    @classmethod
    def safe_error_identifier(cls, value):
        return (
            value
            if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_:]{1,64}", value)
            else None
        )

    @field_validator("started_at")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("started_at must include a timezone")
        return value.astimezone(UTC)


class TraceRead(NamedTuple):
    records: list[TraceRecord]
    skipped_lines: int


def _project(model, value):
    return {key: value[key] for key in model.model_fields if key in value}


def build_trace(
    *,
    tenant_id: str,
    started_at: datetime,
    duration_ms: int,
    message: str,
    result: dict | None,
    failure: dict | None,
    ledger_entries: list[LedgerEntry],
    structured: dict,
) -> TraceRecord:
    """Project explicit metadata fields; never traverse source or model bodies."""
    result = result or {}
    plans = []
    for plan in result.get("plans", []):
        image = plan.get("image")
        composed = image.get("composed") if isinstance(image, dict) else None
        composed_contrast = None
        if (
            isinstance(composed, dict)
            and type(composed.get("contrast_adjusted")) is bool
        ):
            contrast = composed.get("min_contrast")
            if contrast is None or (
                type(contrast) in (int, float) and isfinite(contrast) and contrast >= 0
            ):
                composed_contrast = TraceComposedContrast(
                    contrast_adjusted=composed["contrast_adjusted"],
                    min_contrast=float(contrast) if contrast is not None else None,
                )
        alignment = plan.get("pattern_alignment")
        alignment = alignment if isinstance(alignment, dict) else {}
        attempts = []
        for attempt in plan.get("attempts", []):
            scores = attempt.get("scores")
            attempts.append(
                TraceAttempt(
                    **{
                        **_project(TraceAttempt, attempt),
                        "scores": {
                            key: value
                            for key, value in scores.items()
                            if type(value) is int
                        }
                        if isinstance(scores, dict)
                        else None,
                    }
                )
            )
        plans.append(
            TracePlan(
                **{
                    **_project(TracePlan, plan),
                    "composed_contrast": composed_contrast,
                    "efficacy_status": {
                        key: value
                        for key, value in plan.get("efficacy_status", {}).items()
                        if isinstance(value, str)
                    },
                    "attempts": attempts,
                    "alignment": {
                        key: value
                        for key, value in alignment.items()
                        if key in TraceAlignment.model_fields
                        and type(value) is int
                        and value >= 0
                    },
                }
            )
        )
    calls = [
        TraceCall(
            **_project(TraceCall, entry.model_dump()),
            ended_at=entry.ts if entry.duration_ms is not None else None,
        )
        for entry in ledger_entries
    ]
    by_purpose = defaultdict(list)
    for call in calls:
        by_purpose[call.purpose].append(call.cost_usd)
    trims = [
        TraceInputTrim(**_project(TraceInputTrim, trim))
        for trim in result.get("input_trims", [])
    ]
    return TraceRecord(
        tenant_id=tenant_id,
        started_at=started_at,
        duration_ms=duration_ms,
        outcome="error" if failure is not None else "ok",
        error_class=failure.get("class") if failure is not None else None,
        error_code=failure.get("code") if failure is not None else None,
        kind=result.get("kind"),
        efficacy_unavailable=TraceEfficacyUnavailable(
            reason=result["efficacy_unavailable"]["reason"],
            brand=result.get("product_display", {}).get("brand"),
            product_name=result.get("product_display", {}).get("product_name"),
        )
        if result.get("kind") == "efficacy_unavailable"
        else None,
        intent=result.get("intent"),
        message_chars=len(message),
        message_trimmed=len(message) > _DECIDE_MAX_CHARS
        or any(trim.field == "message" and trim.kept < trim.total for trim in trims),
        steps=[
            TraceStep(**_project(TraceStep, step)) for step in result.get("steps", [])
        ],
        tools=[
            TraceTool(**_project(TraceTool, tool))
            for tool in result.get("handoff", {}).get("result_counts", [])
        ],
        plans=plans,
        pattern_distribution=[
            TracePatternDistribution(**_project(TracePatternDistribution, row))
            for row in result.get("pattern_distribution", [])
        ],
        prompt_versions=result.get("prompt_versions", {}),
        limit_hit=result.get("limit_hit", False),
        limit_kinds=result.get("limit_kinds", []),
        limit_detail=[
            TraceLimitDetail(**_project(TraceLimitDetail, detail))
            for detail in result.get("limit_detail", [])
        ],
        input_trims=trims,
        aggregates_removed_count=len(result.get("aggregates_removed", [])),
        text_spent_usd=result.get("limits", {}).get("text_spent_usd"),
        calls=calls,
        cost_total_usd=fsum(call.cost_usd for call in calls),
        cost_by_purpose={purpose: fsum(costs) for purpose, costs in by_purpose.items()},
        structured={
            model: TraceStructured(**_project(TraceStructured, stats))
            for model, stats in structured.items()
        },
    )


def append_trace(path: Path, record: TraceRecord) -> None:
    """Append one serialized line in one write, across local threads."""
    line = record.model_dump_json() + "\n"
    with _trace_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(line)


def read_traces(path: Path) -> TraceRead:
    """Ignore malformed lines without emitting their contents or errors."""
    records, skipped_lines = [], 0
    with _trace_lock:
        try:
            stream = path.open(encoding="utf-8")
        except FileNotFoundError:
            return TraceRead([], 0)
        with stream:
            for line in stream:
                try:
                    records.append(TraceRecord.model_validate_json(line))
                except ValidationError:
                    skipped_lines += 1
    return TraceRead(records, skipped_lines)


def summarize_by_tenant(records: list[TraceRecord]) -> dict[str, dict]:
    """Aggregate observed calls and costs independently for each tenant."""
    grouped = defaultdict(list)
    for record in records:
        grouped[record.tenant_id].append(record)
    summaries = {}
    for tenant, traces in grouped.items():
        purposes = defaultdict(list)
        durations = defaultdict(int)
        failures = defaultdict(int)
        details = defaultdict(int)
        structured_calls = 0
        distribution = []
        for trace in traces:
            for call in trace.calls:
                if call.duration_ms is not None:
                    durations[call.purpose] += call.duration_ms
            distribution.extend(row.model_dump() for row in trace.pattern_distribution)
            for purpose, cost in trace.cost_by_purpose.items():
                purposes[purpose].append(cost)
            for stats in trace.structured.values():
                structured_calls += stats.calls
                for kind, count in stats.first_attempt_failures.items():
                    failures[kind] += count
                for key, count in stats.first_attempt_failure_details.items():
                    details[key] += count
        summaries[tenant] = {
            "requests": len(traces),
            "errors": sum(trace.outcome == "error" for trace in traces),
            "calls": sum(len(trace.calls) for trace in traces),
            "cost_usd": fsum(trace.cost_total_usd for trace in traces),
            "cost_by_purpose": {
                purpose: fsum(costs) for purpose, costs in purposes.items()
            },
            "first_attempt_failures": dict(failures),
            "structured_calls": structured_calls,
            **({"duration_ms_by_purpose": dict(durations)} if durations else {}),
            **({"pattern_distribution": distribution} if distribution else {}),
            **({"first_attempt_failure_details": dict(details)} if details else {}),
        }
    return summaries
