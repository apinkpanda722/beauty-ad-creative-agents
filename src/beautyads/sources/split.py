"""Register reproducible brand partitions before collection or model analysis."""

import argparse
import random
import sys
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

CATEGORIES = ("mask_pack", "serum_ampoule", "sun_care")
_SOURCES = ("youtube", "instagram", "tiktok")
_CONFIG = Path(__file__).resolve().parents[3] / "config"
_STATIC_CONSTRAINTS = [
    "dev와 test는 겹치지 않고 합집합은 등록한 전체 브랜드와 같다.",
    "dev 브랜드 수는 dev_size와 같다.",
    "dev와 test 각각은 후보 정보 기준 mask_pack, serum_ampoule, sun_care를 모두 포함한다.",
    "dev와 test 각각은 YouTube 계정 브랜드와 Instagram 계정 브랜드를 하나 이상 포함한다.",
]


class VolumeConstraints(BaseModel):
    """Draft thresholds, to be confirmed by the user and checked after collection."""

    model_config = ConfigDict(extra="forbid")

    test_analyzable_min_total: int = Field(default=300, ge=0)
    test_analyzable_min_per_source: int = Field(default=100, ge=0)
    dev_analyzable_min_total: int = Field(default=60, ge=0)


class ResplitRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_times: int = Field(default=1, ge=0)
    allowed_until: str = "E1 1단계 라벨링 시작 전"


class ResplitRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    resplit_on: str
    reason: str = Field(min_length=1)
    previous_seed: int
    previous_attempt: int = Field(ge=0)
    previous_dev: list[str]
    previous_test: list[str]


class BrandSplit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    registered_on: str
    seed: int
    attempt: int = Field(ge=0)
    dev_size: int = Field(ge=0)
    brands: list[str]
    dev: list[str]
    test: list[str]
    static_constraints: list[str]
    volume: VolumeConstraints
    resplit: ResplitRule
    history: list[ResplitRecord] = Field(default_factory=list)


