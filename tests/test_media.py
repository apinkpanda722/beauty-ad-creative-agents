"""Memory-only media downloads through a fake MediaGet; no external requests."""

import inspect

import pytest

from beautyads.sources.media import (
    DEFAULT_MAX_BYTES,
    DEFAULT_TIMEOUT_S,
    DownloadedMedia,
    MediaError,
    MediaResponse,
    download_media,
)

URL = "https://media.example.invalid/video.mp4?oe=FFFFFFFF&variant=sample"


class FakeMediaGet:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def __call__(self, url, timeout_s, max_bytes):
        self.calls.append((url, timeout_s, max_bytes))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


@pytest.mark.parametrize("content_length", [4, None])
def test_download_returns_media_with_or_without_content_length(content_length):
    get = FakeMediaGet(MediaResponse(200, "video/mp4", content_length, b"test"))

    result = download_media(get, URL)

    assert isinstance(result, DownloadedMedia)
    assert result.data == b"test"
    assert result.content_type == "video/mp4"
    assert result.size == len(result.data)
    assert get.calls == [(URL, DEFAULT_TIMEOUT_S, DEFAULT_MAX_BYTES)]


@pytest.mark.parametrize(
    ("response", "code"),
    [
        # Each earlier check wins even if subsequent checks would also fail.
        (MediaResponse(403, None, 8, b""), "MEDIA_URL_UNAVAILABLE"),
        (MediaResponse(404, "text/html", 8, b""), "MEDIA_URL_UNAVAILABLE"),
        (MediaResponse(410, "video/mp4", 8, b""), "MEDIA_URL_UNAVAILABLE"),
        (MediaResponse(500, None, 8, b""), "MEDIA_HTTP_500"),
        (MediaResponse(206, "video/mp4", 4, b"test"), "MEDIA_HTTP_206"),
        (MediaResponse(200, "text/html", 8, b""), "MEDIA_NOT_VIDEO"),
        (MediaResponse(200, None, 8, b""), "MEDIA_NOT_VIDEO"),
        (MediaResponse(200, "video/mp4", 8, b""), "MEDIA_EMPTY"),
        (MediaResponse(200, "video/mp4", 8, b"test"), "MEDIA_TRUNCATED"),
        (MediaResponse(200, "video/mp4", 2, b"test"), "MEDIA_TRUNCATED"),
    ],
)
def test_failures_follow_validation_order_without_exposing_url(response, code):
    get = FakeMediaGet(response)

    with pytest.raises(MediaError) as caught:
        download_media(get, URL)

    assert caught.value.code == code
    assert str(caught.value) == code
    assert URL not in str(caught.value)
    assert URL not in repr(caught.value)
    assert "oe=" not in str(caught.value)
    assert "oe=" not in repr(caught.value)
    assert len(get.calls) == 1


def test_caller_limits_are_forwarded_and_video_content_type_is_preserved():
    get = FakeMediaGet(MediaResponse(200, "video/webm", 4, b"test"))

    result = download_media(get, URL, timeout_s=17.5, max_bytes=64, min_bytes=4)

    assert get.calls == [(URL, 17.5, 64)]
    assert result == DownloadedMedia(b"test", "video/webm", 4)


def test_caller_minimum_size_is_checked_before_content_length():
    get = FakeMediaGet(MediaResponse(200, "video/mp4", 8, b"a"))

    with pytest.raises(MediaError, match="^MEDIA_EMPTY$"):
        download_media(get, URL, min_bytes=2)


@pytest.mark.parametrize("code", ["MEDIA_TOO_LARGE", "MEDIA_REQUEST_FAILED"])
def test_transport_failure_is_propagated_without_retry(code):
    error = MediaError(code)
    get = FakeMediaGet(error)

    with pytest.raises(MediaError) as caught:
        download_media(get, URL)

    assert caught.value is error
    assert URL not in str(caught.value)
    assert URL not in repr(caught.value)
    assert len(get.calls) == 1


def test_download_defaults_use_documented_constants():
    assert DEFAULT_TIMEOUT_S == 120.0
    assert DEFAULT_MAX_BYTES == 50 * 1024 * 1024
    parameters = inspect.signature(download_media).parameters
    assert parameters["timeout_s"].default == DEFAULT_TIMEOUT_S
    assert parameters["max_bytes"].default == DEFAULT_MAX_BYTES
    assert parameters["min_bytes"].default == 1


def test_download_does_not_create_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    get = FakeMediaGet(MediaResponse(200, "video/mp4", 4, b"test"))

    result = download_media(get, URL)

    assert result.data == b"test"
    assert list(tmp_path.iterdir()) == []
