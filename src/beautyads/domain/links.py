"""Frozen, text-only product matching and storage-independent layer-two inputs."""

import random
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol

from beautyads.domain.creative import Source
from beautyads.domain.labels import Claim, ContentType
from beautyads.domain.products import Product
from beautyads.domain.sync import SyncCreative, SyncLabel

MIN_ALIAS_LEN = 3
DEFAULT_SEED = 20261115
DEFAULT_SAMPLE_PAIRS = 20


def normalize(text: str | None) -> str:
    return "".join(unicodedata.normalize("NFKC", text or "").casefold().split())


@dataclass(frozen=True)
class LinkCreative:
    creative: SyncCreative
    labels: Sequence[SyncLabel] = ()

    def final_labels(self, kind: str) -> Mapping[str, Any]:
        return next(
            (
                job.labels
                for job in self.labels
                if job.kind == kind
                and job.status == "done"
                and isinstance(job.labels, Mapping)
            ),
            {},
        )

    @property
    def is_product(self) -> bool:
        return (
            self.final_labels("content_type@v1").get("content_type")
            == ContentType.product_creative
        )


@dataclass(frozen=True)
class ProductMatch:
    status: Literal["matched"]
    product: Product
    basis: Literal["title", "caption", "video"]
    confidence: Literal["name_full", "alias", "model"]
    matched_text: str


@dataclass(frozen=True)
class ProductLinks:
    """Every product named in a creative's text (one link per product)."""

    status: Literal["matched", "ambiguous", "no_match", "not_product"]
    matches: tuple[ProductMatch, ...] = ()

    @property
    def multi_product(self) -> bool:
        return len(self.matches) > 1


def _occurrences(text: str, needle: str):
    start = text.find(needle)
    while start != -1:
        yield start, start + len(needle)
        start = text.find(needle, start + 1)


def match_products(creative: LinkCreative, products: Sequence[Product]) -> ProductLinks:
    """Link every same-brand product whose whole name or alias appears in the text.

    A mention inside a longer different product's mention (a shorter name within a
    longer product name) does not count. Two different products with the identical
    mention are ambiguous and neither is linked for it. One product with several
    matching names is one link: the longest name, full name before alias, title
    before caption. Links are ordered by where they appear (title first). A creative
    that names more than one product is multi_product.
    """
    if not creative.is_product:
        return ProductLinks("not_product")
    properties = creative.creative.properties
    texts = [
        (basis, normalize(properties.get(basis))) for basis in ("title", "caption")
    ]
    mentions = []
    for product in products:
        if product.brand != properties.get("brand"):
            continue
        names = [
            (product.name_ko, "name_full"),
            (product.name_en, "alias"),
            *((alias, "alias") for alias in product.aliases),
        ]
        for name, confidence in names:
            compact = normalize(name)
            if not compact or (confidence == "alias" and len(compact) < MIN_ALIAS_LEN):
                continue
            for basis, text in texts:
                for start, end in _occurrences(text, compact):
                    mentions.append(
                        (basis, start, end, product, name, confidence, compact)
                    )
    survivors = []
    ambiguous = False
    for mention in mentions:
        basis, start, end, product, *_ = mention
        covered = any(
            other[0] == basis
            and other[3].key != product.key
            and other[1] <= start
            and end <= other[2]
            and other[2] - other[1] > end - start
            for other in mentions
        )
        if covered:
            continue
        shared = any(
            other[:3] == mention[:3] and other[3].key != product.key
            for other in mentions
        )
        if shared:
            ambiguous = True
            continue
        survivors.append(mention)
    best = {}
    for basis, start, end, product, name, confidence, compact in survivors:
        rank = (
            -len(compact),
            confidence != "name_full",
            basis != "title",
            compact,
            name,
        )
        position = (basis != "title", start)
        current = best.get(product.key)
        if current is None or rank < current[0]:
            best[product.key] = (
                rank,
                position,
                ProductMatch("matched", product, basis, confidence, name),
            )
    if not best:
        return ProductLinks("ambiguous" if ambiguous else "no_match")
    ordered = sorted(best.values(), key=lambda item: (item[1], item[0]))
    return ProductLinks("matched", tuple(item[2] for item in ordered))


