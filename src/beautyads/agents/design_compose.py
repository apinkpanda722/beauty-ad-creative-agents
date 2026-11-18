"""Pure, local Pillow composition of copy over a text-free generated design."""

import re
import unicodedata
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from beautyads.domain.labels import CtaType

MARGIN_RATIO = 0.05
HEADLINE_HEIGHT_RATIO = 0.16
CTA_HEIGHT_RATIO = 0.06
HEADLINE_FONT_RATIO = 0.055
CTA_FONT_RATIO = 0.035
BAND_AREA_MAX_RATIO = 0.20
BAND_RGBA = (0, 0, 0, round(255 * 0.45))
TEXT_COLOR = "white"
MIN_FONT_PX = 18
MAX_HEADLINE_CHARS = 80
MAX_HEADLINE_LINES = 2
CTA_LABELS: dict[CtaType, str] = {
    CtaType.shop_now: "지금 만나보기",
    CtaType.learn_more: "자세히 보기",
    CtaType.store_mention: "매장에서 만나보세요",
    CtaType.event: "이벤트 보러 가기",
    CtaType.follow_engage: "팔로우하고 소식 받기",
    CtaType.none: "",
}
_URL = re.compile(r"(?:https?://|ftp://|file://|www\.|data:)\S+", re.IGNORECASE)
_BOLD = "Pretendard-Bold.otf"
_SEMIBOLD = "Pretendard-SemiBold.otf"
Box = tuple[int, int, int, int]


class FontMissing(Exception):
    code = "FONT_MISSING"

    def __init__(self):
        super().__init__(self.code)


@dataclass(frozen=True)
class ComposedImage:
    png_bytes: bytes
    width: int
    height: int
    headline_box: Box | None
    cta_box: Box | None
    headline_size: int | None
    cta_size: int | None
    lines: tuple[str, ...]


def cta_label(cta_type: CtaType | str) -> str | None:
    return CTA_LABELS[CtaType(cta_type)] or None


def _clean(text: str) -> str:
    text = _URL.sub("", text)
    text = "".join(
        " " if char.isspace() else char
        for char in text
        if char.isspace() or not unicodedata.category(char).startswith("C")
    )
    return " ".join(text.split())


def _load_font(directory: Path, filename: str, size: int):
    """Single font-loading seam; tests inject Pillow's bundled default font."""
    path = directory / filename
    if not path.is_file():
        raise FontMissing() from None
    return ImageFont.truetype(str(path), size=size)


def _bbox(text, font) -> Box:
    return font.getbbox(text)


def _width(text, font):
    left, _, right, _ = _bbox(text, font)
    return right - left


def _wrap(text, font, width):
    """Prefer a word boundary, then split even a single long word by character."""
    lines = []
    while text:
        end = 0
        for index in range(1, len(text) + 1):
            if _width(text[:index], font) > width:
                break
            end = index
        if end == len(text):
            lines.append(text)
            break
        # Keep an oversized character so the fitting loop can shrink/elide it.
        end = max(1, end)
        space = text.rfind(" ", 0, end + 1)
        if space > 0:
            end = space
        lines.append(text[:end].rstrip())
        text = text[end:].lstrip()
    return lines


def _height(lines, font, spacing):
    return (
        sum(_bbox(line, font)[3] - _bbox(line, font)[1] for line in lines)
        + max(0, len(lines) - 1) * spacing
    )


def _ellipsis(text, font, width):
    text = text.rstrip()
    while text and _width(text + "…", font) > width:
        text = text[:-1].rstrip()
    return text + "…" if _width(text + "…", font) <= width else ""


def layout_regions(width: int, height: int) -> dict[str, tuple[int, int, int, int]]:
    """Keep bands at the edges, clamping vertical margins for wide images."""
    margin = int(width * MARGIN_RATIO)
    vertical_margin = min(margin, int(height * MARGIN_RATIO))
    top, bottom = vertical_margin, height - vertical_margin
    return {
        "headline": (
            margin,
            top,
            width - margin,
            min(bottom, top + int(height * HEADLINE_HEIGHT_RATIO)),
        ),
        "cta": (
            margin,
            max(top, bottom - int(height * CTA_HEIGHT_RATIO)),
            width - margin,
            bottom,
        ),
    }


