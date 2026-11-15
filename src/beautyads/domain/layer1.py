"""Storage-independent product snapshots and validated layer-one evidence tables."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, Field, StringConstraints, model_validator

from beautyads.domain.labels import Claim
from beautyads.domain.mfds import IngredientStandard
from beautyads.domain.products import Product, ProductCert, ProductIngredient
from beautyads.domain.skin import SkinConcern

Nonblank = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]


class EfficacyIngredient(BaseModel):
    inci: Nonblank
    standard_name: Nonblank
    matched_by: Literal["eng_name_exact"]


class IngredientEfficacyLink(BaseModel):
    efficacy: list[Claim] = Field(min_length=1)
    basis: Literal["regulatory_notice", "literature_review"]
    conditional: bool = Field(strict=True)
    source_ref: Nonblank
    ingredients: list[EfficacyIngredient] = Field(min_length=1)


class IngredientEfficacyTable(BaseModel):
    # Author/version and annotations are retained in the read-only YAML source.
    efficacy_values: list[Claim] = Field(default_factory=list)
    links: list[IngredientEfficacyLink]
    unmatched: list[dict] = Field(default_factory=list)
    not_linked_for_now: list[Nonblank] = Field(default_factory=list)


class EfficacyConcern(BaseModel):
    efficacy: Claim
    concern: SkinConcern
    status: Literal["draft", "confirmed"]
    basis: str | None = None
    source_ref: str | None = None

    @model_validator(mode="after")
    def confirmed_provenance(self) -> "EfficacyConcern":
        if self.status == "confirmed" and (
            self.basis != "taxonomy_definition"
            or not self.source_ref
            or not self.source_ref.strip()
        ):
            raise ValueError("confirmed taxonomy requires basis and source_ref")
        return self


class EfficacyConcernTable(BaseModel):
    rows: list[EfficacyConcern]


@dataclass(frozen=True)
class Layer1Tables:
    ingredient_links: list[IngredientEfficacyLink]
    concerns: list[EfficacyConcern]
    unmatched: int = 0
    not_linked_for_now: int = 0


@dataclass(frozen=True)
class SyncProduct:
    product: Product
    updated_at: datetime
    # Complete current sets, never just the changed child rows.
    ingredients: list[ProductIngredient] = field(default_factory=list)
    certs: list[ProductCert] = field(default_factory=list)
    standards: list[IngredientStandard] = field(default_factory=list)


class Layer1SyncSource(Protocol):
    def read_changed(
        self, *, since: datetime | None, limit: int | None
    ) -> list[SyncProduct]: ...

    def get_watermark(self) -> datetime | None: ...

    def set_watermark(self, value: datetime) -> None:
        """Persist the layer-specific checkpoint only after successful graph writes."""
        ...
