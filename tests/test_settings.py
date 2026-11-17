from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from beautyads.settings import (
    DEFAULT_ENV_FILE,
    InvalidSetting,
    MissingSetting,
    SettingError,
    Settings,
    ThinkingLevel,
    get_setting,
    load_settings,
    neo4j_password,
    neo4j_uri,
    read_env_file,
    require_setting,
)


def test_read_env_file_parses_literal_values(tmp_path):
    path = tmp_path / ".env"
    contents = (
        "# comment\n\n  # indented comment\n"
        " NAME = plain \nSINGLE='quoted value'\nDOUBLE=\"two=parts\"\n"
        "EQUALS=a=b=c\nEMPTY=\nSPACES='   '\n"
        "LITERAL=${NAME}\nHASH=value#suffix\nUNPAIRED='value\n"
    )
    path.write_text(contents, encoding="utf-8")
    assert read_env_file(path) == {
        "NAME": "plain",
        "SINGLE": "quoted value",
        "DOUBLE": "two=parts",
        "EQUALS": "a=b=c",
        "EMPTY": "",
        "SPACES": "   ",
        "LITERAL": "${NAME}",
        "HASH": "value#suffix",
        "UNPAIRED": "'value",
    }
    assert path.read_text(encoding="utf-8") == contents


@pytest.mark.parametrize("environment", ["process", "", " \t ", None])
@pytest.mark.parametrize("file_value", ["file", "", " \t ", None])
def test_setting_precedence_and_blank_fallback(tmp_path, environment, file_value):
    path = tmp_path / ".env"
    path.write_text(
        "" if file_value is None else f"OPTION={file_value}\n", encoding="utf-8"
    )
    environ = {} if environment is None else {"OPTION": environment}
    expected = "process" if environment == "process" else "file"
    if environment != "process" and file_value != "file":
        expected = "fallback"
    assert get_setting("OPTION", "fallback", environ=environ, env_file=path) == expected


def test_unset_value_and_disabled_file():
    assert get_setting("OPTION", environ={}, env_file=None) is None
    assert require_setting("OPTION", environ={"OPTION": "present"}, env_file=None)


def test_disabled_file_does_not_read_default_file(monkeypatch):
    def unexpected_read(path):
        pytest.fail("env_file=None must not read a file")

    monkeypatch.setattr("beautyads.settings.read_env_file", unexpected_read)
    assert get_setting("OPTION", "fallback", environ={}, env_file=None) == "fallback"


@pytest.mark.parametrize("value", [None, "", " \t "])
def test_missing_setting_has_name_only(value):
    environ = {} if value is None else {"OPTION": value}
    with pytest.raises(MissingSetting) as caught:
        require_setting("OPTION", environ=environ, env_file=None)
    assert isinstance(caught.value, SettingError)
    assert caught.value.name == "OPTION"
    assert caught.value.code == "MISSING_SETTING"
    assert str(caught.value) == "OPTION"


@pytest.mark.parametrize("value", ["x", "x" * 7])
def test_short_password_is_rejected_without_value(value):
    with pytest.raises(InvalidSetting) as caught:
        neo4j_password(environ={"NEO4J_PASSWORD": value}, env_file=None)
    assert isinstance(caught.value, SettingError)
    assert caught.value.name == "NEO4J_PASSWORD"
    assert caught.value.code == "INVALID_SETTING"
    assert str(caught.value) == "NEO4J_PASSWORD"
    assert value not in str(caught.value)


def test_password_boundary_and_missing_value():
    value = "x" * 8
    assert neo4j_password(environ={"NEO4J_PASSWORD": value}, env_file=None) == value
    with pytest.raises(MissingSetting):
        neo4j_password(environ={}, env_file=None)


@pytest.mark.parametrize("blank", [None, "", " \t "])
def test_neo4j_uri_defaults_and_blank_fallback(blank):
    env = {} if blank is None else {"BEAUTYADS_NEO4J_URI": blank}
    assert neo4j_uri(environ=env, env_file=None) == "bolt://127.0.0.1:7688"


