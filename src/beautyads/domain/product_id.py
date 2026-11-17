"""Closed, per-request product candidates, independent of model and storage."""

from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator

from beautyads.domain.creative import Source
from beautyads.domain.links import LinkCreative, match_products
from beautyads.domain.products import Product, ProductKey

PRODUCT_ID_KIND = "product-id@v2"
# resembles_only gives the model an honest outlet; validation discards it.
EVIDENCE_KINDS = (
    "spoken_name",
    "on_screen_text",
    "package_label",
    "title_caption",
    "resembles_only",
)
REJECTED_EVIDENCE = "resembles_only"


def candidates_for_brand(
    brand: str | None, products: Sequence[Product]
) -> dict[str, Product]:
    unique = {p.key: p for p in products if p.brand == brand}
    return {
        f"C{index}": product
        for index, product in enumerate(
            sorted(unique.values(), key=lambda p: p.source_url), 1
        )
    }


class ProductSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    candidate: str
    evidence: Literal[
        "spoken_name",
        "on_screen_text",
        "package_label",
        "title_caption",
        "resembles_only",
    ]


class ProductIdResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    selections: list[ProductSelection]

    @field_validator("selections")
    @classmethod
    def closed_unique_ids(
        cls, values: list[ProductSelection], info: ValidationInfo
    ) -> list[ProductSelection]:
        allowed = (info.context or {}).get("candidates", {})
        ids = [value.candidate for value in values]
        if len(set(ids)) != len(ids) or any(i not in allowed for i in ids):
            raise ValueError("candidates must be unique ids from this request")
        return values

    def kept(self) -> list[ProductSelection]:
        return [s for s in self.selections if s.evidence != REJECTED_EVIDENCE]

    @property
    def dropped(self) -> int:
        return len(self.selections) - len(self.kept())

    def kept_evidence(self) -> dict[str, str]:
        return {s.candidate: s.evidence for s in self.kept()}

    def products(self, candidates: Mapping[str, Product]) -> list[ProductKey]:
        return [candidates[s.candidate].key for s in self.kept()]


def product_id_schema(candidates: Mapping[str, Product]) -> dict:
    return {
        "type": "object",
        "properties": {
            "selections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "candidate": {"type": "string", "enum": list(candidates)},
                        "evidence": {"type": "string", "enum": list(EVIDENCE_KINDS)},
                    },
                    "required": ["candidate", "evidence"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["selections"],
        "additionalProperties": False,
    }


def select_targets(
    entries: Sequence[LinkCreative], products: Sequence[Product]
) -> list[LinkCreative]:
    brands = {p.brand for p in products}
    return [
        entry
        for entry in entries
        if entry.creative.key.source in {Source.youtube, Source.instagram}
        and entry.is_product
        and entry.creative.properties.get("brand") in brands
        and not any(
            job.kind == PRODUCT_ID_KIND and job.status == "done" for job in entry.labels
        )
        and match_products(entry, products).status != "matched"
    ]
