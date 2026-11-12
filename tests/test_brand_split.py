"""Pre-collection splits use only configuration and synthetic volume counts."""

import random
from datetime import date
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from beautyads.sources import split as module
from beautyads.sources.split import (
    CATEGORIES,
    BrandSplit,
    ResplitRule,
    SplitError,
    VolumeConstraints,
    brand_group,
    brands_by_source,
    brands_from_sources,
    load_brand_categories,
    load_brand_split,
    main,
    make_split,
    resplit,
    static_violations,
    volume_violations,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ("youtube", "instagram", "tiktok")


def write_yaml(path, data):
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


@pytest.fixture
def synthetic(monkeypatch):
    brands = [f"synthetic_{i}" for i in range(len(CATEGORIES) * 2)]
    categories = {
        brand: frozenset([CATEGORIES[i % len(CATEGORIES)]])
        for i, brand in enumerate(brands)
    }
    sources = {source: frozenset(brands) for source in SOURCES}
    monkeypatch.setattr(module, "brands_by_source", lambda path: sources)
    return brands, categories, sources


def new_split(synthetic):
    brands, categories, _ = synthetic
    dev_size = len(brands) // 2
    seed = 17
    dev, test, attempt = make_split(
        brands, seed=seed, dev_size=dev_size, categories=categories
    )
    return BrandSplit(
        registered_on="2026-11-12",
        seed=seed,
        attempt=attempt,
        dev_size=dev_size,
        brands=brands,
        dev=dev,
        test=test,
        static_constraints=["Synthetic static constraints"],
        volume=VolumeConstraints(),
        resplit=ResplitRule(),
    )


def test_make_split_is_deterministic_and_uses_first_valid_attempt(synthetic):
    brands, categories, _ = synthetic
    dev_size = len(brands) // 2
    # Choose a synthetic seed whose initial attempt fails, so minimality is tested.
    seed = next(
        seed
        for seed in range(100)
        if make_split(brands, seed=seed, dev_size=dev_size, categories=categories)[2]
        > 0
    )
    result = make_split(brands, seed=seed, dev_size=dev_size, categories=categories)
    assert result == make_split(
        list(reversed(brands)), seed=seed, dev_size=dev_size, categories=categories
    )
    dev, test, attempt = result
    for k in range(attempt + 1):
        shuffled = sorted(brands)
        random.Random(seed * 1000 + k).shuffle(shuffled)
        violations = static_violations(
            shuffled[:dev_size],
            shuffled[dev_size:],
            brands=brands,
            categories=categories,
            dev_size=dev_size,
        )
        if k < attempt:
            assert violations
        else:
            assert not violations
            assert (dev, test) == (shuffled[:dev_size], shuffled[dev_size:])


def test_no_valid_split(synthetic):
    brands, _, _ = synthetic
    with pytest.raises(SplitError) as caught:
        make_split(brands, seed=0, dev_size=len(brands) // 2, categories={})
    assert caught.value.code == "NO_VALID_SPLIT"


@pytest.mark.parametrize(
    "case, expected",
    [
        ("overlap", "overlap"),
        ("union", "union"),
        ("size", "dev_size"),
        ("category", "dev missing category"),
        ("youtube", "dev missing youtube"),
        ("instagram", "test missing instagram"),
    ],
)
def test_static_constraints_independently(synthetic, case, expected):
    brands, categories, sources = synthetic
    split = new_split(synthetic)
    dev, test = split.dev.copy(), split.test.copy()
    dev_size = split.dev_size
    if case == "overlap":
        test.append(dev[0])
    elif case == "union":
        test.pop()
    elif case == "size":
        dev_size += 1
    elif case == "category":
        categories = {
            brand: values for brand, values in categories.items() if brand not in dev
        }
    elif case == "youtube":
        sources["youtube"] = frozenset(test)
    else:
        sources["instagram"] = frozenset(dev)
    assert any(
        expected in item
        for item in static_violations(
            dev, test, brands=brands, categories=categories, dev_size=dev_size
        )
    )


def source_document():
    brands = [f"source_brand_{i}" for i in range(3)]
    return {
        "youtube": [{"brand": brands[0]}, {"brand": brands[0]}],
        "instagram": [{"brand": brands[1]}],
        "tiktok": {
            "countries": ["DE"],
            "brands": [{"brand": brands[2], "search_term": "synthetic"}],
        },
    }


def test_source_shapes_and_deduplication(tmp_path):
    document = source_document()
    path = write_yaml(tmp_path / "sources.yaml", document)
    expected = {
        source: frozenset(
            item["brand"]
            for item in (
                document[source]["brands"] if source == "tiktok" else document[source]
            )
        )
        for source in SOURCES
    }
    assert brands_by_source(path) == expected
    assert brands_from_sources(path) == sorted(set().union(*expected.values()))


@pytest.mark.parametrize("source", SOURCES)
@pytest.mark.parametrize("bad", [None, "invalid", {}, [None], [{"brand": " "}]])
def test_invalid_source_shapes(tmp_path, source, bad):
    document = source_document()
    document[source] = bad
    with pytest.raises(SplitError) as caught:
        brands_by_source(write_yaml(tmp_path / "sources.yaml", document))
    assert caught.value.code == "SOURCES_CONFIG_INVALID"


@pytest.mark.parametrize("source", SOURCES)
def test_missing_source_section(tmp_path, source):
    document = source_document()
    document.pop(source)
    with pytest.raises(SplitError, match="SOURCES_CONFIG_INVALID"):
        brands_by_source(write_yaml(tmp_path / "sources.yaml", document))


def test_invalid_tiktok_nested_brand(tmp_path):
    document = source_document()
    document["tiktok"]["brands"] = [{"search_term": "synthetic"}]
    with pytest.raises(SplitError, match="SOURCES_CONFIG_INVALID"):
        brands_by_source(write_yaml(tmp_path / "sources.yaml", document))


def test_categories_are_aggregated_without_inventing_missing_brands(tmp_path):
    brands = [f"candidate_brand_{i}" for i in range(2)]
    path = write_yaml(
        tmp_path / "candidates.yaml",
        {
            "candidates": [
                {"brand": brands[0], "category": category} for category in CATEGORIES
            ]
        },
    )
    assert load_brand_categories(path) == {brands[0]: frozenset(CATEGORIES)}
    assert brands[1] not in load_brand_categories(path)


def test_repository_registration_is_current_and_reproducible():
    split = load_brand_split(ROOT / "config" / "brand_split.yaml")
    sources_path = ROOT / "config" / "sources.yaml"
    brands = brands_from_sources(sources_path)
    assert split.brands == brands, "sources.yaml 변경: 브랜드 분할 재등록이 필요합니다"
    assert all(brands_by_source(sources_path).values())
    categories = load_brand_categories(ROOT / "config" / "product_candidates.yaml")
    assert make_split(
        brands, seed=split.seed, dev_size=split.dev_size, categories=categories
    ) == (split.dev, split.test, split.attempt)
    assert len(split.dev) == split.dev_size
    assert len(split.test) == len(brands) - split.dev_size
    assert (
        static_violations(
            split.dev,
            split.test,
            brands=brands,
            categories=categories,
            dev_size=split.dev_size,
        )
        == []
    )
    assert split.history == []


def test_volume_thresholds_and_empty_input(synthetic):
    split = new_split(synthetic)
    counts = {
        (source, split.test[0]): split.volume.test_analyzable_min_per_source
        for source in SOURCES
    }
    counts[(SOURCES[0], split.dev[0])] = split.volume.dev_analyzable_min_total
    assert volume_violations(split, counts) == []
    empty = volume_violations(split, {})
    assert len(empty) == len(SOURCES) + 2
    assert any("test total" in item for item in empty)
    assert any("dev total" in item for item in empty)
    for source in SOURCES:
        assert any(source in item for item in empty)
    # Isolate each check by relaxing the other thresholds.
    total_only = split.model_copy(
        update={
            "volume": VolumeConstraints(
                test_analyzable_min_total=split.volume.test_analyzable_min_total + 1,
                test_analyzable_min_per_source=0,
                dev_analyzable_min_total=0,
            )
        }
    )
    assert len(volume_violations(total_only, counts)) == 1
    without_source = {
        key: value for key, value in counts.items() if key[0] != SOURCES[-1]
    }
    source_only = split.model_copy(
        update={
            "volume": VolumeConstraints(
                test_analyzable_min_total=0,
                dev_analyzable_min_total=0,
            )
        }
    )
    assert len(volume_violations(source_only, without_source)) == 1
    without_dev = {key: value for key, value in counts.items() if key[1] in split.test}
    assert len(volume_violations(split, without_dev)) == 1
    assert volume_violations(split, {("unknown", "unregistered"): 10000}) == empty


def test_brand_group(synthetic):
    split = new_split(synthetic)
    for brand in split.dev:
        assert brand_group(split, brand) == "dev"
    for brand in split.test:
        assert brand_group(split, brand) == "test"
    with pytest.raises(SplitError) as caught:
        brand_group(split, "unregistered")
    assert caught.value.code == "BRAND_NOT_IN_SPLIT"


@pytest.mark.parametrize(
    "case, code",
    [
        ("extra", "BRAND_SPLIT_INVALID"),
        ("overlap", "SPLIT_OVERLAP"),
        ("union", "SPLIT_BRANDS_MISMATCH"),
        ("date", "SPLIT_DATE_INVALID"),
        ("size", "SPLIT_DEV_SIZE"),
        ("history", "RESPLIT_LIMIT"),
    ],
)
def test_load_rejects_invalid_registration(tmp_path, synthetic, case, code):
    split = new_split(synthetic)
    raw = split.model_dump()
    if case == "extra":
        raw["unexpected"] = True
    elif case == "overlap":
        raw["test"].append(raw["dev"][0])
    elif case == "union":
        raw["brands"].pop()
    elif case == "date":
        raw["registered_on"] = "2026-02-30"
    elif case == "size":
        raw["dev_size"] += 1
    else:
        record = {
            "resplit_on": split.registered_on,
            "reason": "synthetic shortage",
            "previous_seed": split.seed,
            "previous_attempt": split.attempt,
            "previous_dev": split.dev,
            "previous_test": split.test,
        }
        raw["history"] = [record for _ in range(split.resplit.max_times + 1)]
    with pytest.raises(SplitError) as caught:
        load_brand_split(write_yaml(tmp_path / "split.yaml", raw))
    assert caught.value.code == code


@pytest.mark.parametrize(
    "loader", [brands_by_source, load_brand_categories, load_brand_split]
)
def test_yaml_read_failures_are_split_errors(tmp_path, loader):
    path = tmp_path / "missing.yaml"
    with pytest.raises(SplitError):
        loader(path)
    path.write_text("broken: [", encoding="utf-8")
    with pytest.raises(SplitError):
        loader(path)


def test_model_forbids_extras_and_history_defaults_are_independent(synthetic):
    first, second = new_split(synthetic), new_split(synthetic)
    assert first.history is not second.history
    with pytest.raises(ValidationError):
        BrandSplit.model_validate({**first.model_dump(), "extra": True})


def test_resplit_records_previous_partition_and_roundtrips(tmp_path, synthetic):
    split = new_split(synthetic)
    changed = resplit(
        split,
        reason="synthetic collection shortage",
        categories=synthetic[1],
        resplit_on="2026-11-13",
    )
    assert changed.seed >= split.seed + 1
    assert set(changed.dev) != set(split.dev)
    assert len(changed.history) == len(split.history) + 1
    record = changed.history[-1]
    assert record.model_dump() == {
        "resplit_on": "2026-11-13",
        "reason": "synthetic collection shortage",
        "previous_seed": split.seed,
        "previous_attempt": split.attempt,
        "previous_dev": split.dev,
        "previous_test": split.test,
    }
    assert make_split(
        changed.brands,
        seed=changed.seed,
        dev_size=changed.dev_size,
        categories=synthetic[1],
    ) == (changed.dev, changed.test, changed.attempt)
    assert (
        static_violations(
            changed.dev,
            changed.test,
            brands=changed.brands,
            categories=synthetic[1],
            dev_size=changed.dev_size,
        )
        == []
    )
    assert (
        load_brand_split(write_yaml(tmp_path / "split.yaml", changed.model_dump()))
        == changed
    )
    assert split.history == []
    with pytest.raises(SplitError, match="RESPLIT_LIMIT"):
        resplit(
            changed,
            reason="another shortage",
            categories=synthetic[1],
            resplit_on="2026-11-14",
        )


def test_resplit_skips_seed_with_same_dev_set(monkeypatch, synthetic):
    split = new_split(synthetic)
    original = module.make_split
    seeds = []

    def same_first(brands, *, seed, **kwargs):
        seeds.append(seed)
        if seed == split.seed + 1:
            return list(reversed(split.dev)), split.test.copy(), 0
        return original(brands, seed=seed, **kwargs)

    monkeypatch.setattr(module, "make_split", same_first)
    changed = resplit(
        split, reason="shortage", categories=synthetic[1], resplit_on="2026-11-13"
    )
    assert seeds == list(range(split.seed + 1, changed.seed + 1))
    assert changed.seed > split.seed + 1
    assert set(changed.dev) != set(split.dev)


@pytest.mark.parametrize("reason", ["", " \t "])
def test_resplit_requires_reason(synthetic, reason):
    with pytest.raises(SplitError, match="RESPLIT_REASON_REQUIRED"):
        resplit(
            new_split(synthetic),
            reason=reason,
            categories=synthetic[1],
            resplit_on="2026-11-13",
        )


def test_cli_initial_write_and_resplit(tmp_path, monkeypatch, synthetic):
    brands, categories, _ = synthetic
    monkeypatch.setattr(module, "brands_from_sources", lambda path: brands)
    monkeypatch.setattr(module, "load_brand_categories", lambda path: categories)
    path = tmp_path / "split.yaml"
    assert (
        main(
            ["--write", str(path), "--seed", "17", "--dev-size", str(len(brands) // 2)]
        )
        == 0
    )
    first = load_brand_split(path)
    assert first.registered_on == date.today().isoformat()
    assert first.history == []
    assert (
        main(["--resplit", "--reason", "synthetic shortage", "--path", str(path)]) == 0
    )
    changed = load_brand_split(path)
    assert set(changed.dev) != set(first.dev)
    assert changed.history[-1].reason == "synthetic shortage"


def test_cli_resplit_requires_reason_without_writing(tmp_path, synthetic):
    path = write_yaml(tmp_path / "split.yaml", new_split(synthetic).model_dump())
    before = path.read_bytes()
    with pytest.raises(SystemExit) as caught:
        main(["--resplit", "--path", str(path)])
    assert caught.value.code != 0
    assert path.read_bytes() == before
