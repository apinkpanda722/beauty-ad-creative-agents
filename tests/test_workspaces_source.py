"""Workspace data and synthetic loader failures, without service access."""

from pathlib import Path

import pytest
import yaml

from beautyads.domain.tenant import WorkspaceProfile, price_band
from beautyads.sources.workspaces import Workspace, load_workspaces


def workspace(**changes):
    return {
        "tenant_id": "synthetic-a",
        "display_name": "합성 작업 공간",
        "brand": "synthetic-brand",
        "own_product_url": "https://example.invalid/product",
        "tone": "간결한 말투",
        "group": "dev",
        **changes,
    }


def test_config_workspace_invariants():
    items = load_workspaces(
        Path(__file__).resolve().parents[1] / "config/workspaces.yaml"
    )
    assert items
    ids = [item.tenant_id for item in items]
    assert len(ids) == len(set(ids))
    assert {item.group for item in items} == {"dev", "test"}
    for item in items:
        assert isinstance(item, Workspace)
        assert WorkspaceProfile.model_validate(item.model_dump(exclude={"group"}))


def test_defaults_and_existing_price_band_contract(tmp_path):
    path = tmp_path / "workspaces.yaml"
    path.write_text(yaml.safe_dump([workspace()]), encoding="utf-8")
    item = load_workspaces(path)[0]
    assert item.forbidden_terms == []
    assert item.price_band_pct == 30
    assert price_band(1000, item.price_band_pct).model_dump() == {
        "price_min": 700,
        "price_max": 1300,
    }


@pytest.mark.parametrize(
    "document",
    [
        [workspace(), workspace()],
        [workspace(group="private-invalid-group")],
        [workspace(**{"private-unknown-key": "private-value"})],
        [workspace(tenant_id="PRIVATE INVALID TENANT")],
        [workspace(price_band_pct=0)],
        [workspace(tone={"private-key": "private-value"})],
        ["private-value"],
        {"private-key": "private-value"},
        None,
    ],
)
def test_invalid_workspace_reports_only_position(tmp_path, document, caplog):
    path = tmp_path / "workspaces.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    with pytest.raises(
        ValueError, match=r"^WORKSPACES_INVALID(?: at \[\d+\])?$"
    ) as caught:
        load_workspaces(path)
    message = str(caught.value)
    assert "private" not in message.lower()
    assert "synthetic" not in message
    assert "private" not in caplog.text.lower()


@pytest.mark.parametrize("contents", ["[private-value: [", "\udcff"])
def test_unreadable_yaml_is_value_free(tmp_path, contents):
    path = tmp_path / "workspaces.yaml"
    path.write_bytes(contents.encode("utf-8", errors="surrogateescape"))
    with pytest.raises(ValueError, match="^WORKSPACES_INVALID$"):
        load_workspaces(path)


def test_missing_file_is_value_free(tmp_path):
    with pytest.raises(ValueError, match="^WORKSPACES_INVALID$"):
        load_workspaces(tmp_path / "private-name.yaml")
