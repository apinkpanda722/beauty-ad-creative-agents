"""Synthetic channel populations with hand-calculated ranks and fixed dates."""

import socket
from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from beautyads.analysis import metrics as module
from beautyads.analysis.metrics import MetricBand, NormalizedMetric, normalize_views
from beautyads.domain import Creative, Metrics, Source

AS_OF = date(2026, 11, 14)
PUBLISHED = datetime(2026, 10, 1, tzinfo=UTC)
COLLECTED = datetime(2026, 11, 14, tzinfo=UTC)


def creative(index, views, **overrides):
    return Creative(
        **{
            "source": Source.youtube,
            "source_id": f"video-{index:02d}",
            "account": "synthetic-channel",
            "brand": "synthetic-brand",
            "published_at": PUBLISHED,
            "collected_at": COLLECTED,
            "metrics": Metrics() if views is None else Metrics(view_count=views),
            **overrides,
        }
    )


def population(views=range(8), **overrides):
    return [creative(index, count, **overrides) for index, count in enumerate(views)]


def test_eight_distinct_counts_have_hand_calculated_percentiles_and_bands():
    items = population([0, 10, 20, 30, 40, 50, 60, 70])
    results = normalize_views(items, as_of=AS_OF)
    assert [result.key for result in results] == [item.key for item in items]
    assert [result.percentile for result in results] == [
        0.0625,
        0.1875,
        0.3125,
        0.4375,
        0.5625,
        0.6875,
        0.8125,
        0.9375,
    ]
    assert [result.band for result in results] == [
        MetricBand.bottom,
        MetricBand.bottom,
        MetricBand.middle,
        MetricBand.middle,
        MetricBand.middle,
        MetricBand.middle,
        MetricBand.top,
        MetricBand.top,
    ]
    assert all(result.reason is None for result in results)
    assert all(
        result.channel == (Source.youtube, "synthetic-channel") for result in results
    )


def test_average_ranks_include_exact_quartile_boundaries():
    # Ranks 2 and 3 average to 2.5; ranks 6 and 7 average to 6.5.
    results = normalize_views(population([0, 10, 10, 30, 40, 50, 50, 70]), as_of=AS_OF)
    assert [result.percentile for result in results] == [
        0.0625,
        0.25,
        0.25,
        0.4375,
        0.5625,
        0.75,
        0.75,
        0.9375,
    ]
    assert [result.band for result in results] == [
        MetricBand.bottom,
        MetricBand.bottom,
        MetricBand.bottom,
        MetricBand.middle,
        MetricBand.middle,
        MetricBand.top,
        MetricBand.top,
        MetricBand.top,
    ]


def test_all_tied_counts_are_middle():
    results = normalize_views(population([42] * 8), as_of=AS_OF)
    assert all(result.percentile == 0.5 for result in results)
    assert all(result.band == MetricBand.middle for result in results)


@pytest.mark.parametrize(
    "other_channel",
    [{"source": Source.instagram}, {"account": "another-channel"}],
)
def test_each_source_and_account_uses_its_own_population(other_channel):
    items = population(range(8)) + population(range(100, 108), **other_channel)
    results = normalize_views(items, as_of=AS_OF)
    channels = {}
    for result in results:
        channels.setdefault(result.channel, []).append(result.percentile)
    assert len(channels) == 2
    for percentiles in channels.values():
        assert percentiles == [
            0.0625,
            0.1875,
            0.3125,
            0.4375,
            0.5625,
            0.6875,
            0.8125,
            0.9375,
        ]


@pytest.mark.parametrize(
    "overrides,reason",
    [
        ({"published_at": datetime(2026, 11, 1, tzinfo=UTC)}, "TOO_RECENT"),
        ({"published_at": datetime(2026, 11, 15, tzinfo=UTC)}, "TOO_RECENT"),
        ({"published_at": None}, "NO_PUBLISHED_AT"),
        ({"metrics": Metrics()}, "NO_VIEW_COUNT"),
        ({"metrics": Metrics(view_count=None)}, "NO_VIEW_COUNT"),
        ({"account": None}, "NO_CHANNEL"),
        ({"account": ""}, "NO_CHANNEL"),
        ({"account": "  "}, "NO_CHANNEL"),
    ],
)
def test_ineligible_items_have_reason_and_do_not_change_population(overrides, reason):
    items = population() + [creative(8, 100_000, **overrides)]
    results = normalize_views(items, as_of=AS_OF)
    skipped = results[-1]
    assert skipped.key == items[-1].key
    assert skipped.percentile is None
    assert skipped.band is None
    assert skipped.reason == reason
    if reason == "NO_CHANNEL":
        assert skipped.channel == (Source.youtube, "")
    assert [result.percentile for result in results[:8]] == [
        0.0625,
        0.1875,
        0.3125,
        0.4375,
        0.5625,
        0.6875,
        0.8125,
        0.9375,
    ]


