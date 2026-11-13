"""E1 stage one uses only synthetic creatives and isolated temporary paths."""

import csv
import hashlib
import json
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml

from beautyads.domain import Creative, Source
from beautyads.eval import e1_sampling as e1
from beautyads.sources.split import BrandSplit, ResplitRule, VolumeConstraints

ROOT = Path(__file__).resolve().parents[1]


def config_data():
    return {
        "seed": 20261112,
        "stage1": {"min_labeled": 4, "max_labeled": 8, "target_product": 2},
        "stage2": {"size": 2},
        "sources": ["youtube", "instagram"],
        "dedupe": {
            "youtube": ["source", "account", "title", "caption"],
            "instagram": ["source", "account", "caption"],
        },
    }


@pytest.fixture
def config():
    return e1.E1Config.model_validate(config_data())


@pytest.fixture
def split():
    return BrandSplit(
        registered_on="2026-11-12",
        seed=1,
        attempt=0,
        dev_size=1,
        brands=["dev", "test", "test2"],
        dev=["dev"],
        test=["test", "test2"],
        static_constraints=[],
        volume=VolumeConstraints(),
        resplit=ResplitRule(),
    )


def creative(number, **changes):
    return Creative.model_validate(
        {
            "source": "youtube",
            "source_id": str(number),
            "brand": "test",
            "account": "ACCOUNT_SENTINEL",
            "url": f"https://youtube.com/watch?v={number}",
            "title": f"title {number}",
            "caption": "caption",
            "analyzable": True,
            "collected_at": datetime(2026, 11, 12, tzinfo=UTC),
            "attributes": {"media_url": "MEDIA_SENTINEL"},
            **changes,
        }
    )


@pytest.fixture
def workspace(tmp_path, monkeypatch, split):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "docs/results").mkdir(parents=True)
    (tmp_path / "docs/results/e1_preregistration.md").write_text(
        "synthetic registration"
    )
    (tmp_path / "docs/TAXONOMY.md").write_text(
        (ROOT / "docs/TAXONOMY.md").read_text(), encoding="utf-8"
    )
    (tmp_path / "config/e1_sampling.yaml").write_text(yaml.safe_dump(config_data()))
    (tmp_path / "config/brand_split.yaml").write_text(
        yaml.safe_dump(split.model_dump())
    )
    return tmp_path


def invoke(items=(), **overrides):
    store = Mock(spec=["list_creatives"])
    store.list_creatives.return_value = list(items)
    factory = Mock(return_value=SimpleNamespace(store=store))
    out = StringIO()
    kwargs = {
        "environ": {"POSTGRES_PASSWORD": "synthetic-password"},
        "out": out,
        "docker_check": lambda: True,
        "tcp_check": lambda *args: True,
        "deps_factory": factory,
    }
    kwargs.update(overrides)
    code = e1.main([], **kwargs)
    return code, out.getvalue(), factory, store


def test_frame_filters(config, split):
    items = [
        creative(1),
        creative(2, source="instagram"),
        creative(3, brand="dev"),
        creative(4, source="tiktok"),
        creative(5, analyzable=None),
        creative(6, analyzable=False),
        creative(7, brand=None),
        creative(8, brand="unknown"),
    ]
    report = e1.build_frame(items, split, config)
    assert {item.source_id for item in report.items} == {"1", "2"}
    assert report.frame_size_before == report.frame_size_after == 2


def test_dedupe_exact_keys_and_counts(config, split):
    items = [
        creative(1, title="a"),
        creative(2, title="b"),
        creative(3, title="a"),
        creative(4, title="a", account="another"),
        creative(5, source="instagram"),
        creative(6, source="instagram"),
    ]
    report = e1.build_frame(items, split, config)
    assert report.frame_size_before == 6
    assert report.frame_size_after == 4
    assert report.dropped_duplicates == {"youtube": 1, "instagram": 1}
    assert any(item.source_id == "2" for item in report.items)
    assert any(item.source_id == "4" for item in report.items)
    assert {item.key for item in report.items} == {
        item.key for item in e1.build_frame(list(reversed(items)), split, config).items
    }
    assert report == e1.build_frame(items, split, config)


@pytest.mark.parametrize("field", ["caption", "title", "account"])
@pytest.mark.parametrize("value", [None, "", " \t\n"])
def test_missing_key_fields_do_not_group(config, split, field, value):
    items = [
        creative(i, title="same", **{field: value})
        if field != "title"
        else creative(i, title=value)
        for i in range(3)
    ]
    assert all(e1.dedupe_key(item, config) is None for item in items)
    assert e1.build_frame(items, split, config).frame_size_after == 3


def test_no_normalization(config, split):
    items = [
        creative(i, title="same", caption=value)
        for i, value in enumerate(["Caption", "caption", " caption", "caption "])
    ]
    assert e1.build_frame(items, split, config).frame_size_after == 4


@pytest.mark.parametrize("value", [None, "", " \t\n"])
def test_instagram_empty_captions_are_individual(config, split, value):
    items = [creative(i, source="instagram", caption=value) for i in range(3)]
    frame = e1.build_frame(items, split, config)
    assert frame.frame_size_before == frame.frame_size_after == 3
    assert frame.dropped_duplicates == {"youtube": 0, "instagram": 0}


