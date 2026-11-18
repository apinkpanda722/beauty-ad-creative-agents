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
    for text in [value.image_brief, *value.scenes]:
        assert text in prompt
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
    assert "빛나는 표면" in prompt
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
