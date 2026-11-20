"""Check local deployment files without invoking Docker or reading .env."""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def compose():
    return yaml.safe_load(
        (ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8")
    )


@pytest.fixture
def makefile():
    return (ROOT / "Makefile").read_text(encoding="utf-8")


def recipe(makefile: str, target: str) -> list[str]:
    match = re.search(
        rf"^{re.escape(target)}:[^\n]*\n((?:\t[^\n]*\n)+)", makefile, re.MULTILINE
    )
    assert match is not None, f"Missing recipe: {target}"
    return [line.strip() for line in match.group(1).splitlines()]


def test_project_name_and_required_services(compose):
    assert compose["name"] == "beautyads"
    assert {"postgres", "neo4j"} <= compose["services"].keys()


def test_all_images_have_explicit_non_latest_tags(compose):
    for service in compose["services"].values():
        image = service["image"].rsplit("/", 1)[-1]
        name, separator, tag = image.partition(":")
        assert name and separator and tag and tag.lower() != "latest"


@pytest.mark.parametrize(
    ("service", "image"),
    [("postgres", "postgres:17.11"), ("neo4j", "neo4j:2026.10.1-community")],
)
def test_database_image_versions(compose, service, image):
    assert compose["services"][service]["image"] == image


def test_ports_are_loopback_only_and_avoid_other_stack(compose):
    for service in compose["services"].values():
        for mapping in service.get("ports", []):
            assert mapping.startswith("127.0.0.1:")
            assert int(mapping.split(":")[1]) not in {5432, 3000, 7474, 7687}
    assert compose["services"]["postgres"]["ports"] == ["127.0.0.1:5433:5432"]
    assert set(compose["services"]["neo4j"]["ports"]) == {
        "127.0.0.1:7475:7474",
        "127.0.0.1:7688:7687",
    }


@pytest.mark.parametrize(
    ("service", "key", "prefix", "variable"),
    [
        ("postgres", "POSTGRES_PASSWORD", "", "POSTGRES_PASSWORD"),
        ("neo4j", "NEO4J_AUTH", "neo4j/", "NEO4J_PASSWORD"),
    ],
)
def test_passwords_use_required_environment_references(
    compose, service, key, prefix, variable
):
    value = compose["services"][service]["environment"][key]
    assert re.fullmatch(re.escape(prefix) + r"\$\{" + variable + r":\?[^}]+\}", value)


def test_container_and_volume_names_are_project_scoped(compose):
    for service in compose["services"].values():
        assert service["container_name"].startswith("beautyads-")
        for mount in service.get("volumes", []):
            source = mount.split(":", 1)[0]
            assert source in compose["volumes"]
            assert source.startswith("beautyads_")
    for volume in compose["volumes"].values():
        assert volume["name"].startswith("beautyads_")


@pytest.mark.parametrize(
    ("service", "volume", "destination"),
    [
        ("postgres", "beautyads_pgdata", "/var/lib/postgresql/data"),
        ("neo4j", "beautyads_neo4j_data", "/data"),
    ],
)
def test_database_identity_and_persistent_volumes(
    compose, service, volume, destination
):
    config = compose["services"][service]
    assert config["container_name"] == f"beautyads-{service}"
    assert config["volumes"] == [f"{volume}:{destination}"]
    assert compose["volumes"][volume]["name"] == volume


def test_postgres_environment_and_healthcheck(compose):
    postgres = compose["services"]["postgres"]
    assert postgres["environment"]["POSTGRES_USER"] == "beautyads"
    assert postgres["environment"]["POSTGRES_DB"] == "beautyads"
    assert postgres["healthcheck"]["test"] == [
        "CMD",
        "pg_isready",
        "-U",
        "beautyads",
        "-d",
        "beautyads",
    ]
    assert "healthcheck" not in compose["services"]["neo4j"]


def test_database_targets_and_shared_compose_command(makefile):
    assert "COMPOSE := docker compose --env-file .env -f deploy/docker-compose.yml" in (
        makefile
    )
    assert recipe(makefile, "db-up") == ["$(COMPOSE) up -d postgres neo4j"]
    assert recipe(makefile, "db-down") == ["$(COMPOSE) down"]
    assert recipe(makefile, "db-migrate") == [
        "uv run python -m beautyads.pipeline.migrate"
    ]
    phony = set(re.findall(r"^\.PHONY:\s*([^\n]+)", makefile, re.MULTILINE)[0].split())
    assert {
        "verify",
        "db-up",
        "db-down",
        "db-migrate",
        "graph-reset",
        "live-compare",
    } <= phony


def test_graph_reset_requires_confirmation_before_removing_only_graph(makefile):
    lines = recipe(makefile, "graph-reset")
    assert 'if [ "$(CONFIRM)" != "yes" ]' in lines[0]
    assert "GRAPH_RESET_NOT_CONFIRMED: make graph-reset CONFIRM=yes" in lines[0]
    assert "exit 1" in lines[0]
    stop = lines.index("$(COMPOSE) stop neo4j")
    remove_container = lines.index("$(COMPOSE) rm -f neo4j")
    remove_volume = lines.index("docker volume rm beautyads_neo4j_data")
    assert 0 < stop < remove_container < remove_volume
    assert all("volume rm" not in line for line in lines[:remove_volume])
    assert "beautyads_pgdata" not in makefile


def test_verify_remains_offline(makefile):
    for line in recipe(makefile, "verify"):
        assert not any(prefix in line for prefix in ("db-", "graph-", "live-"))


OBS_IMAGES = {
    "langfuse-web": "langfuse/langfuse:3.225.11",
    "langfuse-worker": "langfuse/langfuse-worker:3.225.11",
    "langfuse-postgres": "postgres:17.11",
    "clickhouse": "clickhouse/clickhouse-server:25.12.9.61",
    "redis": "redis:7.4.11",
    "minio": "cgr.dev/chainguard/minio@sha256:4cf4831a2bbcf13ddca09c1cbcc9faff716dd3c4247e0babc32864b8ee8e0034",
}


def test_obs_is_optional_and_images_are_pinned(compose):
    for name, image in OBS_IMAGES.items():
        assert compose["services"][name]["profiles"] == ["obs"]
        assert compose["services"][name]["image"] == image
    for name in ("postgres", "neo4j"):
        assert "profiles" not in compose["services"][name]
    assert compose["services"]["langfuse-web"]["ports"] == ["127.0.0.1:3001:3000"]


def test_obs_secrets_are_optional_references_and_postgres_is_separate(compose):
    references = set()
    for name in OBS_IMAGES:
        service = compose["services"][name]
        encoded = str(service)
        assert ":?" not in encoded
        for value in service.get("environment", {}).values():
            for variable in re.findall(r"\$\{([^}:]+):([^}]*)\}", str(value)):
                assert variable[1] == "-"
                references.add(variable[0])
    assert {
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "LANGFUSE_INIT_USER_EMAIL",
        "LANGFUSE_INIT_USER_PASSWORD",
        "LANGFUSE_NEXTAUTH_SECRET",
        "LANGFUSE_SALT",
        "LANGFUSE_ENCRYPTION_KEY",
        "LANGFUSE_PG_PASSWORD",
        "LANGFUSE_CLICKHOUSE_PASSWORD",
        "LANGFUSE_REDIS_AUTH",
        "LANGFUSE_MINIO_PASSWORD",
    } <= references
    pg = compose["services"]["langfuse-postgres"]
    assert pg["environment"]["POSTGRES_DB"] == "langfuse"
    assert pg["volumes"] == ["beautyads_langfuse_pgdata:/var/lib/postgresql/data"]
    assert "beautyads_pgdata" not in str(pg)
    assert (
        compose["volumes"]["beautyads_langfuse_pgdata"]["name"]
        == "beautyads_langfuse_pgdata"
    )


def test_obs_make_targets_are_separate_and_preserve_volumes(makefile):
    assert ".PHONY: obs-up obs-down obs-check\n" in makefile
    assert recipe(makefile, "obs-up") == [
        "uv run python -m beautyads.obs.langfuse_check preflight",
        "$(COMPOSE) --profile obs up -d",
    ]
    assert recipe(makefile, "obs-check") == [
        "uv run python -m beautyads.obs.langfuse_check"
    ]
    down = recipe(makefile, "obs-down")
    assert down == ["$(COMPOSE) --profile obs stop", "$(COMPOSE) --profile obs rm -f"]
    assert all("volume rm" not in line and "down -v" not in line for line in down)
    assert all("obs-" not in line for line in recipe(makefile, "verify"))


def test_obs_minio_initializes_event_bucket_and_redis_preserves_queue(compose):
    minio = compose["services"]["minio"]
    assert minio["entrypoint"] == "sh"
    command = " ".join(minio["command"])
    assert "mkdir -p /data/langfuse" in command and "exec minio server" in command
    assert minio["volumes"] == ["beautyads_langfuse_minio_data:/data"]
    redis = compose["services"]["redis"]
    assert "--maxmemory-policy noeviction" in " ".join(redis["command"])
