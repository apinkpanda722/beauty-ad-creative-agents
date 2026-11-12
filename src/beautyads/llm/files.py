"""Gemini Files lifecycle via LiteLLM, without token cost ledger entries."""

import time
from collections.abc import Callable, Mapping
from typing import Any, NamedTuple

import litellm

from beautyads.settings import require_setting

from .errors import ErrorKind, classify_error


class UploadedFile(NamedTuple):
    id: str
    size_bytes: int


class FileError(Exception):
    """A stable file failure code with a caller-sanitized message."""

    def __init__(self, code: str, *, retryable: bool = False, message: str = ""):
        self.code = code
        self.retryable = retryable
        super().__init__(f"{code}: {message}" if message else code)


def _field(response: Any, name: str) -> Any:
    if isinstance(response, Mapping):
        return response.get(name)
    return getattr(response, name, None)


def _call_error(code: str, exc: Exception, key: str) -> FileError:
    message = str(exc).replace(key, "[redacted]") if key else str(exc)
    return FileError(
        code,
        retryable=classify_error(exc) == ErrorKind.RETRYABLE,
        message=message,
    )


def upload_video(
    data: bytes,
    *,
    filename: str,
    mime_type: str = "video/mp4",
    api_key: str | None = None,
    create_file_fn: Callable[..., Any] | None = None,
) -> UploadedFile:
    if len(data) == 0:
        raise FileError("EMPTY_FILE")
    key = api_key if api_key is not None else require_setting("GEMINI_API_KEY")
    create = create_file_fn if create_file_fn is not None else litellm.create_file
    try:
        response = create(
            file=(filename, data, mime_type),
            purpose="user_data",
            custom_llm_provider="gemini",
            api_key=key,
        )
        raw = response if isinstance(response, Mapping) else response.model_dump()
        file_id, size = raw.get("id"), raw.get("bytes")
        if not isinstance(file_id, str) or not file_id:
            raise ValueError("File upload response has no id")
        if type(size) is not int or size < 0:
            raise ValueError("File upload response has no valid byte count")
        return UploadedFile(file_id, size)
    except Exception as exc:  # noqa: BLE001 -- normalize SDK and parsing errors
        raise _call_error("FILE_UPLOAD_FAILED", exc, key) from None


def wait_processed(
    file_id: str,
    *,
    api_key: str | None = None,
    retrieve_fn: Callable[..., Any] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    interval_s: float = 2.0,
    timeout_s: float = 120.0,
) -> None:
    key = api_key if api_key is not None else require_setting("GEMINI_API_KEY")
    retrieve = retrieve_fn if retrieve_fn is not None else litellm.file_retrieve
    deadline = monotonic() + timeout_s
    while True:
        if monotonic() >= deadline:
            raise FileError("FILE_PROCESS_TIMEOUT", retryable=True)
        try:
            response = retrieve(
                file_id=file_id, custom_llm_provider="gemini", api_key=key
            )
            status = _field(response, "status")
        except Exception as exc:  # noqa: BLE001 -- SDK failures become file errors
            raise _call_error("FILE_RETRIEVE_FAILED", exc, key) from None
        if status == "processed":
            return
        if status == "error":
            raise FileError("FILE_STATUS_ERROR")
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise FileError("FILE_PROCESS_TIMEOUT", retryable=True)
        sleep(min(interval_s, remaining))


def delete_file(
    file_id: str,
    *,
    api_key: str | None = None,
    delete_fn: Callable[..., Any] | None = None,
) -> bool:
    try:
        key = api_key if api_key is not None else require_setting("GEMINI_API_KEY")
        delete = delete_fn if delete_fn is not None else litellm.file_delete
        response = delete(file_id=file_id, custom_llm_provider="gemini", api_key=key)
        return _field(response, "deleted") is True
    except Exception:  # noqa: BLE001 -- cleanup must never mask analysis results
        return False


def file_error_code(message: str) -> str | None:
    message = message.lower()
    if "permission_denied" in message or "may not exist" in message:
        return "FILE_NOT_FOUND"
    if "not in an active state" in message:
        return "FILE_NOT_ACTIVE"
    return None
