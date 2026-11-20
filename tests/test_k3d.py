"""Inspect deployment files only; never build images or contact a cluster."""

import json
import re
from pathlib import Path

import pytest
import yaml
from test_compose import recipe

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"


@pytest.fixture
def objects():
    paths = sorted((DEPLOY / "k3d").glob("*.yaml"))
    assert {path.name for path in paths} == {
        "namespace.yaml",
        "kustomization.yaml",
        "postgres.yaml",
        "neo4j.yaml",
        "api.yaml",
        "web.yaml",
    }
    return [obj for path in paths for obj in yaml.safe_load_all(path.read_text())]


def workload(objects, name):
    return next(
        obj
        for obj in objects
        if obj["kind"] in {"Deployment", "StatefulSet"}
        and obj["metadata"]["name"] == name
    )


def pod_spec(objects, name):
    return workload(objects, name)["spec"]["template"]["spec"]


def test_yaml_namespaces_and_kustomization_resources(objects):
    for obj in objects:
        assert isinstance(obj, dict)
        if obj["kind"] == "Namespace":
            assert obj["metadata"]["name"] == "beautyads"
        else:
            assert obj["metadata"]["namespace"] == "beautyads"
    kustomization = next(obj for obj in objects if obj["kind"] == "Kustomization")
    assert kustomization["namespace"] == "beautyads"
    assert set(kustomization["resources"]) == {
        "namespace.yaml",
        "postgres.yaml",
        "neo4j.yaml",
        "api.yaml",
        "web.yaml",
    }


def test_no_secret_objects_or_literal_credentials(objects):
    for obj in objects:
        assert obj["kind"] != "Secret"
        assert "stringData" not in obj and "data" not in obj
        rendered = json.dumps(obj)
        assert not re.search(
            r"(?:sk-[A-Za-z0-9_-]{12,}|AIza[A-Za-z0-9_-]{20,})", rendered
        )
        if obj["kind"] not in {"Deployment", "StatefulSet"}:
            continue
        spec = obj["spec"]["template"]["spec"]
        for container in spec.get("initContainers", []) + spec["containers"]:
            for env in container.get("env", []):
                if re.search(r"PASSWORD|SECRET|TOKEN|API_KEY", env["name"]):
                    assert "value" not in env
                    assert env["valueFrom"]["secretKeyRef"] == {
                        "name": "beautyads-env",
                        "key": env["name"],
                    }


def test_container_images_are_tagged_and_apps_never_pull(objects):
    for obj in objects:
        if obj["kind"] not in {"Deployment", "StatefulSet"}:
            continue
        spec = obj["spec"]["template"]["spec"]
        for container in spec.get("initContainers", []) + spec["containers"]:
            image = container["image"]
            name, separator, tag = image.rsplit("/", 1)[-1].partition(":")
            assert name and separator and tag and tag.lower() != "latest"
            if image.startswith("beautyads-"):
                assert tag == "local" and container["imagePullPolicy"] == "Never"


def test_api_configuration_storage_health_and_service(objects):
    spec = pod_spec(objects, "api")
    container = spec["containers"][0]
    assert container["image"] == "beautyads-api:local"
    assert container["envFrom"] == [{"secretRef": {"name": "beautyads-env"}}]
    env = {item["name"]: item["value"] for item in container["env"]}
    assert (
        env.items()
        >= {
            "BEAUTYADS_GROUP": "test",
            "BEAUTYADS_EVAL_MODEL": "claude-sonnet-5-5",
            "BEAUTYADS_WITH_IMAGE": "1",
            "BEAUTYADS_POSTGRES_HOST": "postgres",
            "BEAUTYADS_POSTGRES_PORT": "5432",
            "BEAUTYADS_NEO4J_URI": "bolt://neo4j:7687",
            "BEAUTYADS_API_HOST": "0.0.0.0",
        }.items()
    )
    mount = next(m for m in container["volumeMounts"] if m["mountPath"] == "/app/data")
    volume = next(v for v in spec["volumes"] if v["name"] == mount["name"])
    claim = volume["persistentVolumeClaim"]["claimName"]
    assert any(
        o["kind"] == "PersistentVolumeClaim" and o["metadata"]["name"] == claim
        for o in objects
    )
    assert container["readinessProbe"]["httpGet"] == {"path": "/healthz", "port": 8000}
    services = {o["metadata"]["name"]: o for o in objects if o["kind"] == "Service"}
    assert services["api"]["spec"]["ports"][0]["port"] == 8000
    assert services["web"]["spec"]["type"] == "NodePort"
    assert services["web"]["spec"]["ports"][0]["nodePort"] == 30000
    for name in ("api", "web", "postgres", "neo4j"):
        assert (
            services[name]["spec"]["selector"].items()
            <= workload(objects, name)["spec"]["template"]["metadata"]["labels"].items()
        )


