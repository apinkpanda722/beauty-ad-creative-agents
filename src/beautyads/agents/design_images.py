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
IMAGE_NO_TEXT_CLAUSE = (
    "하나의 구도로 단일 컷만 그린다(콜라주·그리드·스토리보드·여러 컷 금지). "
    "이미지에는 글자·자막·카피·로고·브랜드·제품명·라벨 문구를 넣지 않는다. "
    "제품은 무라벨 일반 병·튜브·패키지의 형태로만 묘사한다."
)


def image_prompt(plan: Plan) -> str:
    """Keep scene text, remove annotations locally, and reserve the no-text suffix."""
    parts = [plan.image_brief or ""]
    cleaned = []
    for part in parts:
        text = "\n".join(
            line
            for line in part.splitlines()
            if not line.lstrip().startswith(
                ("※", "참고:", "주의:", "설명:", "지시:", "Note:")
            )
        )
        # Remove inner comments first, including mixed nested bracket styles.
        while True:
            stripped = re.sub(
                r"\([^()]*\)|\[[^\[\]]*\]|（[^（）]*）|<[^<>]*>", "", text
            )
            if stripped == text:
                break
            text = stripped
        # Ignore quote markers in removed annotations; discard nested quoted copy.
        pairs = {'"': '"', "“": "”", "‘": "’", "'": "'", "「": "」", "『": "』"}
        stack = []
        unquoted = []
        for char in text:
            if stack and char == stack[-1]:
                stack.pop()
            elif char in pairs:
                stack.append(pairs[char])
            elif not stack:
                unquoted.append(char)
        text = "".join(unquoted)
        cleaned.extend(
            line.strip() for line in _URL.sub("", text).splitlines() if line.strip()
        )
    scene = "\n".join(cleaned)[: 2000 - len(IMAGE_NO_TEXT_CLAUSE) - 1].rstrip()
    return (scene + "\n" if scene else "") + IMAGE_NO_TEXT_CLAUSE


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


def save_composed_design(
    png_bytes: bytes,
    *,
    request_key: str,
    index: int,
    base_dir: Path = Path("data/design"),
) -> SavedImage:
    """Atomically store a composed PNG beside its unmodified generated original."""
    if type(index) is not int or index < 0:
        raise ValueError("IMAGE_INDEX_INVALID")
    directory = base_dir / sha256(request_key.encode("utf-8")).hexdigest()[:16]
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{index:02d}_composed.png"
    temporary = None
    try:
        with NamedTemporaryFile(dir=directory, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(png_bytes)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return SavedImage(path, sha256(png_bytes).hexdigest(), len(png_bytes), "image/png")
