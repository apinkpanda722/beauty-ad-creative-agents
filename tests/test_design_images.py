"""Design prompts and atomic files use synthetic plans and temporary paths."""

from dataclasses import fields, replace
from hashlib import sha256
from pathlib import Path
from unittest.mock import Mock

import pytest

from beautyads.agents.design_images import SavedImage, image_prompt, save_design_image
from beautyads.domain.plan import Plan
from beautyads.llm import ImageOutcome


def plan(**updates):
    return Plan.model_validate(
        {
            "title": "synthetic title",
            "hook_type": "question",
            "hook_text": "synthetic hook",
            "scenes": ["synthetic scene"],
            "copy_lines": ["synthetic copy"],
            "image_brief": "synthetic brief",
            "cta_type": "none",
            "angle": "desire",
            "format": "static_image",
            "category": "serum_ampoule",
            "product_url": "https://example.invalid/private-product",
            "claimed_efficacy": [],
            "evidence_ids": ["synthetic-evidence"],
        }
        | updates
    )


def test_prompt_includes_only_plan_text():
    value = plan()
    prompt = image_prompt(value)
    assert isinstance(prompt, str)
    assert value.hook_text not in prompt
    assert value.image_brief in prompt
    assert all(text not in prompt for text in value.scenes)
    assert value.product_url not in prompt and value.evidence_ids[0] not in prompt
    assert len(prompt) <= 2000


def test_prompt_strips_embedded_urls_and_limits_length():
    value = plan(
        image_brief="brief https://example.invalid/image.png data:image/png;base64,c3ludGhldGlj",
        hook_text="hook www.example.invalid/image",
        scenes=["scene file:///synthetic.png"],
    )
    prompt = image_prompt(value)
    assert all(
        marker not in prompt
        for marker in ("https:", "data:", "base64", "www.", "file:", "c3ludGhldGlj")
    )
    assert len(image_prompt(plan(image_brief="가" * 3000))) == 2000
    assert isinstance(image_prompt(plan(image_brief=None)), str)


def outcome(mime="image/png"):
    payload = b"\x89PNG\r\n\x1a\nsynthetic-padding"
    return ImageOutcome(
        ok=True,
        image_bytes=payload,
        mime=mime,
        size=len(payload),
        sha256=sha256(payload).hexdigest(),
        cost_usd=0.0336,
        model="gemini-3.1-flash-lite-image",
        code=None,
    )


@pytest.mark.parametrize(
    "mime,ext", [("image/png", "png"), ("image/jpeg", "jpg"), ("image/webp", "webp")]
)
@pytest.mark.parametrize("key", ["request", "../../escape", "/absolute/request"])
def test_save_hashed_path_and_metadata(tmp_path, mime, ext, key):
    value = outcome(mime)
    saved = save_design_image(value, request_key=key, index=3, base_dir=tmp_path)
    assert isinstance(saved, SavedImage)
    assert saved.path == tmp_path / sha256(key.encode()).hexdigest()[:16] / f"03.{ext}"
    assert saved.path.resolve().is_relative_to(tmp_path.resolve())
    assert saved.path.read_bytes() == value.image_bytes
    assert (saved.sha256, saved.size, saved.mime) == (
        value.sha256,
        value.size,
        value.mime,
    )
    assert {field.name for field in fields(saved)} == {"path", "sha256", "size", "mime"}
    assert list(saved.path.parent.iterdir()) == [saved.path]


def test_failed_outcome_not_saved(tmp_path):
    with pytest.raises(ValueError):
        save_design_image(
            replace(outcome(), ok=False, image_bytes=None),
            request_key="request",
            index=0,
            base_dir=tmp_path,
        )
    assert list(tmp_path.iterdir()) == []


def test_atomic_replace_and_cleanup(tmp_path, monkeypatch):
    original = Path.replace
    observed = []

    def rename(source, target):
        assert source.parent == target.parent and source != target
        assert source.read_bytes() == outcome().image_bytes
        assert not target.exists()
        observed.append(target)
        return original(source, target)

    monkeypatch.setattr(Path, "replace", rename)
    saved = save_design_image(
        outcome(), request_key="request", index=0, base_dir=tmp_path
    )
    assert observed == [saved.path]
    monkeypatch.setattr(Path, "replace", Mock(side_effect=OSError("synthetic failure")))
    with pytest.raises(OSError):
        save_design_image(outcome(), request_key="request", index=1, base_dir=tmp_path)
    assert list(saved.path.parent.iterdir()) == [saved.path]


