"""채널별 조회수 백분위와 조회수 상위·중간·하위 구분을 계산한다.

채널은 (출처, 계정)이며 출처 간 직접 비교는 하지 않는다. 대상 소재를
조회수 오름차순으로 정렬하고 1부터 시작하는 순위를 부여한다. 동률에는
해당 순위들의 평균을 쓰며 percentile = (평균 순위 - 0.5) / n 이다.
n은 채널 내 대상 소재 수다. 기본 최소 채널 크기 8건은 가정이다.
조회수에는 광고비 효과가 섞여 있으므로 구분은 조회수 상위를 뜻한다.
"""

from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from itertools import groupby

from pydantic import BaseModel, ConfigDict, Field

from beautyads.domain import Creative, CreativeKey, Source


class MetricBand(StrEnum):
    """채널 내 조회수 상위·중간·하위 구분. 광고비 효과가 섞여 있다."""

    top = "top"
    middle = "middle"
    bottom = "bottom"


class NormalizedMetric(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: CreativeKey
    channel: tuple[Source, str]
    percentile: float | None = Field(ge=0, le=1)
    band: MetricBand | None
    reason: str | None


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def normalize_views(
    creatives: Sequence[Creative],
    *,
    as_of: date | datetime,
    min_age_days: int = 14,
    min_channel_size: int = 8,
) -> list[NormalizedMetric]:
    """입력 변경이나 입출력 없이 키 순서로 결과를 반환한다.

    date 기준일은 UTC 게시 날짜와 달력 일수를 비교하고 datetime 기준일은
    온전히 지난 24시간 단위로 비교한다. 시간대 없는 datetime은 UTC로 본다.
    누락 사유 우선순위는 채널, 게시 시각, 게시 후 경과 기간, 조회수 순이다.
    계정이 없거나 공백뿐이면 channel의 식별자를 빈 문자열로 표시한다.
    """
    channels: dict[tuple[Source, str], list[Creative]] = defaultdict(list)
    results: list[NormalizedMetric] = []
    for creative in creatives:
        account = (
            creative.account if creative.account and creative.account.strip() else ""
        )
        channel = (creative.source, account)
        reason = None
        if not account:
            reason = "NO_CHANNEL"
        elif creative.published_at is None:
            reason = "NO_PUBLISHED_AT"
        else:
            published = _utc(creative.published_at)
            age = (
                _utc(as_of) - published
                if isinstance(as_of, datetime)
                else as_of - published.date()
            )
            if age < timedelta(days=min_age_days):
                reason = "TOO_RECENT"
            elif creative.metrics.view_count is None:
                reason = "NO_VIEW_COUNT"
        if reason is not None:
            results.append(
                NormalizedMetric(
                    key=creative.key,
                    channel=channel,
                    percentile=None,
                    band=None,
                    reason=reason,
                )
            )
        else:
            channels[channel].append(creative)

    for channel, candidates in channels.items():
        n = len(candidates)
        if n < min_channel_size:
            results.extend(
                NormalizedMetric(
                    key=creative.key,
                    channel=channel,
                    percentile=None,
                    band=None,
                    reason="CHANNEL_TOO_SMALL",
                )
                for creative in candidates
            )
            continue

        ordered = sorted(
            candidates,
            key=lambda item: (item.metrics.view_count, item.source_id),
        )
        start_rank = 1
        for _, tied in groupby(ordered, key=lambda item: item.metrics.view_count):
            group = list(tied)
            end_rank = start_rank + len(group) - 1
            average_rank = (start_rank + end_rank) / 2
            percentile = (average_rank - 0.5) / n
            if percentile >= 0.75:
                band = MetricBand.top
            elif percentile <= 0.25:
                band = MetricBand.bottom
            else:
                band = MetricBand.middle
            results.extend(
                NormalizedMetric(
                    key=creative.key,
                    channel=channel,
                    percentile=percentile,
                    band=band,
                    reason=None,
                )
                for creative in group
            )
            start_rank = end_rank + 1

    return sorted(results, key=lambda result: (result.key.source, result.key.source_id))
