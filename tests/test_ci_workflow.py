"""Check CI configuration locally without invoking GitHub or reading .env."""

import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
ACTION_PINS = {
    "actions/checkout": "3d3c42e5aac5ba805825da76410c181273ba90b1",
    "astral-sh/setup-uv": "68559e99cc807c1eb7e9238fd43a15bba460eec2",
    "pnpm/action-setup": "73e46992e05b19abd31f2f3c20e0e7370d762115",
    "actions/setup-node": "949feb2413d6458794dcd2491c4babbbce0c15c1",
}


@pytest.fixture
def workflow():
    return yaml.safe_load(
        (ROOT / ".github/workflows/verify.yml").read_text(encoding="utf-8")
    )


def mappings(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from mappings(child)
    elif isinstance(value, list):
        for child in value:
            yield from mappings(child)


def test_verify_job_and_triggers(workflow):
    assert workflow["name"] == "verify"
    assert set(workflow["on"]) == {"push", "pull_request"}
    assert all(value is None for value in workflow["on"].values())
    assert workflow["permissions"] == {"contents": "read"}
    assert set(workflow["jobs"]) == {"verify"}
    job = workflow["jobs"]["verify"]
    assert job["runs-on"] == "ubuntu-latest"
    assert "${{ github.ref }}" in job["concurrency"]["group"]
    assert job["concurrency"]["cancel-in-progress"] is True


def test_all_actions_use_approved_commit_pins(workflow):
    uses = [item["uses"] for item in mappings(workflow) if "uses" in item]
    assert uses
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", use) for use in uses)
    assert set(uses) == {f"{action}@{sha}" for action, sha in ACTION_PINS.items()}


def test_install_and_verify_steps_in_order(workflow):
    steps = workflow["jobs"]["verify"]["steps"]
    assert [step.get("run", step.get("uses")) for step in steps] == [
        f"actions/checkout@{ACTION_PINS['actions/checkout']}",
        f"astral-sh/setup-uv@{ACTION_PINS['astral-sh/setup-uv']}",
        "uv sync --locked",
        f"pnpm/action-setup@{ACTION_PINS['pnpm/action-setup']}",
        f"actions/setup-node@{ACTION_PINS['actions/setup-node']}",
        "make web-install",
        "make verify",
    ]


def test_no_keys_or_service_containers_anywhere(workflow):
    for item in mappings(workflow):
        assert not {"secrets", "env", "services"} & item.keys()
        assert "secrets." not in str(item)


def test_runtime_versions_and_caches(workflow):
    settings = {
        step["uses"].split("@")[0]: step.get("with", {})
        for step in workflow["jobs"]["verify"]["steps"]
        if "uses" in step
    }
    assert settings["astral-sh/setup-uv"]["enable-cache"] is True
    assert settings["actions/setup-node"] == {
        "node-version": "24",
        "cache": "pnpm",
        "cache-dependency-path": "web/pnpm-lock.yaml",
    }
    assert settings["pnpm/action-setup"]["package_json_file"] == "web/package.json"
    package = json.loads((ROOT / "web/package.json").read_text(encoding="utf-8"))
    assert package["packageManager"] == "pnpm@12.8.1"


def test_verify_job_has_timeout(workflow):
    assert workflow["jobs"]["verify"]["timeout-minutes"] == 20