class SplitError(Exception):
    """Invalid configuration or a failed split, identified without raw input."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _read_yaml(path: Path, code: str):
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        raise SplitError(code) from None


def _brand_items(items, code: str) -> frozenset[str]:
    if not isinstance(items, list):
        raise SplitError(code)
    brands = set()
    for item in items:
        brand = item.get("brand") if isinstance(item, dict) else None
        if not isinstance(brand, str) or not brand.strip():
            raise SplitError(code)
        brands.add(brand.strip())
    return frozenset(brands)


def brands_by_source(path: Path) -> dict[str, frozenset[str]]:
    document = _read_yaml(path, "SOURCES_CONFIG_INVALID")
    if not isinstance(document, dict) or not isinstance(document.get("tiktok"), dict):
        raise SplitError("SOURCES_CONFIG_INVALID")
    return {
        "youtube": _brand_items(document.get("youtube"), "SOURCES_CONFIG_INVALID"),
        "instagram": _brand_items(document.get("instagram"), "SOURCES_CONFIG_INVALID"),
        "tiktok": _brand_items(
            document.get("tiktok", {}).get("brands"), "SOURCES_CONFIG_INVALID"
        ),
    }


def brands_from_sources(path: Path) -> list[str]:
    return sorted(set().union(*brands_by_source(path).values()))


def load_brand_categories(path: Path) -> dict[str, frozenset[str]]:
    code = "PRODUCT_CANDIDATES_INVALID"
    document = _read_yaml(path, code)
    candidates = document.get("candidates") if isinstance(document, dict) else None
    _brand_items(candidates, code)
    categories: dict[str, set[str]] = {}
    for item in candidates:
        category = item.get("category")
        if category not in CATEGORIES:
            raise SplitError(code)
        categories.setdefault(item.get("brand").strip(), set()).add(category)
    return {brand: frozenset(values) for brand, values in categories.items()}


def static_violations(
    dev: Sequence[str],
    test: Sequence[str],
    *,
    brands: Sequence[str],
    categories: Mapping[str, frozenset[str]],
    dev_size: int,
) -> list[str]:
    """Check static metadata; account membership comes from sources.yaml only."""
    violations = []
    if set(dev) & set(test):
        violations.append("dev/test overlap")
    if set(dev) | set(test) != set(brands):
        violations.append("dev/test union differs from brands")
    if len(dev) != dev_size:
        violations.append("dev_size differs from len(dev)")
    if len(set(dev)) != len(dev) or len(set(test)) != len(test):
        violations.append("duplicate brand within a group")
    sources = brands_by_source(_CONFIG / "sources.yaml")
    for name, group in (("dev", dev), ("test", test)):
        covered = set().union(*(categories.get(brand, frozenset()) for brand in group))
        for category in CATEGORIES:
            if category not in covered:
                violations.append(f"{name} missing category {category}")
        for source in ("youtube", "instagram"):
            if not set(group) & sources.get(source, frozenset()):
                violations.append(f"{name} missing {source} account brand")
    return violations


def make_split(
    brands: Sequence[str],
    *,
    seed: int,
    dev_size: int,
    categories: Mapping[str, frozenset[str]],
    max_attempts: int = 1000,
) -> tuple[list[str], list[str], int]:
    for attempt in range(max_attempts):
        shuffled = sorted(brands)
        random.Random(seed * 1000 + attempt).shuffle(shuffled)
        dev, test = shuffled[:dev_size], shuffled[dev_size:]
        if not static_violations(
            dev, test, brands=brands, categories=categories, dev_size=dev_size
        ):
            return dev, test, attempt
    raise SplitError("NO_VALID_SPLIT")


def _validate_date(value: str) -> None:
    try:
        if date.fromisoformat(value).isoformat() == value:
            return
    except ValueError:
        pass
    raise SplitError("SPLIT_DATE_INVALID")


def load_brand_split(path: Path) -> BrandSplit:
    document = _read_yaml(path, "BRAND_SPLIT_UNREADABLE")
    try:
        split = BrandSplit.model_validate(document)
    except ValidationError:
        raise SplitError("BRAND_SPLIT_INVALID") from None
    _validate_date(split.registered_on)
    for record in split.history:
        _validate_date(record.resplit_on)
    if set(split.dev) & set(split.test):
        raise SplitError("SPLIT_OVERLAP")
    if (
        set(split.brands) != set(split.dev) | set(split.test)
        or split.brands != sorted(set(split.brands))
        or len(set(split.dev)) != len(split.dev)
        or len(set(split.test)) != len(split.test)
    ):
        raise SplitError("SPLIT_BRANDS_MISMATCH")
    if len(split.dev) != split.dev_size:
        raise SplitError("SPLIT_DEV_SIZE")
    if len(split.history) > split.resplit.max_times:
        raise SplitError("RESPLIT_LIMIT")
    return split


def brand_group(split: BrandSplit, brand: str) -> Literal["dev", "test"]:
    if brand in split.dev:
        return "dev"
    if brand in split.test:
        return "test"
    raise SplitError("BRAND_NOT_IN_SPLIT")


def volume_violations(
    split: BrandSplit,
    analyzable_by_source_brand: Mapping[tuple[str, str], int],
) -> list[str]:
    totals = {"dev": 0, "test": 0}
    test_by_source = dict.fromkeys(_SOURCES, 0)
    dev, test = set(split.dev), set(split.test)
    for (source, brand), count in analyzable_by_source_brand.items():
        if source not in _SOURCES:
            continue
        if brand in test:
            totals["test"] += count
            test_by_source[source] += count
        elif brand in dev:
            totals["dev"] += count
    violations = []
    if totals["test"] < split.volume.test_analyzable_min_total:
        violations.append(f"test total below {split.volume.test_analyzable_min_total}")
    for source, count in test_by_source.items():
        if count < split.volume.test_analyzable_min_per_source:
            violations.append(
                f"test {source} below {split.volume.test_analyzable_min_per_source}"
            )
    if totals["dev"] < split.volume.dev_analyzable_min_total:
        violations.append(f"dev total below {split.volume.dev_analyzable_min_total}")
    return violations


def resplit(
    split: BrandSplit,
    *,
    reason: str,
    categories: Mapping[str, frozenset[str]],
    resplit_on: str,
) -> BrandSplit:
    if len(split.history) >= split.resplit.max_times:
        raise SplitError("RESPLIT_LIMIT")
    if not reason.strip():
        raise SplitError("RESPLIT_REASON_REQUIRED")
    _validate_date(resplit_on)
    seed = split.seed
    while True:
        seed += 1
        dev, test, attempt = make_split(
            split.brands, seed=seed, dev_size=split.dev_size, categories=categories
        )
        if set(dev) != set(split.dev):
            break
    previous = ResplitRecord(
        resplit_on=resplit_on,
        reason=reason,
        previous_seed=split.seed,
        previous_attempt=split.attempt,
        previous_dev=split.dev,
        previous_test=split.test,
    )
    return split.model_copy(
        deep=True,
        update={
            "seed": seed,
            "attempt": attempt,
            "dev": dev,
            "test": test,
            "history": [*split.history, previous],
        },
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--write", type=Path)
    action.add_argument("--resplit", action="store_true")
    parser.add_argument("--seed", type=int, default=20261112)
    parser.add_argument("--dev-size", type=int, default=5)
    parser.add_argument("--registered-on")
    parser.add_argument("--reason")
    parser.add_argument("--path", type=Path)
    args = parser.parse_args(argv)
    if args.resplit and (args.path is None or args.reason is None):
        parser.error("--resplit requires --path and --reason")
    try:
        categories = load_brand_categories(_CONFIG / "product_candidates.yaml")
        if args.resplit:
            split = resplit(
                load_brand_split(args.path),
                reason=args.reason,
                categories=categories,
                resplit_on=date.today().isoformat(),
            )
            path = args.path
        else:
            registered_on = args.registered_on or date.today().isoformat()
            _validate_date(registered_on)
            brands = brands_from_sources(_CONFIG / "sources.yaml")
            dev, test, attempt = make_split(
                brands, seed=args.seed, dev_size=args.dev_size, categories=categories
            )
            split = BrandSplit(
                registered_on=registered_on,
                seed=args.seed,
                attempt=attempt,
                dev_size=args.dev_size,
                brands=brands,
                dev=dev,
                test=test,
                static_constraints=_STATIC_CONSTRAINTS,
                volume=VolumeConstraints(),
                resplit=ResplitRule(),
            )
            path = args.write
        path.write_text(
            yaml.safe_dump(split.model_dump(), allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    except SplitError as exc:
        print(exc.code, file=sys.stderr)
        return 1
    except OSError:
        print("BRAND_SPLIT_WRITE_FAILED", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
