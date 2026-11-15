"""Product detail extraction uses in-memory synthetic images and fake calls only."""

import base64
import json
from copy import deepcopy
from io import BytesIO
from itertools import pairwise
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError

from beautyads.analysis.models import ANALYSIS_MODEL_ID
from beautyads.analysis.product_detail import (
    PROMPT_VERSION,
    ProductImageInvalid,
    extract_product_detail,
    product_detail_schema,
    split_image,
)
from beautyads.domain import JobStatus
from beautyads.domain.products import ProductDetailResult, ProductExtraction, ProductKey
from beautyads.domain.skin import SkinType
from beautyads.llm import CostCapExceeded, DailyLimitReached, LlmCallError


def png(width=1000, height=5000):
    with Image.new("RGB", (width, height), "white") as image, BytesIO() as buffer:
        image.save(buffer, format="PNG")
        return buffer.getvalue()


def payload(**changes):
    return {
        "ingredients": [],
        "volume": None,
        "volume_unit": None,
        "form": None,
        "skin_types": [],
        "efficacy_texts": [],
        "functional_texts": [],
        **changes,
    }


def ingredients():
    # Synthetic text tests lossless transport, never extraction accuracy.
    return [
        {"raw_name": "  Synthetic A\t", "amount_text": "(1,000 ppm)"},
        {"raw_name": "synthetic B", "amount_text": None},
        {"raw_name": "  Synthetic A\t", "amount_text": None},
    ]


def response(data):
    fixture = json.loads(
        (
            Path(__file__).parent
            / "fixtures/contracts/gemini_interactions_image_input.json"
        ).read_text()
    )
    body = deepcopy(fixture["probes"][0]["response"])
    body["steps"] = [
        {"type": "thought"},
        {"type": "model_output", "content": [{"type": "text", "text": data}]},
    ]
    return body


class FakeInteractions:
    def __init__(self, *outputs):
        self.outputs = iter(outputs)
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        output = next(self.outputs)
        if isinstance(output, Exception):
            raise output
        return response(output if isinstance(output, str) else json.dumps(output))


class HttpError(Exception):
    def __init__(self, status_code, message="synthetic failure", headers=None):
        self.status_code = status_code
        self.response = {"headers": headers or {}}
        super().__init__(message)


