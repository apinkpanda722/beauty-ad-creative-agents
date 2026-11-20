"""Offline server entry configuration and lifespan integration."""

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_api_ask import services

from beautyads.api import main as entry
from beautyads.settings import InvalidSetting, get_setting, load_settings


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_defaults_and_deferred_assembly(blank):
    environ = (
        {}
        if blank is None
        else dict.fromkeys(
            (
                "BEAUTYADS_GROUP",
                "BEAUTYADS_EVAL_MODEL",
                "BEAUTYADS_WITH_IMAGE",
                "BEAUTYADS_API_PORT",
            ),
            blank,
        )
    )
    calls = []

    def fake(
        *, settings, group, evaluation_model, with_image_enabled, environ, env_file
    ):
        calls.append(
            (settings, group, evaluation_model, with_image_enabled, environ, env_file)
        )
        return services()

    app = entry.build_app(environ=environ, env_file=None, assemble=fake)
    assert calls == []
    assert entry.server_port(environ=environ, env_file=None) == 8000
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        assert len(calls) == 1
        settings, group, model, image, received_environ, env_file = calls[0]
        assert settings == load_settings(environ=environ, env_file=None)
        assert (group, model, image) == ("dev", "claude-haiku-5-5", False)
        assert received_environ is environ and env_file is None
    assert len(calls) == 1


@pytest.mark.parametrize("async_assembly", [False, True])
def test_configured_entry_reaches_ask_and_closes(async_assembly):
    environ = {
        "BEAUTYADS_GROUP": "test",
        "BEAUTYADS_EVAL_MODEL": "claude-sonnet-5-5",
        "BEAUTYADS_WITH_IMAGE": "1",
    }
    built, asked, closed = [], [], []

    def ask(message, ctx, profile, feedback, with_image, on_event):
        asked.append((message, ctx, with_image))
        return {"kind": "no_evidence"}

    initial = services(ask)
    initial.image_enabled = True
    initial.close = lambda: closed.append(True)

    def fake(
        *, settings, group, evaluation_model, with_image_enabled, environ, env_file
    ):
        built.append(
            (settings, group, evaluation_model, with_image_enabled, environ, env_file)
        )
        return initial

    async def async_fake(**kwargs):
        return fake(**kwargs)

    app = entry.build_app(
        environ=environ, env_file=None, assemble=async_fake if async_assembly else fake
    )
    assert built == []
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        response = client.post(
            "/ask",
            headers={"X-Tenant-Id": "demo-a"},
            json={"message": "synthetic", "with_image": True},
        )
        assert response.status_code == 200
        assert len(built) == len(asked) == 1
        assert built[0][0] == load_settings(environ=environ, env_file=None)
        assert built[0][1:4] == ("test", "claude-sonnet-5-5", True)
        assert built[0][4] is environ and built[0][5] is None
        assert asked[0][1].tenant_id == "demo-a" and asked[0][2] is True
    assert closed == [True]


@pytest.mark.parametrize(
    "name,value",
    [
        ("BEAUTYADS_GROUP", "isolation"),
        ("BEAUTYADS_GROUP", "unknown-group"),
        ("BEAUTYADS_EVAL_MODEL", "unknown-model"),
        ("BEAUTYADS_WITH_IMAGE", "2"),
        ("BEAUTYADS_WITH_IMAGE", "yes"),
        ("BEAUTYADS_API_PORT", "80"),
        ("BEAUTYADS_API_PORT", "abc"),
        ("BEAUTYADS_API_PORT", "70000"),
        ("BEAUTYADS_API_PORT", "1023"),
        ("BEAUTYADS_API_PORT", "65536"),
        ("BEAUTYADS_API_PORT", "8000.0"),
    ],
)
def test_invalid_settings_expose_only_name(name, value):
    target = entry.server_port if name == "BEAUTYADS_API_PORT" else entry.build_app
    with pytest.raises(InvalidSetting) as caught:
        target(environ={name: value}, env_file=None)
    assert caught.value.name == name
    assert str(caught.value) == name and value not in str(caught.value)


@pytest.mark.parametrize("port", [1024, 8000, 65535])
def test_valid_ports(port):
    assert (
        entry.server_port(environ={"BEAUTYADS_API_PORT": str(port)}, env_file=None)
        == port
    )


def configure_main(monkeypatch, environ):
    # Force every settings read through a synthetic mapping, without reading .env.
    monkeypatch.setattr(
        entry,
        "get_setting",
        lambda name, default=None, **kwargs: get_setting(
            name, default, environ=environ, env_file=None
        ),
    )
    monkeypatch.setattr(
        entry,
        "load_settings",
        lambda **kwargs: load_settings(environ=environ, env_file=None),
    )