def test_neo4j_uri_file_and_environment(tmp_path):
    path = tmp_path / ".env"
    path.write_text("BEAUTYADS_NEO4J_URI=bolt://127.0.0.1:9999\n")
    assert neo4j_uri(environ={}, env_file=path) == "bolt://127.0.0.1:9999"
    assert (
        neo4j_uri(
            environ={"BEAUTYADS_NEO4J_URI": "bolt://localhost:8888"}, env_file=path
        )
        == "bolt://localhost:8888"
    )


def test_settings_defaults_and_missing_file(tmp_path):
    missing = tmp_path / ".env"
    assert DEFAULT_ENV_FILE == Path(".env")
    assert read_env_file(missing) == {}
    for env_file in (None, missing):
        settings = load_settings(environ={}, env_file=env_file)
        assert settings.ledger_path == Path("data/manifest/costs.jsonl")
        assert settings.analysis_window_max_s == 60
        assert settings.video_length_cut_s == 600
        assert settings.thinking_level == "minimal"
    assert not missing.exists()


def test_load_settings_from_file_and_environment(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "BEAUTYADS_LEDGER_PATH=custom/costs.jsonl\n"
        "BEAUTYADS_ANALYSIS_WINDOW_MAX_S=30\n"
        "BEAUTYADS_VIDEO_LENGTH_CUT_S=300\n"
        "BEAUTYADS_THINKING_LEVEL=low\n",
        encoding="utf-8",
    )
    settings = load_settings(
        environ={"BEAUTYADS_ANALYSIS_WINDOW_MAX_S": "45"}, env_file=path
    )
    assert settings.ledger_path == Path("custom/costs.jsonl")
    assert settings.analysis_window_max_s == 45
    assert settings.video_length_cut_s == 300
    assert settings.thinking_level == "low"
    assert sorted(p.name for p in tmp_path.iterdir()) == [".env"]


@pytest.mark.parametrize("blank", ["", " \t "])
def test_blank_settings_preserve_defaults(tmp_path, blank):
    names = (
        "BEAUTYADS_LEDGER_PATH",
        "BEAUTYADS_ANALYSIS_WINDOW_MAX_S",
        "BEAUTYADS_VIDEO_LENGTH_CUT_S",
        "BEAUTYADS_THINKING_LEVEL",
    )
    path = tmp_path / ".env"
    path.write_text("\n".join(f"{name}='{blank}'" for name in names), encoding="utf-8")
    assert (
        load_settings(environ=dict.fromkeys(names, blank), env_file=path) == Settings()
    )


@pytest.mark.parametrize(
    "name",
    ["BEAUTYADS_ANALYSIS_WINDOW_MAX_S", "BEAUTYADS_VIDEO_LENGTH_CUT_S"],
)
@pytest.mark.parametrize("value", ["not-an-integer", "1.5", "0", "-1"])
def test_invalid_integer_setting_has_name_only(name, value):
    with pytest.raises(InvalidSetting) as caught:
        load_settings(environ={name: value}, env_file=None)
    assert caught.value.name == name
    assert str(caught.value) == name
    assert value not in str(caught.value)


@pytest.mark.parametrize("level", get_args(ThinkingLevel))
def test_all_thinking_levels_are_accepted(level):
    settings = load_settings(environ={"BEAUTYADS_THINKING_LEVEL": level}, env_file=None)
    assert settings.thinking_level == level


def test_default_thinking_level_is_an_allowed_comparison():
    assert "default" in get_args(ThinkingLevel)


def test_invalid_thinking_level_has_name_only(tmp_path):
    name = "BEAUTYADS_THINKING_LEVEL"
    path = tmp_path / ".env"
    path.write_text(f"{name}=maximum\n", encoding="utf-8")
    with pytest.raises(InvalidSetting) as caught:
        load_settings(environ={}, env_file=path)
    assert caught.value.name == name
    assert str(caught.value) == name
    assert "maximum" not in str(caught.value)


def test_settings_forbid_unknown_fields():
    with pytest.raises(ValidationError):
        Settings(unknown=True)