def test_stage1_round_robin_and_seed(config):
    items = [
        creative(f"{source}-{brand}-{i}", source=source, brand=brand)
        for source in config.sources
        for brand in ("test", "test2")
        for i in range(12)
    ]
    ordered = e1.order_stage1(items, config, seed=1)
    assert len(ordered) == config.stage1.max_labeled
    assert ordered == e1.order_stage1(list(reversed(items)), config, seed=1)
    assert ordered != e1.order_stage1(items, config, seed=2)
    for start in (0, 4):
        assert (
            len({(item.source, item.brand) for item in ordered[start : start + 4]}) == 4
        )


def test_blind_sheet_and_provenance(config):
    sheet = e1.build_stage1_sheet(
        [
            creative(
                1,
                brand="BRAND_SENTINEL",
                metrics={"view_count": 987654321},
                published_at=datetime(2031, 3, 5, tzinfo=UTC),
            )
        ],
        seed=config.seed,
        provenance={"preregistration_sha256": "p", "config_sha256": "c"},
    )
    assert list(sheet.rows[0]) == [
        "item_id",
        "link",
        "text",
        "content_type",
        "category",
    ]
    assert sheet.rows[0]["item_id"] == "E001"
    assert sheet.rows[0]["link"] == creative(1).url
    assert not any(
        token in json.dumps(sheet.rows)
        for token in (
            "MEDIA_SENTINEL",
            "ACCOUNT_SENTINEL",
            "BRAND_SENTINEL",
            "987654321",
            "2031-03-05",
            "metrics",
            "published_at",
            '"brand"',
        )
    )
    assert sheet.key_rows[0]["preregistration_sha256"] == "p"
    assert sheet.key_rows[0]["config_sha256"] == "c"


def test_cli_outputs_and_no_overwrite(workspace, split):
    code, text, factory, store = invoke([creative(1), creative(2, source="instagram")])
    assert code == 0
    factory.assert_called_once_with()
    store.list_creatives.assert_called_once_with(
        brands=split.test,
        sources=(Source.youtube, Source.instagram),
        analyzable_only=True,
    )
    assert "shortfall" in text and "키 파일" in text
    summary = json.loads(text.splitlines()[0])
    assert summary["shortfall"] == {
        "total": 6,
        "by_stratum": [
            {"source": "instagram", "stratum": "test", "missing": 1},
            {"source": "instagram", "stratum": "test2", "missing": 2},
            {"source": "youtube", "stratum": "test", "missing": 1},
            {"source": "youtube", "stratum": "test2", "missing": 2},
        ],
    }
    out_dir = workspace / "data/interim/e1"
    snapshots = {p.name: p.read_bytes() for p in out_dir.iterdir()}
    key = json.loads(snapshots["e1_stage1_key.json"])
    for name, path in (
        ("preregistration_sha256", workspace / "docs/results/e1_preregistration.md"),
        ("config_sha256", workspace / "config/e1_sampling.yaml"),
        ("split_sha256", workspace / "config/brand_split.yaml"),
    ):
        assert key[name] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert key["frame_size_before"] == key["frame_size_after"] == 2
    assert key["seed"] == 20261112 and key["generated_at"]
    assert set(key["items"]["E001"]) == {
        "source",
        "source_id",
        "brand",
        "account",
        "url",
    }
    assert {
        row["axis"]
        for row in csv.DictReader(
            snapshots["e1_stage1_codebook.csv"].decode().splitlines()
        )
    } == {"content_type", "category"}
    code, text, factory, _ = invoke([creative(3)])
    assert code == 2 and "E1_OUTPUT_EXISTS" in text
    factory.assert_not_called()
    assert snapshots == {p.name: p.read_bytes() for p in out_dir.iterdir()}


@pytest.mark.parametrize(
    "name", ["sheet.csv", "codebook.csv", "instructions.md", "key.json"]
)
def test_even_one_existing_stage1_artifact_blocks_all_writes(workspace, name):
    folder = workspace / "data/interim/e1"
    folder.mkdir(parents=True)
    path = folder / f"e1_stage1_{name}"
    path.write_text("existing labeling artifact")
    code, text, factory, _ = invoke([creative(1)])
    assert code == 2 and "E1_OUTPUT_EXISTS" in text
    factory.assert_not_called()
    assert list(folder.iterdir()) == [path]
    assert path.read_text() == "existing labeling artifact"


def test_sheet_instructions_keep_brand_metadata_blind(workspace):
    assert invoke([creative(1)])[0] == 0
    folder = workspace / "data/interim/e1"
    key = json.loads((folder / "e1_stage1_key.json").read_text())
    instructions = (folder / "e1_stage1_instructions.md").read_text()
    assert key["preregistration_sha256"] in instructions
    assert key["config_sha256"] in instructions
    assert '"stratum"' not in instructions and '"brand"' not in instructions
    assert "건너뛰지 않는다" in instructions


