"""Font fetch CLI is exercised with injected byte streams, never a network."""

from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
from io import BytesIO
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlsplit

import pytest

_SPEC = spec_from_file_location(
    "fetch_design_font", Path(__file__).parents[1] / "scripts" / "fetch_design_font.py"
)
fetch = module_from_spec(_SPEC)
_SPEC.loader.exec_module(fetch)


def test_fixed_downloads_atomic_write_and_metadata(tmp_path, capsys, monkeypatch):
    calls, replacements = [], []
    body = b"synthetic font or license"
    replace = Path.replace

    def opened(url, **kwargs):
        assert kwargs["timeout"] > 0
        calls.append(url)
        return BytesIO(body)

    def replaced(source, target):
        assert source.parent == target.parent and source != target
        assert source.read_bytes() == body and not target.exists()
        replacements.append(target.name)
        return replace(source, target)

    monkeypatch.setattr(Path, "replace", replaced)
    assert fetch.main([], font_dir=tmp_path, urlopen_fn=opened) == 0
    assert (
        set(replacements)
        == set(fetch.FONT_URLS)
        == {"Pretendard-Bold.otf", "Pretendard-SemiBold.otf", "LICENSE-Pretendard.txt"}
    )
    assert calls == list(fetch.FONT_URLS.values())
    assert all(
        urlsplit(url).hostname == "raw.githubusercontent.com" and "/v1.3.9/" in url
        for url in calls
    )
    for name, url in fetch.FONT_URLS.items():
        assert url.endswith(
            "/LICENSE"
            if name.startswith("LICENSE")
            else "/packages/pretendard/dist/public/static/" + name
        )
        assert (tmp_path / name).read_bytes() == body
    output = capsys.readouterr().out
    for name in fetch.FONT_URLS:
        assert name in output
    assert str(len(body)) in output and sha256(body).hexdigest() in output
    assert {path.name for path in tmp_path.iterdir()} == set(fetch.FONT_URLS)
    assert fetch.MAX_FONT_BYTES == 12 * 1024 * 1024


@pytest.mark.parametrize("force", [False, True])
def test_existing_files_are_kept_unless_forced(tmp_path, force):
    for name in fetch.FONT_URLS:
        (tmp_path / name).write_bytes(b"original")
    calls = []

    def opened(url, **kwargs):
        calls.append(url)
        return BytesIO(b"replacement")

    assert (
        fetch.main(["--force"] if force else [], font_dir=tmp_path, urlopen_fn=opened)
        == 0
    )
    assert len(calls) == (len(fetch.FONT_URLS) if force else 0)
    assert all(
        (tmp_path / name).read_bytes() == (b"replacement" if force else b"original")
        for name in fetch.FONT_URLS
    )


@pytest.mark.parametrize("failure", ["oversize", "network", "partial"])
def test_failed_download_is_safe_and_leaves_no_partial_file(
    tmp_path, monkeypatch, capsys, failure
):
    monkeypatch.setattr(fetch, "MAX_FONT_BYTES", 10)

    class Broken(BytesIO):
        def read(self, size=-1):
            if self.tell():
                raise OSError("synthetic-private-diagnostic")
            return super().read(2)

    def opened(url, **kwargs):
        if failure == "network":
            raise URLError("synthetic-private-url-query-value")
        return Broken(b"partial") if failure == "partial" else BytesIO(b"X" * 11)

    assert fetch.main([], font_dir=tmp_path, urlopen_fn=opened) == 2
    output = capsys.readouterr()
    assert (
        "FONT_FETCH_FAILED" in output.err and "raw.githubusercontent.com" in output.err
    )
    assert "synthetic-private" not in output.err + output.out
    assert "https://" not in output.err and "/v1.3.9/" not in output.err
    assert list(tmp_path.iterdir()) == []


def test_failed_force_keeps_previous_file(tmp_path, capsys):
    name = next(iter(fetch.FONT_URLS))
    (tmp_path / name).write_bytes(b"previous")

    def opened(*args, **kwargs):
        raise URLError("synthetic-private")

    assert fetch.main(["--force"], font_dir=tmp_path, urlopen_fn=opened) == 2
    assert (tmp_path / name).read_bytes() == b"previous"
    assert list(tmp_path.iterdir()) == [tmp_path / name]


def test_exact_size_limit_is_allowed(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "MAX_FONT_BYTES", 10)
    assert (
        fetch.main(
            [], font_dir=tmp_path, urlopen_fn=lambda *a, **kw: BytesIO(b"X" * 10)
        )
        == 0
    )
    assert all((tmp_path / name).stat().st_size == 10 for name in fetch.FONT_URLS)


def test_make_target_is_separate_from_verify():
    text = (Path(__file__).parents[1] / "Makefile").read_text()
    assert ".PHONY: fetch-font\n" in text
    assert "fetch-font:\n\tuv run python scripts/fetch_design_font.py $(ARGS)" in text
    body = text.split("verify:\n", 1)[1].split("\n\n", 1)[0]
    assert "fetch-" not in body