def test_provider_caps_defaults_are_independent():
    settings = load_settings(environ={}, env_file=None)
    assert settings.provider_caps_usd == {
        "gemini": 12.0,
        "openai": 10.0,
        "anthropic": 8.0,
    }
    settings.provider_caps_usd["gemini"] = 0.0
    assert Settings().provider_caps_usd["gemini"] == 12.0


def test_provider_caps_load_from_file_and_environment(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "BEAUTYADS_CAP_GEMINI_USD=4.5\n"
        "BEAUTYADS_CAP_OPENAI_USD=5.5\n"
        "BEAUTYADS_CAP_ANTHROPIC_USD=6.5\n",
        encoding="utf-8",
    )
    settings = load_settings(environ={"BEAUTYADS_CAP_OPENAI_USD": "0"}, env_file=path)
    assert settings.provider_caps_usd == {
        "gemini": 4.5,
        "openai": 0.0,
        "anthropic": 6.5,
    }


@pytest.mark.parametrize("blank", ["", " \t "])
def test_blank_provider_caps_preserve_defaults(tmp_path, blank):
    names = [
        f"BEAUTYADS_CAP_{provider}_USD"
        for provider in ("GEMINI", "OPENAI", "ANTHROPIC")
    ]
    path = tmp_path / ".env"
    path.write_text("\n".join(f"{name}='{blank}'" for name in names), encoding="utf-8")
    assert (
        load_settings(environ=dict.fromkeys(names, blank), env_file=path) == Settings()
    )


@pytest.mark.parametrize("provider", ["GEMINI", "OPENAI", "ANTHROPIC"])
@pytest.mark.parametrize("value", ["not-a-number", "-0.1", "nan", "inf", "-inf"])
@pytest.mark.parametrize("source", ["environment", "file"])
def test_invalid_provider_cap_has_name_only(tmp_path, provider, value, source):
    name = f"BEAUTYADS_CAP_{provider}_USD"
    path = tmp_path / ".env"
    environ = {name: value} if source == "environment" else {}
    if source == "file":
        path.write_text(f"{name}={value}\n", encoding="utf-8")
    with pytest.raises(InvalidSetting) as caught:
        load_settings(environ=environ, env_file=path)
    assert caught.value.name == name
    assert caught.value.code == "INVALID_SETTING"
    assert str(caught.value) == name
    assert value not in str(caught.value)


def test_purpose_caps_defaults_and_overrides(tmp_path):
    name = "BEAUTYADS_CAP_IMAGE_USD"
    defaults = load_settings(environ={}, env_file=None)
    assert defaults.purpose_caps_usd == {"image": 3.5}
    defaults.purpose_caps_usd["image"] = 0
    assert Settings().purpose_caps_usd == {"image": 3.5}
    path = tmp_path / ".env"
    path.write_text(f"{name}=2.5\n", encoding="utf-8")
    assert load_settings(environ={}, env_file=path).purpose_caps_usd == {"image": 2.5}
    assert load_settings(environ={name: "0"}, env_file=path).purpose_caps_usd == {
        "image": 0
    }


@pytest.mark.parametrize("value", ["", " \t "])
def test_blank_purpose_cap_preserves_default(tmp_path, value):
    name = "BEAUTYADS_CAP_IMAGE_USD"
    path = tmp_path / ".env"
    path.write_text(f"{name}='{value}'\n", encoding="utf-8")
    assert load_settings(environ={name: value}, env_file=path).purpose_caps_usd == {
        "image": 3.5
    }


@pytest.mark.parametrize("value", ["negative-invalid", "-1", "nan", "inf", "-inf"])
@pytest.mark.parametrize("source", ["file", "environment"])
def test_invalid_purpose_cap(tmp_path, value, source):
    name = "BEAUTYADS_CAP_IMAGE_USD"
    path = tmp_path / ".env"
    if source == "file":
        path.write_text(f"{name}={value}\n", encoding="utf-8")
    with pytest.raises(InvalidSetting) as caught:
        load_settings(
            environ={name: value} if source == "environment" else {}, env_file=path
        )
    assert caught.value.name == name
    assert caught.value.code == "INVALID_SETTING"
    assert str(caught.value) == name