@pytest.mark.parametrize(
    "problem,expected",
    [
        ("prereg", "PREREGISTRATION_MISSING"),
        ("config", "E1_CONFIG_INVALID"),
        ("split", "E1_SPLIT_FILE_INVALID"),
        ("env", "ENV_MISSING:POSTGRES_PASSWORD"),
        ("docker", "DOCKER_DOWN"),
        ("tcp", "POSTGRES_UNREACHABLE"),
    ],
)
def test_preflight_no_connection(workspace, problem, expected):
    overrides = {}
    if problem == "prereg":
        (workspace / "docs/results/e1_preregistration.md").unlink()
        (workspace / "config/e1_sampling.yaml").unlink()
    elif problem in ("config", "split"):
        (
            workspace
            / f"config/{'e1_sampling' if problem == 'config' else 'brand_split'}.yaml"
        ).write_text("{}")
    elif problem == "env":
        overrides["environ"] = {}
    elif problem == "docker":
        overrides["docker_check"] = lambda: False
    else:
        overrides["tcp_check"] = lambda *args: False
    code, text, factory, _ = invoke(**overrides)
    assert code == 2 and f"PREFLIGHT_FAILED {expected}" in text
    factory.assert_not_called()
    assert "synthetic-password" not in text and "postgresql://" not in text
    assert not (workspace / "data").exists()


@pytest.mark.parametrize(
    "mutation", ["missing", "extra", "bad_yaml", "bad_key", "range"]
)
def test_invalid_config(tmp_path, mutation):
    data = config_data()
    if mutation == "missing":
        del data["seed"]
    elif mutation == "extra":
        data["stage1"]["extra"] = 1
    elif mutation == "bad_key":
        data["dedupe"]["youtube"].remove("title")
    elif mutation == "range":
        data["stage1"]["min_labeled"] = 20
    path = tmp_path / "config.yaml"
    path.write_text("[" if mutation == "bad_yaml" else yaml.safe_dump(data))
    with pytest.raises(e1.E1Error, match="E1_CONFIG_INVALID"):
        e1.load_e1_config(path)


def test_empty_frame(workspace):
    code, text, _, _ = invoke([creative(1, brand="dev")])
    assert code == 2 and "E1_FRAME_EMPTY" in text
    assert not (workspace / "data").exists()


@pytest.mark.parametrize("port", ["bad", "0", "65536"])
def test_bad_port_does_not_probe_or_connect(workspace, port):
    tcp = Mock()
    code, text, factory, _ = invoke(
        environ={
            "POSTGRES_PASSWORD": "synthetic-password",
            "BEAUTYADS_POSTGRES_PORT": port,
        },
        tcp_check=tcp,
    )
    assert code == 2 and "POSTGRES_UNREACHABLE" in text
    tcp.assert_not_called()
    factory.assert_not_called()


def test_missing_local_files_precede_all_probes(workspace):
    docker, tcp = Mock(), Mock()
    for path, expected in (
        (workspace / "docs/results/e1_preregistration.md", "PREREGISTRATION_MISSING"),
        (workspace / "config/e1_sampling.yaml", "E1_CONFIG_INVALID"),
        (workspace / "config/brand_split.yaml", "E1_SPLIT_FILE_INVALID"),
    ):
        content = path.read_bytes()
        path.unlink()
        code, text, factory, _ = invoke(environ={}, docker_check=docker, tcp_check=tcp)
        assert code == 2 and expected in text
        factory.assert_not_called()
        docker.assert_not_called()
        tcp.assert_not_called()
        path.write_bytes(content)


def test_connection_error_is_sanitized(workspace):
    factory = Mock(side_effect=e1.StoreConnectError("POSTGRES_AUTH_FAILED"))
    code, text, _, _ = invoke(deps_factory=factory)
    assert code == 2 and "POSTGRES_AUTH_FAILED" in text
    assert "postgresql://" not in text and "synthetic-password" not in text


def test_output_restrictions(workspace):
    outside = workspace / "outside"
    outside.mkdir()
    symlink = workspace / "data/interim/link"
    symlink.parent.mkdir(parents=True)
    symlink.symlink_to(outside, target_is_directory=True)
    for path in (outside, symlink, workspace / "data/interim/../../escape"):
        factory = Mock()
        out = StringIO()
        assert (
            e1.main(
                ["--out-dir", str(path)],
                environ={},
                out=out,
                docker_check=Mock(),
                tcp_check=Mock(),
                deps_factory=factory,
            )
            == 2
        )
        assert "OUTPUT_NOT_IGNORED" in out.getvalue()
        factory.assert_not_called()
    assert not list(outside.iterdir())


def test_make_targets():
    text = (ROOT / "Makefile").read_text()
    assert {"e1-stage1", "e1-stage2"} <= set(text.splitlines()[0].split())
    assert "e1-" not in text.split("verify:\n", 1)[1].split("\n\n", 1)[0]
    for target, module in (("e1-stage1", "e1_sampling"), ("e1-stage2", "e1_stage2")):
        assert f"{target}:\n\tuv run python -m beautyads.eval.{module}" in text