def test_design_default_and_gitignore():
    assert save_design_image.__kwdefaults__.get("base_dir") == Path("data/design")
    assert (
        "data/design/"
        in (Path(__file__).parents[1] / ".gitignore").read_text().splitlines()
    )


@pytest.mark.parametrize(
    "brief",
    [
        None,
        "창가의 병 (메타1) [메타2] （메타3） <메타4>\n※ 메타5\n참고: 메타6\n주의: 메타7\n설명: 메타8\n지시: 메타9\nNote: meta10\n물방울 https://example.invalid/meta11",
    ],
)
def test_prompt_removes_meta_copy_and_always_ends_with_no_text_clause(brief):
    from beautyads.agents.design_images import IMAGE_NO_TEXT_CLAUSE

    prompt = image_prompt(
        plan(
            image_brief=brief,
            hook_text="COPY_ONLY_SENTINEL",
            scenes=["빛나는 표면 (장면주석)\nNote: scene-meta"],
        )
    )
    assert prompt.endswith(IMAGE_NO_TEXT_CLAUSE)
    assert "빛나는 표면" not in prompt
    if brief is not None:
        assert "창가의 병" in prompt and "물방울" in prompt
    for marker in (
        "메타",
        "meta",
        "COPY_ONLY_SENTINEL",
        "장면주석",
        "Note:",
        "https://",
        "※",
    ):
        assert marker not in prompt
    assert len(prompt) <= 2000


def test_prompt_nested_comments_and_length_reserve_no_text_clause():
    from beautyads.agents.design_images import IMAGE_NO_TEXT_CLAUSE

    prompt = image_prompt(
        plan(image_brief="장면 (바깥 [안쪽] 남은주석)\n" + "가" * 3000)
    )
    assert "남은주석" not in prompt and "바깥" not in prompt and "안쪽" not in prompt
    assert len(prompt) == 2000 and prompt.endswith(IMAGE_NO_TEXT_CLAUSE)


def test_composed_saved_atomically_beside_untouched_original(tmp_path, monkeypatch):
    from beautyads.agents.design_images import save_composed_design

    raw = save_design_image(
        outcome(), request_key="../../request", index=2, base_dir=tmp_path
    )
    payload = b"\x89PNG\r\n\x1a\nsynthetic-composed"
    replace = Path.replace
    observed = []

    def atomic(source, target):
        assert source.parent == target.parent == raw.path.parent
        assert source.read_bytes() == payload
        assert source != target and not target.exists()
        observed.append(target)
        return replace(source, target)

    monkeypatch.setattr(Path, "replace", atomic)
    composed = save_composed_design(
        payload, request_key="../../request", index=2, base_dir=tmp_path
    )
    assert composed.path == raw.path.with_name("02_composed.png")
    assert observed == [composed.path]
    assert composed.path.read_bytes() == payload
    assert (composed.mime, composed.size, composed.sha256) == (
        "image/png",
        len(payload),
        sha256(payload).hexdigest(),
    )
    assert raw.path.read_bytes() == outcome().image_bytes
    monkeypatch.setattr(Path, "replace", Mock(side_effect=OSError("synthetic")))
    with pytest.raises(OSError):
        save_composed_design(
            payload, request_key="../../request", index=3, base_dir=tmp_path
        )
    assert set(raw.path.parent.iterdir()) == {raw.path, composed.path}


@pytest.mark.parametrize("index", [-1, True, 1.5])
def test_composed_rejects_invalid_index_without_writing(tmp_path, index):
    from beautyads.agents.design_images import save_composed_design

    with pytest.raises(ValueError, match="IMAGE_INDEX_INVALID"):
        save_composed_design(
            b"synthetic", request_key="request", index=index, base_dir=tmp_path
        )
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "quotes",
    [
        '"SYNTH_QUOTE_A" “SYNTH_QUOTE_B” 「SYNTH_QUOTE_C」',
        "‘SYNTH_QUOTE_A’ 'SYNTH_QUOTE_B' 『SYNTH_QUOTE_C』",
        "「SYNTH_QUOTE_A “SYNTH_QUOTE_B 'SYNTH_QUOTE_C'”」",
        "「SYNTH_QUOTE_A「SYNTH_QUOTE_B」SYNTH_QUOTE_C」",
        "“SYNTH_QUOTE_A\nSYNTH_QUOTE_B” 『SYNTH_QUOTE_C』",
    ],
)
def test_single_cut_prompt_removes_all_quoted_copy_and_video_scenes(quotes):
    from beautyads.agents.design_images import IMAGE_NO_TEXT_CLAUSE, IMAGE_PROMPT_SUFFIX

    value = plan(
        image_brief=f"SYNTH_VISUAL {quotes} (SYNTH_COMMENT)",
        scenes=["SYNTH_SCENE_X"],
        hook_text="SYNTH_HOOK",
        copy_lines=["SYNTH_COPY"],
    )
    prompt = image_prompt(value)
    assert prompt == "SYNTH_VISUAL\n" + IMAGE_PROMPT_SUFFIX
    for marker in (
        "SYNTH_QUOTE_",
        "SYNTH_SCENE_X",
        "SYNTH_HOOK",
        "SYNTH_COPY",
        "SYNTH_COMMENT",
    ):
        assert marker not in prompt
    for phrase in ("콜라주", "스토리보드", "여러 컷", "단일 컷", "자막", "무라벨"):
        assert phrase in IMAGE_NO_TEXT_CLAUSE


