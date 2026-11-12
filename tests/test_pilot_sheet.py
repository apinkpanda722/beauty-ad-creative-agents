"""Pilot selection and blind artifacts use only synthetic, temporary data."""

import csv
import hashlib
import inspect
import json
import random
from datetime import UTC, datetime

import pytest

from beautyads.domain import (
    Angle,
    Category,
    Claim,
    ContentType,
    Creative,
    CtaType,
    Format,
    HookType,
    JobResult,
    JobStatus,
    Metrics,
    PlatformFitFlags,
    Source,
    StructureFlags,
    Talent,
)
from beautyads.eval.pilot import PilotSelection, select_pilot
from beautyads.eval.sheets import (
    SheetError,
    build_blind_sheet,
    codebook_rows,
    instructions_text,
    label_columns,
    parse_taxonomy,
    sha256_of,
    write_docs_files,
    write_sheet_files,
)
from beautyads.sources.split import BrandSplit, ResplitRule, VolumeConstraints

NOW = datetime(2026, 11, 12, tzinfo=UTC)


@pytest.fixture
def split():
    return BrandSplit(
        registered_on="2026-11-12",
        seed=17,
        attempt=0,
        dev_size=2,
        brands=["dev-a", "dev-b", "test-a"],
        dev=["dev-a", "dev-b"],
        test=["test-a"],
        static_constraints=[],
        volume=VolumeConstraints(),
        resplit=ResplitRule(),
    )


def creative(index, source=Source.youtube, brand="dev-a", **updates):
    values = {
        "source": source,
        "source_id": f"id-{index:03}",
        "url": f"https://example.invalid/watch/{source}/{index}",
        "title": f"제목 {index}",
        "caption": f"캡션 {index}, 여러 줄\n다음 줄",
        "brand": brand,
        "account": "ACCOUNT_SENTINEL",
        "metrics": Metrics(
            view_count=987654321, like_count=876543219, comment_count=765432198
        ),
        "published_at": NOW,
        "collected_at": NOW,
        "analyzable": True,
    }
    values.update(updates)
    return Creative(**values)


def candidates():
    return [
        creative(index + offset * 10, source, brand)
        for source in (Source.youtube, Source.instagram)
        for offset, brand in enumerate(("dev-a", "dev-b"))
        for index in range(10)
    ]


def test_selection_reproducible_balanced_and_input_order_independent(split):
    items = candidates()
    before = list(items)
    selected = select_pilot(items, split, seed=19)
    assert selected == select_pilot(items, split, seed=19)
    assert selected == select_pilot(list(reversed(items)), split, seed=19)
    assert items == before
    assert selected.shortfall == 0
    assert len(selected.items) == 20
    assert {item.source for item in selected.items} == {
        Source.youtube,
        Source.instagram,
    }
    assert {item.brand for item in selected.items} == {"dev-a", "dev-b"}
    groups = [(item.source, item.brand) for item in selected.items]
    assert all(groups.count(group) == 5 for group in set(groups))


def test_selection_sorted_shuffled_groups_and_round_robin(split):
    items = candidates()
    rng = random.Random(13)
    groups = []
    for source in sorted((Source.youtube, Source.instagram)):
        for brand in sorted(split.dev):
            group = sorted(
                (
                    item
                    for item in items
                    if (item.source, item.brand) == (source, brand)
                ),
                key=lambda item: item.source_id,
            )
            rng.shuffle(group)
            groups.append(group)
    expected = [group[index] for index in range(10) for group in groups][:7]
    assert select_pilot(items, split, n=7, seed=13).items == expected


@pytest.mark.parametrize(
    "updates",
    [
        {"brand": "test-a"},
        {"brand": None},
        {"brand": "unknown"},
        {"analyzable": False},
        {"analyzable": None},
        {"source": Source.tiktok},
    ],
)
def test_selection_excludes_ineligible_without_raising(split, updates):
    allowed = creative(1)
    excluded = creative(2, **updates)
    assert select_pilot([excluded, allowed], split, n=3, seed=1) == PilotSelection(
        [allowed], 2
    )


