"""Pinned prices and usage accounting, without model calls."""

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from beautyads.llm.prices import (
    PRICE_TABLE_CHECKED_ON,
    PriceUnknown,
    compute_cost,
    price_for,
    resolve_cost,
)

FIXTURES = Path(__file__).parent / "fixtures" / "contracts"
MODELS = ("gpt-6-luna", "gpt-6.1-terra", "claude-haiku-5-5", "claude-sonnet-5-5")


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("model", MODELS)
def test_prices_are_frozen_dated_and_sourced(model):
    price = price_for(model)
    assert price.model == model
    assert PRICE_TABLE_CHECKED_ON == "2026-11-17"
    assert price.source_url == (
        "https://developers.openai.com/api/docs/pricing"
        if price.provider == "openai"
        else "https://platform.claude.com/docs/en/about-claude/pricing"
    )
    assert price_for(f"{price.provider}/{model}") == price
    with pytest.raises(FrozenInstanceError):
        price.input = 0


@pytest.mark.parametrize(
    ("model", "short", "long"),
    [
        (MODELS[0], 0.236, 0.261),
        (MODELS[1], 2.355, 2.605),
        (MODELS[2], 1.18, 1.255),
        (MODELS[3], 4.71, 5.01),
    ],
)
def test_exact_cost_with_disjoint_synthetic_tokens(model, short, long):
    # 100k uncached + 100k read + 200k write + 400k output.
    args = {
        "input_tokens": 100_000,
        "cache_read_tokens": 100_000,
        "cache_write_tokens": 200_000,
        "output_tokens": 400_000,
    }
    # Haiku's total input includes caches and exceeds the tier boundary.
    assert compute_cost(model, **args) == short
    assert compute_cost(model, **args, cache_write_long=True) == long


@pytest.mark.parametrize("tokens", [100_000, 100_001])
def test_haiku_tier_boundary(tokens):
    price = price_for("claude-haiku-5-5")
    assert price.tier_threshold_tokens == 100_000
    assert price.tier_over.output == 2.5
    expected = (
        tokens * (0.1 if tokens == 100_000 else 0.5)
        + 10 * (0.5 if tokens == 100_000 else 2.5)
    ) / 1_000_000
    assert compute_cost(price.model, input_tokens=tokens, output_tokens=10) == expected


PROBE = load("litellm_openai_anthropic_probe.json").get("results")
MEASURED = [
    (name, item)
    for name, item in PROBE.items()
    if isinstance(item, dict)
    and (item.get("response") or {}).get("model") in (MODELS[0], MODELS[2])
    and (item.get("hidden") or {}).get("response_cost", 0) is not None
    and (item.get("hidden") or {}).get("response_cost", 0) > 0
]


@pytest.mark.parametrize(("name", "item"), MEASURED, ids=[name for name, _ in MEASURED])
def test_measured_luna_haiku_prices_including_cache(name, item):
    raw = item.get("response")
    usage = raw.get("usage")
    details = usage.get("prompt_tokens_details") or {}
    read = usage.get("cache_read_input_tokens", details.get("cached_tokens", 0)) or 0
    write = usage.get("cache_creation_input_tokens", 0) or 0
    # LiteLLM's normalized prompt_tokens includes both cache categories.
    cost = compute_cost(
        raw.get("model"),
        input_tokens=usage.get("prompt_tokens", 0) - read - write,
        output_tokens=usage.get("completion_tokens", 0),
        cache_read_tokens=read,
        cache_write_tokens=write,
    )
    measured = item.get("hidden").get("response_cost")
    assert cost == pytest.approx(measured, rel=1e-6, abs=0)
    assert resolve_cost(raw.get("model"), response_cost=None, usage=usage) == (
        cost,
        "price_table",
    )


@pytest.mark.parametrize("cost", [None, 0.0, -1.0])
def test_fallback_and_unknown(cost):
    usage = {"prompt_tokens": 100, "completion_tokens": 20}
    assert resolve_cost(MODELS[0], response_cost=cost, usage=usage) == (
        0.00002,
        "price_table",
    )
    with pytest.raises(PriceUnknown) as caught:
        resolve_cost("unknown", response_cost=cost, usage=usage)
    assert caught.value.code == "PRICE_UNKNOWN"
    with pytest.raises(PriceUnknown):
        compute_cost("unknown", input_tokens=10, output_tokens=1)
    assert price_for("unknown") is None


def test_positive_cost_and_zero_token_calls():
    assert resolve_cost("unknown", response_cost=0.25, usage={}) == (
        0.25,
        "response_cost",
    )
    for cost in (None, 0.0, -1.0):
        assert resolve_cost("unknown", response_cost=cost, usage={}) == (
            0.0,
            "response_cost",
        )


@pytest.mark.parametrize("name", ["terra_effort_none", "haiku_plain", "sonnet_plain"])
def test_p5_zero_reported_cost_becomes_positive(name):
    item = load("litellm_p5_chat_models.json").get(name)
    assert item.get("response_cost") == 0.0
    raw = item.get("raw")
    cost, source = resolve_cost(
        raw.get("model"), response_cost=0.0, usage=raw.get("usage")
    )
    assert cost > 0
    assert source == "price_table"


def test_native_anthropic_separate_cache_and_mixed_write_lifetimes():
    usage = {
        "input_tokens": 100,
        "output_tokens": 20,
        "cache_read_input_tokens": 200,
        "cache_creation_input_tokens": 500,
        "cache_creation_token_details": {
            "ephemeral_5m_input_tokens": 300,
            "ephemeral_1h_input_tokens": 200,
        },
    }
    assert resolve_cost(MODELS[2], response_cost=None, usage=usage) == (
        0.0000995,
        "price_table",
    )


def test_embedding_price_candidates_are_positive():
    from beautyads.llm.prices import EMBEDDING_PRICES

    assert set(EMBEDDING_PRICES) == {"text-embedding-3-small", "text-embedding-3-large"}
    assert all(model and rate > 0 for model, rate in EMBEDDING_PRICES.items())
