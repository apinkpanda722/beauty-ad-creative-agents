"""Only the YouTube section is interpreted; the checked-in config is read-only."""

from pathlib import Path

import pytest
import yaml

from beautyads.sources.config import ConfigError, YouTubeChannel, load_youtube_channels


def channel_data():
    return {
        "brand": "torriden",
        "handle": "@torriden-official",
        "channel_id": "UC3wmXZAsLYGINtBuZZOonLQ",
        "verified": "owner_watched_video",
    }


def write_config(tmp_path, data):
    path = tmp_path / "sources.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_load_youtube_only(tmp_path):
    raw = channel_data()
    path = write_config(
        tmp_path, {"youtube": [raw], "instagram": None, "tiktok": "ignored"}
    )
    assert load_youtube_channels(path) == [YouTubeChannel(**raw)]


@pytest.mark.parametrize("field", ["brand", "handle", "channel_id", "verified"])
def test_missing_required_channel_field(tmp_path, field):
    raw = channel_data()
    raw.pop(field)
    with pytest.raises(ConfigError):
        load_youtube_channels(write_config(tmp_path, {"youtube": [raw]}))


@pytest.mark.parametrize("field", ["brand", "handle", "channel_id", "verified"])
@pytest.mark.parametrize("value", [None, "", "   ", 123])
def test_invalid_required_channel_value(tmp_path, field, value):
    raw = channel_data()
    raw[field] = value
    with pytest.raises(ConfigError):
        load_youtube_channels(write_config(tmp_path, {"youtube": [raw]}))


def test_duplicate_channel_id_is_rejected(tmp_path):
    raw = channel_data()
    other = {**raw, "brand": "other", "handle": "@other"}
    with pytest.raises(ConfigError):
        load_youtube_channels(write_config(tmp_path, {"youtube": [raw, other]}))


@pytest.mark.parametrize("data", [None, [], {}, {"youtube": None}, {"youtube": {}}])
def test_invalid_youtube_section(tmp_path, data):
    with pytest.raises(ConfigError):
        load_youtube_channels(write_config(tmp_path, data))


def test_empty_youtube_list(tmp_path):
    assert load_youtube_channels(write_config(tmp_path, {"youtube": []})) == []


def test_unreadable_or_invalid_yaml_is_config_error(tmp_path):
    path = tmp_path / "sources.yaml"
    with pytest.raises(ConfigError):
        load_youtube_channels(path)
    path.write_text("youtube: [", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_youtube_channels(path)


def test_checked_in_youtube_channels():
    path = Path(__file__).resolve().parents[1] / "config" / "sources.yaml"
    channels = load_youtube_channels(path)
    assert channels
    ids = [channel.channel_id for channel in channels]
    assert len(set(ids)) == len(ids)
    assert all(channel_id.startswith("UC") for channel_id in ids)


def instagram_account_data():
    return {
        "brand": "torriden",
        "username": "torriden_official",
        "region": "kr",
        "verified": "official_site_link",
    }


def test_load_instagram_only(tmp_path):
    from beautyads.sources.config import InstagramAccount, load_instagram_accounts

    raw = instagram_account_data()
    path = write_config(tmp_path, {"instagram": [raw], "youtube": None})
    assert load_instagram_accounts(path) == [InstagramAccount(**raw)]


def test_instagram_optional_fields_can_be_absent(tmp_path):
    from beautyads.sources.config import load_instagram_accounts

    raw = instagram_account_data()
    raw.pop("region")
    raw.pop("verified")
    accounts = load_instagram_accounts(write_config(tmp_path, {"instagram": [raw]}))
    assert len(accounts) == 1
    assert accounts[0].brand == raw.get("brand")
    assert accounts[0].username == raw.get("username")
    assert accounts[0].region is None
    assert accounts[0].verified is None


@pytest.mark.parametrize("field", ["brand", "username"])
@pytest.mark.parametrize("value", [None, "", "   ", 123, "missing"])
def test_instagram_required_fields(tmp_path, field, value):
    from beautyads.sources.config import load_instagram_accounts

    raw = instagram_account_data()
    if value == "missing":
        raw.pop(field)
    else:
        raw[field] = value
    with pytest.raises(ConfigError, match="^INSTAGRAM_CONFIG_INVALID$"):
        load_instagram_accounts(write_config(tmp_path, {"instagram": [raw]}))


def test_duplicate_instagram_username(tmp_path):
    from beautyads.sources.config import load_instagram_accounts

    raw = instagram_account_data()
    other = {**raw, "brand": "other", "username": f" {raw.get('username')} "}
    with pytest.raises(ConfigError, match="^INSTAGRAM_USERNAME_DUPLICATE$"):
        load_instagram_accounts(write_config(tmp_path, {"instagram": [raw, other]}))


@pytest.mark.parametrize("data", [None, [], {}, {"instagram": None}, {"instagram": {}}])
def test_invalid_instagram_section(tmp_path, data):
    from beautyads.sources.config import load_instagram_accounts

    with pytest.raises(ConfigError, match="^INSTAGRAM_CONFIG_INVALID$"):
        load_instagram_accounts(write_config(tmp_path, data))


def test_empty_instagram_accounts(tmp_path):
    from beautyads.sources.config import load_instagram_accounts

    assert load_instagram_accounts(write_config(tmp_path, {"instagram": []})) == []


@pytest.mark.parametrize("content", [None, "instagram: [", b"\xff"])
def test_unreadable_instagram_config(tmp_path, content):
    from beautyads.sources.config import load_instagram_accounts

    path = tmp_path / "sources.yaml"
    if isinstance(content, str):
        path.write_text(content, encoding="utf-8")
    elif isinstance(content, bytes):
        path.write_bytes(content)
    with pytest.raises(ConfigError, match="^INSTAGRAM_CONFIG_UNREADABLE$"):
        load_instagram_accounts(path)


def test_checked_in_instagram_accounts():
    from beautyads.sources.config import load_instagram_accounts

    path = Path(__file__).resolve().parents[1] / "config" / "sources.yaml"
    accounts = load_instagram_accounts(path)
    assert accounts
    usernames = [account.username for account in accounts]
    assert len(set(usernames)) == len(usernames)
