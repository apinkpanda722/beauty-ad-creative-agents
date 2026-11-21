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
IMAGE_STYLE_CLAUSE = (
    "장면은 훅 문구를 가장 잘 보여 주는 하나의 순간으로 고르고 기본은 사용 장면이다(손등이나 볼에 제품을 바르는 손과 피부 클로즈업). "
    "얼굴 전체를 정면으로 잡는 구도와 병이나 튜브를 코나 입에 대는 구도는 그리지 않는다. "
    "유리병 용기는 내용물이 보여야 한다(맑은 물처럼 투명한 액체 금지, 세럼은 약간 점성이 있는 연한 색 액체와 스포이트 형태). "
    "튜브는 전체가 불투명한 단색 소재의 닫힌 튜브이며 내용물이 비쳐 보이지 않고(내용물은 손가락 끝에 덜어낸 모습으로만 보인다) 튜브 끝을 얼굴 쪽으로 향하게 하거나 얼굴에 대지 않는다. "
    "같은 제품은 화면에 한 개만 그리고 스포이트를 든 손이 있으면 병 안에 스포이트를 또 그리지 않는다. "
    "제품을 얼굴에 직접 대거나 문지르지 말고 손가락 끝에 덜어 바르는 모습으로 그린다. 인물이 나오면 한국인 모델이다."
)
IMAGE_PROMPT_SUFFIX = IMAGE_STYLE_CLAUSE + " " + IMAGE_NO_TEXT_CLAUSE


def image_prompt(plan: Plan) -> str:
    """Clean only scene text and reserve the complete style and no-text suffix."""
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
    scene = "\n".join(cleaned)[: 2000 - len(IMAGE_PROMPT_SUFFIX) - 1].rstrip()
    return (scene + "\n" if scene else "") + IMAGE_PROMPT_SUFFIX


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
