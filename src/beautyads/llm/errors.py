"""HTTP status takes precedence over provider error body shapes."""

import re
from collections.abc import Mapping
from enum import StrEnum
from math import isfinite

import litellm


class ErrorKind(StrEnum):
    RETRYABLE = "RETRYABLE"
    DAILY_LIMIT = "DAILY_LIMIT"
    RATE_LIMIT = "RATE_LIMIT"
    FATAL = "FATAL"


class LlmResponseError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class LlmCallError(Exception):
    """Call failures contain a stable code and a caller-sanitized message."""

    def __init__(
        self,
        *,
        kind: ErrorKind,
        code: str,
        message: str = "",
        retry_after_s: float | None = None,
    ):
        self.kind = kind
        self.code = code
        self.retry_after_s = retry_after_s
        super().__init__(f"{code}: {message}" if message else code)


class DailyLimitReached(LlmCallError):
    """Stop the batch rather than consuming further daily quota."""


def retry_after_seconds(exc: BaseException) -> float | None:
    response = getattr(exc, "response", None)
    headers = (
        response.get("headers")
        if isinstance(response, Mapping)
        else getattr(response, "headers", None)
    )
    if isinstance(headers, Mapping):
        value = next(
            (
                value
                for key, value in headers.items()
                if str(key).lower() == "retry-after"
            ),
            None,
        )
        try:
            seconds = float(value)
        except (TypeError, ValueError, OverflowError):
            pass
        else:
            if isfinite(seconds) and seconds >= 0:
                return seconds
    duration = re.search(
        r"Please retry in\s+((?:\d+[hms]\s*)+)", str(exc), flags=re.IGNORECASE
    )
    if duration is None:
        return None
    multipliers = {"h": 3600, "m": 60, "s": 1}
    return float(
        sum(
            int(value) * multipliers[unit.lower()]
            for value, unit in re.findall(
                r"(\d+)([hms])", duration.group(1), re.IGNORECASE
            )
        )
    )


def classify_error(exc: BaseException) -> ErrorKind:
    status = getattr(exc, "status_code", None)
    if status == 429 or isinstance(exc, litellm.RateLimitError):
        retry_after = retry_after_seconds(exc)
        message = str(exc).lower()
        if (
            retry_after is not None
            and retry_after >= 3600
            or "per day" in message
            or "daily" in message
        ):
            return ErrorKind.DAILY_LIMIT
        return ErrorKind.RATE_LIMIT
    if status in {400, 401, 403, 404}:
        return ErrorKind.FATAL
    if status == 503 or isinstance(
        exc,
        (litellm.ServiceUnavailableError, litellm.APIConnectionError, litellm.Timeout),
    ):
        return ErrorKind.RETRYABLE
    return ErrorKind.FATAL
