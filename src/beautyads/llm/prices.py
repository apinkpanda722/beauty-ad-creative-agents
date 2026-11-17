"""Pinned standard token prices in USD per million, checked on the stated date."""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal, NamedTuple

from .errors import ErrorKind, LlmCallError

PRICE_TABLE_CHECKED_ON = "2026-11-17"
CostSource = Literal["response_cost", "price_table"]


@dataclass(frozen=True)
class TokenPrice:
    input: float
    cache_read: float
    cache_write_short: float
    cache_write_long: float
    output: float


@dataclass(frozen=True)
class ModelPrice(TokenPrice):
    model: str
    provider: Literal["openai", "anthropic"]
    source_url: str
    tier_threshold_tokens: int | None = None
    tier_over: TokenPrice | None = None


_OPENAI = "https://developers.openai.com/api/docs/pricing"
_ANTHROPIC = "https://platform.claude.com/docs/en/about-claude/pricing"
_PRICES = {
    price.model: price
    for price in (
        ModelPrice(1.0, 0.05, 1.25, 2.5, 5.0, "gpt-6.1-terra", "openai", _OPENAI),
        ModelPrice(0.1, 0.01, 0.125, 0.25, 0.5, "gpt-6-luna", "openai", _OPENAI),
        ModelPrice(
            2.0, 0.1, 2.5, 4.0, 10.0, "claude-sonnet-5-5", "anthropic", _ANTHROPIC
        ),
        ModelPrice(
            0.1,
            0.01,
            0.125,
            0.2,
            0.5,
            "claude-haiku-5-5",
            "anthropic",
            _ANTHROPIC,
            100_000,
            TokenPrice(0.5, 0.05, 0.625, 1.0, 2.5),
        ),
    )
}


class PriceUnknown(LlmCallError):
    def __init__(self):
        super().__init__(kind=ErrorKind.FATAL, code="PRICE_UNKNOWN")


def price_for(model: str) -> ModelPrice | None:
    for prefix in ("openai/", "anthropic/"):
        if model.startswith(prefix):
            model = model.removeprefix(prefix)
            break
    return _PRICES.get(model)


class _Tokens(NamedTuple):
    input: int
    output: int
    read: int
    write_short: int
    write_long: int

    @property
    def total_input(self) -> int:
        return self.input + self.read + self.write_short + self.write_long


def _usage_tokens(model: str, usage: Mapping[str, Any]) -> _Tokens:
    """Normalize SDK totals and native, disjoint Anthropic usage by field name."""
    details = usage.get("prompt_tokens_details") or {}
    price = price_for(model)
    anthropic = (
        price is not None and price.provider == "anthropic"
    ) or model.removeprefix("anthropic/").startswith("claude-")
    if anthropic:
        read = usage.get("cache_read_input_tokens") or 0
        write = usage.get("cache_creation_input_tokens") or 0
        lifetimes = (
            usage.get("cache_creation_token_details")
            or details.get("cache_creation_token_details")
            or {}
        )
        long = lifetimes.get("ephemeral_1h_input_tokens") or 0
        short = lifetimes.get("ephemeral_5m_input_tokens")
        short = max(0, write - long) if short is None else short
    else:
        read = details.get("cached_tokens") or 0
        write = (
            details.get("cache_write_tokens")
            or details.get("cache_creation_tokens")
            or 0
        )
        short, long = write, 0
    if "input_tokens" in usage:
        uncached = usage.get("input_tokens") or 0
    else:
        # Both providers' LiteLLM normalized prompt_tokens include cache tokens.
        uncached = max(0, (usage.get("prompt_tokens") or 0) - read - short - long)
    output = (
        usage.get("output_tokens")
        if "output_tokens" in usage
        else usage.get("completion_tokens")
    )
    return _Tokens(uncached, output or 0, read, short, long)


def _cost(model: str, tokens: _Tokens) -> float:
    price = price_for(model)
    if price is None:
        raise PriceUnknown()
    rates = price
    if (
        price.tier_threshold_tokens is not None
        and tokens.total_input > price.tier_threshold_tokens
    ):
        rates = price.tier_over
    amount = sum(
        Decimal(count) * Decimal(str(rate))
        for count, rate in zip(
            tokens,
            (
                rates.input,
                rates.output,
                rates.cache_read,
                rates.cache_write_short,
                rates.cache_write_long,
            ),
            strict=True,
        )
    )
    return float(amount / Decimal(1_000_000))


def compute_cost(
    model: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    cache_write_long: bool = False,
) -> float:
    """Input and cache counts are disjoint; tier selection includes all input."""
    return _cost(
        model,
        _Tokens(
            input_tokens,
            output_tokens,
            cache_read_tokens,
            0 if cache_write_long else cache_write_tokens,
            cache_write_tokens if cache_write_long else 0,
        ),
    )


def resolve_cost(
    model: str, *, response_cost: float | None, usage: Mapping[str, Any]
) -> tuple[float, CostSource]:
    if response_cost is not None and response_cost > 0:
        return response_cost, "response_cost"
    tokens = _usage_tokens(model, usage)
    if tokens.total_input == 0 and tokens.output == 0:
        return 0.0, "response_cost"
    return _cost(model, tokens), "price_table"