@pytest.fixture
def kwargs(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-test-only")
    return {
        "product": ProductKey(brand="Synthetic", source_url="https://example.com/p"),
        "thinking_level": "minimal",
        "ledger_path": tmp_path / "costs.jsonl",
        "caps": {"gemini": 12.0},
        "sleep": lambda _: None,
    }


def image_sizes(fake):
    sizes = []
    for call in fake.calls:
        part = next(p for p in call["input"] if p["type"] == "image")
        with Image.open(BytesIO(base64.b64decode(part["data"]))) as image:
            sizes.append(image.size)
    return sizes


def test_chunks_geometry_overlap_and_no_disk_writes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    chunks = list(split_image(png()))
    assert [(c.top, c.bottom) for c in chunks] == [
        (0, 2000),
        (1600, 3600),
        (3200, 5000),
    ]
    assert len(chunks) == 3
    assert [c.height for c in chunks] == [2000, 2000, 1800]
    assert all(a.bottom - b.top == 400 for a, b in pairwise(chunks))
    assert all(c.width == 1000 for c in chunks)
    assert list(tmp_path.iterdir()) == []
    for chunk in chunks:
        with Image.open(BytesIO(chunk.data)) as image:
            assert image.size == (chunk.width, chunk.height)


def test_reverse_chunk_coordinates():
    assert [(c.top, c.bottom) for c in split_image(png(), reverse=True)] == [
        (3200, 5000),
        (1600, 3600),
        (0, 2000),
    ]


@pytest.mark.parametrize(
    "width,height,expected",
    [
        (2000, 6000, (1000, 3000)),
        (600, 3000, (600, 3000)),
        (1000, 2000, (1000, 2000)),
        (1000, 2001, (1000, 2001)),
    ],
)
def test_resize_and_last_short_chunk(width, height, expected):
    chunks = list(split_image(png(width, height)))
    assert chunks[-1].bottom == expected[1]
    assert all(c.width == expected[0] for c in chunks)
    assert all(0 < c.height <= 2000 for c in chunks)
    assert len(chunks) == (1 if expected[1] <= 2000 else 2)


def test_reverse_order_and_early_stop(kwargs):
    fake = FakeInteractions(payload(), payload(ingredients=ingredients()))
    result = extract_product_detail(
        images=[png(500, 500), png()], interactions_fn=fake, **kwargs
    )
    assert image_sizes(fake) == [(1000, 1800), (1000, 2000)]
    assert result.status is JobStatus.done
    assert result.result.ingredients
    assert len(fake.calls) == 2


def test_no_ingredients_is_done_and_reads_every_chunk(kwargs):
    fake = FakeInteractions(*[payload() for _ in range(4)])
    outcome = extract_product_detail(
        images=[png(500, 500), png()], interactions_fn=fake, **kwargs
    )
    assert outcome.status is JobStatus.done
    assert outcome.result.ingredients == []
    assert image_sizes(fake) == [(1000, 1800), (1000, 2000), (1000, 2000), (500, 500)]


def test_read_all_merges_facts_without_reordering_ingredient_list(kwargs):
    data = payload(
        ingredients=ingredients(),
        skin_types=[next(iter(SkinType)).value],
        efficacy_texts=["  Synthetic text\n"],
        functional_texts=["synthetic notice"],
    )
    fake = FakeInteractions(
        data, data, payload(form="synthetic form", volume=12, volume_unit="ml")
    )
    outcome = extract_product_detail(
        images=[png()], read_all=True, interactions_fn=fake, **kwargs
    )
    assert len(fake.calls) == 3
    assert outcome.result.model_dump(mode="json")["ingredients"] == data["ingredients"]
    assert len(outcome.result.skin_types) == len(outcome.result.efficacy_texts) == 1
    assert outcome.result.efficacy_texts == data["efficacy_texts"]
    assert outcome.result.volume is not None and outcome.result.form is not None


@pytest.mark.parametrize(
    "bad",
    [
        "not JSON",
        "{}",
        "[]",
        json.dumps(payload(skin_types=["outside-list"])),
        json.dumps(payload(volume_unit="outside-list")),
        json.dumps(payload(price=100)),
    ],
)
def test_invalid_output_repeated_once_then_held(kwargs, bad):
    fake = FakeInteractions(bad, bad)
    outcome = extract_product_detail(
        images=[png(100, 100)], interactions_fn=fake, **kwargs
    )
    assert outcome.status is JobStatus.held
    assert outcome.result is None
    assert len(fake.calls) == 2
    assert fake.calls[0] == fake.calls[1]
    assert outcome.issues[0].error_code == "INVALID_OUTPUT"
    assert all(isinstance(e, ProductExtraction) for e in outcome.extractions)
    assert [e.raw_output for e in outcome.extractions] == [bad, bad]


def test_validation_recovers_and_raw_outputs_are_preserved(kwargs):
    valid = "\n```json\n" + json.dumps(payload(ingredients=ingredients())) + "\n```\n"
    fake = FakeInteractions("bad", valid)
    outcome = extract_product_detail(
        images=[png(100, 100)], interactions_fn=fake, **kwargs
    )
    assert outcome.status is JobStatus.done
    assert [e.raw_output for e in outcome.extractions] == ["bad", valid]
    assert all(
        e.product == kwargs["product"] and e.prompt_version == PROMPT_VERSION
        for e in outcome.extractions
    )


@pytest.mark.parametrize(
    "error",
    [
        HttpError(503),
        ConnectionError("synthetic connection"),
        TimeoutError("synthetic timeout"),
    ],
)
def test_retryable_failures_use_llm_wrapper_retries(kwargs, error):
    # Built-in connection errors are not SDK errors, so use the SDK-compatible
    # fake status for 503 here; SDK-specific cases are also covered by test_llm.
    if not isinstance(error, HttpError):
        from litellm import APIConnectionError, Timeout

        error = (Timeout if isinstance(error, TimeoutError) else APIConnectionError)(
            message="synthetic", model=ANALYSIS_MODEL_ID, llm_provider="gemini"
        )
    fake = FakeInteractions(error, payload())
    outcome = extract_product_detail(
        images=[png(100, 100)], interactions_fn=fake, **kwargs
    )
    assert outcome.status is JobStatus.done
    assert len(fake.calls) == 2


def test_chunk_error_is_isolated_without_extra_nonretryable_calls(kwargs):
    fake = FakeInteractions(HttpError(400), payload(ingredients=ingredients()))
    outcome = extract_product_detail(images=[png()], interactions_fn=fake, **kwargs)
    assert len(fake.calls) == 2
    assert outcome.status is JobStatus.done
    assert len(outcome.issues) == 1
    assert outcome.issues[0].image_index == 0
    assert outcome.issues[0].top == 3200


def test_exhausted_chunk_retries_continue_to_next_chunk(kwargs):
    fake = FakeInteractions(
        HttpError(503),
        HttpError(503),
        HttpError(503),
        payload(ingredients=ingredients()),
    )
    outcome = extract_product_detail(images=[png()], interactions_fn=fake, **kwargs)
    assert outcome.status is JobStatus.done
    assert len(fake.calls) == 4
    assert len(outcome.issues) == 1


@pytest.mark.parametrize(
    "error,raised",
    [
        (HttpError(402), DailyLimitReached),
        (HttpError(429, headers={"retry-after": "7200"}), DailyLimitReached),
        (HttpError(429), LlmCallError),
        (HttpError(401), LlmCallError),
        (HttpError(403), LlmCallError),
    ],
)
def test_system_errors_escape_without_retry_or_product_failure(
    kwargs, error, raised, caplog
):
    fake = FakeInteractions(error)
    with pytest.raises(raised):
        extract_product_detail(images=[png()], interactions_fn=fake, **kwargs)
    assert len(fake.calls) == 1
    assert not caplog.records


def test_cost_cap_is_not_converted_to_product_failure(kwargs):
    kwargs["caps"] = {"gemini": 0.0}
    fake = FakeInteractions()
    with pytest.raises(CostCapExceeded):
        extract_product_detail(images=[png()], interactions_fn=fake, **kwargs)
    assert not fake.calls


@pytest.mark.parametrize("data", [b"", b"not an image", png(100, 100)[:-20]])
def test_bad_images_are_isolated(kwargs, data):
    fake = FakeInteractions(payload(ingredients=ingredients()))
    outcome = extract_product_detail(
        images=[png(100, 100), data], interactions_fn=fake, **kwargs
    )
    assert outcome.issues[0].error_code == "PRODUCT_IMAGE_INVALID"
    assert outcome.status is JobStatus.done
    assert len(fake.calls) == 1


@pytest.mark.parametrize("size", [(101, 100), (201, 100)])
def test_decompression_warning_and_bomb_are_invalid(kwargs, monkeypatch, size):
    data = png(*size)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 10_000)
    with pytest.raises(ProductImageInvalid, match="PRODUCT_IMAGE_INVALID"):
        list(split_image(data))
    outcome = extract_product_detail(
        images=[data], interactions_fn=FakeInteractions(), **kwargs
    )
    assert outcome.status is JobStatus.failed
    assert outcome.issues[0].error_code == "PRODUCT_IMAGE_INVALID"


