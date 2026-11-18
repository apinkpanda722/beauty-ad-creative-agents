"""Pure, local Pillow composition of copy over a text-free generated design."""

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from beautyads.domain.labels import CtaType

MARGIN_RATIO = 0.05
HEADLINE_HEIGHT_RATIO = 0.16
CTA_HEIGHT_RATIO = 0.06
HEADLINE_FONT_RATIO = 0.055
CTA_FONT_RATIO = 0.035
BAND_AREA_MAX_RATIO = 0.20
TEXT_COLOR = "white"
PRODUCT_HEIGHT_RATIO = 0.045
PRODUCT_FONT_RATIO = 0.03
MAX_PRODUCT_LINE_CHARS = 60
# 2026-11-18: replace bands with subtle shadows and local large-text AA contrast (B안).
MIN_CONTRAST_RATIO = 3.0
SCRIM_MAX_ALPHA = 0.5
SCRIM_STEP = 0.05
SHADOW_OFFSET_RATIO = 0.04
SHADOW_BLUR_RATIO = 0.05
SHADOW_ALPHA = 0.6
DARK_TEXT = (17, 17, 17)
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
    headline_contrast: float | None = None
    headline_scrim: float = 0.0
    headline_color: str | None = None
    product_box: Box | None = None
    product_size: int | None = None
    product_text: str | None = None
    product_contrast: float | None = None
    product_scrim: float = 0.0
    product_color: str | None = None
    cta_contrast: float | None = None
    cta_scrim: float = 0.0
    cta_color: str | None = None
    contrast_adjusted: bool = False
    min_contrast: float | None = None


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


