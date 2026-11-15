"""Product records and deterministic aliases, independent of storage and SDKs."""

import re
import unicodedata
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit, urlunsplit

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from beautyads.domain.labels import Category
from beautyads.domain.mfds import CertStatus, FunctionalKind, IngredientStandard
from beautyads.domain.skin import SkinType

CONTAINER_WORDS = frozenset(
    {"튜브", "펌프", "캡", "리필", "용기", "파우치", "데일리", "픽"}
)
STOPWORDS = frozenset(
    {
        "더",
        "the",
        "new",
        "리뉴얼",
        "어드밴스드",
        "플러스",
        "하이퍼",
        "마일드",
        "워터리",
        "릴리프",
    }
)
_SUN_FORMS = frozenset(
    {"세럼", "크림", "스틱", "스크린", "로션", "젤", "쿠션", "플루이드", "파우더"}
)
FORM_WORDS = frozenset(
    {
        "세럼",
        "앰플",
        "마스크",
        "시트",
        "팩",
        "에센스",
        "크림",
        "젤",
        "로션",
        *("선" + form for form in _SUN_FORMS),
    }
)
_REMOVABLE = re.compile(r"(?:\d+(?:\.\d+)?(?:ml|g|매|입|ea)|\d+\+\d+|spf\d+\+?|pa\+*)")
PriceBasis = Literal["list_price", "sale_price_fallback"]


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).lower()


def _compact(text: str) -> str:
    return "".join(_normalize(text).split())


def _tokens(name: str) -> list[str]:
    # Promotion prefixes are not part of the product identity or its aliases.
    name = re.sub(r"^(?:\s*\[[^\]]*\]\s*)+", "", _normalize(name))
    tokens = [
        token
        for token in name.split()
        if token not in CONTAINER_WORDS and not _REMOVABLE.fullmatch(token)
    ]
    result = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if (
            token == "선"
            and index + 1 < len(tokens)
            and tokens[index + 1] in _SUN_FORMS
        ):
            result.append("선 " + tokens[index + 1])
            index += 2
        else:
            result.append(token)
            index += 1
    return result


def _identity(name: str) -> str:
    # A double pack is an option of the same product, not another formulation.
    return _compact(" ".join(token for token in _tokens(name) if token != "더블"))


def derive_aliases(name_ko: str, *, brand_products: Sequence[str]) -> list[str]:
    """Derive at most three aliases and drop collisions within one brand.

    The caller supplies the entire same-brand listing, not just selected items.
    Brand-only filtering needs the brand itself and is enforced by Product.
    Split sun forms remain single tokens, so shortening never loses '선'.
    """
    tokens = _tokens(name_ko)
    meaningful = [token for token in tokens if token not in STOPWORDS]
    candidates = [" ".join(tokens), " ".join(meaningful)]
    forms = [token for token in meaningful if _compact(token) in FORM_WORDS]
    sun_forms = [token for token in forms if _compact(token).startswith("선")]
    if sun_forms:
        forms = sun_forms
    if meaningful and forms and meaningful[0] != forms[-1]:
        candidates.append(" ".join((meaningful[0], forms[-1])))
    own_identity = _identity(name_ko)
    result = []
    seen = set()
    for candidate in candidates:
        normalized = _compact(candidate)
        if normalized in seen or len(normalized) < 3 or normalized in FORM_WORDS:
            continue
        seen.add(normalized)
        if brand_products:
            matches = {own_identity}
            matches.update(
                _identity(name)
                for name in brand_products
                if normalized in _compact(name)
            )
            if len(matches) > 1:
                continue
        result.append(candidate)
    return result


