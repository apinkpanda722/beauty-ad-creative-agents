"""Offline image contracts use only magic bytes and synthetic padding."""

import base64
import inspect
import json
import traceback
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import Mock
from uuid import uuid4

import pytest

from beautyads.llm import (
    CostCapExceeded,
    DailyLimitReached,
    ImageOutcome,
    LlmCallError,
    generate_image,
    image,
)
from beautyads.obs import LedgerEntry, append_entry, purpose_total, read_entries

STAMP = datetime(2026, 11, 17, tzinfo=UTC)
PNG = b"\x89PNG\r\n\x1a\nsynthetic-padding"
JPEG = b"\xff\xd8\xffsynthetic-padding"
WEBP = b"RIFF\x00\x00\x00\x00WEBPsynthetic-padding"
SIGNATURE = "synthetic-signature-do-not-retain"
FIXTURE = (
    Path(__file__).parent
    / "fixtures/contracts/gemini_image_completion_flash_lite_abridged.json"
)


def response(payload=PNG, *, cost=0.0341885, position=0):
    measured = json.loads(FIXTURE.read_text()).get("image_completion")
    raw = measured.get("raw")
    message = next(iter(raw.get("choices"))).get("message")
    item = next(iter(message.get("images")))
    item.get("image_url")["url"] = "data:image/png;base64," + base64.b64encode(
        payload
    ).decode("ascii")
    message["images"] = [{"type": "text", "text": "synthetic"}] * position + [item]
    message["provider_specific_fields"] = {"thought_signatures": [SIGNATURE]}
    raw["_hidden_params"] = {"response_cost": cost}
    return raw


@pytest.fixture
def args(tmp_path):
    return {
        "prompt": "synthetic text brief",
        "ledger_path": tmp_path / "costs.jsonl",
        "caps": {"gemini": 12.0},
        "purpose_caps": {"image": 3.5},
        "api_key": uuid4().hex,
        "now": lambda: STAMP,
    }


def message(raw):
    return next(iter(raw.get("choices"))).get("message")


@pytest.mark.parametrize(
    "payload,mime", [(PNG, "image/png"), (JPEG, "image/jpeg"), (WEBP, "image/webp")]
)
@pytest.mark.parametrize("position", [0, 1, 2])
def test_magic_bytes_and_named_item(args, payload, mime, position):
    fn = Mock(return_value=response(payload, position=position))
    outcome = generate_image(**args, completion_fn=fn)
    assert isinstance(outcome, ImageOutcome) and outcome.ok
    assert outcome.image_bytes == payload
    assert outcome.mime == mime and outcome.size == len(payload)
    assert outcome.sha256 == sha256(payload).hexdigest()
    assert outcome.model == "gemini-3.1-flash-lite-image" and outcome.code is None
    call = fn.call_args.kwargs
    assert call.get("model") == "gemini/gemini-3.1-flash-lite-image"
    assert call.get("modalities") == ["image", "text"]
    assert call.get("messages") == [{"role": "user", "content": args.get("prompt")}]
    assert call.get("timeout") == 120.0 and call.get("num_retries") == 0
    assert "temperature" not in call and "reasoning_effort" not in call


@pytest.mark.parametrize(
    "cost,source,expected",
    [
        (0.0341885, "response_cost", 0.0341885),
        (0, "price_table", 0.0336),
        (None, "price_table", 0.0336),
    ],
)
def test_accounting(args, cost, source, expected):
    outcome = generate_image(**args, completion_fn=lambda **_: response(cost=cost))
    (row,) = read_entries(args.get("ledger_path")).entries
    assert row.cost_usd == outcome.cost_usd == expected
    assert row.cost_source == source and row.reasoning_effort is None
    assert row.model == outcome.model and row.provider == "gemini"
    assert row.purpose == "image-plan" and row.ts == STAMP
    assert row.input_tokens == 20 and row.output_tokens == 1509


