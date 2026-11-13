"""Stage two validates human labels and never needs a database or model result."""

import csv
import hashlib
import json
from io import StringIO
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from beautyads.eval import e1_sampling as e1
from beautyads.eval import e1_stage2 as stage2
from beautyads.eval.sheets import label_columns

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ["item_id", "link", "text", "content_type", "category"]


def write_labels(path, rows, fields=FIELDS):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = {
        "seed": 1,
        "stage1": {"min_labeled": 4, "max_labeled": 8, "target_product": 3},
        "stage2": {"size": 3},
        "sources": ["youtube", "instagram"],
        "dedupe": {
            "youtube": ["source", "account", "title", "caption"],
            "instagram": ["source", "account", "caption"],
        },
    }
    (tmp_path / "config").mkdir()
    (tmp_path / "config/e1_sampling.yaml").write_text(yaml.safe_dump(config))
    (tmp_path / "docs/results").mkdir(parents=True)
    prereg = tmp_path / "docs/results/e1_preregistration.md"
    prereg.write_text("synthetic registration")
    (tmp_path / "docs/TAXONOMY.md").write_text((ROOT / "docs/TAXONOMY.md").read_text())
    folder = tmp_path / "data/interim/e1"
    folder.mkdir(parents=True)
    rows = [
        {
            "item_id": f"E{i:03}",
            "link": f"https://example.org/{i}",
            "text": f"title {i}",
            "content_type": "product_creative" if i % 2 else "other",
            "category": "mask_pack" if i % 2 else "other",
        }
        for i in range(1, 9)
    ]
    items = {
        row["item_id"]: {
            "source": "youtube" if i % 2 else "instagram",
            "source_id": str(i),
            "brand": "BRAND_SENTINEL",
            "account": "ACCOUNT_SENTINEL",
            "url": row["link"],
        }
        for i, row in enumerate(rows, 1)
    }
    key = folder / "e1_stage1_key.json"
    key.write_text(
        json.dumps(
            {
                "seed": 1,
                "items": items,
                "preregistration_sha256": e1.sha256_of(prereg),
                "config_sha256": e1.sha256_of(tmp_path / "config/e1_sampling.yaml"),
            }
        )
    )
    labels = folder / "e1_stage1_sheet_labeled.csv"
    write_labels(labels, rows)
    return folder, labels, key, rows, e1.E1Config.model_validate(config)


def call_main(folder, labels=None, key=None):
    out = StringIO()
    args = ["--out-dir", str(folder)]
    if labels is not None:
        args += ["--labels", str(labels)]
    if key is not None:
        args += ["--key", str(key)]
    return stage2.main(args, out=out), out.getvalue()


@pytest.mark.parametrize(
    "problem",
    [
        "missing",
        "headers",
        "value",
        "category",
        "unknown",
        "skip",
        "gap",
        "partial",
        "duplicate",
        "order",
        "extra_cell",
    ],
)
def test_invalid_labels_write_nothing(workspace, problem):
    folder, labels, key, rows, config = workspace
    if problem == "missing":
        labels.unlink()
    elif problem == "headers":
        write_labels(labels, [], ["item_id", "content_type"])
    else:
        if problem == "value":
            rows[0]["content_type"] = "not_in_codebook"
        elif problem == "category":
            rows[0]["category"] = "not_in_codebook"
        elif problem == "unknown":
            rows[0]["item_id"] = "E999"
        elif problem == "skip":
            rows.pop(1)
        elif problem == "gap":
            rows[1].update(content_type="", category="")
        elif problem == "partial":
            rows[1]["category"] = ""
        elif problem == "duplicate":
            rows[1]["item_id"] = rows[0]["item_id"]
        elif problem == "order":
            rows[0], rows[1] = rows[1], rows[0]
        write_labels(labels, rows)
        if problem == "extra_cell":
            with labels.open("a") as stream:
                stream.write("E009,x,x,other,other,extra\n")
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    expected = "LABEL_FILE_MISSING" if problem == "missing" else "LABEL_FILE_INVALID"
    with pytest.raises(e1.E1Error, match=expected):
        stage2.read_stage1_labels(labels, key, config)
    code, text = call_main(folder)
    assert code == 2 and expected in text
    assert before == {p.name: p.read_bytes() for p in folder.iterdir()}


def test_first_stop_and_unused(workspace):
    _, labels, key, _, config = workspace
    loaded = stage2.read_stage1_labels(labels, key, config)
    stop = stage2.stop_point(loaded, config)
    assert stop.position == 5 and stop.product_count == 3
    assert stop.unused_count == 3
    assert [item.item_id for item in stop.items] == [f"E{i:03}" for i in range(1, 6)]
    # Product target alone is insufficient before the minimum number of labels.
    config = config.model_copy(
        update={"stage1": config.stage1.model_copy(update={"target_product": 1})}
    )
    assert stage2.stop_point(loaded, config).position == 4


def test_trailing_blanks_and_maximum(workspace):
    _, labels, key, rows, config = workspace
    for row in rows[6:]:
        row.update(content_type="", category="")
    write_labels(labels, rows)
    loaded = stage2.read_stage1_labels(labels, key, config)
    assert len(loaded.items) == 6
    config = config.model_copy(
        update={
            "stage1": config.stage1.model_copy(
                update={"max_labeled": 4, "target_product": 3}
            )
        }
    )
    stop = stage2.stop_point(loaded, config)
    assert (stop.position, stop.product_count, stop.unused_count) == (4, 2, 2)