def _fit(text, *, directory, filename, region, max_lines, image_height, font_ratio):
    width, height = region[2] - region[0], region[3] - region[1]
    start = max(MIN_FONT_PX, int(image_height * font_ratio))
    sizes = list(range(start, MIN_FONT_PX, -2)) + [MIN_FONT_PX]
    for size in sizes:
        font = _load_font(directory, filename, size)
        spacing = max(1, size // 5)
        lines = _wrap(text, font, width) if max_lines > 1 else [text]
        if (
            len(lines) <= max_lines
            and all(_width(line, font) <= width for line in lines)
            and _height(lines, font, spacing) <= height
        ):
            return lines, font, size, spacing
    # At minimum size, elide the last visible line and discard the remainder.
    lines = lines[:max_lines]
    while lines:
        last = _ellipsis(lines[-1], font, width)
        candidate = [*lines[:-1], last]
        if (
            last
            and all(_width(line, font) <= width for line in candidate)
            and _height(candidate, font, spacing) <= height
        ):
            return candidate, font, size, spacing
        lines = lines[:-1]
    return [], font, size, spacing


def _draw(image, *, text, region, filename, directory, max_lines):
    lines, font, size, spacing = _fit(
        text,
        directory=directory,
        filename=filename,
        region=region,
        max_lines=max_lines,
        image_height=image.height,
        font_ratio=HEADLINE_FONT_RATIO if filename == _BOLD else CTA_FONT_RATIO,
    )
    if not lines:
        return None, size, ()
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    band = ImageDraw.Draw(overlay)
    left, top, right, bottom = region
    band.rectangle((left, top, right - 1, bottom - 1), fill=BAND_RGBA)
    image.paste(Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB"))
    draw = ImageDraw.Draw(image)
    y = top + (bottom - top - _height(lines, font, spacing)) // 2
    boxes = []
    for line in lines:
        lft, up, rgt, down = _bbox(line, font)
        x = left + (right - left - (rgt - lft)) // 2
        draw.text((x - lft, y - up), line, font=font, fill=TEXT_COLOR)
        boxes.append((x, y, x + rgt - lft, y + down - up))
        y += down - up + spacing
    box = (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )
    return box, size, tuple(lines)


def compose_design(
    image_bytes: bytes,
    *,
    headline: str,
    cta: str,
    font_dir: Path = Path("assets/fonts"),
) -> ComposedImage:
    """Return PNG and measured glyph boxes; never write files or call a service."""
    # Validate both packaged fonts even when one of the text regions is empty.
    _load_font(font_dir, _BOLD, MIN_FONT_PX)
    _load_font(font_dir, _SEMIBOLD, MIN_FONT_PX)
    with Image.open(BytesIO(image_bytes)) as source:
        image = source.convert("RGB")
    width, height = image.size
    regions = layout_regions(width, height)
    headline = _clean(headline)[:MAX_HEADLINE_CHARS].rstrip()
    cta = _clean(cta)
    headline_box = cta_box = headline_size = cta_size = None
    lines = ()
    if headline:
        headline_box, headline_size, lines = _draw(
            image,
            text=headline,
            region=regions["headline"],
            filename=_BOLD,
            directory=font_dir,
            max_lines=MAX_HEADLINE_LINES,
        )
    if cta:
        cta_box, cta_size, _ = _draw(
            image,
            text=cta,
            region=regions["cta"],
            filename=_SEMIBOLD,
            directory=font_dir,
            max_lines=1,
        )
    stream = BytesIO()
    image.save(stream, format="PNG")
    return ComposedImage(
        stream.getvalue(),
        width,
        height,
        headline_box,
        cta_box,
        headline_size,
        cta_size,
        lines,
    )
