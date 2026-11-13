"""Gemini Files contracts using injected SDK calls and synthetic bytes only."""

import json
import traceback
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call
from uuid import uuid4

import pytest

from beautyads import llm
from beautyads.llm import (
    FileError,
    UploadedFile,
    delete_file,
    file_error_code,
    upload_video,
    wait_processed,
)

FIXTURES = Path(__file__).parent / "fixtures" / "contracts"


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def flow():
    return fixture("litellm_gemini_files_flow.json")


@pytest.fixture
def failures():
    return fixture("gemini_files_failures_thinking_burst_probe.json")


class FileObject:
    def __init__(self, raw):
        self.raw = raw

    def model_dump(self):
        return dict(self.raw)


class Clock:
    def __init__(self):
        self.now = 0.0
        self.sleep = Mock(side_effect=self.advance)

    def advance(self, seconds):
        self.now += seconds

    def monotonic(self):
        return self.now


@pytest.mark.parametrize("as_object", [False, True])
def test_upload_wait_delete_contract(flow, as_object, monkeypatch):
    key = uuid4().hex
    data = b"x" * flow.get("create_file").get("bytes")
    create = Mock(
        return_value=FileObject(flow.get("create_file"))
        if as_object
        else flow.get("create_file")
    )
    statuses = [flow.get("retrieve_first"), flow.get("retrieve_processed")]
    retrieve = Mock(
        side_effect=[SimpleNamespace(**raw) if as_object else raw for raw in statuses]
    )
    delete = Mock(
        return_value=SimpleNamespace(**flow.get("file_delete"))
        if as_object
        else flow.get("file_delete")
    )
    monkeypatch.setattr("beautyads.llm.files.litellm.file_retrieve", retrieve)
    clock = Clock()

    uploaded = upload_video(
        data, filename="synthetic.mp4", api_key=key, create_file_fn=create
    )
    assert uploaded == UploadedFile(flow.get("create_file").get("id"), len(data))
    assert uploaded.id.startswith("https://generativelanguage.googleapis.com/")
    create.assert_called_once_with(
        file=("synthetic.mp4", data, "video/mp4"),
        purpose="user_data",
        custom_llm_provider="gemini",
        api_key=key,
    )
    wait_processed(
        uploaded.id,
        api_key=key,
        retrieve_fn=retrieve,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        interval_s=2.0,
    )
    clock.sleep.assert_called_once_with(2.0)
    expected = {"file_id": uploaded.id, "custom_llm_provider": "gemini", "api_key": key}
    assert retrieve.call_args_list == [call(**expected), call(**expected)]
    retrieve.reset_mock()
    assert delete_file(uploaded.id, api_key=key, delete_fn=delete) is True
    delete.assert_called_once_with(**expected)
    retrieve.assert_not_called()


def test_empty_upload_never_resolves_key_or_calls_sdk(monkeypatch):
    create, require = Mock(), Mock()
    monkeypatch.setattr("beautyads.llm.files.require_setting", require)
    with pytest.raises(FileError) as caught:
        upload_video(b"", filename="empty.mp4", create_file_fn=create)
    assert caught.value.code == "EMPTY_FILE"
    assert caught.value.retryable is False
    create.assert_not_called()
    require.assert_not_called()


def test_status_error_stops_immediately(failures):
    clock = Clock()
    retrieve = Mock(return_value=failures.get("junk_upload"))
    with pytest.raises(FileError) as caught:
        wait_processed(
            "file-id",
            api_key=uuid4().hex,
            retrieve_fn=retrieve,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )
    assert caught.value.code == "FILE_STATUS_ERROR"
    assert caught.value.retryable is False
    retrieve.assert_called_once()
    clock.sleep.assert_not_called()


@pytest.mark.parametrize("status", ["uploaded", None, "unknown"])
def test_unprocessed_file_times_out(flow, status):
    clock = Clock()
    retrieve = Mock(return_value={**flow.get("retrieve_first"), "status": status})
    with pytest.raises(FileError) as caught:
        wait_processed(
            "file-id",
            api_key=uuid4().hex,
            retrieve_fn=retrieve,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
            interval_s=2.0,
            timeout_s=3.0,
        )
    assert caught.value.code == "FILE_PROCESS_TIMEOUT"
    assert caught.value.retryable is True
    assert clock.now == 3.0
    assert retrieve.call_count == 2


def test_advanced_monotonic_times_out_without_real_wait(flow):
    retrieve, sleep = Mock(return_value=flow.get("retrieve_first")), Mock()
    monotonic = Mock(side_effect=[0.0, 0.0, 121.0])
    with pytest.raises(FileError) as caught:
        wait_processed(
            "file-id",
            api_key=uuid4().hex,
            retrieve_fn=retrieve,
            sleep=sleep,
            monotonic=monotonic,
        )
    assert caught.value.code == "FILE_PROCESS_TIMEOUT"
    assert caught.value.retryable is True
    retrieve.assert_called_once()
    sleep.assert_not_called()