@dataclass(frozen=True)
class Mention:
    raw_name: str
    standard_name: str


@dataclass(frozen=True)
class LinkPlan:
    product_links: ProductLinks
    claims: tuple[str, ...]
    mentions: tuple[Mention, ...]
    unresolved: int

    @property
    def status(self) -> str:
        return self.product_links.status

    @property
    def links(self) -> tuple[ProductMatch, ...]:
        return self.product_links.matches

    @property
    def multi_product(self) -> bool:
        return self.product_links.multi_product


def _list(value) -> list:
    return value if isinstance(value, list) else []


# Video identification feeds PROMOTES only for a version a person approved after
# reviewing its pairs. Empty means no video result is read.
PRODUCT_ID_APPROVED_TAG = ""


def approved_video_kinds() -> tuple[str, ...]:
    return (f"product-id@{PRODUCT_ID_APPROVED_TAG}",) if PRODUCT_ID_APPROVED_TAG else ()


def _video_supplement(
    creative: LinkCreative,
    products: Sequence[Product],
    text: ProductLinks,
    video_kind: str | None,
) -> ProductLinks:
    if video_kind is None:
        kinds = approved_video_kinds()
        video_kind = kinds[0] if kinds else None
    if (
        video_kind is None
        or text.status
        in {
            "matched",
            "not_product",
        }
        or creative.creative.key.source not in {Source.youtube, Source.instagram}
    ):
        return text
    selected = _list(creative.final_labels(video_kind).get("products"))
    identities = {
        (row.get("brand"), row.get("source_url"))
        for row in selected
        if isinstance(row, Mapping)
        and isinstance(row.get("brand"), str)
        and isinstance(row.get("source_url"), str)
    }
    matches = tuple(
        ProductMatch("matched", product, "video", "model", "")
        for product in products
        if product.brand == creative.creative.properties.get("brand")
        and (product.brand, product.source_url) in identities
    )
    return ProductLinks("matched", matches) if matches else text


def plan_links(
    creative: LinkCreative,
    products: Sequence[Product],
    *,
    video_kind: str | None = None,
) -> LinkPlan:
    full = creative.final_labels("full@v1")
    allowed = {claim.value for claim in Claim if claim is not Claim.other}
    claims = tuple(
        sorted(
            {
                v
                for v in _list(full.get("claims"))
                if isinstance(v, str) and v in allowed
            }
        )
    )
    matches = _list(creative.final_labels("ingredient-matches@v1").get("ingredients"))
    raw_names = sorted(
        {v for v in _list(full.get("ingredients")) if isinstance(v, str) and v.strip()}
    )
    mentions = []
    for raw in raw_names:
        standards = {
            row.get("standard_name")
            for row in matches
            if isinstance(row, Mapping)
            and row.get("raw_name") == raw
            and row.get("status") == "resolved"
            and isinstance(row.get("standard_name"), str)
            and row.get("standard_name").strip()
        }
        if len(standards) == 1:
            mentions.append(Mention(raw, next(iter(standards))))
    return LinkPlan(
        _video_supplement(
            creative, products, match_products(creative, products), video_kind
        ),
        claims,
        tuple(mentions),
        len(raw_names) - len(mentions),
    )


def select_rules(dev_creatives: Sequence[LinkCreative]) -> dict:
    """The approved rule is fixed; only dev inputs may enter rule selection.

    No coverage (including test coverage) changes these constants at runtime.
    """
    return {"min_alias_len": MIN_ALIAS_LEN, "candidate_selection": "longest_unique"}


