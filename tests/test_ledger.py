"""Ledger behavior uses only explicitly injected temporary paths."""

import inspect
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from beautyads.obs.ledger import (
    CostCapExceeded,
    LedgerEntry,
    LedgerRead,
    append_entry,
    check_cap,
    provider_total,
    read_entries,
)


@pytest.fixture
def entry():
    return LedgerEntry(
        ts=datetime(2026, 11, 12, tzinfo=UTC),
        provider="gemini",
        model="response-model",
        requested_model="requested-model",
        purpose="analysis",
        input_tokens=100,
        output_tokens=20,
        thought_tokens=30,
        cached_tokens=40,
        cost_usd=0.25,
        cost_source="response_cost",
    )


def test_append_and_read_round_trip(tmp_path, entry):
    path = tmp_path / "nested" / "ledger.jsonl"
    append_entry(path, entry)
    append_entry(path, entry)
    result = read_entries(path)
    assert isinstance(result, LedgerRead)
    assert result.skipped_lines == 0
    assert [item.model_dump() for item in result.entries] == [entry.model_dump()] * 2
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2


def test_missing_file_is_empty_and_not_created(tmp_path):
    path = tmp_path / "missing" / "ledger.jsonl"
    assert read_entries(path) == LedgerRead([], 0)
    assert provider_total(path, "gemini") == 0.0
    assert not path.parent.exists()


def test_corrupt_lines_are_counted_and_missing_tokens_default_to_zero(tmp_path, entry):
    path = tmp_path / "ledger.jsonl"
    minimal = entry.model_dump(mode="json")
    token_fields = ("input_tokens", "output_tokens", "thought_tokens", "cached_tokens")
    for field in (*token_fields, "requested_model"):
        minimal.pop(field)
    malformed = [
        "{broken json",
        json.dumps({key: value for key, value in minimal.items() if key != "provider"}),
        json.dumps({key: value for key, value in minimal.items() if key != "cost_usd"}),
        "null",
        "[]",
        json.dumps({**minimal, "provider": "unknown"}),
        json.dumps({**minimal, "cost_usd": "invalid"}),
    ]
    path.write_text(
        "\n".join([entry.model_dump_json(), *malformed, json.dumps(minimal)]) + "\n",
        encoding="utf-8",
    )
    result = read_entries(path)
    assert result.skipped_lines == len(malformed)
    assert len(result.entries) == 2
    assert result.entries[0].model_dump() == entry.model_dump()
    for field in token_fields:
        assert getattr(result.entries[1], field) == 0
    assert result.entries[1].requested_model is None
    assert provider_total(path, "gemini") == pytest.approx(2 * entry.cost_usd)


@pytest.mark.parametrize("provider", ["gemini", "openai", "anthropic"])
def test_provider_totals_and_cap_boundaries(tmp_path, entry, provider):
    path = tmp_path / "ledger.jsonl"
    caps = {"gemini": 2.0, "openai": 3.0, "anthropic": 4.0}
    for name in caps:
        for _ in range(2):
            append_entry(path, entry.model_copy(update={"provider": name}))
    assert provider_total(path, provider) == 0.5
    check_cap(path, provider, caps)
    check_cap(path, provider, caps, additional_usd=caps[provider] - 0.75)
    for additional in (caps[provider] - 0.5, caps[provider]):
        with pytest.raises(CostCapExceeded) as caught:
            check_cap(path, provider, caps, additional_usd=additional)
        assert caught.value.provider == provider
        assert caught.value.total_usd == 0.5
        assert caught.value.cap_usd == caps[provider]
        assert caught.value.code == f"COST_CAP:{provider}"


@pytest.mark.parametrize("cost", [1.0, 1.5])
def test_existing_total_at_or_above_cap_is_rejected(tmp_path, entry, cost):
    path = tmp_path / "ledger.jsonl"
    append_entry(path, entry.model_copy(update={"cost_usd": cost}))
    with pytest.raises(CostCapExceeded):
        check_cap(path, "gemini", {"gemini": 1.0})


def test_zero_cap_blocks_missing_ledger_and_unknown_cap_is_rejected(tmp_path):
    path = tmp_path / "missing.jsonl"
    with pytest.raises(CostCapExceeded):
        check_cap(path, "gemini", {"gemini": 0.0})
    for provider, caps in (("unknown", {"gemini": 1.0}), ("openai", {})):
        with pytest.raises(ValueError):
            check_cap(path, provider, caps)
    assert not path.exists()


def test_concurrent_appends_preserve_every_complete_line(tmp_path, entry):
    path = tmp_path / "nested" / "ledger.jsonl"
    workers, per_worker = 8, 40

    def append_many(worker):
        for index in range(per_worker):
            append_entry(
                path, entry.model_copy(update={"purpose": f"worker-{worker}-{index}"})
            )

    with ThreadPoolExecutor(max_workers=workers) as executor:
        list(executor.map(append_many, range(workers)))
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == workers * per_worker
    assert all(isinstance(json.loads(line), dict) for line in lines)
    result = read_entries(path)
    assert result.skipped_lines == 0
    assert len(result.entries) == workers * per_worker
    assert {item.purpose for item in result.entries} == {
        f"worker-{worker}-{index}"
        for worker in range(workers)
        for index in range(per_worker)
    }


@pytest.mark.parametrize("field", ["prompt", "response", "headers", "unknown"])
def test_entry_rejects_unknown_fields(tmp_path, entry, field):
    with pytest.raises(ValidationError):
        LedgerEntry.model_validate({**entry.model_dump(), field: "excluded"})


def test_entry_requires_aware_timestamp_and_normalizes_to_utc(tmp_path, entry):
    with pytest.raises(ValidationError):
        LedgerEntry.model_validate({**entry.model_dump(), "ts": datetime(2026, 11, 12)})
    offset_time = datetime(2026, 11, 12, 9, tzinfo=timezone(timedelta(hours=9)))
    normalized = LedgerEntry.model_validate({**entry.model_dump(), "ts": offset_time})
    assert normalized.ts == entry.ts
    assert normalized.ts.utcoffset() == timedelta(0)


@pytest.mark.parametrize("field", ["purpose", "model", "cost_source"])
def test_entry_requires_call_metadata(tmp_path, entry, field):
    values = entry.model_dump()
    values.pop(field)
    with pytest.raises(ValidationError):
        LedgerEntry.model_validate(values)


def test_ledger_functions_have_no_default_path(tmp_path):
    for function in (append_entry, read_entries, provider_total, check_cap):
        parameter = inspect.signature(function).parameters["path"]
        assert parameter.default is inspect.Parameter.empty
    assert inspect.signature(check_cap).parameters["additional_usd"].kind == (
        inspect.Parameter.KEYWORD_ONLY
    )
