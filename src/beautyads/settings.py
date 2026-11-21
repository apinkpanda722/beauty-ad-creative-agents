"""Read configuration without allowing blank values to replace defaults."""

import os
from collections.abc import Mapping
from math import isfinite
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


def neo4j_uri(
    *,
    environ: Mapping[str, str] | None = None,
    env_file: Path | None = DEFAULT_ENV_FILE,
) -> str:
    return get_setting(
        "BEAUTYADS_NEO4J_URI",
        "bolt://127.0.0.1:7688",
        environ=environ,
        env_file=env_file,
    )


class LangfuseSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    host: str = Field(default="http://127.0.0.1:3001", repr=False)
    public_key: str = Field(repr=False)
    secret_key: str = Field(repr=False)
    capture_io: bool = True


def langfuse_settings(
    *,
    environ: Mapping[str, str] | None = None,
    env_file: Path | None = DEFAULT_ENV_FILE,
) -> LangfuseSettings | None:
    config = {"environ": environ, "env_file": env_file}
    public_key = get_setting("LANGFUSE_PUBLIC_KEY", **config)
    secret_key = get_setting("LANGFUSE_SECRET_KEY", **config)
    if public_key is None or secret_key is None:
        return None
    capture_io = get_setting("BEAUTYADS_LANGFUSE_IO", "1", **config)
    if capture_io not in {"1", "0"}:
        raise InvalidSetting("BEAUTYADS_LANGFUSE_IO")
    return LangfuseSettings(
        public_key=public_key,
        secret_key=secret_key,
        capture_io=capture_io == "1",
        host=get_setting("LANGFUSE_HOST", "http://127.0.0.1:3001", **config),
    )


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ledger_path: Path = Path("data/manifest/costs.jsonl")
    provider_caps_usd: dict[str, float] = Field(
        default_factory=lambda: {"gemini": 12.0, "openai": 10.0, "anthropic": 8.0}
    )
    purpose_caps_usd: dict[str, float] = Field(default_factory=lambda: {"image": 3.5})
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
    caps = Settings().provider_caps_usd
    for provider in caps:
        name = f"BEAUTYADS_CAP_{provider.upper()}_USD"
        value = get_setting(name, environ=environ, env_file=env_file)
        if value is not None:
            try:
                cap = float(value)
            except ValueError:
                raise InvalidSetting(name) from None
            if not isfinite(cap) or cap < 0:
                raise InvalidSetting(name)
            caps[provider] = cap
    values["provider_caps_usd"] = caps
    purpose_caps = Settings().purpose_caps_usd
    for purpose in purpose_caps:
        name = f"BEAUTYADS_CAP_{purpose.upper()}_USD"
        value = get_setting(name, environ=environ, env_file=env_file)
        if value is not None:
            try:
                cap = float(value)
            except ValueError:
                raise InvalidSetting(name) from None
            if not isfinite(cap) or cap < 0:
                raise InvalidSetting(name)
            purpose_caps[purpose] = cap
    values["purpose_caps_usd"] = purpose_caps
    try:
        return Settings.model_validate(values)
    except ValidationError as error:
        field = error.errors(include_input=False)[0]["loc"][0]
        raise InvalidSetting(names[field]) from None
