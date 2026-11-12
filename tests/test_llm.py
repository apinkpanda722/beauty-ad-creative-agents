"""Gemini wrapper contracts, with generated text and no live service calls."""

# isort: off
# The wrapper must be imported before litellm to disable remote pricing downloads.
import ast
import json
import os
import subprocess
import sys
import traceback
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from beautyads import llm
from beautyads.llm import (
    CostCapExceeded,
    DailyLimitReached,
    ErrorKind,
    InteractionResult,
    LlmCallError,
    LlmResponseError,
    ThinkingLevel,
    UsageInfo,
    classify_error,
    extract_output_text,
    gemini_interact,
    json_schema_format,
    parse_json_output,
    retry_after_seconds,
    text_part,
    usage_from_response,
    video_part,
)
from beautyads.obs import LedgerEntry, append_entry, read_entries

# Import the SDK only after the wrapper has selected its bundled price map.
import httpx
import litellm
# isort: on

FIXTURES = Path(__file__).parent / "fixtures" / "contracts"
MODEL = "gemini-3.6-flash"
TEXT = json.dumps({"test_payload": [1, True, None]})
STAMP = datetime(2026, 11, 12, tzinfo=UTC)


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def response_with_text(name="gemini_interactions_36flash_response_format_schema.json"):
    raw = fixture(name)
    response = deepcopy(raw.get("response", raw.get("interactions")))
    for step in response.get("steps", []):
        if step.get("type") == "model_output":
            step["content"] = [{"type": "text", "text": TEXT}]
    return response


class ResponseObject:
    def __init__(self, raw, hidden=None):
        self.raw = raw
        self._hidden_params = hidden or {}

    def model_dump(self):
        return deepcopy(self.raw)


def sdk_error(cls, message="test failure", status=None, headers=None):
    kwargs = {"message": message, "model": MODEL, "llm_provider": "gemini"}
    if status is not None:
        kwargs["response"] = httpx.Response(
            status,
            headers=headers,
            request=httpx.Request("POST", "https://example.invalid/interactions"),
        )
    return cls(**kwargs)


def daily_error():
    body = fixture("gemini_error_free_tier_daily_limit.json").get("response")
    return sdk_error(litellm.RateLimitError, "GeminiException - " + json.dumps(body))


@pytest.fixture
def call_args(tmp_path):
    return {
        "model": MODEL,
        "input_parts": [text_part("test prompt"), video_part("test-video")],
        "thinking_level": "minimal",
        "purpose": "wrapper-test",
        "ledger_path": tmp_path / "costs.jsonl",
        "caps": {"gemini": 12.0},
        "api_key": uuid4().hex,
        "now": lambda: STAMP,
    }


@pytest.mark.parametrize(
    "name",
    [
        "gemini_interactions_36flash_response_format_schema.json",
        "gemini_interactions_36flash_youtube_offset.json",
        "litellm_gemini_files_flow.json",
    ],
)
@pytest.mark.parametrize("as_object", [False, True])
def test_extract_by_type_regardless_of_order(name, as_object):
    raw = response_with_text(name)
    for steps in (raw.get("steps"), list(reversed(raw.get("steps")))):
        raw["steps"] = steps
        response = ResponseObject(raw) if as_object else raw
        assert extract_output_text(response) == TEXT


@pytest.mark.parametrize("text", [TEXT, f"```json\n{TEXT}\n```", f"```\n{TEXT}\n```"])
def test_parse_json_with_or_without_fences(text):
    assert parse_json_output(text) == {"test_payload": [1, True, None]}


@pytest.mark.parametrize("text", ["", "broken", "```json\ninvalid\n```"])
def test_invalid_json_has_safe_code(text):
    with pytest.raises(LlmResponseError) as caught:
        parse_json_output(text)
    assert caught.value.code == "INVALID_JSON"


@pytest.mark.parametrize(
    "raw",
    [{}, {"steps": None}, {"steps": [{"type": "thought"}]}, {"outputs": TEXT}],
)
def test_absent_model_output(raw):
    with pytest.raises(LlmResponseError) as caught:
        extract_output_text(raw)
    assert caught.value.code == "NO_MODEL_OUTPUT"


def test_missing_content_is_read_defensively():
    raw = {"steps": [{"type": "model_output"}, {"type": "model_output", "content": []}]}
    assert extract_output_text(raw) == ""


