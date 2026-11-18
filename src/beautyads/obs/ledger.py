"""Append-only JSONL costs; every operation requires an explicit ledger path."""

from collections.abc import Mapping
from datetime import UTC, datetime
from math import fsum
from pathlib import Path
from threading import Lock
from typing import Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

Provider = Literal["gemini", "openai", "anthropic"]
_ledger_lock = Lock()


class LedgerEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    ts: datetime
    provider: Provider
    model: str
    requested_model: str | None = None
    purpose: str
    input_tokens: int = 0
    output_tokens: int = 0
    thought_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: float
    cost_source: Literal["response_cost", "computed", "missing", "price_table"]
    reasoning_effort: str | None = None

    @field_validator("ts")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("ts must include a timezone")
        return value.astimezone(UTC)


class LedgerRead(NamedTuple):
    entries: list[LedgerEntry]
    skipped_lines: int


def append_entry(path: Path, entry: LedgerEntry) -> None:
    """Serialize once and append in one write, guarded across local threads."""
    line = entry.model_dump_json() + "\n"
    with _ledger_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as ledger:
            ledger.write(line)


def read_entries(path: Path) -> LedgerRead:
    """Skip malformed records without exposing their potentially unsafe contents."""
    entries = []
    skipped_lines = 0
    with _ledger_lock:
        try:
            ledger = path.open(encoding="utf-8")
        except FileNotFoundError:
            return LedgerRead([], 0)
        with ledger:
            for line in ledger:
                try:
                    entries.append(LedgerEntry.model_validate_json(line))
                except ValidationError:
                    skipped_lines += 1
    return LedgerRead(entries, skipped_lines)


def provider_total(path: Path, provider: str) -> float:
    return fsum(
        entry.cost_usd
        for entry in read_entries(path).entries
        if entry.provider == provider
    )


class CostCapExceeded(Exception):
    """The current spend plus the proposed cost has reached the supplied cap."""

    def __init__(self, provider: str, total_usd: float, cap_usd: float):
        self.provider = provider
        self.total_usd = total_usd
        self.cap_usd = cap_usd
        self.code = f"COST_CAP:{provider}"
        super().__init__(self.code)


def check_cap(
    path: Path,
    provider: str,
    caps: Mapping[str, float],
    *,
    additional_usd: float = 0.0,
) -> None:
    if provider not in caps:
        raise ValueError(f"Unknown provider: {provider}")
    cap = caps[provider]
    total = provider_total(path, provider)
    if total + additional_usd >= cap:
        raise CostCapExceeded(provider, total, cap)


def purpose_total(path: Path, prefix: str) -> float:
    return fsum(
        entry.cost_usd
        for entry in read_entries(path).entries
        if entry.purpose == prefix or entry.purpose.startswith(prefix + "-")
    )


def check_purpose_cap(
    path: Path, prefix: str, cap: float, *, additional_usd: float = 0.0
) -> None:
    total = purpose_total(path, prefix)
    if total + additional_usd >= cap:
        raise CostCapExceeded(f"purpose:{prefix}", total, cap)


def ledger_total(path: Path, *, exclude_purpose_prefix: str | None = None) -> float:
    """Sum every provider, optionally excluding one exact purpose family."""
    return fsum(
        entry.cost_usd
        for entry in read_entries(path).entries
        if exclude_purpose_prefix is None
        or not (
            entry.purpose == exclude_purpose_prefix
            or entry.purpose.startswith(exclude_purpose_prefix + "-")
        )
    )
