"""Download transient video URLs into memory through an injectable HTTP boundary."""

from collections.abc import Callable
from typing import NamedTuple

# Measured: an 8.19 MB video took 9.9 s; a 29.5 MB TikTok video may take
# roughly 36 s, with substantial variation between downloads.
DEFAULT_TIMEOUT_S = 120.0
# Leave headroom above the largest measured TikTok video (29.5 MB).
DEFAULT_MAX_BYTES = 50 * 1024 * 1024


class MediaResponse(NamedTuple):
    status: int
    content_type: str | None
    content_length: int | None
    data: bytes


MediaGet = Callable[[str, float, int], MediaResponse]


class MediaError(Exception):
    """A stable code without transient URLs or transport diagnostics."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class DownloadedMedia(NamedTuple):
    data: bytes
    content_type: str
    size: int


def httpx_media_get(url: str, timeout_s: float, max_bytes: int) -> MediaResponse:
    """The sole httpx boundary; stream with a bounded in-memory buffer."""
    import httpx

    try:
        with httpx.stream(
            "GET", url, timeout=timeout_s, follow_redirects=True
        ) as response:
            content_type = response.headers.get("Content-Type")
            raw_length = response.headers.get("Content-Length")
            try:
                content_length = int(raw_length) if raw_length is not None else None
            except ValueError:
                content_length = None
            data = bytearray()
            for chunk in response.iter_bytes():
                if len(data) + len(chunk) > max_bytes:
                    raise MediaError("MEDIA_TOO_LARGE")
                data.extend(chunk)
            return MediaResponse(
                response.status_code, content_type, content_length, bytes(data)
            )
    except httpx.RequestError:
        raise MediaError("MEDIA_REQUEST_FAILED") from None


def download_media(
    get: MediaGet,
    url: str,
    *,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    max_bytes: int = DEFAULT_MAX_BYTES,
    min_bytes: int = 1,
) -> DownloadedMedia:
    """Validate one response; the caller limits concurrency and refreshes URLs."""
    response = get(url, timeout_s, max_bytes)
    if response.status != 200:
        if response.status in {403, 404, 410}:
            raise MediaError("MEDIA_URL_UNAVAILABLE")
        raise MediaError(f"MEDIA_HTTP_{response.status}")
    if response.content_type is None or not response.content_type.startswith("video/"):
        raise MediaError("MEDIA_NOT_VIDEO")
    size = len(response.data)
    if size < min_bytes:
        raise MediaError("MEDIA_EMPTY")
    if response.content_length is not None and response.content_length != size:
        raise MediaError("MEDIA_TRUNCATED")
    return DownloadedMedia(response.data, response.content_type, size)
