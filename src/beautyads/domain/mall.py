"""Facts read from official product HTML; image contents are never interpreted."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MallProduct(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_url: str
    list_price: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    sale_price: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    currency: str | None = None
    price: Decimal = Field(ge=0, allow_inf_nan=False)
    price_basis: Literal["list_price", "sale_price_fallback"]
    ingredients_text: str | None = None
    detail_image_urls: tuple[str, ...] = ()
