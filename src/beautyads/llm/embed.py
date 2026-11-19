"""Batched embeddings with safe decoding, bounded retries and paid-call accounting."""

import math
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

import litellm

from beautyads.obs.ledger import LedgerEntry, append_entry, check_cap

from .chat import _call_error
from .errors import ErrorKind, LlmResponseError, classify_error
from .prices import EMBEDDING_PRICES


@dataclass(frozen=True)
class EmbedResult:
    vectors: list[list[float]]
    input_tokens: int
    cost_usd: float
    # Sanitized first-response structure, for the user's later contract measurement.
    response_shape: dict | None = None


def _invalid():
    raise LlmResponseError("EMBED_RESPONSE_INVALID")


def _mapping(value):
    if isinstance(value, Mapping):
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        value = dump()
        if isinstance(value, Mapping):
            return value
    _invalid()


def _shape(value, *, embedding=False):
    if isinstance(value, Mapping):
        return {str(k): _shape(v, embedding=k == "embedding") for k, v in value.items()}
    if isinstance(value, list):
        if embedding:
            return value[:3]
        return [_shape(v) for v in value[:1]]
    return type(value).__name__


def embed_texts(
    texts,
    *,
    model,
    ledger_path,
    caps,
    api_key,
    purpose="embed",
    batch_size=64,
    embedding_fn=None,
) -> EmbedResult:
    """No unspecified model options; every retry is checked against current spend."""
    price = EMBEDDING_PRICES.get(model)
    if price is None:
        raise LlmResponseError("EMBED_MODEL_UNPRICED")
    texts = list(texts)
    if (
        type(batch_size) is not int
        or batch_size < 1
        or any(not isinstance(t, str) or not t for t in texts)
    ):
        raise ValueError("EMBED_INPUT_INVALID")
    vectors, total_tokens, total_cost, shape = [], 0, 0.0, None
    call = embedding_fn if embedding_fn is not None else litellm.embedding
    for offset in range(0, len(texts), batch_size):
        batch = texts[offset : offset + batch_size]
        # UTF-8 bytes bound byte-level token counts, including non-ASCII text.
        upper_cost = sum(len(t.encode("utf-8")) for t in batch) * price / 1e6
        for attempt in range(3):
            check_cap(
                ledger_path, provider="openai", caps=caps, additional_usd=upper_cost
            )
            try:
                response = call(
                    model=f"openai/{model}",
                    input=batch,
                    api_key=api_key,
                    num_retries=0,
                    timeout=120.0,
                )
            except Exception as exc:  # noqa: BLE001 -- never expose SDK request bodies
                kind = classify_error(exc)
                if kind == ErrorKind.RETRYABLE and attempt < 2:
                    time.sleep((2.0, 5.0)[attempt])
                    continue
                raise _call_error(exc, exhausted=kind == ErrorKind.RETRYABLE) from None
            break
        raw = _mapping(response)
        usage = raw.get("usage")
        if not isinstance(usage, Mapping):
            _invalid()
        tokens = usage.get("prompt_tokens")
        if type(tokens) is not int or tokens < 0:
            _invalid()
        cost = tokens * price / 1e6
        # Account paid usage even if the vectors subsequently fail validation.
        append_entry(
            ledger_path,
            LedgerEntry(
                ts=datetime.now(UTC),
                provider="openai",
                model=model,
                requested_model=model,
                purpose=purpose,
                input_tokens=tokens,
                cost_usd=cost,
                cost_source="price_table",
            ),
        )
        data = raw.get("data")
        if not isinstance(data, list) or len(data) != len(batch):
            _invalid()
        by_index = {}
        for value in data:
            item = _mapping(value)
            index, vector = item.get("index"), item.get("embedding")
            if (
                type(index) is not int
                or index not in range(len(batch))
                or index in by_index
            ):
                _invalid()
            if (
                not isinstance(vector, list)
                or not vector
                or any(
                    type(v) not in (int, float) or not math.isfinite(v) for v in vector
                )
            ):
                _invalid()
            by_index[index] = [float(v) for v in vector]
        ordered = [v for _, v in sorted(by_index.items())]
        dimension = len(next(iter(vectors or ordered)))
        if any(len(v) != dimension for v in ordered):
            _invalid()
        vectors.extend(ordered)
        total_tokens += tokens
        total_cost += cost
        if shape is None:
            # Keep key names/types only; sample only validated numeric vectors.
            shape = _shape(dict(raw))
    return EmbedResult(vectors, total_tokens, total_cost, shape)
