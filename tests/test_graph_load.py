from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from neo4j.exceptions import AuthError, ConstraintError, ServiceUnavailable

from beautyads.domain.sync import SyncCreative, SyncLabel
from beautyads.graph.connection import GraphConnection, GraphError, connect_graph
from beautyads.graph.load import AXES, load_creatives, verify_counts


class Driver:
    def __init__(self):
        self.calls = []

    def execute_query(self, query, *, parameters_, **kwargs):
        self.calls.append((query, parameters_))
        return SimpleNamespace(
            records=[],
            summary=SimpleNamespace(
                counters=SimpleNamespace(
                    nodes_created=0, relationships_created=0, properties_set=1
                )
            ),
        )


def creative(**values):
    return SyncCreative(
        properties={
            "source": "youtube",
            "source_id": "watch-marker-'-$",
            "url": "https://example.invalid/watch-marker",
            "latest_view_count": "1099511627776",
            "duration_s": 12.5,
            "title": "do not copy",
            "attributes": {"raw": "do not copy"},
            **values,
        },
        updated_at=datetime(2026, 11, 15, tzinfo=UTC),
    )


def labels(content_type="product_creative"):
    return [
        SyncLabel(
            "content_type@v1",
            "done",
            {"category": "sun_care", "content_type": content_type},
        ),
        SyncLabel(
            "hook@v1",
            "done",
            {"hook_description": "watch-marker-description", "hook_type": "question"},
        ),
        SyncLabel(
            "full@v1",
            "done",
            {"cta_type": "none", "talent": "none", "format": "demo", "angle": "how_to"},
        ),
    ]


def test_parameterized_repeatable_merges_and_integer_metrics():
    driver = Driver()
    graph = GraphConnection(driver)
    rows = [(creative(), labels())]
    load_creatives(graph, rows, run_tag="v1")
    first = driver.calls.copy()
    load_creatives(graph, rows, run_tag="v1")
    assert driver.calls == first * 2
    assert first
    assert all("CREATE" not in query for query, _ in first)
    assert all("watch-marker" not in query for query, _ in first)
    merges = [(q, p) for q, p in first if "MERGE" in q]
    assert all("UNWIND $rows" in q for q, _ in merges)
    props = merges[0][1]["rows"][0]["properties"]
    assert props["latest_view_count"] == 2**40
    assert props["duration_s"] == 12.5
    assert "title" not in props and "attributes" not in props
    assert props["source_id"] == creative().properties["source_id"]
    hook = next(p for q, p in merges if ":USES_HOOK]" in q)
    assert hook["rows"][0]["description"] == "watch-marker-description"
    assert len([q for q, _ in merges if "MERGE (c)-" in q]) == 5


@pytest.mark.parametrize("kind", ["hook@minimal", "hook@default", "hook@v0"])
def test_old_tags_are_not_loaded(kind):
    driver = Driver()
    jobs = [labels()[0], SyncLabel(kind, "done", {"hook_type": "question"})]
    result = load_creatives(GraphConnection(driver), [(creative(), jobs)], run_tag="v1")
    assert result.skipped_invalid == 0
    assert not any("MERGE (c)-" in q for q, _ in driver.calls)


@pytest.mark.parametrize("tag", ["minimal", "default", "v0"])
def test_all_axes_require_the_final_tag(tag):
    driver = Driver()
    jobs = [
        SyncLabel(job.kind.replace("@v1", f"@{tag}"), job.status, job.labels)
        for job in labels()
    ]
    load_creatives(GraphConnection(driver), [(creative(), jobs)], run_tag="v1")
    assert not any("MERGE (c)-" in q for q, _ in driver.calls)
    properties = driver.calls[0][1]["rows"][0]["properties"]
    assert properties["content_type"] is None
    assert properties["category"] is None


def test_invalid_category_and_non_scalar_axis_are_skipped():
    driver = Driver()
    jobs = labels()
    jobs[0] = SyncLabel(
        "content_type@v1",
        "done",
        {"content_type": "product_creative", "category": "unknown-marker"},
    )
    jobs[1] = SyncLabel("hook@v1", "done", {"hook_type": ["unknown-marker"]})
    report = load_creatives(GraphConnection(driver), [(creative(), jobs)], run_tag="v1")
    assert report.skipped_invalid == 2
    assert "unknown-marker" not in repr(driver.calls)
    assert not any("MERGE (c)-[r:USES_HOOK]" in q for q, _ in driver.calls)


def test_load_is_bounded_by_batch_size():
    driver = Driver()
    entries = [(creative(source_id=str(i)), labels()) for i in range(3)]
    load_creatives(GraphConnection(driver), entries, run_tag="v1", batch_size=2)
    batches = [
        params["rows"]
        for query, params in driver.calls
        if "SET c += row.properties" in query
    ]
    assert [len(batch) for batch in batches] == [2, 1]
    assert {row["source_id"] for batch in batches for row in batch} == {"0", "1", "2"}


@pytest.mark.parametrize("status", ["pending", "held", "failed"])
def test_incomplete_final_jobs_are_not_loaded(status):
    driver = Driver()
    jobs = [labels()[0], SyncLabel("hook@v1", status, {"hook_type": "question"})]
    load_creatives(GraphConnection(driver), [(creative(), jobs)], run_tag="v1")
    assert not any("MERGE (c)-" in q for q, _ in driver.calls)


