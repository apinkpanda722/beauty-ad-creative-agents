"""Pure evidence-band calculations using the frozen CQ-v1 percentile rule."""

from collections import defaultdict
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class EvidenceAxis(StrEnum):
    hook_type = "hook_type"
    angle = "angle"
    format = "format"
    claim = "claim"


class CategoryBasis(StrEnum):
    creative_label = "creative_label"
    product_link = "product_link"


class EvidenceSource(StrEnum):
    youtube = "youtube"
    instagram = "instagram"
    tiktok = "tiktok"


class CertificationKind(StrEnum):
    brightening = "brightening"
    anti_aging = "anti_aging"
    sun_protection = "sun_protection"


MIN_BAND_N = 10
BAND_NOTE = "기술적 비교이며 인과를 뜻하지 않는다. 조회수에는 광고비 효과가 섞여 있다."


class BandValue(BaseModel):
    value: str
    n_top: int
    n_bottom: int
    creative_ids: list[str] = Field(max_length=3)


class BandResult(BaseModel):
    rows: list[BandValue]
    top_total: int
    bottom_total: int
    excluded_missing_views: int
    note: str = BAND_NOTE

    @property
    def low_n(self) -> bool:
        return min(self.top_total, self.bottom_total) < MIN_BAND_N

    @property
    def summary(self) -> str:
        counts = f"상위 n={self.top_total}, 하위 n={self.bottom_total}"
        return (
            f"표본 부족(n<10): {counts}" if self.low_n else counts
        ) + f". {self.note}"


def _datetime(value):
    native = getattr(value, "to_native", None)
    if callable(native):
        value = native()
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            return _datetime(datetime.fromisoformat(value))
        except ValueError:
            pass
    return None


def split_top_bottom(rows, *, mature_before) -> BandResult:
    """Rank unique creatives within source/brand, then count each axis value.

    The graph retains brand rather than original channel identity. As in CQ-06,
    all-equal groups belong to top (top takes precedence over bottom on ties).
    A multivalued claim must not multiply the population or percentile weights.
    """
    mature = _datetime(mature_before)
    if mature is None:
        raise ValueError("EVIDENCE_MATURITY_INVALID")
    groups = defaultdict(dict)
    eligible = []
    excluded = 0
    for row in rows:
        if row.get("views") is None:
            excluded += 1
            continue
        published = _datetime(row.get("published_at"))
        if published is not None and published <= mature:
            groups[(row.get("source"), row.get("channel_brand"))][
                row.get("creative_id")
            ] = row.get("views")
            eligible.append(row)
    bands = {}
    for group in groups.values():
        values = sorted(group.values())

        def threshold(index, values=values):
            lo = int(index)
            hi = min(lo + 1, len(values) - 1)
            return values[lo] + (values[hi] - values[lo]) * (index - lo)

        low = threshold((len(values) - 1) * 0.25)
        high = threshold((len(values) - 1) * 0.75)
        for key, value in group.items():
            bands[key] = (
                "top" if value >= high else "bottom" if value <= low else "middle"
            )
    by_value = defaultdict(dict)
    for row in eligible:
        by_value[row.get("value")][row.get("creative_id")] = row.get("views")
    counts = []
    for value, creatives in sorted(by_value.items()):
        counts.append(
            BandValue(
                value=value,
                n_top=sum(bands[key] == "top" for key in creatives),
                n_bottom=sum(bands[key] == "bottom" for key in creatives),
                creative_ids=sorted(creatives, key=lambda key: (-creatives[key], key))[
                    :3
                ],
            )
        )
    return BandResult(
        rows=counts,
        top_total=sum(band == "top" for band in bands.values()),
        bottom_total=sum(band == "bottom" for band in bands.values()),
        excluded_missing_views=excluded,
    )
