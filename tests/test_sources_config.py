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


def tiktok_config_data():
    return {
        "countries": ["DE", "FR"],
        "lookback_days": 330,
        "search_type": "exact_phrase",
        "brands": [{"brand": "mixsoon", "search_term": "mixsoon"}],
    }


def test_tiktok_dict_section(tmp_path):
    from beautyads.sources.config import TikTokConfig, load_tiktok_config

    raw = tiktok_config_data()
    assert load_tiktok_config(
        write_config(tmp_path, {"tiktok": raw, "instagram": None})
    ) == TikTokConfig(**raw)


@pytest.mark.parametrize("section", [None, [], [tiktok_config_data()], "invalid", {}])
def test_tiktok_invalid_structure(tmp_path, section):
    from beautyads.sources.config import load_tiktok_config

    with pytest.raises(ConfigError, match="^TIKTOK_CONFIG_INVALID$"):
        load_tiktok_config(write_config(tmp_path, {"tiktok": section}))


@pytest.mark.parametrize("field", ["brand", "search_term"])
@pytest.mark.parametrize("value", [None, "", "   ", 123, "missing"])
def test_tiktok_brand_required_fields(tmp_path, field, value):
    from beautyads.sources.config import load_tiktok_config

    raw = tiktok_config_data()
    if value == "missing":
        raw["brands"][0].pop(field)
    else:
        raw["brands"][0][field] = value
    with pytest.raises(ConfigError, match="^TIKTOK_CONFIG_INVALID$"):
        load_tiktok_config(write_config(tmp_path, {"tiktok": raw}))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("countries", []),
        ("countries", "DE"),
        ("lookback_days", 0),
        ("lookback_days", "330"),
        ("search_type", " "),
        ("brands", {}),
    ],
)
def test_tiktok_config_invalid_fields(tmp_path, field, value):
    from beautyads.sources.config import load_tiktok_config

    raw = {**tiktok_config_data(), field: value}
    with pytest.raises(ConfigError, match="^TIKTOK_CONFIG_INVALID$"):
        load_tiktok_config(write_config(tmp_path, {"tiktok": raw}))


@pytest.mark.parametrize("content", [None, "tiktok: [", b"\xff"])
def test_tiktok_config_unreadable(tmp_path, content):
    from beautyads.sources.config import load_tiktok_config

    path = tmp_path / "sources.yaml"
    if isinstance(content, str):
        path.write_text(content, encoding="utf-8")
    elif isinstance(content, bytes):
        path.write_bytes(content)
    with pytest.raises(ConfigError, match="^TIKTOK_CONFIG_UNREADABLE$"):
        load_tiktok_config(path)


def test_checked_in_tiktok_config():
    from beautyads.sources.config import load_tiktok_config

    config = load_tiktok_config(
        Path(__file__).resolve().parents[1] / "config/sources.yaml"
    )
    assert config.countries
    assert config.brands
    names = [brand.brand for brand in config.brands]
    assert len(names) == len(set(names))


def test_retailers_normalized(tmp_path):
    from beautyads.sources.config import load_retailers

    retailers = load_retailers(
        write_config(tmp_path, {"retailers": ["  SEPHORA ", "Etos", "etos", "PILULKA"]})
    )
    assert retailers.names == frozenset({"sephora", "etos", "pilulka"})


def test_checked_in_retailers():
    from beautyads.sources.config import load_retailers

    retailers = load_retailers(
        Path(__file__).resolve().parents[1] / "config/retailers.yaml"
    )
    assert {
        "sephora",
        "etos",
        "cosibella",
        "pilulka",
        "pharmacontinente",
    } <= retailers.names


@pytest.mark.parametrize(
    "data",
    [None, [], {}, {"retailers": {}}, {"retailers": [None]}, {"retailers": [" "]}],
)
def test_retailers_invalid(tmp_path, data):
    from beautyads.sources.config import load_retailers

    with pytest.raises(ConfigError, match="^RETAILERS_CONFIG_INVALID$"):
        load_retailers(write_config(tmp_path, data))


def test_retailers_unreadable(tmp_path):
    from beautyads.sources.config import load_retailers

    with pytest.raises(ConfigError, match="^RETAILERS_CONFIG_UNREADABLE$"):
        load_retailers(tmp_path / "absent.yaml")