@pytest.mark.parametrize(
    "options,expected",
    [
        (
            {},
            "group=dev eval_model=claude-haiku-5-5 image=off url=http://127.0.0.1:8000",
        ),
        (
            {
                "BEAUTYADS_GROUP": "test",
                "BEAUTYADS_EVAL_MODEL": "claude-sonnet-5-5",
                "BEAUTYADS_WITH_IMAGE": "1",
                "BEAUTYADS_API_PORT": "8765",
            },
            "group=test eval_model=claude-sonnet-5-5 image=on url=http://127.0.0.1:8765",
        ),
    ],
)
def test_main_loopback_and_safe_start_line(monkeypatch, capsys, options, expected):
    secret = uuid4().hex
    configure_main(monkeypatch, {**options, "OPENAI_API_KEY": secret})
    runs = []
    monkeypatch.setattr(
        entry.uvicorn, "run", lambda app, **kwargs: runs.append((app, kwargs))
    )
    entry.main()
    output = capsys.readouterr().out
    assert output == f"SERVE {expected}\n" and secret not in output
    assert len(runs) == 1 and isinstance(runs[0][0], FastAPI)
    assert runs[0][1] == {
        "host": "127.0.0.1",
        "port": int(options.get("BEAUTYADS_API_PORT", "8000")),
    }


@pytest.mark.parametrize(
    "name,value",
    [
        ("BEAUTYADS_GROUP", "isolation"),
        ("BEAUTYADS_EVAL_MODEL", "unknown-model"),
        ("BEAUTYADS_WITH_IMAGE", "yes"),
        ("BEAUTYADS_API_PORT", "80"),
        ("BEAUTYADS_ANALYSIS_WINDOW_MAX_S", "invalid-number"),
    ],
)
def test_main_setting_error_exits_without_starting(monkeypatch, capsys, name, value):
    configure_main(monkeypatch, {name: value})
    monkeypatch.setattr(
        entry.uvicorn, "run", lambda *a, **kw: pytest.fail("must not start")
    )
    with pytest.raises(SystemExit) as caught:
        entry.main()
    assert caught.value.code == 2
    assert capsys.readouterr().out == f"SERVE_FAILED INVALID_SETTING:{name}\n"


def test_main_leaves_startup_failure_to_uvicorn(monkeypatch):
    configure_main(monkeypatch, {})
    error = RuntimeError("ASSEMBLY_FAILED")

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(entry.uvicorn, "run", fail)
    with pytest.raises(RuntimeError) as caught:
        entry.main()
    assert caught.value is error


def test_make_serve_and_environment_names():
    text = Path("Makefile").read_text()
    assert ".PHONY: serve\nserve:\n\tuv run python -m beautyads.api.main" in text
    verify = text.split("verify:\n", 1)[1].split("\n\n", 1)[0]
    assert "serve" not in verify
    example = Path(".env.example").read_text()
    for name in (
        "BEAUTYADS_GROUP",
        "BEAUTYADS_EVAL_MODEL",
        "BEAUTYADS_WITH_IMAGE",
        "BEAUTYADS_API_PORT",
    ):
        assert f"# {name}=" in example.splitlines()


@pytest.mark.parametrize("host", [None, "", " \t ", "127.0.0.1", "0.0.0.0"])
def test_server_host_defaults_and_explicit_interfaces(host):
    environ = {} if host is None else {"BEAUTYADS_API_HOST": host}
    assert entry.server_host(environ=environ, env_file=None) == (
        "0.0.0.0" if host == "0.0.0.0" else "127.0.0.1"
    )


@pytest.mark.parametrize("host", ["localhost", "::", "arbitrary-private-input"])
def test_server_host_rejects_other_values_without_exposing_them(host):
    with pytest.raises(InvalidSetting) as caught:
        entry.server_host(environ={"BEAUTYADS_API_HOST": host}, env_file=None)
    assert caught.value.name == "BEAUTYADS_API_HOST"
    assert str(caught.value) == "BEAUTYADS_API_HOST"
    assert host not in str(caught.value)


@pytest.mark.parametrize("host", ["127.0.0.1", "0.0.0.0"])
def test_main_passes_configured_host_and_prints_matching_url(monkeypatch, capsys, host):
    configure_main(monkeypatch, {"BEAUTYADS_API_HOST": host})
    runs = []
    monkeypatch.setattr(entry.uvicorn, "run", lambda app, **kw: runs.append(kw))
    entry.main()
    assert runs == [{"host": host, "port": 8000}]
    assert capsys.readouterr().out == (
        "SERVE group=dev eval_model=claude-haiku-5-5 image=off "
        f"url=http://{host}:8000\n"
    )


def test_main_invalid_host_exits_without_starting(monkeypatch, capsys):
    configure_main(monkeypatch, {"BEAUTYADS_API_HOST": "localhost"})
    monkeypatch.setattr(
        entry.uvicorn, "run", lambda *a, **kw: pytest.fail("must not start")
    )
    with pytest.raises(SystemExit) as caught:
        entry.main()
    assert caught.value.code == 2
    assert (
        capsys.readouterr().out == "SERVE_FAILED INVALID_SETTING:BEAUTYADS_API_HOST\n"
    )
