"""User-run, pinned Pretendard font/license fetcher; standard library only."""

import argparse
import sys
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlsplit
from urllib.request import urlopen

MAX_FONT_BYTES = 12 * 1024 * 1024
_BASE = "https://raw.githubusercontent.com/orioncactus/pretendard/v1.3.9"
FONT_URLS = {
    "Pretendard-Bold.otf": _BASE + "/packages/pretendard/dist/public/static/Pretendard-Bold.otf",
    "Pretendard-SemiBold.otf": _BASE + "/packages/pretendard/dist/public/static/Pretendard-SemiBold.otf",
    "LICENSE-Pretendard.txt": _BASE + "/LICENSE",
}
DEFAULT_FONT_DIR = Path(__file__).resolve().parents[1] / "assets" / "fonts"


def _fetch(url, path, opener):
    temporary = None
    try:
        with opener(url, timeout=30) as response:
            with NamedTemporaryFile(dir=path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                size, digest = 0, sha256()
                while True:
                    chunk = response.read(min(64 * 1024, MAX_FONT_BYTES - size + 1))
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_FONT_BYTES:
                        raise ValueError("FONT_SIZE_LIMIT")
                    stream.write(chunk)
                    digest.update(chunk)
        temporary.replace(path)
        return size, digest.hexdigest()
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv=None, *, font_dir=DEFAULT_FONT_DIR, urlopen_fn=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="replace existing files")
    args = parser.parse_args(argv)
    opener = urlopen_fn if urlopen_fn is not None else urlopen
    for filename, url in FONT_URLS.items():
        try:
            font_dir.mkdir(parents=True, exist_ok=True)
            path = font_dir / filename
            if path.exists() and not args.force:
                body = path.read_bytes()
                size, digest = len(body), sha256(body).hexdigest()
            else:
                size, digest = _fetch(url, path, opener)
            print(f"{filename} size={size} sha256={digest}")
        except Exception:  # no URL path, response body or diagnostic values on failure
            print(f"FONT_FETCH_FAILED {urlsplit(url).hostname}", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