def product_line(brand: str | None, product_name: str | None) -> str:
    """Format server brand and official mall name; never infer another identity."""
    brand = _clean(brand.replace("_", " ")) if isinstance(brand, str) else ""
    name = _clean(product_name) if isinstance(product_name, str) else ""
    name = re.sub(
        r"[\s,()]*\d+(?:\.\d+)?\s*(?:ml|mL|kg|g|l|L|매|입|ea|개)[\s,()]*",
        " ",
        name,
    )
    name = _clean(name)
    return "  ".join(part for part in (brand, name) if part)[
        :MAX_PRODUCT_LINE_CHARS
    ].rstrip()


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
    """Reserve separate text regions at the edges, leaving the center untouched."""
    margin = int(width * MARGIN_RATIO)
    vertical_margin = min(margin, int(height * MARGIN_RATIO))
    top, bottom = vertical_margin, height - vertical_margin
    product_top = bottom - int(height * PRODUCT_HEIGHT_RATIO)
    return {
        "headline": (
            margin,
            top,
            width - margin,
            min(bottom, top + int(height * HEADLINE_HEIGHT_RATIO)),
        ),
        "cta": (
            margin,
            max(top, product_top - int(height * CTA_HEIGHT_RATIO)),
            width - margin,
            product_top,
        ),
        "product": (margin, product_top, width - margin, bottom),
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


def _luminance(rgb) -> float:
    channels = [value / 255 for value in rgb]
    linear = [
        value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        for value in channels
    ]
    return sum(
        value * weight
        for value, weight in zip(linear, (0.2126, 0.7152, 0.0722), strict=True)
    )


def _contrasts(image, box) -> tuple[float, float]:
    """Exact pixel percentiles, counting repeated RGB values only once."""
    counts = Counter(image.crop(box).getdata())
    values = sorted((_luminance(rgb), count) for rgb, count in counts.items())
    total = sum(counts.values())
    percentiles = []
    for fraction in (0.1, 0.9):
        rank, cumulative = int((total - 1) * fraction), 0
        for value, count in values:
            cumulative += count
            if cumulative > rank:
                percentiles.append(value)
                break
    low, high = percentiles
    return 1.05 / (high + 0.05), (low + 0.05) / (_luminance(DARK_TEXT) + 0.05)


def _scrim(patch, *, alpha, color, edge):
    """Fade from the outside image edge to zero across this region only."""
    mask = Image.new("L", patch.size, 0)
    draw = ImageDraw.Draw(mask)
    for y in range(patch.height):
        fraction = y / max(1, patch.height - 1)
        strength = 1 - fraction if edge == "top" else fraction
        draw.line((0, y, patch.width - 1, y), fill=round(255 * alpha * strength))
    background = "black" if color == "white" else "white"
    return Image.composite(Image.new("RGB", patch.size, background), patch, mask)


def _contrast_style(original, *, box, region, edge):
    patch = original.crop(region)
    local_box = (
        box[0] - region[0],
        box[1] - region[1],
        box[2] - region[0],
        box[3] - region[1],
    )
    white, dark = _contrasts(patch, local_box)
    if white >= MIN_CONTRAST_RATIO:
        return "white", 0.0, white, None
    if dark >= MIN_CONTRAST_RATIO:
        return "dark", 0.0, dark, None
    color = "white" if white >= dark else "dark"
    index = 0 if color == "white" else 1
    for step in range(1, round(SCRIM_MAX_ALPHA / SCRIM_STEP) + 1):
        alpha = min(SCRIM_MAX_ALPHA, round(step * SCRIM_STEP, 10))
        adjusted = _scrim(patch, alpha=alpha, color=color, edge=edge)
        contrast = _contrasts(adjusted, local_box)[index]
        if contrast >= MIN_CONTRAST_RATIO:
            break
    return color, alpha, contrast, adjusted


def _draw(
    image, *, original, text, region, filename, directory, max_lines, font_ratio, edge
):
    lines, font, size, spacing = _fit(
        text,
        directory=directory,
        filename=filename,
        region=region,
        max_lines=max_lines,
        image_height=image.height,
        font_ratio=font_ratio,
    )
    if not lines:
        return {
            "box": None,
            "size": size,
            "lines": (),
            "contrast": None,
            "scrim": 0.0,
            "color": None,
        }
    left, top, right, bottom = region
    y = top + (bottom - top - _height(lines, font, spacing)) // 2
    boxes, positions = [], []
    for line in lines:
        lft, up, rgt, down = _bbox(line, font)
        x = left + (right - left - (rgt - lft)) // 2
        positions.append((x - lft - left, y - up - top))
        boxes.append((x, y, x + rgt - lft, y + down - up))
        y += down - up + spacing
    box = (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )
    color, alpha, contrast, patch = _contrast_style(
        original, box=box, region=region, edge=edge
    )
    if patch is not None:
        image.paste(patch, (left, top))
    # Clip blurred shadows to the text region so the central artwork stays intact.
    shadow = Image.new("RGBA", (right - left, bottom - top), (0, 0, 0, 0))
    draw = ImageDraw.Draw(shadow)
    offset = max(1, round(size * SHADOW_OFFSET_RATIO))
    shadow_rgb = (0, 0, 0) if color == "white" else (255, 255, 255)
    for position, line in zip(positions, lines, strict=True):
        draw.text(
            (position[0] + offset, position[1] + offset),
            line,
            font=font,
            fill=(*shadow_rgb, round(255 * SHADOW_ALPHA)),
        )
    shadow = shadow.filter(ImageFilter.GaussianBlur(max(1, size * SHADOW_BLUR_RATIO)))
    patch = Image.alpha_composite(image.crop(region).convert("RGBA"), shadow).convert(
        "RGB"
    )
    draw = ImageDraw.Draw(patch)
    for position, line in zip(positions, lines, strict=True):
        draw.text(
            position,
            line,
            font=font,
            fill=TEXT_COLOR if color == "white" else DARK_TEXT,
        )
    image.paste(patch, (left, top))
    return {
        "box": box,
        "size": size,
        "lines": tuple(lines),
        "contrast": contrast,
        "scrim": alpha,
        "color": color,
    }


def compose_design(
    image_bytes: bytes,
    *,
    headline: str,
    cta: str = "",
    product_line: str = "",
    with_cta: bool = False,
    font_dir: Path = Path("assets/fonts"),
) -> ComposedImage:
    """Return PNG and measured glyph boxes; never write files or call a service."""
    # Validate both packaged fonts even when one of the text regions is empty.
    _load_font(font_dir, _BOLD, MIN_FONT_PX)
    _load_font(font_dir, _SEMIBOLD, MIN_FONT_PX)
    with Image.open(BytesIO(image_bytes)) as source:
        image = source.convert("RGB")
    original = image.copy()
    width, height = image.size
    regions = layout_regions(width, height)
    texts = {
        "headline": _clean(headline)[:MAX_HEADLINE_CHARS].rstrip(),
        "product": "  ".join(
            clean for part in product_line.split("  ") if (clean := _clean(part))
        ),
        "cta": _clean(cta) if with_cta else "",
    }
    elements = {}
    for name, filename, max_lines, ratio, edge in (
        ("headline", _BOLD, MAX_HEADLINE_LINES, HEADLINE_FONT_RATIO, "top"),
        ("product", _SEMIBOLD, 1, PRODUCT_FONT_RATIO, "bottom"),
        ("cta", _SEMIBOLD, 1, CTA_FONT_RATIO, "bottom"),
    ):
        elements[name] = (
            _draw(
                image,
                original=original,
                text=texts[name],
                region=regions[name],
                filename=filename,
                directory=font_dir,
                max_lines=max_lines,
                font_ratio=ratio,
                edge=edge,
            )
            if texts[name]
            else {
                "box": None,
                "size": None,
                "lines": (),
                "contrast": None,
                "scrim": 0.0,
                "color": None,
            }
        )
    headline, product, cta = (elements[name] for name in ("headline", "product", "cta"))
    contrasts = [
        item["contrast"] for item in elements.values() if item["box"] is not None
    ]
    stream = BytesIO()
    image.save(stream, format="PNG")
    return ComposedImage(
        stream.getvalue(),
        width,
        height,
        headline["box"],
        cta["box"],
        headline["size"],
        cta["size"],
        headline["lines"],
        headline_contrast=headline["contrast"],
        headline_scrim=headline["scrim"],
        headline_color=headline["color"],
        product_box=product["box"],
        product_size=product["size"],
        product_text=product["lines"][0] if product["lines"] else None,
        product_contrast=product["contrast"],
        product_scrim=product["scrim"],
        product_color=product["color"],
        cta_contrast=cta["contrast"],
        cta_scrim=cta["scrim"],
        cta_color=cta["color"],
        contrast_adjusted=any(
            item["color"] == "dark" or item["scrim"] > 0 for item in elements.values()
        ),
        min_contrast=min(contrasts) if contrasts else None,
    )