def summarize_links(
    entries: Sequence[LinkCreative],
    products: Sequence[Product],
    *,
    dev_brands: Sequence[str],
    test_brands: Sequence[str],
    sample_pairs: int = DEFAULT_SAMPLE_PAIRS,
    seed: int = DEFAULT_SEED,
) -> dict:
    if sample_pairs < 0:
        raise ValueError("sample_pairs must be nonnegative")
    available = {product.brand for product in products}
    prepared = [(entry, plan_links(entry, products)) for entry in entries]

    def counts(rows):
        product_rows = [(entry, plan) for entry, plan in rows if entry.is_product]
        eligible = [
            (entry, plan)
            for entry, plan in product_rows
            if entry.creative.properties.get("brand") in available
        ]
        promotes = sum(plan.status == "matched" for _, plan in eligible)
        return {
            "promotes": promotes,
            "product_creatives": len(eligible),
            "all_product_creatives": len(product_rows),
            "excluded_no_product_info": len(product_rows) - len(eligible),
            "coverage": promotes / len(eligible) if eligible else 0,
            "ambiguous": sum(plan.status == "ambiguous" for _, plan in eligible),
            "promotes_links": sum(len(plan.links) for _, plan in eligible),
            "by_basis": {
                basis: sum(
                    match.basis == basis for _, plan in eligible for match in plan.links
                )
                for basis in ("title", "caption", "video")
            },
            "multi_product_creatives": sum(plan.multi_product for _, plan in eligible),
            "claims": sum(len(plan.claims) for _, plan in rows),
            "mentions": sum(len(plan.mentions) for _, plan in rows),
            "unresolved": sum(plan.unresolved for _, plan in rows),
            "candidates": sum(
                any(
                    normalize(entry.creative.properties.get(field))
                    for field in ("title", "caption")
                )
                for entry, _ in product_rows
            ),
        }

    def by_source(rows):
        return {
            source.value: counts(
                [(e, p) for e, p in rows if e.creative.key.source == source]
            )
            for source in Source
        }

    report = counts(prepared)
    report["by_source"] = by_source(prepared)
    report["candidates_by_source"] = {
        source: values["candidates"] for source, values in report["by_source"].items()
    }
    groups = {}
    for name, brands in (("dev", dev_brands), ("test", test_brands)):
        rows = [
            (e, p) for e, p in prepared if e.creative.properties.get("brand") in brands
        ]
        groups[name] = rows
        report[name] = {**counts(rows), "by_source": by_source(rows)}
    report["rules"] = select_rules([e for e, _ in groups["dev"]])
    brands = (
        set(dev_brands)
        | set(test_brands)
        | {e.creative.properties.get("brand") for e in entries}
    )
    report["no_product_info_brands"] = sorted(b for b in brands - available if b)
    linked = sorted(
        [(e, match, p.multi_product) for e, p in prepared for match in p.links],
        key=lambda item: (
            item[0].creative.key.source.value,
            item[0].creative.key.source_id,
            item[1].product.source_url,
        ),
    )
    report["sample_pairs"] = [
        {
            "source": entry.creative.key.source.value,
            "source_id": entry.creative.key.source_id,
            "title": (entry.creative.properties.get("title") or "")[:120],
            "caption": (entry.creative.properties.get("caption") or "")[:120],
            "product_name": match.product.name_ko,
            "product_source_url": match.product.source_url,
            "matched_text": match.matched_text,
            "basis": match.basis,
            "confidence": match.confidence,
            "multi_product": multi,
        }
        for entry, match, multi in random.Random(seed).sample(
            linked, min(sample_pairs, len(linked))
        )
    ]
    report["sample_seed"] = seed
    report["recommendation"] = (
        "YouTube·Instagram의 test 제품 소재에 미연결 소재가 있습니다. 영상에서 제품을 식별하는 별도 추출을 제안합니다(유료 모델 비용 발생, 실행하지 않음)."
        if any(
            values["product_creatives"] > values["promotes"]
            for source, values in report["test"]["by_source"].items()
            if source in {"youtube", "instagram"}
        )
        else None
    )
    return report


@dataclass(frozen=True)
class LinksSnapshot:
    changed: Sequence[LinkCreative]
    products: Sequence[Product]


class LinksSource(Protocol):
    def read_snapshot(
        self, *, since: datetime | None, limit: int | None
    ) -> LinksSnapshot: ...

    def get_watermark(self) -> datetime | None: ...

    def set_watermark(self, value: datetime) -> None: ...