@pytest.mark.parametrize("operation", ["upload", "retrieve"])
@pytest.mark.parametrize(
    ("status", "retryable"), [(503, True), (400, False), (429, False), (None, False)]
)
def test_call_exceptions_are_wrapped_and_redacted(
    operation, status, retryable, failures
):
    key = uuid4().hex
    error = ValueError(failures.get("empty_upload").get("msg") + " " + key)
    error.status_code = status
    fn = Mock(side_effect=error)
    with pytest.raises(FileError) as caught:
        if operation == "upload":
            upload_video(b"x", filename="test.mp4", api_key=key, create_file_fn=fn)
        else:
            wait_processed("file-id", api_key=key, retrieve_fn=fn)
    assert caught.value.code == (
        "FILE_UPLOAD_FAILED" if operation == "upload" else "FILE_RETRIEVE_FAILED"
    )
    assert caught.value.retryable is retryable
    assert key not in str(caught.value)
    assert key not in repr(caught.value)
    assert key not in "".join(traceback.format_exception(caught.value))
    fn.assert_called_once()


@pytest.mark.parametrize("raw", [{}, {"id": None}, {"id": "", "bytes": 1}])
def test_missing_upload_id_is_a_file_error(raw):
    with pytest.raises(FileError) as caught:
        upload_video(
            b"x",
            filename="test.mp4",
            api_key=uuid4().hex,
            create_file_fn=Mock(return_value=raw),
        )
    assert caught.value.code == "FILE_UPLOAD_FAILED"
    assert caught.value.retryable is False


@pytest.mark.parametrize("deleted", [False, None, 1, "true"])
def test_delete_requires_boolean_true(deleted):
    assert (
        delete_file(
            "file-id",
            api_key=uuid4().hex,
            delete_fn=Mock(return_value={"deleted": deleted}),
        )
        is False
    )


def test_delete_missing_flag_or_exception_never_raises():
    for fn in (Mock(return_value={}), Mock(side_effect=ValueError("cleanup failed"))):
        assert delete_file("file-id", api_key=uuid4().hex, delete_fn=fn) is False


def test_delete_setting_failure_never_raises(monkeypatch):
    require = Mock(side_effect=RuntimeError("missing setting"))
    monkeypatch.setattr("beautyads.llm.files.require_setting", require)
    delete = Mock()
    assert delete_file("file-id", delete_fn=delete) is False
    delete.assert_not_called()


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("analyze_deleted_file", "FILE_NOT_FOUND"),
        ("analyze_missing_file", "FILE_NOT_FOUND"),
        ("analyze_junk", "FILE_NOT_ACTIVE"),
    ],
)
def test_file_error_codes_from_measured_messages(failures, name, code):
    error = failures.get(name).get("body").get("error")
    for message in (error.get("message"), json.dumps(error)):
        for case in (message, message.upper(), message.lower()):
            assert file_error_code(case) == code


@pytest.mark.parametrize(
    ("message", "code"),
    [
        ("PERMISSION_DENIED", "FILE_NOT_FOUND"),
        ("may NOT exist", "FILE_NOT_FOUND"),
        ("unrelated failure", None),
        ("", None),
    ],
)
def test_file_error_patterns(message, code):
    assert file_error_code(message) == code


def test_default_sdk_functions_and_setting_resolve_at_call_time(flow, monkeypatch):
    key = uuid4().hex
    require = Mock(return_value=key)
    create = Mock(return_value=flow.get("create_file"))
    retrieve = Mock(return_value=flow.get("retrieve_processed"))
    delete = Mock(return_value=flow.get("file_delete"))
    monkeypatch.setattr("beautyads.llm.files.require_setting", require)
    for name, fn in (
        ("create_file", create),
        ("file_retrieve", retrieve),
        ("file_delete", delete),
    ):
        monkeypatch.setattr("beautyads.llm.files.litellm." + name, fn)
    uploaded = upload_video(b"x", filename="test.webm", mime_type="video/webm")
    wait_processed(uploaded.id)
    assert delete_file(uploaded.id) is True
    assert require.call_args_list == [call("GEMINI_API_KEY")] * 3
    for fn in (create, retrieve, delete):
        fn.assert_called_once()
        assert fn.call_args.kwargs.get("api_key") == key
        assert fn.call_args.kwargs.get("custom_llm_provider") == "gemini"
    assert create.call_args.kwargs.get("file") == ("test.webm", b"x", "video/webm")


def test_public_file_exports():
    from beautyads.llm import files

    for name in (
        "UploadedFile",
        "FileError",
        "upload_video",
        "wait_processed",
        "delete_file",
        "file_error_code",
    ):
        assert getattr(llm, name) is getattr(files, name)
        assert name in llm.__all__
