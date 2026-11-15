"""Closed classification values from the frozen v1 taxonomy."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, model_validator


class HookType(StrEnum):
    question = "question"
    problem = "problem"
    result_first = "result_first"
    bold_claim = "bold_claim"
    product_first = "product_first"
    person_first = "person_first"
    other = "other"


class HookResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hook_type: HookType


class ContentType(StrEnum):
    product_creative = "product_creative"
    event_place = "event_place"
    brand_campaign = "brand_campaign"
    other = "other"


class Angle(StrEnum):
    problem_solution = "problem_solution"
    desire = "desire"
    social_proof = "social_proof"
    comparison = "comparison"
    ingredient_science = "ingredient_science"
    how_to = "how_to"
    other = "other"


class Format(StrEnum):
    ugc_style = "ugc_style"
    studio_film = "studio_film"
    demo = "demo"
    text_motion = "text_motion"
    static_image = "static_image"
    other = "other"


class Talent(StrEnum):
    none = "none"
    ordinary_person = "ordinary_person"
    creator = "creator"
    celebrity = "celebrity"
    expert = "expert"
    staff = "staff"


class CtaType(StrEnum):
    none = "none"
    shop_now = "shop_now"
    learn_more = "learn_more"
    store_mention = "store_mention"
    event = "event"
    follow_engage = "follow_engage"


class Claim(StrEnum):
    hydration = "hydration"
    soothing = "soothing"
    brightening = "brightening"
    firming_elasticity = "firming_elasticity"
    pore_sebum = "pore_sebum"
    acne_trouble = "acne_trouble"
    barrier = "barrier"
    anti_aging = "anti_aging"
    sun_protection = "sun_protection"
    texture_finish = "texture_finish"
    other = "other"


class Category(StrEnum):
    mask_pack = "mask_pack"
    serum_ampoule = "serum_ampoule"
    sun_care = "sun_care"
    other = "other"


class StructureFlags(BaseModel):
    model_config = ConfigDict(extra="forbid")

    has_demo_segment: bool
    has_proof_segment: bool
    has_cta: bool


class PlatformFitFlags(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_vertical: bool
    has_text_overlay: bool
    has_voice: bool
    has_music_only: bool
    has_subtitles: bool


class ContentTypeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_type: ContentType
    category: Category


class FullResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    angle: Angle
    format: Format
    talent: Talent
    structure: StructureFlags
    platform_fit: PlatformFitFlags
    cta_type: CtaType
    claims: list[Claim]
    ingredients: list[str]

    @model_validator(mode="after")
    def validate_cta_consistency(self) -> "FullResult":
        if self.structure.has_cta != (self.cta_type != CtaType.none):
            raise ValueError("structure.has_cta must equal (cta_type != none)")
        return self
