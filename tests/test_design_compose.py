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
        source,
        headline="Synthetic headline",
        cta="View details",
        with_cta=True,
        font_dir=font_dir,
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
        compose.layout_regions(1024, 1024)["cta"],
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
        assert rendered.getpixel((margin + 1, margin + 1)) == before.convert(
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
        pixels((100, 1024)),
        headline="W" * 800,
        cta="W" * 800,
        with_cta=True,
        font_dir=directory,
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
        pixels((100, 1024)),
        headline="",
        cta="W" * 80,
        with_cta=True,
        font_dir=directory,
    )
    assert drawn and set(drawn) == {drawn[0]} and drawn[0].endswith("…")


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
    assert set(regions) == {"headline", "cta", "product"}
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
    value = compose.compose_design(
        source, headline="Hi", cta="Go", with_cta=True, font_dir=directory
    )
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


@pytest.mark.parametrize(
    "brand,name,expected",
    [
        (
            "beauty_of_joseon",
            "인삼선세럼 SPF50+ 50ml",
            "beauty of joseon  인삼선세럼 SPF50+",
        ),
        (
            "English_Brand",
            "세럼, (100mL), 30 g 2매 0.5kg 1L 3입 4ea 5개",
            "English Brand  세럼",
        ),
        ("brand", None, "brand"),
        (None, "세럼 50ml", "세럼"),
        (None, None, ""),
        ("", " \t", ""),
        (123, [], ""),
        ({}, True, ""),
        (
            "brand\x00\n https://example.invalid/private",
            "세럼\x1b www.example.invalid/x",
            "brand  세럼",
        ),
    ],
)
def test_product_line_only_cleans_supplied_identity(brand, name, expected):
    assert compose.product_line(brand, name) == expected


def test_product_line_is_bounded_and_does_not_transliterate():
    line = compose.product_line("English_Brand", "합성" * 100)
    assert line.startswith("English Brand  ")
    assert len(line) == compose.MAX_PRODUCT_LINE_CHARS