def test_stage2_human_strata_round_robin(workspace):
    _, labels, key, rows, config = workspace
    for i, row in enumerate(rows):
        row["content_type"] = "product_creative"
        row["category"] = "sun_care" if i < 4 else "mask_pack"
    write_labels(labels, rows)
    loaded = stage2.read_stage1_labels(labels, key, config)
    config = config.model_copy(
        update={"stage2": config.stage2.model_copy(update={"size": 4})}
    )
    selected = stage2.select_stage2(loaded.items, config, 1)
    assert len(selected.items) == 4
    assert len({(item.source, item.category) for item in selected.items}) == 4
    assert selected == stage2.select_stage2(list(reversed(loaded.items)), config, 1)
    assert selected != stage2.select_stage2(loaded.items, config, 2)
    short = stage2.select_stage2(loaded.items[:1], config, 1)
    assert len(short.items) == 1 and short.shortfall["total"] == 3


def test_stage2_rounds_fill_available_strata_before_reusing(workspace):
    _, labels, key, rows, config = workspace
    for row in rows:
        row.update(content_type="product_creative", category="mask_pack")
    rows[0]["category"] = "other"
    write_labels(labels, rows)
    loaded = stage2.read_stage1_labels(labels, key, config)
    selected = stage2.select_stage2(loaded.items, config, 5)
    assert {(item.source, item.category) for item in selected.items} == {
        ("youtube", "other"),
        ("youtube", "mask_pack"),
        ("instagram", "mask_pack"),
    }


@pytest.mark.parametrize(
    "name", ["sheet.csv", "codebook.csv", "instructions.md", "key.json"]
)
def test_one_existing_stage2_artifact_blocks_all_writes(workspace, name):
    folder, _, _, _, _ = workspace
    path = folder / f"e1_stage2_{name}"
    path.write_text("existing labeling artifact")
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    code, text = call_main(folder)
    assert code == 2 and "E1_OUTPUT_EXISTS" in text
    assert before == {p.name: p.read_bytes() for p in folder.iterdir()}


def test_outputs_blind_and_hashes_no_database(workspace, monkeypatch):
    folder, _, key, _, _ = workspace
    from beautyads import store

    connect = Mock(side_effect=AssertionError("database forbidden"))
    monkeypatch.setattr(store, "connect", connect)
    code, text = call_main(folder)
    assert code == 0 and '"unused_count": 3' in text
    connect.assert_not_called()
    with (folder / "e1_stage2_sheet.csv").open() as stream:
        reader = csv.DictReader(stream)
        assert set(reader.fieldnames) == {
            "item_id",
            "link",
            "text",
            *(
                col
                for col in label_columns()
                if col not in ("content_type", "category")
            ),
        }
        sheet = list(reader)
    assert [row["item_id"] for row in sheet] == ["F001", "F002", "F003"]
    assert all(
        not row[col]
        for row in sheet
        for col in label_columns()
        if col not in ("content_type", "category")
    )
    assert "BRAND_SENTINEL" not in json.dumps(sheet)
    document = json.loads((folder / "e1_stage2_key.json").read_text())
    assert document["stage1_key_sha256"] == hashlib.sha256(key.read_bytes()).hexdigest()
    assert document["stop_position"] == 5 and document["unused_count"] == 3
    assert (
        len(document["preregistration_sha256"]) == len(document["config_sha256"]) == 64
    )
    assert {item["source_id"] for item in document["items"].values()} == {"1", "3", "5"}
    assert all(
        item["stage1_human_labels"]["content_type"] == "product_creative"
        for item in document["items"].values()
    )
    instructions = (folder / "e1_stage2_instructions.md").read_text()
    assert "7일" in instructions and "쉼표" in instructions
    assert document["config_sha256"] in instructions
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    code, text = call_main(folder)
    assert code == 2 and "E1_OUTPUT_EXISTS" in text
    assert before == {p.name: p.read_bytes() for p in folder.iterdir()}


def test_product_shortfall_is_success(workspace):
    folder, labels, _, rows, _ = workspace
    write_labels(labels, rows[:2])
    code, text = call_main(folder)
    assert code == 0 and "E1_PRODUCT_SHORTFALL 2" in text
    document = json.loads((folder / "e1_stage2_key.json").read_text())
    assert len(document["items"]) == 1
    assert document["shortfall"]["total"] == 2


def test_no_products_still_writes_header(workspace):
    folder, labels, _, rows, _ = workspace
    for row in rows:
        row.update(content_type="other", category="other")
    write_labels(labels, rows)
    code, text = call_main(folder)
    assert code == 0 and "E1_PRODUCT_SHORTFALL 3" in text
    assert json.loads((folder / "e1_stage2_key.json").read_text())["items"] == {}


@pytest.mark.parametrize(
    "problem,expected",
    [
        ("prereg", "PREREGISTRATION_MISSING"),
        ("config", "E1_CONFIG_INVALID"),
        ("provenance", "LABEL_FILE_INVALID"),
    ],
)
def test_stage2_preflight(workspace, problem, expected):
    folder, _, key, _, _ = workspace
    if problem == "prereg":
        Path("docs/results/e1_preregistration.md").unlink()
    elif problem == "config":
        Path("config/e1_sampling.yaml").unlink()
    else:
        document = json.loads(key.read_text())
        document["config_sha256"] = "changed"
        key.write_text(json.dumps(document))
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    code, text = call_main(folder)
    assert code == 2 and expected in text
    assert before == {p.name: p.read_bytes() for p in folder.iterdir()}