def test_output_fragments_ignore_other_types():
    raw = {
        "steps": [
            {"type": "thought", "content": [{"text": "ignore"}]},
            {"type": "model_output", "content": [{}, {"text": "one"}, {"text": "two"}]},
        ]
    }
    assert extract_output_text(raw) == "onetwo"


@pytest.mark.parametrize("as_object", [False, True])
def test_usage_reads_named_fields_and_hidden_cost(as_object):
    raw = response_with_text()
    raw["usage"] = {
        "total_input_tokens": 11,
        "total_output_tokens": 22,
        "total_thought_tokens": 33,
        "total_cached_tokens": 44,
    }
    hidden = {"response_cost": 0.125}
    if as_object:
        response = ResponseObject(raw, hidden)
    else:
        response = {**raw, "_hidden_params": hidden}
    assert usage_from_response(response) == UsageInfo(MODEL, 11, 22, 33, 44, 0.125)


@pytest.mark.parametrize("usage", [None, {}, {"total_input_tokens": 8}])
def test_missing_usage_fields_default_to_zero(usage):
    assert usage_from_response({"model": MODEL, "usage": usage}) == UsageInfo(
        MODEL, (usage or {}).get("total_input_tokens", 0), 0, 0, 0, None
    )


def test_request_parts_match_measured_contract():
    request = (
        fixture("gemini_interactions_36flash_youtube_offset.json")
        .get("_meta")
        .get("request_body")
    )
    parts = request.get("input")
    measured_video = next(part for part in parts if part.get("type") == "video")
    assert (
        video_part(measured_video.get("uri"), start_s=0.0, end_s=6.0, fps=2)
        == measured_video
    )
    assert text_part("test") == {"type": "text", "text": "test"}
    assert video_part("uri") == {"type": "video", "uri": "uri"}
    assert video_part("uri", end_s=3.5) == {
        "type": "video",
        "uri": "uri",
        "processing": {"type": "static", "end_offset": "3.5s"},
    }
    assert video_part("uri", fps=1).get("processing") == {"type": "static", "fps": 1}
    schema = {"type": "object", "properties": {}}
    assert json_schema_format(schema) == {
        "type": "text",
        "mime_type": "application/json",
        "schema": schema,
    }


@pytest.mark.parametrize(
    "cls",
    [litellm.ServiceUnavailableError, litellm.APIConnectionError, litellm.Timeout],
)
def test_retryable_sdk_exceptions(cls):
    assert classify_error(sdk_error(cls)) == ErrorKind.RETRYABLE


@pytest.mark.parametrize(
    ("cls", "status"),
    [
        (litellm.BadRequestError, 400),
        (litellm.AuthenticationError, 401),
        (litellm.PermissionDeniedError, 403),
        (litellm.NotFoundError, 404),
        (litellm.UnsupportedParamsError, None),
    ],
)
def test_fatal_sdk_exceptions(cls, status):
    body = fixture("gemini_error_bad_key.json").get("response")
    assert (
        classify_error(sdk_error(cls, "GeminiException - " + json.dumps(body), status))
        == ErrorKind.FATAL
    )


def test_overloaded_object_body_is_retryable():
    body = fixture("gemini_error_overloaded.json").get("response")
    assert (
        classify_error(
            sdk_error(
                litellm.ServiceUnavailableError, "GeminiException - " + json.dumps(body)
            )
        )
        == ErrorKind.RETRYABLE
    )


def test_daily_limit_message_and_duration():
    error = daily_error()
    assert classify_error(error) == ErrorKind.DAILY_LIMIT
    assert retry_after_seconds(error) == pytest.approx(15555)


@pytest.mark.parametrize(
    ("status", "message", "expected"),
    [
        (429, "Per Day quota", ErrorKind.DAILY_LIMIT),
        (429, "DAILY quota", ErrorKind.DAILY_LIMIT),
        (429, "slow down", ErrorKind.RATE_LIMIT),
        (503, "daily", ErrorKind.RETRYABLE),
        (400, "daily", ErrorKind.FATAL),
        (None, "daily", ErrorKind.FATAL),
    ],
)
def test_status_precedes_message(status, message, expected):
    error = RuntimeError(message)
    error.status_code = status
    assert classify_error(error) == expected


@pytest.mark.parametrize(
    ("header", "expected"),
    [("3600", ErrorKind.DAILY_LIMIT), ("3599", ErrorKind.RATE_LIMIT)],
)
def test_retry_after_header_classifies_429(header, expected):
    error = sdk_error(
        litellm.RateLimitError, status=429, headers={"Retry-After": header}
    )
    assert classify_error(error) == expected
    assert retry_after_seconds(error) == float(header)


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Please retry in 2h", 7200),
        ("Please retry in 3m5s", 185),
        ("Please retry in 7s", 7),
        ("no duration", None),
    ],
)
def test_retry_duration_combinations(message, expected):
    assert retry_after_seconds(RuntimeError(message)) == expected