def synthetic_background(size, kind):
    import random

    image = Image.new("RGB", size)
    if isinstance(kind, int):
        image.paste((kind,) * 3, (0, 0, *size))
    else:
        rng = random.Random(0)
        low, high = (200, 255) if kind == "bright_noise" else (60, 160)
        image.putdata(
            [
                (v, v, v)
                for y in range(size[1])
                for x in range(size[0])
                for v in [
                    (255 if (x // 8 + y // 8) % 2 else 0)
                    if kind == "checker"
                    else rng.randint(low, high)
                ]
            ]
        )
    stream = BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def measured_contrast(image, box, color):
    # Independent measurement of the specified percentile contrast, before glyphs.
    def luminance(rgb):
        channels = [v / 255 for v in rgb]
        channels = [
            v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
            for v in channels
        ]
        return sum(
            v * weight
            for v, weight in zip(channels, (0.2126, 0.7152, 0.0722), strict=True)
        )

    values = sorted(luminance(rgb) for rgb in image.crop(box).getdata())
    if color == "white":
        return 1.05 / (values[int((len(values) - 1) * 0.9)] + 0.05)
    return (values[int((len(values) - 1) * 0.1)] + 0.05) / (
        luminance(compose.DARK_TEXT) + 0.05
    )


@pytest.mark.parametrize("size", [(1024, 1024), (512, 1024)])
@pytest.mark.parametrize(
    "kind,color,adjusted",
    [
        (255, "dark", True),
        (240, "dark", True),
        (20, "white", False),
        (128, "white", False),
        ("bright_noise", "dark", True),
        ("complex_noise", None, True),
        ("checker", None, True),
    ],
)
def test_contrast_selection_scrims_best_effort_and_determinism(
    fonts, size, kind, color, adjusted
):
    directory, _ = fonts
    source = synthetic_background(size, kind)
    value = compose.compose_design(
        source,
        headline="Synthetic headline",
        product_line="brand  serum",
        font_dir=directory,
    )
    assert (
        value.png_bytes
        == compose.compose_design(
            source,
            headline="Synthetic headline",
            product_line="brand  serum",
            font_dir=directory,
        ).png_bytes
    )
    assert value.contrast_adjusted is adjusted
    assert value.min_contrast == min(value.headline_contrast, value.product_contrast)
    assert value.cta_contrast is value.cta_color is None
    assert value.cta_scrim == 0.0
    if color:
        assert value.headline_color == color
        assert value.headline_scrim == 0.0
    assert 0 <= value.headline_scrim <= compose.SCRIM_MAX_ALPHA
    if kind == "complex_noise":
        assert value.headline_scrim > 0
    if kind == "checker":
        assert value.min_contrast < compose.MIN_CONTRAST_RATIO
    else:
        assert value.headline_contrast >= compose.MIN_CONTRAST_RATIO
    regions = compose.layout_regions(*size)
    inside(value.headline_box, regions["headline"])
    inside(value.product_box, regions["product"])
    with (
        Image.open(BytesIO(source)) as before,
        Image.open(BytesIO(value.png_bytes)) as after,
    ):
        baseline = measured_contrast(before, value.headline_box, value.headline_color)
        assert value.headline_contrast >= baseline
        center = (0, int(size[1] * 0.25), size[0], int(size[1] * 0.75))
        assert before.crop(center).tobytes() == after.crop(center).tobytes()


def test_no_band_and_subtle_shadow_on_original_background(fonts):
    directory, _ = fonts
    assert not hasattr(compose, "BAND_RGBA")
    value = compose.compose_design(pixels(), headline="Synthetic", font_dir=directory)
    assert value.headline_scrim == 0.0 and value.headline_color == "white"
    assert value.contrast_adjusted is False
    assert value.min_contrast == value.headline_contrast
    margin = int(value.width * compose.MARGIN_RATIO)
    with Image.open(BytesIO(value.png_bytes)) as after:
        original = (0x72, 0x94, 0xB6)
        assert after.getpixel((margin + 1, margin + 1)) == original
        left, top, right, bottom = value.headline_box
        surrounding = after.crop((left - 8, top - 8, right + 8, bottom + 8))
        assert any(
            all(a < b for a, b in zip(rgb, original, strict=True))
            for rgb in surrounding.getdata()
        )


@pytest.mark.parametrize("enabled", [False, True])
def test_cta_is_explicitly_opt_in_and_has_contrast_metadata(fonts, enabled):
    directory, _ = fonts
    value = compose.compose_design(
        pixels(),
        headline="Hi",
        cta="Details",
        with_cta=enabled,
        product_line="brand",
        font_dir=directory,
    )
    if enabled:
        inside(value.cta_box, compose.layout_regions(1024, 1024)["cta"])
        assert value.cta_color == "white" and value.cta_scrim == 0
        assert value.min_contrast == min(
            value.headline_contrast, value.product_contrast, value.cta_contrast
        )
    else:
        assert value.cta_box is value.cta_contrast is value.cta_color is None
    default = compose.compose_design(
        pixels(), headline="", cta="자세히 보기", font_dir=directory
    )
    assert default.cta_box is None and default.min_contrast is None
    assert default.contrast_adjusted is False
    assert default.product_box is default.product_size is default.product_text is None
    with (
        Image.open(BytesIO(default.png_bytes)) as after,
        Image.open(BytesIO(pixels())) as before,
    ):
        assert after.tobytes() == before.tobytes()


@pytest.mark.parametrize("size", [(1024, 1024), (512, 1024), (2048, 64), (8, 256)])
def test_product_region_is_small_separate_and_at_bottom(size):
    width, height = size
    regions = compose.layout_regions(*size)
    for name in ("cta", "product"):
        assert regions[name][1] >= height * 0.75
    assert regions["headline"][3] <= regions["cta"][1]
    assert regions["cta"][3] <= regions["product"][1]
    assert regions["product"][3] <= height - min(
        int(width * compose.MARGIN_RATIO), int(height * compose.MARGIN_RATIO)
    )


@pytest.mark.parametrize("text", ["brand  serum", "W" * 800])
def test_product_font_centering_single_line_and_ellipsis(fonts, text, monkeypatch):
    directory, calls = fonts
    drawn = []
    original = compose.ImageDraw.ImageDraw.text

    def record(self, position, text, *args, **kwargs):
        drawn.append(text)
        return original(self, position, text, *args, **kwargs)

    monkeypatch.setattr(compose.ImageDraw.ImageDraw, "text", record)
    value = compose.compose_design(
        pixels(), headline="Hi", product_line=text, font_dir=directory
    )
    assert 0.025 <= compose.PRODUCT_FONT_RATIO <= 0.035
    assert compose.PRODUCT_FONT_RATIO < compose.HEADLINE_FONT_RATIO
    inside(value.product_box, compose.layout_regions(1024, 1024)["product"])
    assert value.product_size < value.headline_size
    assert (compose._SEMIBOLD, value.product_size) in calls
    assert "\n" not in value.product_text and value.product_text in drawn
    assert abs((value.product_box[0] + value.product_box[2]) / 2 - 512) <= 1
    if len(text) < 60:
        assert value.product_size == max(
            compose.MIN_FONT_PX, int(1024 * compose.PRODUCT_FONT_RATIO)
        )
    else:
        assert value.product_size == compose.MIN_FONT_PX
        assert value.product_text.endswith("…")


def test_short_product_line_retains_identity_separator_when_drawn(fonts):
    directory, _ = fonts
    line = compose.product_line("English_Brand", "합성 세럼 50ml")
    value = compose.compose_design(
        pixels(), headline="", product_line=line, font_dir=directory
    )
    assert value.product_text == line
    assert value.headline_box is None
    assert value.min_contrast == value.product_contrast


def test_scrim_uses_smallest_step_and_correct_edge_fade(fonts):
    directory, _ = fonts
    source = synthetic_background((512, 1024), "complex_noise")
    value = compose.compose_design(
        source,
        headline="Synthetic headline",
        product_line="brand  serum",
        font_dir=directory,
    )
    with Image.open(BytesIO(source)) as original:
        for name in ("headline", "product"):
            region = compose.layout_regions(*original.size)[name]
            box = getattr(value, name + "_box")
            alpha = getattr(value, name + "_scrim")
            color = getattr(value, name + "_color")
            assert alpha > 0
            assert alpha / compose.SCRIM_STEP == pytest.approx(
                round(alpha / compose.SCRIM_STEP)
            )
            # Independently reconstruct the specified gradient, without glyphs/shadow.
            for level in (alpha - compose.SCRIM_STEP, alpha):
                patch = original.copy()
                for y in range(region[1], region[3]):
                    fraction = (y - region[1]) / (region[3] - region[1] - 1)
                    fade = 1 - fraction if name == "headline" else fraction
                    opacity = round(255 * max(0, level) * fade) / 255
                    for x in range(region[0], region[2]):
                        rgb = original.getpixel((x, y))
                        target = 0 if color == "white" else 255
                        patch.putpixel(
                            (x, y),
                            tuple(
                                round(v * (1 - opacity) + target * opacity) for v in rgb
                            ),
                        )
                actual = measured_contrast(patch, box, color)
                if level == alpha:
                    assert actual == pytest.approx(getattr(value, name + "_contrast"))
                    assert actual >= compose.MIN_CONTRAST_RATIO
                else:
                    assert actual < compose.MIN_CONTRAST_RATIO
                # The fade reaches zero at the inner edge and never changes the center.
                inner_y = region[3] - 1 if name == "headline" else region[1]
                assert patch.getpixel((region[0], inner_y)) == original.getpixel(
                    (region[0], inner_y)
                )


def test_scrim_constants_and_expanded_regions_are_fixed():
    assert compose.MIN_CONTRAST_RATIO == 3.0
    assert compose.SCRIM_MAX_ALPHA == 0.5
    assert compose.SCRIM_STEP == 0.05
    assert compose.MARGIN_RATIO == 0.05
    size = (512, 1024)
    regions = compose.layout_regions(*size)
    for name, region in regions.items():
        expected = (
            0,
            0 if name == "headline" else region[1],
            size[0],
            size[1] if name == "product" else region[3],
        )
        assert compose.scrim_region(region, size, name) == expected


@pytest.mark.parametrize("size", [(512, 1024), (1024, 1024)])
@pytest.mark.parametrize("with_cta", [False, True])
def test_scrims_reach_image_edges_without_seams_and_measure_final_background(
    fonts, monkeypatch, size, with_cta
):
    directory, _ = fonts
    names = ("headline", "product", "cta") if with_cta else ("headline", "product")
    options = {
        "headline": "Synthetic headline",
        "product_line": "brand  serum",
        "cta": "Details",
        "with_cta": with_cta,
        "font_dir": directory,
    }
    # Uniform bright pixels correctly select dark text without a scrim.
    bright = synthetic_background(size, 240)
    baseline = compose.compose_design(bright, **options)
    assert baseline.headline_color == "dark" and baseline.headline_scrim == 0
    # Mixed luminance only in the glyph boxes requires a scrim. Keep the bright
    # border uniform so adjacent-pixel checks detect mask seams, not source noise.
    with (
        Image.open(BytesIO(bright)) as source,
        Image.open(BytesIO(synthetic_background(size, "complex_noise"))) as noise,
    ):
        before = source.copy()
        for name in names:
            box = getattr(baseline, name + "_box")
            before.paste(noise.crop(box), box[:2])
    stream = BytesIO()
    before.save(stream, format="PNG")
    data = stream.getvalue()
    measured, events = [], []
    original_contrasts = compose._contrasts
    original_text = compose.ImageDraw.ImageDraw.text

    def record_contrasts(image, box):
        if image.size == size:
            measured.append((image.copy(), box))
            events.append("measure")
        return original_contrasts(image, box)

    def record_text(self, *args, **kwargs):
        events.append("text")
        return original_text(self, *args, **kwargs)

    monkeypatch.setattr(compose, "_contrasts", record_contrasts)
    monkeypatch.setattr(compose.ImageDraw.ImageDraw, "text", record_text)
    value = compose.compose_design(data, **options)
    assert len(measured) == len(names)
    assert events[: len(names)] == ["measure"] * len(names)
    assert "text" in events[len(names) :]
    intermediate = measured[0][0]
    assert all(image.tobytes() == intermediate.tobytes() for image, _ in measured)
    assert value.contrast_adjusted is True
    assert value.min_contrast >= compose.MIN_CONTRAST_RATIO
    contrasts = []
    for name in names:
        assert getattr(value, name + "_scrim") > 0
        assert getattr(value, name + "_color") == "white"
        contrast = measured_contrast(
            intermediate, getattr(value, name + "_box"), "white"
        )
        assert getattr(value, name + "_contrast") == pytest.approx(contrast)
        contrasts.append(contrast)
    assert value.min_contrast == pytest.approx(min(contrasts))
    # Independently reconstruct every expanded row on the original background.
    expected = before.copy()
    regions = compose.layout_regions(*size)
    for name in names:
        region = regions[name]
        start = 0 if name == "headline" else region[1]
        stop = size[1] if name == "product" else region[3]
        alpha = getattr(value, name + "_scrim")
        for y in range(start, stop):
            fraction = min(1, max(0, (y - region[1]) / (region[3] - region[1] - 1)))
            fade = 1 - fraction if name == "headline" else fraction
            opacity = round(255 * alpha * fade) / 255
            for x in range(size[0]):
                expected.putpixel(
                    (x, y),
                    tuple(round(v * (1 - opacity)) for v in before.getpixel((x, y))),
                )
    assert intermediate.tobytes() == expected.tobytes()
    with Image.open(BytesIO(value.png_bytes)) as after:
        assert after.getpixel((0, 0))[0] < 240
        assert after.getpixel((0, size[1] - 1))[0] < 240
        for name in names:
            left, top, right, bottom = regions[name]
            y = top + 1
            for x1, x2 in ((left - 1, left), (right - 1, right)):
                assert (
                    max(
                        abs(a - b)
                        for a, b in zip(
                            after.getpixel((x1, y)),
                            after.getpixel((x2, y)),
                            strict=True,
                        )
                    )
                    <= 1
                )
            if name == "headline":
                assert after.getpixel((0, top - 1)) == after.getpixel((0, top))
                assert after.getpixel((0, bottom - 1)) == (240,) * 3
                assert after.getpixel((0, bottom + 1)) == (240,) * 3
            elif name == "product":
                assert after.getpixel((0, bottom - 1)) == after.getpixel((0, bottom))
                if not with_cta:
                    assert after.getpixel((0, top - 1)) == (240,) * 3
                else:
                    # The preceding row belongs to CTA, not the product scrim.
                    assert after.getpixel((0, top - 1)) == expected.getpixel(
                        (0, top - 1)
                    )
                assert after.getpixel((0, top)) == (240,) * 3
            else:
                # CTA expands horizontally, never vertically into its neighbors.
                assert after.getpixel((0, top - 1)) == (240,) * 3
                assert after.getpixel((0, bottom)) == (240,) * 3
        center = (0, size[1] // 4, size[0], size[1] * 3 // 4)
        assert after.crop(center).tobytes() == before.crop(center).tobytes()
    assert value.png_bytes == compose.compose_design(data, **options).png_bytes