def test_selection_custom_sources_empty_and_shortfall(split):
    items = [creative(1), creative(2, Source.instagram)]
    assert select_pilot(items, split, seed=1, sources=[Source.instagram]) == (
        [items[1]],
        19,
    )
    assert select_pilot(items, split, seed=1, sources=[]) == ([], 20)
    assert select_pilot([], split, n=7, seed=1) == ([], 7)


@pytest.mark.parametrize("n", [0, -1])
def test_selection_invalid_count(split, n):
    with pytest.raises(ValueError):
        select_pilot([], split, n=n, seed=1)


def test_selection_signature_has_no_model_or_metric_input():
    assert set(inspect.signature(select_pilot).parameters) == {
        "creatives",
        "split",
        "n",
        "seed",
        "sources",
    }


def result(item, kind, *, status=JobStatus.done, labels=None):
    return JobResult(
        key=item.key,
        kind=kind,
        status=status,
        labels=labels,
        error_code="ERROR_SENTINEL" if status == JobStatus.failed else None,
        model="MODEL_SENTINEL",
        thinking_level="minimal",
        prompt_version="v0",
        raw_output="RAW_OUTPUT_SENTINEL",
        attempts=1,
        updated_at=NOW,
    )


def sheet_for(items, *, seed=23, results=None):
    return build_blind_sheet(
        items,
        seed=seed,
        job_results=results or {},
        run_tags=["minimal", "default", "missing"],
        split_sha256="SPLIT_HASH_SENTINEL",
        selection_seed=19,
    )


def test_label_columns_and_codebook_follow_domain():
    enums = {
        "content_type": ContentType,
        "category": Category,
        "hook_type": HookType,
        "angle": Angle,
        "format": Format,
        "talent": Talent,
        "cta_type": CtaType,
        "claims": Claim,
    }
    flags = set(StructureFlags.model_fields) | set(PlatformFitFlags.model_fields)
    columns = label_columns()
    assert len(columns) == len(set(columns)) == 17
    assert set(columns) == set(enums) | flags
    assert "ingredients" not in columns
    expected = {(axis, member.value) for axis, enum in enums.items() for member in enum}
    expected |= {(axis, value) for axis in flags for value in ("true", "false")}
    book = codebook_rows()
    assert {(row["axis"], row["value"]) for row in book} == expected
    assert len(book) == len(expected)


TAXONOMY_SAMPLE = """\
### 1. 훅 유형 `hook_type` (하나 선택)

| 값 | 판정 기준 |
|---|---|
| `alpha` | 첫째 기준 |
| `beta` | 둘째 기준 |

둘 이상 해당하면 표의 위쪽 값을 우선한다.

### 4. 출연자 `talent` (하나 선택)

`none`, `staff`(직원)

- `none`과 `staff`는 구별한다.
"""


def test_taxonomy_definitions_and_priority_are_parsed_not_copied():
    guides = parse_taxonomy(TAXONOMY_SAMPLE)
    assert guides["hook_type"].definitions == {
        "alpha": "첫째 기준",
        "beta": "둘째 기준",
    }
    assert (
        guides["hook_type"].order == ["alpha", "beta"] and guides["hook_type"].ordered
    )
    assert guides["talent"].definitions == {"staff": "직원"}
    assert guides["talent"].bullets == ["`none`과 `staff`는 구별한다."]


def test_codebook_notes_carry_taxonomy_definitions_and_priority():
    book = {
        (row["axis"], row["value"]): row["note"]
        for row in codebook_rows(TAXONOMY_SAMPLE)
    }
    # 합성 문서에 없는 값은 일반 note만 갖고, 있는 값은 정의·우선순위가 앞에 붙는다.
    assert book[("hook_type", "question")].startswith("하나만 고른다.")
    guides = parse_taxonomy(TAXONOMY_SAMPLE)
    assert guides["hook_type"].definitions["alpha"] == "첫째 기준"
    synthetic = codebook_rows(TAXONOMY_SAMPLE.replace("alpha", "question"))
    note = next(
        row["note"]
        for row in synthetic
        if (row["axis"], row["value"]) == ("hook_type", "question")
    )
    assert note.startswith("정의: 첫째 기준.")
    assert "우선순위 1/2(둘 이상 해당하면 숫자가 작은 값)." in note
    staff = next(
        row["note"]
        for row in codebook_rows(TAXONOMY_SAMPLE)
        if (row["axis"], row["value"]) == ("talent", "staff")
    )
    assert staff.startswith("정의: 직원.") and "구별한다" in staff


