"""Read only the YouTube channel list from the shared sources configuration."""

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class YouTubeChannel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    brand: str = Field(min_length=1)
    handle: str = Field(min_length=1)
    channel_id: str = Field(min_length=1)
    verified: str = Field(min_length=1)


class ConfigError(Exception):
    """Invalid or unreadable channel configuration."""


def load_youtube_channels(path: Path) -> list[YouTubeChannel]:
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        raise ConfigError("YOUTUBE_CONFIG_UNREADABLE") from None
    if not isinstance(document, dict) or not isinstance(document.get("youtube"), list):
        raise ConfigError("YOUTUBE_CONFIG_INVALID")
    try:
        channels = [
            YouTubeChannel.model_validate(item) for item in document.get("youtube", [])
        ]
    except ValidationError:
        raise ConfigError("YOUTUBE_CONFIG_INVALID") from None
    ids = [channel.channel_id for channel in channels]
    if len(ids) != len(set(ids)):
        raise ConfigError("YOUTUBE_CHANNEL_ID_DUPLICATE")
    return channels


class InstagramAccount(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    brand: str = Field(min_length=1)
    username: str = Field(min_length=1)
    region: str | None = None
    verified: str | None = None


def load_instagram_accounts(path: Path) -> list[InstagramAccount]:
    """Interpret only the Instagram section, independently of other sources."""
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        raise ConfigError("INSTAGRAM_CONFIG_UNREADABLE") from None
    if not isinstance(document, dict) or not isinstance(
        document.get("instagram"), list
    ):
        raise ConfigError("INSTAGRAM_CONFIG_INVALID")
    try:
        accounts = [
            InstagramAccount.model_validate(item)
            for item in document.get("instagram", [])
        ]
    except ValidationError:
        raise ConfigError("INSTAGRAM_CONFIG_INVALID") from None
    usernames = [account.username for account in accounts]
    if len(usernames) != len(set(usernames)):
        raise ConfigError("INSTAGRAM_USERNAME_DUPLICATE")
    return accounts


class TikTokBrand(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    brand: str = Field(min_length=1)
    search_term: str = Field(min_length=1)


class TikTokConfig(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    countries: list[str] = Field(min_length=1)
    lookback_days: int = Field(gt=0, strict=True)
    search_type: str = Field(min_length=1)
    brands: list[TikTokBrand]


def load_tiktok_config(path: Path) -> TikTokConfig:
    """Interpret the TikTok mapping without changing the other source loaders."""
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        raise ConfigError("TIKTOK_CONFIG_UNREADABLE") from None
    if not isinstance(document, dict) or not isinstance(document.get("tiktok"), dict):
        raise ConfigError("TIKTOK_CONFIG_INVALID")
    try:
        return TikTokConfig.model_validate(document.get("tiktok"))
    except ValidationError:
        raise ConfigError("TIKTOK_CONFIG_INVALID") from None


class Retailers(BaseModel):
    names: frozenset[str]


def load_retailers(path: Path) -> Retailers:
    """Read the provisional retailer seed; normalize case and whitespace."""
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        raise ConfigError("RETAILERS_CONFIG_UNREADABLE") from None
    names = document.get("retailers") if isinstance(document, dict) else None
    if not isinstance(names, list) or any(
        not isinstance(name, str) or not name.strip() for name in names
    ):
        raise ConfigError("RETAILERS_CONFIG_INVALID")
    return Retailers(names=frozenset(name.strip().lower() for name in names))
