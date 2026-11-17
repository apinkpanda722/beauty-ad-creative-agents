"""Frozen, exact advertiser-name classification; no heuristic fallback."""

import unicodedata
from collections.abc import Mapping
from pathlib import Path

import yaml

CLASSES = frozenset({"brand_direct", "retailer", "unknown"})


class AdvertiserClassesError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def normalize_advertiser(name: str | None) -> str:
    return unicodedata.normalize("NFKC", name or "").strip().lower()


def advertiser_class(mapping: Mapping[str, str], name: str | None) -> str:
    normalized = normalize_advertiser(name)
    return mapping.get(normalized, "unknown") if normalized else "unknown"


def load_advertiser_classes(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise AdvertiserClassesError("ADVERTISER_CLASSES_UNREADABLE") from None
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError:
        raise AdvertiserClassesError("ADVERTISER_CLASSES_INVALID") from None
    rows = document.get("advertisers") if isinstance(document, dict) else None
    if not isinstance(rows, list):
        raise AdvertiserClassesError("ADVERTISER_CLASSES_INVALID")
    result = {}
    for row in rows:
        name = row.get("name") if isinstance(row, dict) else None
        value = row.get("class") if isinstance(row, dict) else None
        if (
            not isinstance(name, str)
            or not isinstance(value, str)
            or value not in CLASSES
        ):
            raise AdvertiserClassesError("ADVERTISER_CLASSES_INVALID")
        key = normalize_advertiser(name)
        if (not key and value != "unknown") or key in result:
            raise AdvertiserClassesError("ADVERTISER_CLASSES_INVALID")
        result[key] = value
    return result