def test_real_taxonomy_gives_every_tabled_value_a_definition():
    # 표로 정의된 네 축(content_type·hook_type·angle·format)은 값마다 정의 또는
    # 명시적 "정의 없음" 문구가 있어야 한다. 문서와 domain 값이 어긋나면 실패한다.
    notes = {(row["axis"], row["value"]): row["note"] for row in codebook_rows()}
    for axis in ("content_type", "hook_type", "angle", "format"):
        rows = [note for (a, _), note in notes.items() if a == axis]
        assert rows and all(note.startswith(("정의:", "정의 없음")) for note in rows)
    hook_notes = [note for (a, _), note in notes.items() if a == "hook_type"]
    assert all("우선순위" in note for note in hook_notes)


def test_docs_only_rewrite_leaves_sheet_and_key_untouched(tmp_path):
    out = tmp_path / "data/interim/pilot"
    sheet = sheet_for([creative(1), creative(2)])
    files = write_sheet_files(out, sheet, codebook_rows(), instructions_text())
    before = {name: files[name].read_bytes() for name in ("sheet", "key")}
    files["codebook"].write_text("stale", encoding="utf-8")
    written = write_docs_files(out, codebook_rows(), instructions_text())
    assert set(written) == {"codebook", "instructions"}
    assert files["codebook"].read_text(encoding="utf-8") != "stale"
    assert {name: files[name].read_bytes() for name in ("sheet", "key")} == before


def test_docs_only_rewrite_rejects_output_outside_interim(tmp_path):
    out = tmp_path / "tracked"
    with pytest.raises(SheetError) as caught:
        write_docs_files(out, codebook_rows(), instructions_text())
    assert caught.value.code == "OUTPUT_NOT_IGNORED"
    assert not out.exists()


def test_labeling_rules_in_instructions_and_codebook():
    book = codebook_rows()
    for text in (instructions_text(), "\n".join(row["note"] for row in book)):
        for phrase in (
            "product_creative가 아니면",
            "나머지 열",
            "비워",
            "category",
            "other",
            "claims",
            "여럿 선택",
            "쉼표",
            "pilot_key.json",
            "라벨링을 마친 뒤",
            "관찰",
            "추정하지",
            "ingredients",
            "대상이 아니다",
        ):
            assert phrase in text
    for row in book:
        if row["axis"] == "claims":
            assert "여럿 선택" in row["note"] and "쉼표" in row["note"]


def test_sheet_reproducible_shuffled_sequential_and_one_to_one():
    items = [creative(index) for index in range(12)]
    expected = list(items)
    random.Random(23).shuffle(expected)
    sheet = sheet_for(items)
    assert sheet.rows == sheet_for(items).rows
    assert [row["link"] for row in sheet.rows] == [item.url for item in expected]
    assert [row["item_id"] for row in sheet.rows] == [f"P{i:03}" for i in range(1, 13)]
    keys = {row["item_id"]: row for row in sheet.key_rows}
    assert len(keys) == len(items)
    restored = [
        (keys[row["item_id"]]["source"], keys[row["item_id"]]["source_id"])
        for row in sheet.rows
    ]
    assert set(restored) == {(item.source.value, item.source_id) for item in items}
    assert len(set(restored)) == len(items)


