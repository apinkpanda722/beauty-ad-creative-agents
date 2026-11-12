"""Read configuration without allowing blank values to replace defaults."""

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

ThinkingLevel = Literal["default", "minimal", "low", "medium", "high"]
DEFAULT_ENV_FILE = Path(".env")


class SettingError(Exception):
    """Expose only a setting name and a stable reason code, never its value."""

    def __init__(self, name: str, code: str):
        self.name = name
        self.code = code
        super().__init__(name)


class MissingSetting(SettingError):
    def __init__(self, name: str):
        super().__init__(name, "MISSING_SETTING")


class InvalidSetting(SettingError):
    def __init__(self, name: str):
        super().__init__(name, "INVALID_SETTING")


def read_env_file(path: Path) -> dict[str, str]:
    """Parse literal KEY=VALUE lines; a missing file supplies no settings."""
    try:
        contents = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    values = {}
    for line in contents.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name, value = name.strip(), value.strip()
        if len(value) >= 2 and value[0] in {"'", '"'} and value[0] == value[-1]:
            value = value[1:-1]
        if name:
            values[name] = value
    return values


def get_setting(
    name: str,
    default: str | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    env_file: Path | None = DEFAULT_ENV_FILE,
) -> str | None:
    environment = os.environ if environ is None else environ
    value = environment.get(name)
    if value is not None and value.strip():
        return value.strip()
    if env_file is not None:
        value = read_env_file(env_file).get(name)
        if value is not None and value.strip():
            return value.strip()
    return default


def require_setting(
    name: str,
    *,
    environ: Mapping[str, str] | None = None,
    env_file: Path | None = DEFAULT_ENV_FILE,
) -> str:
    value = get_setting(name, environ=environ, env_file=env_file)
    if value is None:
        raise MissingSetting(name)
    return value


def neo4j_password(
    *,
    environ: Mapping[str, str] | None = None,
    env_file: Path | None = DEFAULT_ENV_FILE,
) -> str:
    value = require_setting("NEO4J_PASSWORD", environ=environ, env_file=env_file)
    if len(value) < 8:
        raise InvalidSetting("NEO4J_PASSWORD")
    return value


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ledger_path: Path = Path("data/manifest/costs.jsonl")
    analysis_window_max_s: int = Field(default=60, gt=0)
    video_length_cut_s: int = Field(default=600, gt=0)
    thinking_level: ThinkingLevel = "minimal"


def load_settings(
    *,
    environ: Mapping[str, str] | None = None,
    env_file: Path | None = DEFAULT_ENV_FILE,
) -> Settings:
    names = {
        "ledger_path": "BEAUTYADS_LEDGER_PATH",
        "analysis_window_max_s": "BEAUTYADS_ANALYSIS_WINDOW_MAX_S",
        "video_length_cut_s": "BEAUTYADS_VIDEO_LENGTH_CUT_S",
        "thinking_level": "BEAUTYADS_THINKING_LEVEL",
    }
    values = {}
    for field, name in names.items():
        value = get_setting(name, environ=environ, env_file=env_file)
        if value is not None:
            if field in {"analysis_window_max_s", "video_length_cut_s"}:
                try:
                    value = int(value)
                except ValueError:
                    raise InvalidSetting(name) from None
            values[field] = value
    try:
        return Settings.model_validate(values)
    except ValidationError as error:
        field = error.errors(include_input=False)[0]["loc"][0]
        raise InvalidSetting(names[field]) from None