@pytest.mark.parametrize(
    "brief",
    [None, '"ONLY_COPY"', "“ONLY_COPY”\n「MORE_COPY」", "(COMMENT)\nNote: META"],
)
def test_empty_scene_leaves_only_fixed_image_instruction(brief):
    from beautyads.agents.design_images import IMAGE_PROMPT_SUFFIX

    assert image_prompt(plan(image_brief=brief)) == IMAGE_PROMPT_SUFFIX


@pytest.mark.parametrize(
    "comment",
    ["(don't render)", '[remove "note]', "（remove “note）", "<remove 「note>"],
)
def test_quote_markers_inside_annotations_do_not_remove_scene_body(comment):
    from beautyads.agents.design_images import IMAGE_PROMPT_SUFFIX

    prompt = image_prompt(plan(image_brief=f"{comment} SYNTH_VISUAL_AFTER"))
    assert prompt == "SYNTH_VISUAL_AFTER\n" + IMAGE_PROMPT_SUFFIX


def test_image_style_and_no_text_instructions_are_exact():
    from beautyads.agents.design_images import (
        IMAGE_NO_TEXT_CLAUSE,
        IMAGE_PROMPT_SUFFIX,
        IMAGE_STYLE_CLAUSE,
    )

    assert IMAGE_STYLE_CLAUSE == (
        "장면은 훅 문구를 가장 잘 보여 주는 하나의 순간으로 고르고 기본은 사용 장면이다(손등이나 볼에 제품을 바르는 손과 피부 클로즈업). "
        "얼굴 전체를 정면으로 잡는 구도와 병이나 튜브를 코나 입에 대는 구도는 그리지 않는다. "
        "용기가 나오면 내용물이 보여야 한다(맑은 물처럼 보이는 투명 액체 금지, 세럼은 약간 점성이 있는 연한 색 액체와 스포이트나 펌프 형태, 튜브는 닫힌 튜브). "
        "제품을 얼굴에 직접 대거나 문지르지 말고 손가락 끝에 덜어 바르는 모습으로 그린다. 인물이 나오면 한국인 모델이다."
    )
    assert IMAGE_NO_TEXT_CLAUSE == (
        "하나의 구도로 단일 컷만 그린다(콜라주·그리드·스토리보드·여러 컷 금지). "
        "이미지에는 글자·자막·카피·로고·브랜드·제품명·라벨 문구를 넣지 않는다. "
        "제품은 무라벨 일반 병·튜브·패키지의 형태로만 묘사한다."
    )
    assert IMAGE_PROMPT_SUFFIX == IMAGE_STYLE_CLAUSE + " " + IMAGE_NO_TEXT_CLAUSE


@pytest.mark.parametrize("brief", [None, "SYNTH_SCENE (REMOVE)", "가" * 3000])
def test_style_suffix_survives_cleaning_and_long_scenes(brief):
    from beautyads.agents.design_images import IMAGE_PROMPT_SUFFIX

    prompt = image_prompt(plan(image_brief=brief))
    assert prompt.endswith(IMAGE_PROMPT_SUFFIX)
    assert len(prompt) <= 2000
    assert "(손등이나 볼에 제품을 바르는 손과 피부 클로즈업)" in prompt
    assert "(맑은 물처럼 보이는 투명 액체 금지," in prompt
    assert "REMOVE" not in prompt
    if brief is None:
        assert prompt == IMAGE_PROMPT_SUFFIX
    elif len(brief) > 2000:
        assert len(prompt) == 2000