def test_blind_csv_and_key_separation(tmp_path):
    item = creative(1, Source.instagram, brand="BRAND_SENTINEL")
    jobs = {}
    for axis in ("content_type", "hook", "full"):
        kind = f"{axis}@minimal"
        jobs[kind, item.key] = result(item, kind, labels={axis: "LABEL_SENTINEL"})
    kind = "full@default"
    jobs[kind, item.key] = result(item, kind, status=JobStatus.failed)
    items = [item, creative(2, title=None, caption=None)]
    sheet = sheet_for(items, results=jobs)
    expected_columns = {"item_id", "link", "text"} | set(label_columns())
    for row in sheet.rows:
        assert set(row) == expected_columns
        assert all(row[axis] == "" for axis in label_columns())
    files = write_sheet_files(
        tmp_path / "data/interim/pilot", sheet, codebook_rows(), instructions_text()
    )
    assert {path.name for path in files.values()} == {
        "pilot_sheet.csv",
        "pilot_codebook.csv",
        "pilot_instructions.md",
        "pilot_key.json",
    }
    csv_text = files["sheet"].read_text(encoding="utf-8")
    key_text = files["key"].read_text(encoding="utf-8")
    for sentinel in (
        "BRAND_SENTINEL",
        "ACCOUNT_SENTINEL",
        "987654321",
        "876543219",
        "765432198",
        "LABEL_SENTINEL",
        "MODEL_SENTINEL",
        "ERROR_SENTINEL",
        "SPLIT_HASH_SENTINEL",
    ):
        assert sentinel not in csv_text
        assert sentinel in key_text
    for forbidden in (
        "source",
        "brand",
        "account",
        "view_count",
        "like_count",
        "comment_count",
        "published_at",
        "model",
        "model_labels",
        "raw_output",
        "media_url",
    ):
        assert forbidden not in expected_columns
    assert "media_url" not in csv_text
    assert "RAW_OUTPUT_SENTINEL" not in key_text
    assert "raw_output" not in key_text
    with files["sheet"].open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    by_link = {row["link"]: row for row in rows}
    assert by_link[item.url]["text"] == f"{item.title}\n{item.caption}"
    assert by_link[items[1].url]["text"] == ""
    document = json.loads(key_text)
    assert document["split_sha256"] == "SPLIT_HASH_SENTINEL"
    assert document["selection_seed"] == 19
    assert document["sheet_seed"] == 23
    assert datetime.fromisoformat(document["generated_at"]).tzinfo is not None
    entries = list(document["items"].values())
    entry = next(row for row in entries if row["source_id"] == item.source_id)
    assert entry["published_at"] == NOW.isoformat()
    for axis in ("content_type", "hook", "full"):
        assert entry["runs"]["minimal"][axis] == jobs[
            f"{axis}@minimal", item.key
        ].model_dump(
            mode="json",
            include={
                "status",
                "labels",
                "error_code",
                "model",
                "thinking_level",
                "prompt_version",
            },
        )
    assert entry["runs"]["default"]["content_type"] is None
    assert entry["runs"]["default"]["full"]["status"] == "failed"
    assert entry["runs"]["missing"] is None
    missing = next(row for row in entries if row["source_id"] == items[1].source_id)
    assert all(value is None for value in missing["runs"].values())
    assert files["instructions"].read_text(encoding="utf-8") == instructions_text()


def test_missing_link_stays_blank():
    assert sheet_for([creative(1, url=None)]).rows[0]["link"] == ""


def test_empty_selection():
    with pytest.raises(SheetError) as caught:
        sheet_for([])
    assert caught.value.code == "EMPTY_SELECTION"


@pytest.mark.parametrize(
    "relative", ["tracked", "data/interim-lookalike", "data/interim/../tracked"]
)
def test_output_outside_interim_rejected_before_writing(tmp_path, relative):
    out = tmp_path / relative
    with pytest.raises(SheetError) as caught:
        write_sheet_files(
            out, sheet_for([creative(1)]), codebook_rows(), instructions_text()
        )
    assert caught.value.code == "OUTPUT_NOT_IGNORED"
    assert not out.exists()


@pytest.mark.parametrize("link_file", [False, True])
def test_output_symlink_escape_rejected(tmp_path, link_file):
    root = tmp_path / "data/interim"
    root.mkdir(parents=True)
    outside = tmp_path / "tracked"
    outside.mkdir()
    if link_file:
        out = root / "pilot"
        out.mkdir()
        (out / "pilot_key.json").symlink_to(outside / "key.json")
    else:
        (root / "escape").symlink_to(outside, target_is_directory=True)
        out = root / "escape/pilot"
    with pytest.raises(SheetError) as caught:
        write_sheet_files(
            out, sheet_for([creative(1)]), codebook_rows(), instructions_text()
        )
    assert caught.value.code == "OUTPUT_NOT_IGNORED"
    assert list(outside.iterdir()) == []


def test_sha256_of_file_bytes(tmp_path):
    path = tmp_path / "split.yaml"
    content = "합성 분할\nseed: 19\n".encode()
    path.write_bytes(content)
    assert sha256_of(path) == hashlib.sha256(content).hexdigest()
