from pathlib import Path

import pytest
import yaml

from beautyads.sources.advertiser_classes import (
    AdvertiserClassesError,
    advertiser_class,
    load_advertiser_classes,
)


def test_normalized_mapping_and_unknown(tmp_path):
    path = tmp_path / "classes.yaml"
    path.write_text(
        'advertisers:\n- {name: "ＡＣＭＥ ", class: brand_direct}\n'
        '- {name: Shop, class: retailer}\n- {name: "", class: unknown}\n'
    )
    mapping = load_advertiser_classes(path)
    for name in ("acme", "ACME ", "Ａｃｍｅ"):
        assert advertiser_class(mapping, name) == "brand_direct"
    assert advertiser_class(mapping, " SHOP ") == "retailer"
    for name in ("absent", "", "  ", None):
        assert advertiser_class(mapping, name) == "unknown"


@pytest.mark.parametrize(
    "content",
    [
        "[",
        "{}",
        "advertisers: null",
        "advertisers: [{name: x, class: invented}]",
        "advertisers: [{name: 123, class: unknown}]",
        'advertisers: [{name: "", class: retailer}]',
        'advertisers: [{name: X, class: retailer}, {name: "ｘ ", class: brand_direct}]',
    ],
)
def test_invalid(tmp_path, content):
    path = tmp_path / "bad.yaml"
    path.write_text(content)
    with pytest.raises(AdvertiserClassesError, match="ADVERTISER_CLASSES_INVALID"):
        load_advertiser_classes(path)


def test_missing(tmp_path):
    with pytest.raises(AdvertiserClassesError, match="ADVERTISER_CLASSES_UNREADABLE"):
        load_advertiser_classes(tmp_path / "missing")


def test_repository_mapping_is_valid_without_freezing_names_or_size():
    path = Path("config/advertiser_classes.yaml")
    mapping = load_advertiser_classes(path)
    assert set(mapping.values()) <= {"brand_direct", "retailer", "unknown"}
    for item in yaml.safe_load(path.read_text())["advertisers"]:
        assert item["class"] in {"brand_direct", "retailer", "unknown"}