def test_invalid_values_are_counted_and_not_sent_to_graph():
    driver = Driver()
    jobs = labels()
    jobs[1] = SyncLabel("hook@v1", "done", {"hook_type": "unknown-marker"})
    jobs[2] = SyncLabel(
        "full@v1",
        "done",
        dict.fromkeys(("angle", "format", "talent", "cta_type"), "unknown-marker"),
    )
    report = load_creatives(GraphConnection(driver), [(creative(), jobs)], run_tag="v1")
    assert report.skipped_invalid == 5
    assert "unknown-marker" not in repr(driver.calls)
    assert not any("MERGE (c)-" in q for q, _ in driver.calls)


@pytest.mark.parametrize(
    "content_type", ["event_place", "brand_campaign", "other", "invalid"]
)
def test_non_product_has_no_axes(content_type):
    driver = Driver()
    report = load_creatives(
        GraphConnection(driver), [(creative(), labels(content_type))], run_tag="v1"
    )
    assert not any("MERGE (c)-" in q for q, _ in driver.calls)
    assert report.skipped_invalid == (content_type == "invalid")


def test_missing_content_job_cannot_use_hook_or_full():
    driver = Driver()
    load_creatives(GraphConnection(driver), [(creative(), labels()[1:])], run_tag="v1")
    assert not any("MERGE (c)-" in q for q, _ in driver.calls)


@pytest.mark.parametrize(
    ("error_type", "code"),
    [
        (AuthError, "NEO4J_AUTH_VOLUME_STALE"),
        (ServiceUnavailable, "NEO4J_UNREACHABLE"),
        (ConstraintError, "NEO4J_CONSTRAINT_VIOLATION"),
    ],
)
@pytest.mark.parametrize("phase", ["construct", "connect", "query"])
def test_errors_are_translated_without_diagnostics(error_type, code, phase):
    marker = "injected-credential-marker"

    class Broken(Driver):
        def verify_connectivity(self):
            if phase == "connect":
                raise error_type(marker)

        def execute_query(self, *args, **kwargs):
            raise error_type(marker)

        def close(self):
            pass

    def factory(*args, **kwargs):
        if phase == "construct":
            raise error_type(marker)
        return Broken()

    with pytest.raises(GraphError) as caught:
        graph = connect_graph(
            environ={"NEO4J_PASSWORD": marker}, env_file=None, driver_factory=factory
        )
        graph.run("RETURN $value", {"value": 1})
    assert caught.value.code == code
    assert marker not in str(caught.value)
    if error_type is AuthError:
        assert "make graph-reset" in str(caught.value)
        assert "처음" in str(caught.value)


def test_driver_settings_and_notification_filter():
    calls = []

    class Connected(Driver):
        def verify_connectivity(self):
            calls.append("verified")

    def factory(uri, **kwargs):
        calls.append((uri, kwargs))
        return Connected()

    connect_graph(
        environ={"NEO4J_PASSWORD": "test-placeholder"},
        env_file=None,
        driver_factory=factory,
    )
    uri, config = calls[0]
    assert uri == "bolt://127.0.0.1:7688"
    assert config["auth"] == ("neo4j", "test-placeholder")
    assert config["notifications_min_severity"] == "OFF"
    assert calls[1] == "verified"


def test_verification_counts_closed_values_and_reports_invalid():
    class Counts(Driver):
        def execute_query(self, query, *, parameters_, **kwargs):
            result = super().execute_query(query, parameters_=parameters_)
            result.records = [{"count": 4 if ":Creative" in query else 0}]
            return result

    driver = Counts()
    assert verify_counts(GraphConnection(driver)) == {
        "creative_count": 4,
        "invalid_values": 0,
    }
    assert len(driver.calls) == 1 + len(AXES)
    for query, params in driver.calls[1:]:
        assert "count(" in query
        assert params["values"]


def test_empty_input_issues_no_queries():
    driver = Driver()
    report = load_creatives(GraphConnection(driver), [], run_tag="v1")
    assert (
        report.nodes_created
        == report.relationships_created
        == report.skipped_invalid
        == 0
    )
    assert driver.calls == []


def test_advertiser_name_is_added_without_changing_existing_property_allowlist():
    from beautyads.graph.load import CREATIVE_PROPERTIES

    assert set(CREATIVE_PROPERTIES) == {
        "source",
        "source_id",
        "url",
        "published_at",
        "duration_s",
        "language",
        "brand",
        "latest_view_count",
        "latest_like_count",
        "latest_comment_count",
        "metrics_collected_at",
        "advertiser_name",
    }
    driver = Driver()
    load_creatives(
        GraphConnection(driver),
        [(creative(source="tiktok", advertiser_name="Synthetic Name"), labels())],
        run_tag="v1",
    )
    assert (
        driver.calls[0][1]["rows"][0]["properties"]["advertiser_name"]
        == "Synthetic Name"
    )


def test_legacy_layer2_snapshot_does_not_erase_advertiser_name():
    driver = Driver()
    load_creatives(
        GraphConnection(driver), [(creative(source="tiktok"), labels())], run_tag="v1"
    )
    assert "advertiser_name" not in driver.calls[0][1]["rows"][0]["properties"]
