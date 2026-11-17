"""Closed, per-request product candidates, independent of model and storage."""

from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator

from beautyads.domain.creative import Source
from beautyads.domain.links import LinkCreative, match_products
from beautyads.domain.products import Product, ProductKey

PRODUCT_ID_KIND = "product-id@v1"


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


class ProductIdResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    candidates: list[str]

    @field_validator("candidates")
    @classmethod
    def closed_unique_ids(cls, values: list[str], info: ValidationInfo) -> list[str]:
        allowed = (info.context or {}).get("candidates", {})
        if len(set(values)) != len(values) or any(
            value not in allowed for value in values
        ):
            raise ValueError("candidates must be unique ids from this request")
        return values

    def products(self, candidates: Mapping[str, Product]) -> list[ProductKey]:
        return [candidates[value].key for value in self.candidates]


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