def test_fourteen_calendar_days_are_eligible_with_date_as_of():
    items = population(published_at=datetime(2026, 10, 31, 23, 59, tzinfo=UTC))
    assert all(result.reason is None for result in normalize_views(items, as_of=AS_OF))


def test_datetime_as_of_requires_full_elapsed_days_and_respects_offsets():
    as_of = datetime(2026, 11, 14, 12, tzinfo=UTC)
    published = datetime(2026, 10, 31, 21, tzinfo=timezone(timedelta(hours=9)))
    items = population(published_at=published)
    assert all(result.reason is None for result in normalize_views(items, as_of=as_of))
    items[-1].published_at = published + timedelta(seconds=1)
    results = normalize_views(items, as_of=as_of)
    assert results[-1].reason == "TOO_RECENT"
    assert all(result.reason == "CHANNEL_TOO_SMALL" for result in results[:-1])


def test_naive_datetimes_are_treated_as_utc():
    items = population(published_at=datetime(2026, 10, 31, 12))
    assert normalize_views(items, as_of=datetime(2026, 11, 14, 12)) == normalize_views(
        items, as_of=datetime(2026, 11, 14, 12, tzinfo=UTC)
    )
    assert all(
        result.reason is None
        for result in normalize_views(items, as_of=datetime(2026, 11, 14, 12))
    )


def test_small_channel_counts_only_eligible_items_and_keeps_individual_reasons():
    items = population(range(7)) + [creative(7, None)]
    results = normalize_views(items, as_of=AS_OF)
    assert all(result.reason == "CHANNEL_TOO_SMALL" for result in results[:7])
    assert all(result.percentile is None and result.band is None for result in results)
    assert results[-1].reason == "NO_VIEW_COUNT"


def test_minimum_channel_size_is_not_shared_across_sources():
    items = population(range(4)) + population(range(4), source=Source.instagram)
    assert all(
        result.reason == "CHANNEL_TOO_SMALL"
        for result in normalize_views(items, as_of=AS_OF)
    )


def test_age_and_channel_size_are_configurable():
    items = [creative(0, 0, published_at=datetime(2026, 11, 13, tzinfo=UTC))]
    result = normalize_views(items, as_of=AS_OF, min_age_days=1, min_channel_size=1)[0]
    assert result.percentile == 0.5
    assert result.band == MetricBand.middle
    assert result.reason is None
    assert (
        normalize_views(items, as_of=AS_OF, min_channel_size=1)[0].reason
        == "TOO_RECENT"
    )
    assert (
        normalize_views(items, as_of=AS_OF, min_age_days=1)[0].reason
        == "CHANNEL_TOO_SMALL"
    )


def test_order_is_by_key_and_inputs_are_unchanged():
    items = population([70, 0, 30, 20, 50, 10, 60, 40]) + population(
        source=Source.instagram
    )
    before = [item.model_dump(mode="json") for item in items]
    results = normalize_views(items, as_of=AS_OF)
    assert results == normalize_views(tuple(reversed(items)), as_of=AS_OF)
    assert [(row.key.source, row.key.source_id) for row in results] == sorted(
        (item.source, item.source_id) for item in items
    )
    assert [item.model_dump(mode="json") for item in items] == before


def test_fixed_as_of_needs_no_clock_network_or_files(monkeypatch):
    items = population()

    def forbidden(*args, **kwargs):
        pytest.fail("normalization must not read the clock, network or files")

    class ClockGuard(type):
        def __instancecheck__(cls, instance):
            return isinstance(instance, cls.__bases__[0])

    class NoClockDate(date, metaclass=ClockGuard):
        today = forbidden

    class NoClockDatetime(datetime, metaclass=ClockGuard):
        now = forbidden
        today = forbidden
        utcnow = forbidden

    monkeypatch.setattr(module, "date", NoClockDate)
    monkeypatch.setattr(module, "datetime", NoClockDatetime)
    monkeypatch.setattr("time.time", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr("builtins.open", forbidden)
    assert normalize_views(items, as_of=AS_OF) == normalize_views(items, as_of=AS_OF)
    assert normalize_views(items, as_of=COLLECTED)[0].percentile == 0.0625


def test_empty_input():
    assert normalize_views([], as_of=AS_OF) == []


def test_result_is_frozen_and_percentile_is_bounded():
    result = normalize_views(population(), as_of=AS_OF)[0]
    with pytest.raises(ValidationError, match="frozen"):
        result.percentile = 0.5
    for value in [-0.1, 1.1, float("nan")]:
        with pytest.raises(ValidationError):
            NormalizedMetric.model_validate(
                {**result.model_dump(), "percentile": value}
            )