@pytest.mark.parametrize(
    "case,code",
    [
        ("gif", "IMAGE_MIME_UNSUPPORTED"),
        ("text", "IMAGE_MIME_UNSUPPORTED"),
        ("large", "IMAGE_TOO_LARGE"),
        ("absent", "IMAGE_MISSING"),
        ("empty", "IMAGE_MISSING"),
        ("empty_url", "IMAGE_MISSING"),
        ("wrong_type", "IMAGE_MISSING"),
        ("base64", "IMAGE_DECODE_FAILED"),
        ("url", "IMAGE_DECODE_FAILED"),
        ("choices", "IMAGE_MISSING"),
    ],
)
def test_invalid_image_is_paid_outcome(args, monkeypatch, case, code):
    raw = response(
        b"GIF89asynthetic" if case == "gif" else b"text" if case == "text" else PNG
    )
    msg = message(raw)
    if case == "large":
        monkeypatch.setattr(image, "MAX_IMAGE_BYTES", len(PNG) - 1)
    elif case == "absent":
        msg.pop("images")
    elif case == "empty":
        msg["images"] = []
    elif case == "wrong_type":
        msg["images"] = [{"type": "text", "image_url": {"url": "synthetic"}}]
    elif case in {"empty_url", "base64", "url"}:
        next(iter(msg.get("images"))).get("image_url")["url"] = {
            "empty_url": "",
            "base64": "data:image/png;base64,!!broken!!",
            "url": "https://example.invalid/synthetic.png",
        }.get(case)
    elif case == "choices":
        raw.pop("choices")
    outcome = generate_image(**args, completion_fn=lambda **_: raw)
    assert not outcome.ok and outcome.code == code
    assert outcome.image_bytes is None and outcome.mime is None
    assert outcome.size is None and outcome.sha256 is None
    assert len(read_entries(args.get("ledger_path")).entries) == 1


def test_exact_size_limit_is_allowed(args, monkeypatch):
    assert image.MAX_IMAGE_BYTES == 10_485_760
    monkeypatch.setattr(image, "MAX_IMAGE_BYTES", len(PNG))
    assert generate_image(**args, completion_fn=lambda **_: response()).ok


def spend(args, *, cost, purpose="chat", provider="gemini"):
    append_entry(
        args.get("ledger_path"),
        LedgerEntry(
            ts=STAMP,
            provider=provider,
            model="synthetic",
            purpose=purpose,
            cost_usd=cost,
            cost_source="response_cost",
        ),
    )


@pytest.mark.parametrize("provider_cap", [True, False])
@pytest.mark.parametrize("reserve", [0.0, 0.02, 0.0336])
def test_both_caps_include_next_image(args, provider_cap, reserve):
    spend(
        args,
        cost=(12.0 if provider_cap else 3.5) - reserve,
        purpose="chat" if provider_cap else "image-probe",
    )
    fn = Mock()
    with pytest.raises(CostCapExceeded):
        generate_image(**args, completion_fn=fn)
    fn.assert_not_called()


def test_image_purpose_prefix_only(args):
    spend(args, cost=1.0, purpose="image-plan")
    spend(args, cost=1.0, purpose="image-probe")
    spend(args, cost=2.0, purpose="probe-image")
    spend(args, cost=2.0, purpose="images-plan")
    assert purpose_total(args.get("ledger_path"), "image") == 2.0
    outcome = generate_image(
        **args, purpose_suffix="probe", completion_fn=lambda **_: response()
    )
    assert outcome.ok
    assert read_entries(args.get("ledger_path")).entries[-1].purpose == "image-probe"


def error(status, text="synthetic failure"):
    exc = RuntimeError(text)
    exc.status_code = status
    return exc


@pytest.mark.parametrize("kind", ["503", "APIConnectionError", "Timeout"])
def test_only_retryable_dispatch_failures(args, monkeypatch, kind):
    exc = (
        error(503)
        if kind == "503"
        else getattr(image.litellm, kind)(
            message="synthetic", model="synthetic", llm_provider="gemini"
        )
    )
    fn, sleep = Mock(side_effect=[exc, exc, response()]), Mock()
    checks = [Mock(wraps=image.check_cap), Mock(wraps=image.check_purpose_cap)]
    monkeypatch.setattr(image, "check_cap", checks[0])
    monkeypatch.setattr(image, "check_purpose_cap", checks[1])
    assert generate_image(
        **args, completion_fn=fn, sleep=sleep, backoff_s=(0.1, 0.2)
    ).ok
    assert fn.call_count == 3 and all(check.call_count == 3 for check in checks)
    assert [call.args for call in sleep.call_args_list] == [(0.1,), (0.2,)]
    assert len(read_entries(args.get("ledger_path")).entries) == 1


@pytest.mark.parametrize("purpose", ["chat", "image-plan"])
def test_both_caps_rechecked_after_wait(args, purpose):
    fn = Mock(side_effect=error(503))
    with pytest.raises(CostCapExceeded):
        generate_image(
            **args,
            completion_fn=fn,
            sleep=lambda _: spend(
                args, cost=12 if purpose == "chat" else 3.5, purpose=purpose
            ),
        )
    fn.assert_called_once()


