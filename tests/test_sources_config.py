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