def test_animated_gif_uses_first_frame_only():
    with (
        Image.new("RGB", (50, 50), "white") as first,
        Image.new("RGB", (50, 50), "black") as second,
        BytesIO() as buffer,
    ):
        first.save(buffer, format="GIF", save_all=True, append_images=[second])
        chunks = list(split_image(buffer.getvalue()))
    assert len(chunks) == 1
    with Image.open(BytesIO(chunks[0].data)) as image:
        assert image.convert("RGB").getpixel((0, 0)) == (255, 255, 255)


def test_schema_request_model_thinking_and_ledger(kwargs):
    fake = FakeInteractions(payload())
    extract_product_detail(images=[png(100, 100)], interactions_fn=fake, **kwargs)
    call = fake.calls[0]
    assert call["model"] == "gemini/" + ANALYSIS_MODEL_ID
    assert call["generation_config"] == {"thinking_level": kwargs["thinking_level"]}
    assert call["response_format"]["schema"] == product_detail_schema()
    assert "temperature" not in call and "temperature" not in call["generation_config"]
    assert "price" not in json.dumps(call["response_format"])
    assert "가격" not in next(p["text"] for p in call["input"] if p["type"] == "text")
    ledger = [
        json.loads(line) for line in kwargs["ledger_path"].read_text().splitlines()
    ]
    assert ledger[0]["purpose"] == "product-detail"
    schema = product_detail_schema()
    assert set(schema["required"]) == set(ProductDetailResult.model_fields)
    assert set(schema["properties"]["skin_types"]["items"]["enum"]) == {
        m.value for m in SkinType
    }


def test_schema_requires_fields_and_rejects_blank_ingredients():
    with pytest.raises(ValidationError):
        ProductDetailResult.model_validate({})
    with pytest.raises(ValidationError):
        ProductDetailResult.model_validate(
            payload(ingredients=[{"raw_name": "  ", "amount_text": None}])
        )


def test_validation_hold_is_not_hidden_by_a_later_valid_chunk(kwargs):
    fake = FakeInteractions("bad", "bad", payload(ingredients=ingredients()))
    outcome = extract_product_detail(images=[png()], interactions_fn=fake, **kwargs)
    assert outcome.status is JobStatus.held
    assert outcome.result is None
    assert len(fake.calls) == 3
