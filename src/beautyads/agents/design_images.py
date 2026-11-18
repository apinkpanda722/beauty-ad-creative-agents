"""Pure text briefs and local, atomic storage for optional generated designs."""

import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile

from beautyads.domain.plan import Plan
from beautyads.llm import ImageOutcome

_URL = re.compile(r"\b(?:[a-z][a-z0-9+.-]*://|data:|www\.)\S+", re.IGNORECASE)
_EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}


def image_prompt(plan: Plan) -> str:
    """Use selected plan text only; references and product URLs stay out of prompts."""
    parts = [plan.image_brief or "", plan.hook_text, *plan.scenes]
    return "\n".join(_URL.sub("", part) for part in parts)[:2000]


@dataclass(frozen=True)
class SavedImage:
    path: Path
    sha256: str
    size: int
    mime: str


def save_design_image(
    outcome: ImageOutcome,
    *,
    request_key: str,
    index: int,
    base_dir: Path = Path("data/design"),
) -> SavedImage:
    """Replace the destination only after a complete write in the same directory."""
    if (
        not outcome.ok
        or outcome.image_bytes is None
        or outcome.mime not in _EXTENSIONS
        or outcome.sha256 is None
        or outcome.size is None
    ):
        raise ValueError("IMAGE_NOT_SAVABLE")
    if type(index) is not int or index < 0:
        raise ValueError("IMAGE_INDEX_INVALID")
    directory = base_dir / sha256(request_key.encode("utf-8")).hexdigest()[:16]
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{index:02d}.{_EXTENSIONS[outcome.mime]}"
    temporary = None
    try:
        with NamedTemporaryFile(dir=directory, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(outcome.image_bytes)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return SavedImage(path, outcome.sha256, outcome.size, outcome.mime)
