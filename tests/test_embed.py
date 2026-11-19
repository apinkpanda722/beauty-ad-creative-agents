"""Synthetic, offline embedding boundary contracts."""

from copy import deepcopy
from uuid import uuid4

import pytest

from beautyads.llm.embed import embed_texts
from beautyads.llm.prices import EMBEDDING_PRICES
from beautyads.obs.ledger import CostCapExceeded, read_entries


def response(n=2):
    return {
        "data": [
            {"index": i, "embedding": [float(i), 1.0]} for i in reversed(range(n))
        ],
        "usage": {"prompt_tokens": n * 10},
    }


def args(tmp_path, **overrides):
    return dict(
        model="text-embedding-3-small",
        ledger_path=tmp_path / "ledger",
        caps={"openai": 10.0},
        api_key=uuid4().hex,
        **overrides,
    )


def test_order_batches_accounting_and_options(tmp_path):
    calls = []

    def fake(**kw):
        calls.append(kw)
        return response(len(kw["input"]))

    result = embed_texts(
        ["a", "b", "c"], **args(tmp_path), batch_size=2, embedding_fn=fake
    )
    assert result.vectors == [[0.0, 1.0], [1.0, 1.0], [0.0, 1.0]]
    assert result.input_tokens == 30
    assert result.cost_usd == pytest.approx(
        30 * EMBEDDING_PRICES["text-embedding-3-small"] / 1e6
    )
    entries = read_entries(tmp_path / "ledger").entries
    assert len(entries) == 2
    assert all(
        e.cost_source == "price_table" and e.reasoning_effort is None for e in entries
    )
    assert all(
        set(c) == {"model", "input", "api_key", "num_retries", "timeout"} for c in calls
    )


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"data": []},
        {"data": [{}]},
        {"data": [{"index": 0, "embedding": [1.0]}]},
        {"data": [{"index": 0, "embedding": [1.0]}, {"index": 0, "embedding": [2.0]}]},
        {"data": [{"index": 0, "embedding": []}, {"index": 1, "embedding": []}]},
    ],
)
def test_missing_or_invalid_response_is_safe(tmp_path, bad):
    with pytest.raises(Exception, match="^EMBED_RESPONSE_INVALID$"):
        embed_texts(
            ["private", "payload"],
            **args(tmp_path),
            embedding_fn=lambda **kw: deepcopy(bad),
        )


def test_cap_before_dispatch_and_unpriced(tmp_path):
    calls = []
    options = args(tmp_path)
    options["caps"] = {"openai": 0.000001}
    with pytest.raises(CostCapExceeded):
        embed_texts(["가" * 100], **options, embedding_fn=lambda **kw: calls.append(kw))
    options["model"] = "unpriced"
    with pytest.raises(Exception, match="^EMBED_MODEL_UNPRICED$"):
        embed_texts(["x"], **options, embedding_fn=lambda **kw: calls.append(kw))
    assert calls == []


@pytest.mark.parametrize("status,attempts", [(503, 3), (429, 1), (401, 1), (500, 1)])
def test_retry_classification_and_sanitization(tmp_path, monkeypatch, status, attempts):
    from beautyads.llm import embed

    monkeypatch.setattr(embed.time, "sleep", lambda _: None)
    calls = []

    class Failure(Exception):
        status_code = status

    def fail(**kw):
        calls.append(kw)
        raise Failure("SENTINEL_PRIVATE")

    with pytest.raises(Exception) as caught:
        embed_texts(["SENTINEL_PRIVATE"], **args(tmp_path), embedding_fn=fail)
    assert len(calls) == attempts
    assert "SENTINEL_PRIVATE" not in str(caught.value)


def test_empty_input_is_free(tmp_path):
    assert (
        embed_texts(
            [], **args(tmp_path), embedding_fn=lambda **kw: pytest.fail()
        ).vectors
        == []
    )


def test_cap_rechecked_between_batches_and_before_retry(tmp_path, monkeypatch):
    from beautyads.llm import embed

    calls, checks = [], []
    real_check = embed.check_cap

    def checked(*a, **kw):
        checks.append(kw["additional_usd"])
        real_check(*a, **kw)

    monkeypatch.setattr(embed, "check_cap", checked)

    def fake(**kwargs):
        calls.append(kwargs)
        return {
            "data": [{"index": 0, "embedding": [1.0]}],
            "usage": {"prompt_tokens": 100},
        }

    options = args(tmp_path)
    options["caps"] = {"openai": 0.000001}
    with pytest.raises(CostCapExceeded):
        embed_texts(["x", "y"], batch_size=1, **options, embedding_fn=fake)
    assert len(checks) == 2 and len(calls) == 1


@pytest.mark.parametrize(
    "variant",
    [
        "missing_index",
        "missing_embedding",
        "duplicate",
        "out_of_range",
        "nonfinite",
        "mismatched_dimensions",
        "missing_usage",
        "missing_prompt_tokens",
    ],
)
def test_response_fields_fail_closed_independently(tmp_path, variant):
    raw = response()
    data = raw["data"]
    if variant == "missing_index":
        data[0].pop("index")
    elif variant == "missing_embedding":
        data[0].pop("embedding")
    elif variant == "duplicate":
        data[0]["index"] = data[1]["index"]
    elif variant == "out_of_range":
        data[0]["index"] = 2
    elif variant == "nonfinite":
        data[0]["embedding"] = [float("nan"), 0.0]
    elif variant == "mismatched_dimensions":
        data[0]["embedding"] = [1.0]
    elif variant == "missing_usage":
        raw.pop("usage")
    else:
        raw["usage"].pop("prompt_tokens")
    with pytest.raises(Exception, match="^EMBED_RESPONSE_INVALID$"):
        embed_texts(["a", "b"], **args(tmp_path), embedding_fn=lambda **kw: raw)


def test_first_shape_has_no_body_values_and_only_three_vector_values(tmp_path):
    raw = response(1)
    raw["data"][0]["embedding"] = [1.0, 2.0, 3.0, 4.0]
    raw["model"] = "SENTINEL_BODY"
    result = embed_texts(
        ["SENTINEL_INPUT"], **args(tmp_path), embedding_fn=lambda **kw: raw
    )
    import json

    assert "SENTINEL" not in json.dumps(result.response_shape)
    assert result.response_shape["data"][0]["embedding"] == [1.0, 2.0, 3.0]
