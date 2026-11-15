import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from beautyads.analysis.models import FINAL_RUN_TAG
from beautyads.domain.sync import SYNC_OVERLAP, SyncCreative
from beautyads.graph.connection import GraphConnection
from beautyads.pipeline.sync import SyncDeps, main, run_sync

NOW = datetime(2026, 11, 15, tzinfo=UTC)
ENV = {"NEO4J_PASSWORD": "synthetic-value", "POSTGRES_PASSWORD": "synthetic-value"}


class Source:
    def __init__(self, dates=(), watermark=NOW):
        self.watermark = watermark
        self.writes = []
        self.since = []
        self.rows = [
            SyncCreative({"source": "youtube", "source_id": str(i)}, date)
            for i, date in enumerate(dates)
        ]

    def get_watermark(self):
        return self.watermark

    def set_watermark(self, value):
        self.writes.append(value)
        self.watermark = value

    def read_changed(self, *, since, limit, run_tag):
        assert run_tag == FINAL_RUN_TAG
        self.since.append(since)
        rows = [row for row in self.rows if since is None or row.updated_at > since]
        return rows if limit is None else rows[:limit]

    def read_labels(self, key, *, run_tag):
        assert run_tag == FINAL_RUN_TAG
        return []


class Driver:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []
        self.count = 0

    def execute_query(self, query, *, parameters_, **kwargs):
        self.calls.append(query)
        if self.fail and "DELETE r" in query:
            raise RuntimeError("synthetic failure")
        created = 0
        if "SET c += row.properties" in query:
            created = max(0, len(parameters_["rows"]) - self.count)
            self.count += created
        return SimpleNamespace(
            records=[{"count": self.count if ":Creative" in query else 0}]
            if "RETURN count(" in query
            else [],
            summary=SimpleNamespace(
                counters=SimpleNamespace(
                    nodes_created=created, relationships_created=0, properties_set=1
                )
            ),
        )


def test_overlap_cutoff_limit_and_watermark_follow_source_not_counters():
    source = Source(
        [
            NOW - SYNC_OVERLAP - timedelta(seconds=1),
            NOW - timedelta(minutes=5),
            NOW + timedelta(minutes=1),
        ]
    )
    driver = Driver()
    report = run_sync(SyncDeps(source, GraphConnection(driver)), limit=50)
    assert source.since == [NOW - SYNC_OVERLAP]
    assert report["read"] == 2
    assert report["watermark"] == (NOW + timedelta(minutes=1)).isoformat()
    assert source.writes == [NOW + timedelta(minutes=1)]
    second = run_sync(SyncDeps(source, GraphConnection(driver)), limit=50)
    assert second["read"] == 2
    assert second["nodes_created"] == 0
    assert source.watermark == NOW + timedelta(minutes=1)


def test_load_failure_does_not_advance_watermark():
    source = Source([NOW + timedelta(minutes=1)])
    driver = Driver(fail=True)
    with pytest.raises(RuntimeError):
        run_sync(SyncDeps(source, GraphConnection(driver)))
    assert (
        driver.count == 1
    )  # The creative write succeeded before an axis write failed.
    assert source.writes == [] and source.watermark == NOW


def test_full_ignores_cutoff_and_does_not_move_watermark_backwards():
    source = Source([NOW - timedelta(days=1)])
    report = run_sync(SyncDeps(source, GraphConnection(Driver())), full=True, limit=1)
    assert source.since == [None]
    assert report["read"] == 1
    assert source.watermark == NOW


def test_empty_input_keeps_watermark_and_reports_zero():
    source = Source()
    report = run_sync(SyncDeps(source, GraphConnection(Driver())))
    assert (
        report["read"]
        == report["nodes_created"]
        == report["relationships_created"]
        == report["skipped_invalid"]
        == 0
    )
    assert report["watermark"] == NOW.isoformat()
    assert source.writes == []


@pytest.mark.parametrize(
    "code",
    [
        "ENV_MISSING:NEO4J_PASSWORD",
        "ENV_MISSING:POSTGRES_PASSWORD",
        "DOCKER_DOWN",
        "POSTGRES_UNREACHABLE",
        "NEO4J_UNREACHABLE",
    ],
)
@pytest.mark.parametrize("custom_factory", [False, True])
def test_preflight_failure_never_constructs_dependencies(
    monkeypatch, code, custom_factory
):
    env = dict(ENV)
    if code.startswith("ENV_MISSING:"):
        env[code.split(":", 1)[1]] = "   "
    factory = Mock(side_effect=AssertionError("no dependencies before preflight"))
    store = Mock(side_effect=AssertionError("no store connection"))
    graph = Mock(side_effect=AssertionError("no graph driver"))
    monkeypatch.setattr("beautyads.pipeline.sync.connect", store)
    monkeypatch.setattr("beautyads.pipeline.sync.connect_graph", graph)
    out = io.StringIO()
    assert (
        main(
            [],
            environ=env,
            out=out,
            docker_check=lambda: code != "DOCKER_DOWN",
            tcp_check=lambda host, port, timeout: (
                code
                != ("POSTGRES_UNREACHABLE" if port == 5433 else "NEO4J_UNREACHABLE")
            ),
            deps_factory=factory if custom_factory else None,
        )
        == 2
    )
    assert f"PREFLIGHT_FAILED {code}" in out.getvalue()
    assert "synthetic-value" not in out.getvalue()
    factory.assert_not_called()
    store.assert_not_called()
    graph.assert_not_called()


def test_cli_verifies_exact_same_rows_twice_and_emits_counts():
    source = Source([NOW + timedelta(seconds=1)], watermark=None)
    driver = Driver()
    out = io.StringIO()
    assert (
        main(
            ["--limit", "50", "--verify"],
            environ=ENV,
            out=out,
            docker_check=lambda: True,
            tcp_check=lambda *args: True,
            deps_factory=lambda: SyncDeps(source, GraphConnection(driver)),
        )
        == 0
    )
    report = json.loads(out.getvalue())
    assert report["verification"]["nodes_created"] == 0
    assert report["verification"]["relationships_created"] == 0
    assert (
        report["verification"]["creative_count_before"]
        == report["verification"]["creative_count_after"]
        == 1
    )
    assert report["verification"]["invalid_values"] == 0
    assert len(source.since) == 1
    assert source.writes == [NOW + timedelta(seconds=1)]


def test_failed_replay_verification_does_not_advance_watermark():
    source = Source([NOW + timedelta(seconds=1)])

    class BadReplay(Driver):
        def execute_query(self, *args, **kwargs):
            result = super().execute_query(*args, **kwargs)
            result.summary.counters.nodes_created = 1
            return result

    out = io.StringIO()
    assert (
        main(
            ["--verify"],
            environ=ENV,
            out=out,
            docker_check=lambda: True,
            tcp_check=lambda *args: True,
            deps_factory=lambda: SyncDeps(source, GraphConnection(BadReplay())),
        )
        == 2
    )
    assert "GRAPH_VERIFY_FAILED" in out.getvalue()
    assert source.writes == []


def test_make_targets_preserve_offline_verify():
    makefile = Path("Makefile").read_text()
    assert {"sync", "live-graph"} <= set(makefile.splitlines()[0].split()[1:])
    assert "sync:\n\tuv run python -m beautyads.pipeline.sync $(ARGS)" in makefile
    assert (
        "live-graph:\n\tuv run python -m beautyads.pipeline.sync --limit 50 --verify"
        in makefile
    )
    verify = makefile.split("verify:\n", 1)[1].split("\n\n", 1)[0]
    assert "live-" not in verify