@pytest.mark.parametrize(
    "status,text,cls",
    [
        (429, "daily quota", DailyLimitReached),
        (402, "credits", DailyLimitReached),
        (429, "rate", LlmCallError),
        (401, "auth", LlmCallError),
        (500, "failure", LlmCallError),
    ],
)
def test_nonretryable_failures(args, status, text, cls):
    fn, sleep = Mock(side_effect=error(status, text)), Mock()
    with pytest.raises(cls):
        generate_image(**args, completion_fn=fn, sleep=sleep)
    fn.assert_called_once()
    sleep.assert_not_called()


def test_retry_exhaustion(args):
    fn = Mock(side_effect=error(503))
    with pytest.raises(LlmCallError, match="RETRIES_EXHAUSTED"):
        generate_image(**args, completion_fn=fn, sleep=lambda _: None)
    assert fn.call_count == 3


def test_no_payload_or_signature_exposure(args, caplog):
    raw = response()
    encoded = base64.b64encode(PNG).decode()
    outcome = generate_image(**args, completion_fn=lambda **_: raw)
    visible = (
        repr(outcome) + str(outcome) + args.get("ledger_path").read_text() + caplog.text
    )
    assert "image_bytes" not in repr(outcome)
    for marker in (SIGNATURE, encoded, repr(PNG)):
        assert marker not in visible
    with pytest.raises(LlmCallError) as caught:
        generate_image(
            **args, completion_fn=Mock(side_effect=error(401, SIGNATURE + encoded))
        )
    rendered = "".join(traceback.format_exception(caught.value))
    assert SIGNATURE not in rendered and encoded not in rendered


def test_sdk_objects_never_serialize_or_read_signatures(args):
    class Message:
        images: ClassVar = [
            SimpleNamespace(
                type="image_url",
                image_url=SimpleNamespace(
                    url="data:image/png;base64," + base64.b64encode(PNG).decode()
                ),
            )
        ]

        @property
        def provider_specific_fields(self):
            pytest.fail("Signatures must never be accessed")

    class Response:
        choices: ClassVar = [SimpleNamespace(message=Message())]
        usage = SimpleNamespace(prompt_tokens=20, completion_tokens=1509)
        _hidden_params: ClassVar = {"response_cost": 0.0341885}

        def model_dump(self):
            pytest.fail("Do not copy the complete image response")

    assert generate_image(**args, completion_fn=lambda **_: Response()).ok


def test_no_retry_after_response_is_returned(args):
    class BrokenResponse:
        @property
        def choices(self):
            raise error(503, SIGNATURE)

    fn = Mock(return_value=BrokenResponse())
    with pytest.raises(LlmCallError) as caught:
        generate_image(**args, completion_fn=fn)
    assert SIGNATURE not in str(caught.value)
    fn.assert_called_once()
    assert len(read_entries(args.get("ledger_path")).entries) == 1


def test_text_only_signature_and_invalid_input(args):
    assert set(inspect.signature(generate_image).parameters) == {
        "prompt",
        "purpose_suffix",
        "ledger_path",
        "caps",
        "purpose_caps",
        "model",
        "api_key",
        "timeout_s",
        "max_attempts",
        "backoff_s",
        "completion_fn",
        "sleep",
        "now",
    }
    for prompt in (PNG, Path("synthetic"), ["synthetic"]):
        fn = Mock()
        with pytest.raises(ValueError, match="PROMPT_INVALID"):
            generate_image(**(args | {"prompt": prompt}), completion_fn=fn)
        fn.assert_not_called()


@pytest.mark.parametrize("retry", [False, True])
def test_image_duration_measures_only_successful_dispatch(args, monkeypatch, retry):
    clock = {"seconds": 1.0}
    monkeypatch.setattr(image, "_monotonic", lambda: clock["seconds"])
    attempts = []

    def dispatch(**kwargs):
        attempts.append(clock["seconds"])
        if retry and len(attempts) == 1:
            clock["seconds"] += 4.0
            raise error(503)
        clock["seconds"] += 1.5
        return response()

    def sleep(seconds):
        clock["seconds"] += seconds

    assert generate_image(
        **args, completion_fn=dispatch, sleep=sleep, backoff_s=(10.0,)
    ).ok
    assert attempts == ([1.0, 15.0] if retry else [1.0])
    (row,) = read_entries(args["ledger_path"]).entries
    assert row.duration_ms == 1500
    assert row.ts == STAMP
