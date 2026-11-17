"""Frozen percentile semantics on entirely synthetic observations."""

from datetime import UTC, date, datetime

import pytest

from beautyads.domain.evidence import (
    MIN_BAND_N,
    CategoryBasis,
    EvidenceAxis,
    EvidenceSource,
    split_top_bottom,
)
from beautyads.eval.cq_verify import _percentiles
from beautyads.graph.queries import QUESTIONS, question_parameters

AS_OF = date(2026, 11, 17)
MATURE = question_parameters(QUESTIONS["CQ-06"], as_of=AS_OF)["mature_before"]


def observations(views, *, source="youtube", brand="synthetic"):
    return [
        {
            "creative_id": f"{source}:c{i:03}",
            "source": source,
            "channel_brand": brand,
            "views": v,
            "published_at": "2026-10-01T00:00:00Z",
            "value": f"v{i}",
        }
        for i, v in enumerate(views)
    ]


def test_closed_axes_sources_and_bases():
    assert set(EvidenceAxis) == {"hook_type", "angle", "format", "claim"}
    assert set(CategoryBasis) == {"creative_label", "product_link"}
    assert set(EvidenceSource) == {"youtube", "instagram", "tiktok"}
    assert MIN_BAND_N == 10


def test_interpolation_maturity_missing_and_no_mutation():
    rows = observations([0, 10, 20, 30, None, 1000])
    rows[-1]["published_at"] = "2026-11-04T00:00:00Z"
    rows[0]["published_at"] = MATURE
    before = [r.copy() for r in rows]
    result = split_top_bottom(rows, mature_before=MATURE)
    values = {r.value: r for r in result.rows}
    assert result.top_total == result.bottom_total == 1  # q25=7.5, q75=22.5
    assert values["v0"].n_bottom == values["v3"].n_top == 1
    assert values["v1"].n_top == values["v1"].n_bottom == 0
    assert result.excluded_missing_views == 1
    assert "v5" not in values and rows == before
    assert result.low_n and "표본 부족(n<10): 상위 n=1, 하위 n=1" in result.summary
    assert (
        result.note
        == "기술적 비교이며 인과를 뜻하지 않는다. 조회수에는 광고비 효과가 섞여 있다."
    )


@pytest.mark.parametrize("views", [[0, 10, 20, 30, 40], [5, 5, 5], [0, 0, 10, 10]])
def test_boundary_ties_and_cq_regression(views):
    rows = observations(views)
    rows += observations([100, 200, 300, 400], source="instagram")
    more = observations([10000, 20000, 30000, 40000], brand="another")
    for row in more:
        row["creative_id"] += "x"
        row["value"] += "x"
    rows += more
    rows += [dict(rows[0], creative_id="youtube:missing", value="missing", views=None)]
    for row in rows:
        row["value"] = row["creative_id"]
    result = split_top_bottom(rows, mature_before=MATURE)
    for row in rows:
        answers = [dict(row, category="mask_pack", hook=row["value"])]
        reference = _percentiles(rows, answers, AS_OF)
        bands = {r["band"] for r in reference["hook_distribution"]}
        actual = next((r for r in result.rows if r.value == row["value"]), None)
        assert (actual is not None and actual.n_top == 1) == ("top" in bands)
        assert (actual is not None and actual.n_bottom == 1) == ("bottom" in bands)
    assert result.excluded_missing_views == 1


def test_representatives_are_unique_capped_and_sorted_by_views_then_id():
    rows = observations([8, 9, 9, 9, 9])
    for row in rows:
        row["value"] = "shared"
    result = split_top_bottom(rows + rows, mature_before=MATURE)
    assert result.rows[0].creative_ids == [
        "youtube:c001",
        "youtube:c002",
        "youtube:c003",
    ]
    assert result.top_total == 4 and result.bottom_total == 1


@pytest.mark.parametrize("n,low", [(9, True), (10, False)])
def test_low_n_boundary(n, low):
    result = split_top_bottom(observations(range(4 * n)), mature_before=MATURE)
    assert result.top_total == result.bottom_total == n
    assert result.low_n is low
    assert ("표본 부족" in result.summary) is low


def test_empty_and_invalid_publication_dates():
    result = split_top_bottom([], mature_before=MATURE)
    assert result.rows == [] and result.low_n
    assert result.top_total == result.bottom_total == result.excluded_missing_views == 0
    rows = observations([1, 2])
    rows[0]["published_at"] = "invalid"
    rows[1]["published_at"] = None
    assert split_top_bottom(rows, mature_before=MATURE).rows == []


def test_native_temporal_and_timezone_boundary():
    class Temporal:
        def to_native(self):
            return datetime(2026, 11, 3, 23, 59, 59, tzinfo=UTC)

    rows = observations([1, 2, 3])
    rows[0]["published_at"] = Temporal()
    rows[1]["published_at"] = "2026-11-04T08:59:59+09:00"
    rows[2]["published_at"] = datetime(2026, 11, 4)
    result = split_top_bottom(rows, mature_before=datetime.fromisoformat(MATURE))
    assert result.top_total == result.bottom_total == 1


def test_multivalued_axis_does_not_inflate_population():
    rows = observations(range(4))
    rows += [dict(rows[-1], value="additional")]
    result = split_top_bottom(rows, mature_before=MATURE)
    assert result.top_total == result.bottom_total == 1
    assert sum(r.n_top for r in result.rows) == 2