@pytest.mark.parametrize(
    "headers",
    [None, {}, {"retry-after": "bad"}, {"retry-after": "nan"}, {"retry-after": "-1"}],
)
def test_unusable_headers_fall_back_to_message(headers):
    error = RuntimeError("Please retry in 3m")
    error.response = SimpleNamespace(headers=headers)
    assert retry_after_seconds(error) == 180


def test_retryable_twice_then_success(call_args):
    fn = Mock(
        side_effect=[
            sdk_error(litellm.ServiceUnavailableError),
            sdk_error(litellm.ServiceUnavailableError),
            response_with_text(),
        ]
    )
    sleep = Mock()
    result = gemini_interact(
        **call_args, interactions_fn=fn, sleep=sleep, backoff_s=(0.1, 0.2, 0.3)
    )
    assert isinstance(result, InteractionResult)
    assert result.text == TEXT
    assert result.raw == response_with_text()
    assert fn.call_count == 3
    assert [call.args for call in sleep.call_args_list] == [(0.1,), (0.2,)]
    assert len(read_entries(call_args["ledger_path"]).entries) == 1


@pytest.mark.parametrize(
    "error",
    [
        daily_error(),
        sdk_error(litellm.RateLimitError),
        sdk_error(litellm.BadRequestError),
        RuntimeError("unknown"),
    ],
)
def test_non_retryable_calls_stop_without_ledger(call_args, error):
    fn, sleep = Mock(side_effect=error), Mock()
    with pytest.raises(LlmCallError) as caught:
        gemini_interact(**call_args, interactions_fn=fn, sleep=sleep)
    assert caught.value.kind == classify_error(error)
    if classify_error(error) == ErrorKind.DAILY_LIMIT:
        assert isinstance(caught.value, DailyLimitReached)
        assert caught.value.retry_after_s == 15555
    fn.assert_called_once()
    sleep.assert_not_called()
    assert not call_args["ledger_path"].exists()


@pytest.mark.parametrize(
    "cls",
    [litellm.ServiceUnavailableError, litellm.APIConnectionError, litellm.Timeout],
)
def test_retries_exhausted(call_args, cls):
    fn, sleep = Mock(side_effect=sdk_error(cls)), Mock()
    with pytest.raises(LlmCallError) as caught:
        gemini_interact(**call_args, interactions_fn=fn, sleep=sleep, max_attempts=2)
    assert caught.value.kind == ErrorKind.RETRYABLE
    assert caught.value.code == "RETRIES_EXHAUSTED"
    assert fn.call_count == 2
    sleep.assert_called_once_with(2.0)
    assert not call_args["ledger_path"].exists()


@pytest.mark.parametrize("level", ["default", "minimal", "low", "medium", "high"])
def test_request_arguments_and_thinking_comparison(call_args, level):
    fn = Mock(return_value=response_with_text())
    call_args["thinking_level"] = level
    format = json_schema_format({"type": "object"})
    gemini_interact(
        **call_args, interactions_fn=fn, response_format=format, timeout_s=42
    )
    kwargs = fn.call_args.kwargs
    expected = {
        "model": f"gemini/{MODEL}",
        "input": call_args["input_parts"],
        "api_key": call_args["api_key"],
        "timeout": 42,
        "response_format": format,
    }
    if level != "default":
        expected["generation_config"] = {"thinking_level": level}
    else:
        assert "thinking_level" not in kwargs.get("generation_config", {})
        if "generation_config" in kwargs:
            expected["generation_config"] = {}
    assert kwargs == expected
    assert "thinking_budget" not in json.dumps(kwargs)


def test_thinking_level_is_required(call_args):
    call_args.pop("thinking_level")
    fn = Mock()
    with pytest.raises(TypeError):
        gemini_interact(**call_args, interactions_fn=fn)
    fn.assert_not_called()