class ProductKey(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    brand: str = Field(min_length=1)
    source_url: str

    @field_validator("brand")
    @classmethod
    def nonblank_brand(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("brand must not be blank")
        return value.strip()

    @field_validator("source_url")
    @classmethod
    def normalized_url(cls, value: str) -> str:
        parts = urlsplit(value.strip())
        if (
            parts.scheme.lower() not in {"http", "https"}
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
        ):
            raise ValueError(
                "source_url must be an absolute HTTP(S) URL without credentials"
            )
        host = parts.hostname.lower()
        if ":" in host:
            host = f"[{host}]"
        port = parts.port
        if port is not None and (parts.scheme.lower(), port) not in {
            ("http", 80),
            ("https", 443),
        }:
            host += f":{port}"
        return urlunsplit(
            (parts.scheme.lower(), host, parts.path or "/", parts.query, "")
        )


class Product(ProductKey):
    category: Category
    name_ko: str = Field(min_length=1)
    name_en: str | None = None
    aliases: list[str] = Field(default_factory=list)
    volume: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    volume_unit: Literal["ml", "g", "매", "입", "ea"] | None = None
    list_price: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    sale_price: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    price_basis: PriceBasis = "list_price"
    price_collected_at: AwareDatetime | None = None
    form: str | None = None
    skin_types: list[SkinType] = Field(default_factory=list)
    efficacy_texts: list[str] = Field(default_factory=list)
    functional_texts: list[str] = Field(default_factory=list)
    updated_at: AwareDatetime | None = None

    @model_validator(mode="before")
    @classmethod
    def mechanical_aliases(cls, value: Any, info: ValidationInfo) -> Any:
        if not isinstance(value, Mapping):
            return value
        context = info.context or {}
        # Only the storage adapter rehydrates previously derived aliases. Fresh
        # extraction input cannot provide or override them.
        if context.get("from_store"):
            return value
        if "aliases" in value:
            raise ValueError("aliases are derived, not supplied")
        values = dict(value)
        name = values.get("name_ko")
        brand = values.get("brand")
        if isinstance(name, str) and isinstance(brand, str):
            values["aliases"] = [
                alias
                for alias in derive_aliases(
                    name, brand_products=context.get("brand_products", ())
                )
                if _compact(alias) != _compact(brand)
            ]
        return values

    @field_validator("category")
    @classmethod
    def supported_category(cls, category: Category) -> Category:
        if category is Category.other:
            raise ValueError("products must have a supported category")
        return category

    @property
    def key(self) -> ProductKey:
        return ProductKey(brand=self.brand, source_url=self.source_url)


class ProductIngredient(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    product: ProductKey
    order: int = Field(ge=1)
    raw_name: str = Field(min_length=1)
    standard_name: str | None = None
    status: Literal["resolved", "unresolved"]
    matched_by: Literal["kor_exact", "eng_name_exact"] | None = None
    updated_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def consistent_status(self) -> "ProductIngredient":
        if (self.standard_name is not None) != (self.status == "resolved"):
            raise ValueError("only resolved ingredients have a standard name")
        if self.status == "unresolved" and self.matched_by is not None:
            raise ValueError("an unresolved ingredient has no match source")
        return self


class ProductCert(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    product: ProductKey
    kind: FunctionalKind
    status: CertStatus
    evidence_item_name: str | None = None
    evidence_api: Literal["report", "screening"]
    updated_at: AwareDatetime | None = None


class ProductPrice(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    product: ProductKey
    collected_at: AwareDatetime
    list_price: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    sale_price: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    price_basis: PriceBasis


class ProductExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    product: ProductKey
    prompt_version: str = Field(min_length=1)
    raw_output: str


class ProductDetailIngredient(BaseModel):
    """One printed ingredient; parenthesized amounts remain separate raw text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    raw_name: str = Field(min_length=1)
    amount_text: str | None

    @field_validator("raw_name")
    @classmethod
    def nonblank_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("ingredient name must not be blank")
        return value


class ProductDetailResult(BaseModel):
    """Image facts only, with required empty/nullable fields for absent evidence.

    Ingredients retain printed order, spelling, whitespace and repetitions.
    Form and claim texts are source wording, not inferred classifications.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    ingredients: list[ProductDetailIngredient]
    volume: float | None = Field(gt=0, allow_inf_nan=False)
    volume_unit: Literal["ml", "g", "매", "입", "ea"] | None
    form: str | None
    skin_types: list[SkinType]
    efficacy_texts: list[str]
    functional_texts: list[str]


class CachedIngredientStandard(IngredientStandard):
    name_ko: str = Field(min_length=1)
    queried_at: AwareDatetime


class IngredientLookup(BaseModel):
    """One completed ingredient lookup, stored whether or not it matched."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    query_key: str = Field(min_length=1)
    kind: Literal["kor_exact", "eng_exact"]
    standard_name: str | None = None
    queried_at: AwareDatetime


class IngredientCatalogEntry(BaseModel):
    """One row of the MFDS ingredient list, keyed by its position in the download."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    page_no: int = Field(ge=1)
    row_no: int = Field(ge=0)
    name_ko: str = Field(min_length=1)
    name_en: str | None = None
    cas_no: str | None = None
    # totalCount the API reported with this page; tells whether the copy is whole.
    source_total: int = Field(ge=1)
    fetched_at: AwareDatetime


class ProductRepository(Protocol):
    def upsert_product(self, product: Product) -> None:
        """Persist one record and append its price observation atomically."""
        ...

    def get_product(self, key: ProductKey) -> Product | None: ...

    def list_products(self) -> list[Product]: ...

    def add_price(self, price: ProductPrice) -> None: ...

    def get_prices(self, key: ProductKey) -> list[ProductPrice]: ...

    def upsert_ingredients(self, ingredients: Sequence[ProductIngredient]) -> None: ...

    def get_ingredients(self, key: ProductKey) -> list[ProductIngredient]: ...

    def upsert_certs(self, certs: Sequence[ProductCert]) -> None: ...

    def get_certs(self, key: ProductKey) -> list[ProductCert]: ...

    def add_extraction(self, extraction: ProductExtraction) -> None: ...

    def get_extractions(self, key: ProductKey) -> list[ProductExtraction]: ...

    def get_ingredient_standard(
        self, name_ko: str
    ) -> CachedIngredientStandard | None: ...

    def get_ingredient_lookup(
        self, query_key: str, kind: str
    ) -> IngredientLookup | None: ...

    def upsert_ingredient_lookup(self, lookup: IngredientLookup) -> None: ...

    def upsert_catalog_page(
        self, entries: Sequence[IngredientCatalogEntry]
    ) -> None: ...

    def catalog_last_page(self) -> int: ...

    def list_catalog(self) -> list[IngredientCatalogEntry]: ...

    def upsert_ingredient_standard(
        self, standard: CachedIngredientStandard
    ) -> None: ...

    def read_changed_products(self, *, since: datetime | None) -> list[Product]: ...

    def read_changed_ingredients(
        self, *, since: datetime | None
    ) -> list[ProductIngredient]: ...

    def read_changed_certs(self, *, since: datetime | None) -> list[ProductCert]: ...
