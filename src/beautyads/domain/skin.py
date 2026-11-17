"""Closed Korean skin values approved in ADR-012 follow-up decision 5."""

from enum import StrEnum


class SkinType(StrEnum):
    dry = "건성"
    oily = "지성"
    combination = "복합성"
    sensitive = "민감성"


class SkinConcern(StrEnum):
    dryness = "건조"
    acne_trouble = "트러블·여드름"
    redness_sensitivity = "홍조·민감"
    pore_sebum = "모공·피지"
    dullness_spots = "칙칙함·잡티"
    loss_of_elasticity = "탄력 저하"
    wrinkles = "주름"
    rough_texture = "거친 피부결"