@pytest.mark.parametrize("cost", [None, 0.0, 0.125])
def test_success_is_recorded_immediately_with_actual_model(call_args, cost):
    raw = response_with_text()
    raw["model"] = "actual-response-model"
    fn = Mock(return_value=ResponseObject(raw, {"response_cost": cost}))
    result = gemini_interact(**call_args, interactions_fn=fn)
    entries = read_entries(call_args["ledger_path"]).entries
    assert len(entries) == 1
    entry = entries[0]
    assert entry.model == "actual-response-model"
    assert entry.requested_model == MODEL
    assert entry.provider == "gemini"
    assert entry.purpose == call_args["purpose"]
    assert entry.ts == STAMP
    assert entry.cost_usd == (cost or 0.0)
    assert entry.cost_source == ("missing" if cost is None else "response_cost")
    for name in ("input_tokens", "output_tokens", "thought_tokens", "cached_tokens"):
        assert getattr(entry, name) == getattr(result.usage, name)


def test_output_extraction_failure_still_records_paid_call(call_args):
    raw = response_with_text()
    raw.pop("steps")
    fn = Mock(return_value={**raw, "_hidden_params": {"response_cost": 0.25}})
    with pytest.raises(LlmResponseError, match="NO_MODEL_OUTPUT"):
        gemini_interact(**call_args, interactions_fn=fn)
    fn.assert_called_once()
    assert read_entries(call_args["ledger_path"]).entries[0].cost_usd == 0.25


def spend(path, cost):
    append_entry(
        path,
        LedgerEntry(
            ts=STAMP,
            provider="gemini",
            model=MODEL,
            purpose="test",
            cost_usd=cost,
            cost_source="response_cost",
        ),
    )


def test_cap_prevents_any_call(call_args):
    spend(call_args["ledger_path"], 13.0)
    fn = Mock()
    with pytest.raises(CostCapExceeded):
        gemini_interact(**call_args, interactions_fn=fn)
    fn.assert_not_called()


def test_cap_rechecked_after_backoff(call_args):
    fn = Mock(side_effect=sdk_error(litellm.ServiceUnavailableError))
    sleep = Mock(side_effect=lambda _: spend(call_args["ledger_path"], 12.0))
    with pytest.raises(CostCapExceeded):
        gemini_interact(**call_args, interactions_fn=fn, sleep=sleep)
    fn.assert_called_once()
    sleep.assert_called_once()


def test_key_removed_from_message_and_displayed_traceback(call_args):
    fn = Mock(side_effect=RuntimeError("failed " + call_args["api_key"]))
    with pytest.raises(LlmCallError) as caught:
        gemini_interact(**call_args, interactions_fn=fn)
    assert call_args["api_key"] not in str(caught.value)
    assert call_args["api_key"] not in repr(caught.value)
    assert call_args["api_key"] not in "".join(traceback.format_exception(caught.value))


def test_setting_and_sdk_resolved_at_call_time(call_args, monkeypatch):
    call_args.pop("api_key")
    require = Mock(return_value=uuid4().hex)
    fn = Mock(return_value=response_with_text())
    monkeypatch.setattr("beautyads.llm.gemini.require_setting", require)
    monkeypatch.setattr(litellm.interactions, "create", fn)
    gemini_interact(**call_args)
    require.assert_called_once_with("GEMINI_API_KEY")
    assert fn.call_args.kwargs.get("api_key") == require.return_value
    assert "response_format" not in fn.call_args.kwargs


def test_public_reexports():
    from beautyads import obs, settings

    assert ThinkingLevel is settings.ThinkingLevel
    assert CostCapExceeded is obs.CostCapExceeded


def test_local_price_map_setting_precedes_every_import():
    tree = ast.parse(Path(llm.__file__).read_text(encoding="utf-8"))
    settings = [
        node
        for node in tree.body
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and ast.unparse(node.value)
        == "os.environ.setdefault('LITELLM_LOCAL_MODEL_COST_MAP', 'True')"
    ]
    assert len(settings) == 1
    imports = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    assert min(imports) > settings[0].lineno
    assert any(key.endswith(MODEL) for key in litellm.model_cost)


@pytest.mark.parametrize("preexisting", [None, "True"])
def test_clean_import_uses_local_map_without_network(preexisting):
    environment = os.environ.copy()
    environment.pop("LITELLM_LOCAL_MODEL_COST_MAP", None)
    if preexisting is not None:
        environment["LITELLM_LOCAL_MODEL_COST_MAP"] = preexisting
    script = """
import os
import socket
def forbidden(*args, **kwargs):
    raise AssertionError("network access during import")
socket.socket.connect = forbidden
socket.create_connection = forbidden
import beautyads.llm
assert os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] == "True"
"""
    subprocess.run(
        [sys.executable, "-c", script],
        env=environment,
        check=True,
        capture_output=True,
        timeout=45,
    )
