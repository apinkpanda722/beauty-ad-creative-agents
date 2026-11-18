"""Deterministic layout checks use synthetic pixels and Pillow's bundled font."""

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageFont

from beautyads.agents import design_compose as compose
from beautyads.domain.labels import CtaType


def pixels(size=(1024, 1024), mode="RGB"):
    stream = BytesIO()
    Image.new(mode, size, "#7294b6").save(stream, format="PNG")
    return stream.getvalue()


@pytest.fixture
def fonts(monkeypatch, tmp_path):
    calls = []

    def load(directory, filename, size):
        assert directory == tmp_path
        calls.append((filename, size))
        return ImageFont.load_default(size=size)

    monkeypatch.setattr(compose, "_load_font", load)
    return tmp_path, calls


def inside(box, region):
    assert box is not None
    left, top, right, bottom = box
    assert region[0] <= left < right <= region[2]
    assert region[1] <= top < bottom <= region[3]


@pytest.mark.parametrize("mode", ["RGB", "RGBA", "L"])
def test_png_dimensions_safe_regions_and_original_pixels(fonts, mode):
    font_dir, calls = fonts
    source = pixels(mode=mode)
    original = bytes(source)
    value = compose.compose_design(
        source, headline="Synthetic headline", cta="View details", font_dir=font_dir
    )
    assert value.png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    assert (value.width, value.height) == (1024, 1024)
    margin = int(1024 * compose.MARGIN_RATIO)
    inside(
        value.headline_box,
        (
            margin,
            margin,
            1024 - margin,
            margin + int(1024 * compose.HEADLINE_HEIGHT_RATIO),
        ),
    )
    inside(
        value.cta_box,
        (
            margin,
            1024 - margin - int(1024 * compose.CTA_HEIGHT_RATIO),
            1024 - margin,
            1024 - margin,
        ),
    )
    with (
        Image.open(BytesIO(value.png_bytes)) as rendered,
        Image.open(BytesIO(source)) as before,
    ):
        assert rendered.mode == "RGB"
        assert rendered.size == before.size
        assert rendered.getpixel((512, 512)) == before.convert("RGB").getpixel(
            (512, 512)
        )
        assert rendered.getpixel((0, 0)) == before.convert("RGB").getpixel((0, 0))
        # A point inside the band but away from the centered text is darkened.
        assert rendered.getpixel((margin + 1, margin + 1)) != before.convert(
            "RGB"
        ).getpixel((margin + 1, margin + 1))
    assert source == original
    assert {name for name, _ in calls} == {
        "Pretendard-Bold.otf",
        "Pretendard-SemiBold.otf",
    }


@pytest.mark.parametrize("headline", ["W" * 80, "word " * 16])
def test_wraps_and_shrinks_with_at_most_three_lines(fonts, headline):
    directory, _ = fonts
    short = compose.compose_design(pixels(), headline="Hi", cta="", font_dir=directory)
    long = compose.compose_design(
        pixels(), headline=headline, cta="", font_dir=directory
    )
    assert 1 < len(long.lines) <= compose.MAX_HEADLINE_LINES
    assert compose.MIN_FONT_PX <= long.headline_size < short.headline_size
    inside(long.headline_box, compose.layout_regions(1024, 1024)["headline"])
    assert short.headline_size > compose.MIN_FONT_PX


def test_minimum_font_ellipsizes_headline_and_single_line_cta(fonts):
    directory, _ = fonts
    value = compose.compose_design(
        pixels((100, 1024)), headline="W" * 800, cta="W" * 800, font_dir=directory
    )
    assert value.headline_size == value.cta_size == compose.MIN_FONT_PX
    assert len(value.lines) <= compose.MAX_HEADLINE_LINES and value.lines[-1].endswith(
        "…"
    )
    inside(value.headline_box, compose.layout_regions(100, 1024)["headline"])
    inside(value.cta_box, compose.layout_regions(100, 1024)["cta"])
    # CTA has no returned line list; ensure the actually rendered text is elided.


def test_cta_ellipsis_and_centered_text_are_actually_drawn(fonts, monkeypatch):
    directory, _ = fonts
    drawn = []
    original = compose.ImageDraw.ImageDraw.text

    def record(self, position, text, *args, **kwargs):
        drawn.append(text)
        return original(self, position, text, *args, **kwargs)

    monkeypatch.setattr(compose.ImageDraw.ImageDraw, "text", record)
    compose.compose_design(
        pixels((100, 1024)), headline="", cta="W" * 80, font_dir=directory
    )
    assert len(drawn) == 1 and drawn[0].endswith("…")


def test_empty_text_has_no_bands_or_boxes(fonts):
    directory, _ = fonts
    source = pixels()
    value = compose.compose_design(
        source,
        headline=" \n\t",
        cta=compose.cta_label(CtaType.none) or "",
        font_dir=directory,
    )
    assert value.headline_box is value.cta_box is None
    assert not value.lines
    with (
        Image.open(BytesIO(source)) as before,
        Image.open(BytesIO(value.png_bytes)) as after,
    ):
        assert before.tobytes() == after.tobytes()


def test_headline_sanitization_and_length_are_applied_before_layout(fonts):
    directory, _ = fonts
    source = pixels()
    raw = "Hello\x00\x1b\n  worldhttps://example.invalid/private\t www.example.invalid/a data:image/png;base64,secret"
    actual = compose.compose_design(source, headline=raw, cta="", font_dir=directory)
    clean = compose.compose_design(
        source, headline="Hello world", cta="", font_dir=directory
    )
    assert actual.png_bytes == clean.png_bytes
    assert (
        compose.compose_design(
            source, headline="A" * 100, cta="", font_dir=directory
        ).png_bytes
        == compose.compose_design(
            source, headline="A" * 80, cta="", font_dir=directory
        ).png_bytes
    )