@pytest.mark.parametrize("name", ["postgres", "neo4j"])
def test_databases_match_compose_and_use_persistent_storage(objects, name):
    compose = yaml.safe_load((DEPLOY / "docker-compose.yml").read_text())
    obj = workload(objects, name)
    assert obj["kind"] == "StatefulSet"
    spec = pod_spec(objects, name)
    container = spec["containers"][0]
    assert container["image"] == compose["services"][name]["image"]
    claims = {c["metadata"]["name"] for c in obj["spec"]["volumeClaimTemplates"]}
    assert any(m["name"] in claims for m in container["volumeMounts"])
    if name == "postgres":
        env = {e["name"]: e for e in container["env"]}
        assert (
            env["POSTGRES_USER"]["value"] == env["POSTGRES_DB"]["value"] == "beautyads"
        )
        assert (
            env["POSTGRES_PASSWORD"]["valueFrom"]["secretKeyRef"]["key"]
            == "POSTGRES_PASSWORD"
        )
    else:
        command = " ".join(container["command"] + container.get("args", []))
        assert 'NEO4J_AUTH="neo4j/${NEO4J_PASSWORD}"' in command
        assert "exec /startup/docker-entrypoint.sh neo4j" in command


def test_dockerfiles_pin_bases_and_exclude_local_secrets_and_data():
    for name in ("api", "web"):
        text = (DEPLOY / f"Dockerfile.{name}").read_text()
        bases = re.findall(r"^FROM\s+(\S+)", text, re.MULTILINE)
        assert bases
        for base in bases:
            _, separator, tag = base.rsplit("/", 1)[-1].partition(":")
            assert separator and tag and tag.lower() != "latest"
        for line in text.splitlines():
            if line.startswith("COPY "):
                assert not re.search(r"(?:^|[\s/])(?:\.env\S*|data/)(?:\s|$)", line)
                assert not re.search(r"COPY\s+\.\s", line)
    ignored = (ROOT / ".dockerignore").read_text().splitlines()
    assert {
        ".env*",
        "data/",
        "web/node_modules",
        ".git",
        "phases/",
        "!.env.example",
    } <= set(ignored)
    api = (DEPLOY / "Dockerfile.api").read_text()
    assert "uv sync --locked --no-dev" in api
    assert "/app/.venv/bin" in api and "COPY config/" in api
    assert '"beautyads.api.main"' in api


def test_make_targets_confirmation_offline_verify_and_context():
    text = (ROOT / "Makefile").read_text()
    for target in ("k3d-up", "k3d-seed", "k3d-down"):
        assert f".PHONY: {target}\n{target}:" in text
    assert all("k3d-" not in line for line in recipe(text, "verify"))
    for target, code in (
        ("k3d-seed", "K3D_SEED_NOT_CONFIRMED"),
        ("k3d-down", "K3D_DOWN_NOT_CONFIRMED"),
    ):
        first = recipe(text, target)[0]
        assert 'if [ "$(CONFIRM)" != "yes" ]' in first
        assert f"{code}: make {target} CONFIRM=yes" in first and "exit 1" in first
    down = "\n".join(recipe(text, "k3d-down"))
    assert "k3d cluster delete beautyads" in down
    assert not any(s in down for s in ("volume rm", "down -v", "$(COMPOSE)"))
    assert "--context k3d-beautyads" in text
    up = "\n".join(recipe(text, "k3d-up"))
    assert (
        up.index("docker build")
        < up.index("k3d cluster")
        < up.index("k3d image import")
    )
    assert "3100:30000@server:0" in up
    assert "--from-env-file=.env --dry-run=client -o yaml" in up
    assert "apply -k deploy/k3d" in up and "rollout status" in up
    seed = "\n".join(recipe(text, "k3d-seed"))
    assert "pipefail" in seed and "pg_dump" in seed and "psql" in seed
    assert "beautyads-postgres" in seed and "postgres-0" in seed
    assert "ON_ERROR_STOP=1" in seed and "--layers" in seed and "--full" in seed
    assert "costs.jsonl" in seed and " cp " in seed
    assert "volume rm" not in seed and "down -v" not in seed


def test_web_standalone_preserves_rewrite_and_agent_rules():
    config = (ROOT / "web/next.config.ts").read_text()
    assert 'output: "standalone"' in config and "agentRules: false" in config
    assert "rewrites()" in config and "BEAUTYADS_API_ORIGIN" in config
    dockerfile = (DEPLOY / "Dockerfile.web").read_text()
    assert "ARG BEAUTYADS_API_ORIGIN=http://api:8000" in dockerfile
    assert "ENV BEAUTYADS_API_ORIGIN=" in dockerfile
    assert dockerfile.index("ENV BEAUTYADS_API_ORIGIN=") < dockerfile.index(
        "pnpm build"
    )
    assert "pnpm@12.8.1" in dockerfile and ".next/standalone" in dockerfile
    assert ".next/static" in dockerfile and '"server.js"' in dockerfile