def test_cta_mapping_covers_closed_taxonomy():
    assert set(compose.CTA_LABELS) == set(CtaType)
    assert compose.cta_label(CtaType.none) is None
    for cta_type in set(CtaType) - {CtaType.none}:
        assert isinstance(compose.cta_label(cta_type), str)
        assert compose.cta_label(cta_type.value) == compose.CTA_LABELS[cta_type]


def test_missing_font_error_contains_only_code(tmp_path):
    private = tmp_path / "private-font-directory"
    with pytest.raises(compose.FontMissing) as caught:
        compose.compose_design(
            pixels(), headline="headline", cta="cta", font_dir=private
        )
    assert caught.value.code == str(caught.value) == "FONT_MISSING"
    assert str(private) not in str(caught.value)
    assert not private.exists()


@pytest.mark.parametrize("size", [(8, 256), (100, 24), (2048, 64), (512, 1024)])
def test_layout_never_draws_outside_safe_bounds_even_if_text_cannot_fit(fonts, size):
    directory, _ = fonts
    value = compose.compose_design(
        pixels(size), headline="W" * 80, cta="W" * 80, font_dir=directory
    )
    width, height = size
    margin = int(width * compose.MARGIN_RATIO)
    for box in (value.headline_box, value.cta_box):
        if box is not None:
            inside(box, (margin, margin, width - margin, height - margin))


def test_wrapping_prefers_spaces_and_only_splits_oversized_words(fonts):
    directory, _ = fonts
    text = "word " * 16
    value = compose.compose_design(pixels(), headline=text, cta="", font_dir=directory)
    assert " ".join(value.lines) == text.strip()
    assert all(set(line.split()) == {"word"} for line in value.lines)
    plain = compose.compose_design(
        pixels(), headline="W" * 80, cta="", font_dir=directory
    )
    assert "".join(plain.lines) == "W" * 80


def test_short_headline_keeps_starting_font_and_is_centered(fonts):
    directory, _ = fonts
    value = compose.compose_design(pixels(), headline="Hi", cta="", font_dir=directory)
    assert value.headline_size == max(
        compose.MIN_FONT_PX, int(1024 * compose.HEADLINE_FONT_RATIO)
    )
    assert len(value.lines) == 1 and value.cta_box is None
    left, _, right, _ = value.headline_box
    assert abs((left + right) / 2 - 512) <= 1


def test_korean_with_fetched_fonts_when_available():
    directory = Path(__file__).parents[1] / "assets" / "fonts"
    if not all(
        (directory / name).is_file()
        for name in ("Pretendard-Bold.otf", "Pretendard-SemiBold.otf")
    ):
        pytest.skip("font not fetched: run make fetch-font")
    value = compose.compose_design(
        pixels(),
        headline="피부를 위한 새로운 일상",
        cta=compose.cta_label(CtaType.shop_now),
        font_dir=directory,
    )
    assert value.headline_box is not None
    with Image.open(BytesIO(value.png_bytes)) as rendered:
        assert any(
            r > 200 and g > 200 and b > 200
            for r, g, b in rendered.crop(value.headline_box).getdata()
        )


@pytest.mark.parametrize("size", [(1024, 1024), (512, 1024), (2048, 64), (8, 256)])
def test_layout_regions_are_bounded_small_separate_edge_bands(size):
    width, height = size
    regions = compose.layout_regions(width, height)
    assert set(regions) == {"headline", "cta"}
    horizontal = int(width * compose.MARGIN_RATIO)
    vertical = min(horizontal, int(height * compose.MARGIN_RATIO))
    for region in regions.values():
        inside(region, (horizontal, vertical, width - horizontal, height - vertical))
    headline, cta = regions["headline"], regions["cta"]
    area = lambda box: (box[2] - box[0]) * (box[3] - box[1])
    assert area(headline) <= width * height * compose.BAND_AREA_MAX_RATIO
    assert area(cta) < area(headline)
    assert headline[3] <= cta[1]
    assert 0.05 <= compose.HEADLINE_FONT_RATIO <= 0.06
    assert compose.CTA_FONT_RATIO < compose.HEADLINE_FONT_RATIO
    assert compose.MAX_HEADLINE_LINES <= 2


@pytest.mark.parametrize("size", [(1024, 1024), (512, 1024)])
def test_compose_uses_image_height_fonts_and_preserves_entire_center(fonts, size):
    directory, _ = fonts
    source = pixels(size)
    value = compose.compose_design(source, headline="Hi", cta="Go", font_dir=directory)
    width, height = size
    assert value.headline_size == max(
        compose.MIN_FONT_PX, int(height * compose.HEADLINE_FONT_RATIO)
    )
    assert value.cta_size == max(
        compose.MIN_FONT_PX, int(height * compose.CTA_FONT_RATIO)
    )
    assert value.cta_size < value.headline_size
    assert len(value.lines) <= compose.MAX_HEADLINE_LINES <= 2
    regions = compose.layout_regions(*size)
    inside(value.headline_box, regions["headline"])
    inside(value.cta_box, regions["cta"])
    center = (0, int(height * 0.25), width, int(height * 0.75))
    assert regions["headline"][3] <= center[1]
    assert regions["cta"][1] >= center[3]
    with (
        Image.open(BytesIO(source)) as before,
        Image.open(BytesIO(value.png_bytes)) as after,
    ):
        assert before.crop(center).tobytes() == after.crop(center).tobytes()
