import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from beautyads.analysis.models import FINAL_RUN_TAG
from beautyads.domain.labels import HookType
from beautyads.domain.sync import SYNC_OVERLAP, SyncCreative, SyncLabel
from beautyads.graph.connection import GraphConnection, GraphError
from beautyads.graph.load import AXES
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
        "live-graph:\n\tuv run python -m beautyads.pipeline.sync --sample 50 --verify"
        in makefile
    )
    verify = makefile.split("verify:\n", 1)[1].split("\n\n", 1)[0]
    assert "live-" not in verify


class SampleSource(Source):
    """Offline sample source whose creatives have final (v1) labels or not."""

    def __init__(self, *, labeled=True, watermark=NOW):
        super().__init__([NOW - timedelta(days=3)], watermark=watermark)
        self.labeled = labeled
        self.sampled = []

    def read_changed(self, **kwargs):
        raise AssertionError("sample mode must not read the incremental changes")

    def read_sample(self, *, limit, run_tag):
        assert run_tag == FINAL_RUN_TAG
        self.sampled.append(limit)
        return self.rows[:limit]

    def read_labels(self, key, *, run_tag):
        if not self.labeled:
            return []
        hook = next(iter(HookType)).value
        return [
            SyncLabel("content_type@v1", "done", {"content_type": "product_creative"}),
            SyncLabel("hook@v1", "done", {"hook_type": hook}),
        ]


class AxisDriver(Driver):
    def __init__(self, axis_relationships):
        super().__init__()
        self.axis_relationships = axis_relationships

    def execute_query(self, query, *, parameters_, **kwargs):
        if "RETURN count(r)" in query:
            return SimpleNamespace(
                records=[{"count": self.axis_relationships}],
                summary=SimpleNamespace(
                    counters=SimpleNamespace(
                        nodes_created=0, relationships_created=0, properties_set=0
                    )
                ),
            )
        return super().execute_query(query, parameters_=parameters_, **kwargs)


def test_sample_mode_reads_analysed_sample_and_never_moves_the_watermark():
    source = SampleSource()
    report = run_sync(
        SyncDeps(source, GraphConnection(AxisDriver(3))), sample=50, verify=True
    )
    assert source.sampled == [50]
    assert source.writes == [] and source.watermark == NOW
    assert report["sample"] == 50 and report["read"] == 1
    assert report["graph_check"] == {
        "labeled_in_sample": 1,
        "axis_relationships": 3 * len(AXES),  # the fake answers 3 per axis
    }
    assert report["verification"]["relationships_created"] == 0


def test_sample_with_axis_labels_but_no_axis_relationships_fails_verification():
    source = SampleSource()
    with pytest.raises(GraphError) as error:
        run_sync(
            SyncDeps(source, GraphConnection(AxisDriver(0))), sample=50, verify=True
        )
    assert str(error.value) == "GRAPH_VERIFY_NO_RELATIONSHIPS"
    assert source.writes == []


def test_sample_verification_without_analysed_creatives_is_not_a_pass():
    # Checking zero labelled creatives must not look like a successful check.
    source = SampleSource(labeled=False)
    with pytest.raises(GraphError) as error:
        run_sync(
            SyncDeps(source, GraphConnection(AxisDriver(0))), sample=50, verify=True
        )
    assert str(error.value) == "GRAPH_VERIFY_NO_LABELED_SAMPLE"


def test_full_verify_also_checks_axis_relationships_when_labels_exist():
    class FullSource(SampleSource):
        def read_changed(self, *, since, limit, run_tag):
            return self.rows

    with pytest.raises(GraphError) as error:
        run_sync(
            SyncDeps(FullSource(), GraphConnection(AxisDriver(0))),
            full=True,
            verify=True,
        )
    assert str(error.value) == "GRAPH_VERIFY_NO_RELATIONSHIPS"


@pytest.mark.parametrize("extra", [["--limit", "10"], ["--full"]])
def test_sample_is_exclusive_with_limit_and_full(extra):
    factory = Mock()
    out = io.StringIO()
    code = main(
        ["--sample", "50", *extra],
        environ=ENV,
        out=out,
        docker_check=lambda: True,
        tcp_check=lambda *args: True,
        deps_factory=factory,
    )
    assert code == 2
    factory.assert_not_called()


def test_cli_sample_verify_reports_graph_check():
    source = SampleSource()
    out = io.StringIO()
    assert (
        main(
            ["--sample", "50", "--verify"],
            environ=ENV,
            out=out,
            docker_check=lambda: True,
            tcp_check=lambda *args: True,
            deps_factory=lambda: SyncDeps(source, GraphConnection(AxisDriver(2))),
        )
        == 0
    )
    report = json.loads(out.getvalue())
    assert report["graph_check"]["axis_relationships"] == 2 * len(AXES)
    assert source.writes == []


class Layer1Source:
    def __init__(self, dates=(), watermark=NOW):
        from beautyads.domain.layer1 import SyncProduct
        from beautyads.domain.products import Product

        self.watermark = watermark
        self.writes = []
        self.since = []
        self.rows = [
            SyncProduct(
                product=Product(
                    brand="synthetic",
                    source_url=f"https://example.test/{i}",
                    name_ko="합성 세럼",
                    category="serum_ampoule",
                ),
                updated_at=date,
            )
            for i, date in enumerate(dates)
        ]

    def get_watermark(self):
        return self.watermark

    def set_watermark(self, value):
        self.watermark = value
        self.writes.append(value)

    def read_changed(self, *, since, limit):
        self.since.append(since)
        rows = [row for row in self.rows if since is None or row.updated_at > since]
        return rows if limit is None else rows[:limit]


def layer1_tables():
    from beautyads.graph.layer1 import parse_layer1_tables

    return parse_layer1_tables(
        {"links": [], "unmatched": [], "not_linked_for_now": []}, {"rows": []}
    )


def test_layer1_overlap_and_watermark_depend_only_on_source_times():
    from beautyads.pipeline.sync import run_layer1_sync

    source = Layer1Source(
        [
            NOW - SYNC_OVERLAP - timedelta(seconds=1),
            NOW - timedelta(minutes=1),
            NOW + timedelta(minutes=1),
        ]
    )
    report = run_layer1_sync(
        SyncDeps(source, GraphConnection(Driver())), tables=layer1_tables(), limit=50
    )
    assert source.since == [NOW - SYNC_OVERLAP]
    assert report["read"] == 2 and report["layers"] == "1"
    assert source.writes == [NOW + timedelta(minutes=1)]
    assert report["nodes_created"] == report["relationships_created"] == 0


def test_layer1_failure_keeps_watermark_and_empty_input_does_not_write():
    from beautyads.pipeline.sync import run_layer1_sync

    source = Layer1Source([NOW + timedelta(minutes=1)])
    with pytest.raises(RuntimeError):
        run_layer1_sync(
            SyncDeps(source, GraphConnection(Driver(fail=True))), tables=layer1_tables()
        )
    assert source.writes == [] and source.watermark == NOW
    empty = Layer1Source()
    report = run_layer1_sync(
        SyncDeps(empty, GraphConnection(Driver())), tables=layer1_tables()
    )
    assert empty.writes == [] and report["read"] == 0


def test_layer1_full_replay_and_cli_dispatch_are_offline(monkeypatch):
    source = Layer1Source([NOW - timedelta(days=1)])
    monkeypatch.setattr(
        "beautyads.pipeline.sync.load_layer1_tables", lambda *args: layer1_tables()
    )
    monkeypatch.setattr("beautyads.pipeline.sync.load_claim_rules", lambda *args: [])
    out = io.StringIO()
    driver = Driver()
    assert (
        main(
            ["--layers", "1", "--full", "--verify"],
            environ=ENV,
            out=out,
            docker_check=lambda: True,
            tcp_check=lambda *args: True,
            deps_factory=lambda: SyncDeps(source, GraphConnection(driver)),
        )
        == 0
    )
    report = json.loads(out.getvalue())
    assert report["layers"] == "1" and report["read"] == 1
    assert source.since == [None] and source.writes == [NOW]
    assert report["verification"]["nodes_created"] == 0
    assert not any(":Creative" in q for q in driver.calls if not q.startswith("CREATE"))


@pytest.mark.parametrize(
    "args", [["--layers", "invalid"], ["--layers", "1", "--sample", "2"]]
)
def test_invalid_layer_options_do_not_connect(args):
    factory = Mock()
    assert (
        main(
            args,
            environ=ENV,
            out=io.StringIO(),
            docker_check=lambda: True,
            tcp_check=lambda *args: True,
            deps_factory=factory,
        )
        == 2
    )
    factory.assert_not_called()


def test_layer1_failed_replay_does_not_advance_checkpoint():
    from beautyads.pipeline.sync import run_layer1_sync

    class NonIdempotentDriver(Driver):
        def execute_query(self, *args, **kwargs):
            result = super().execute_query(*args, **kwargs)
            result.summary.counters.relationships_created = 1
            return result

    source = Layer1Source([NOW + timedelta(minutes=1)])
    with pytest.raises(GraphError, match="GRAPH_VERIFY_FAILED"):
        run_layer1_sync(
            SyncDeps(source, GraphConnection(NonIdempotentDriver())),
            tables=layer1_tables(),
            verify=True,
        )
    assert source.writes == [] and source.watermark == NOW


def test_layer1_dependency_selection_and_cleanup_use_only_fakes(monkeypatch):
    from contextlib import ExitStack

    from beautyads.pipeline.sync import _live_deps
    from beautyads.store.layer1_source import PostgresLayer1Source

    connection, graph = Mock(), Mock()
    monkeypatch.setattr("beautyads.pipeline.sync.connect", lambda *args: connection)
    monkeypatch.setattr("beautyads.pipeline.sync.connect_graph", lambda **kwargs: graph)
    with ExitStack() as stack:
        deps = _live_deps(environ=ENV, env_file=None, stack=stack, layers="1")
        assert isinstance(deps.source, PostgresLayer1Source)
        assert deps.source.conn is connection and deps.graph is graph
    connection.close.assert_called_once_with()
    graph.close.assert_called_once_with()


class LinksSource:
    def __init__(self, entries=(), products=(), watermark=NOW):
        self.entries, self.products = list(entries), list(products)
        self.watermark = watermark
        self.since, self.writes = [], []

    def read_snapshot(self, *, since, limit):
        from beautyads.domain.links import LinksSnapshot

        self.since.append(since)
        changed = [
            e for e in self.entries if since is None or e.creative.updated_at > since
        ]
        return LinksSnapshot(
            changed if limit is None else changed[:limit], self.products
        )

    def get_watermark(self):
        return self.watermark

    def set_watermark(self, value):
        self.writes.append(value)
        self.watermark = value


def test_layer2_cli_dispatch_split_seed_and_full_summary_are_offline():
    from test_graph_layer2 import Graph
    from test_links_domain import creative, product

    p = product(brand="cosrx")
    source = LinksSource([creative(p.name_ko, brand="cosrx")], [p])
    out = io.StringIO()
    assert (
        main(
            [
                "--layers",
                "2",
                "--full",
                "--sample-pairs",
                "1",
                "--seed",
                "17",
                "--verify",
            ],
            environ=ENV,
            out=out,
            docker_check=lambda: True,
            tcp_check=lambda *args: True,
            deps_factory=lambda: SyncDeps(source, Graph()),
        )
        == 0
    )
    report = json.loads(out.getvalue())
    assert (
        report["layers"] == "2" and report["promotes"] == report["dev"]["promotes"] == 1
    )
    assert report["test"]["promotes"] == 0 and len(report["sample_pairs"]) == 1
    assert report["coverage_scope"] == "applied_batch"
    assert list(report)[-1] == "recommendation"
    assert "torriden" in report["no_product_info_brands"]
    assert source.since == [None] and source.writes == [NOW]
    assert report["verification"]["same_relationships"] is True


def test_layer2_overlap_checkpoint_empty_and_failed_transaction():
    from test_graph_layer2 import Graph
    from test_links_domain import creative, product

    from beautyads.pipeline.sync import run_layer2_sync

    p = product()
    source = LinksSource([creative(p.name_ko)], [p])
    report = run_layer2_sync(
        SyncDeps(source, Graph()), dev_brands=["dev"], test_brands=[]
    )
    assert source.since == [NOW - SYNC_OVERLAP] and source.writes == [NOW]
    assert report["promotes"] == 1
    empty = LinksSource()
    report = run_layer2_sync(SyncDeps(empty, Graph()), dev_brands=[], test_brands=[])
    assert report["read"] == 0 and empty.writes == []
    source.writes.clear()
    graph = Graph()
    graph.fail = True
    with pytest.raises(RuntimeError):
        run_layer2_sync(SyncDeps(source, graph), dev_brands=["dev"], test_brands=[])
    assert source.writes == []


def test_layer2_failed_semantic_replay_does_not_checkpoint():
    from test_graph_layer2 import Graph
    from test_links_domain import creative, product

    from beautyads.pipeline.sync import run_layer2_sync

    class BadReplay(Graph):
        def run(self, query, params=None):
            from beautyads.graph.layer2 import LINK_STATE

            result = super().run(query, params)
            if query == LINK_STATE:
                result.records.append({"unstable": len(self.calls)})
            return result

    p = product()
    source = LinksSource([creative(p.name_ko)], [p])
    with pytest.raises(GraphError, match="GRAPH_VERIFY_FAILED"):
        run_layer2_sync(
            SyncDeps(source, BadReplay()),
            dev_brands=["dev"],
            test_brands=[],
            verify=True,
        )
    assert source.writes == []


def test_layer2_dependency_selection_and_cleanup_use_only_fakes(monkeypatch):
    from contextlib import ExitStack

    from beautyads.pipeline.sync import _live_deps
    from beautyads.store.links_source import PostgresLinksSource

    connection, graph = Mock(), Mock()
    monkeypatch.setattr("beautyads.pipeline.sync.connect", lambda *args: connection)
    monkeypatch.setattr("beautyads.pipeline.sync.connect_graph", lambda **kwargs: graph)
    with ExitStack() as stack:
        deps = _live_deps(environ=ENV, env_file=None, stack=stack, layers="2")
        assert isinstance(deps.source, PostgresLinksSource)
    connection.close.assert_called_once_with()
    graph.close.assert_called_once_with()


@pytest.mark.parametrize(
    "options",
    [
        ["--layers", "2", "--sample-pairs", "-1"],
        ["--layers", "2", "--sample-pairs", "invalid"],
    ],
)
def test_layer2_invalid_options_never_connect(options):
    factory = Mock()
    assert main(options, environ=ENV, out=io.StringIO(), deps_factory=factory) == 2
    factory.assert_not_called()


def test_explicit_layer2_preserves_existing_sample_mode():
    source = SampleSource()
    out = io.StringIO()
    assert (
        main(
            ["--layers", "2", "--sample", "50", "--verify"],
            environ=ENV,
            out=out,
            docker_check=lambda: True,
            tcp_check=lambda *args: True,
            deps_factory=lambda: SyncDeps(source, GraphConnection(AxisDriver(2))),
        )
        == 0
    )
    report = json.loads(out.getvalue())
    assert report["sample"] == 50 and report["graph_check"]["labeled_in_sample"] == 1
    assert source.sampled == [50] and source.writes == []


class FeedbackSource(Layer1Source):
    def __init__(self, dates=(), watermark=NOW):
        from test_feedback_sync_domain import feedback

        super().__init__((), watermark)
        self.rows = [
            feedback(feedback_id=str(i), updated_at=d) for i, d in enumerate(dates)
        ]


def test_feedback_overlap_checkpoint_uses_times_even_when_counters_are_zero():
    from test_graph_feedback import Graph

    from beautyads.pipeline.sync import run_feedback_sync

    source = FeedbackSource(
        [NOW - SYNC_OVERLAP, NOW - timedelta(minutes=1), NOW + timedelta(minutes=1)]
    )
    report = run_feedback_sync(SyncDeps(source, Graph()), limit=20)
    assert source.since == [NOW - SYNC_OVERLAP]
    assert report["read"] == report["loaded"] == 2 and report["rejected"] == 0
    assert report["nodes_created"] == report["relationships_created"] == 0
    assert source.writes == [NOW + timedelta(minutes=1)]


def test_feedback_failure_and_empty_input_do_not_checkpoint():
    from test_graph_feedback import Graph

    from beautyads.pipeline.sync import run_feedback_sync

    source = FeedbackSource([NOW + timedelta(seconds=1)])
    graph = Graph()
    graph.fail = True
    with pytest.raises(RuntimeError):
        run_feedback_sync(SyncDeps(source, graph))
    assert source.writes == [] and source.watermark == NOW
    empty = FeedbackSource()
    report = run_feedback_sync(SyncDeps(empty, Graph()))
    assert report["read"] == report["loaded"] == report["rejected"] == 0
    assert empty.writes == []


def test_feedback_cli_full_verify_counts_and_rejections_are_offline():
    from test_feedback_sync_domain import feedback
    from test_graph_feedback import Graph

    source = FeedbackSource([NOW - timedelta(days=1)])
    source.rows.append(feedback(decision="invalid", updated_at=NOW))
    graph = Graph()
    out = io.StringIO()
    assert (
        main(
            ["--layers", "3", "--full", "--verify"],
            environ=ENV,
            out=out,
            docker_check=lambda: True,
            tcp_check=lambda *args: True,
            deps_factory=lambda: SyncDeps(source, graph),
        )
        == 0
    )
    report = json.loads(out.getvalue())
    assert report["layers"] == "3" and report["read"] == 2
    assert report["loaded"] == report["rejected"] == 1
    assert report["errors"][0]["code"] == "FEEDBACK_VALUE_INVALID"
    assert report["verification"]["same_feedback"] is True
    assert source.since == [None] and source.writes == [NOW]
    assert not any(
        ":Creative" in query
        for query, _ in graph.calls
        if not query.startswith("CREATE CONSTRAINT")
    )


def test_feedback_failed_semantic_replay_does_not_checkpoint():
    from test_graph_feedback import Graph

    from beautyads.graph.feedback import FEEDBACK_STATE
    from beautyads.pipeline.sync import run_feedback_sync

    class BadReplay(Graph):
        def run(self, query, params=None):
            result = super().run(query, params)
            if query == FEEDBACK_STATE:
                result.records.append({"unstable": len(self.calls)})
            return result

    source = FeedbackSource([NOW])
    with pytest.raises(GraphError, match="GRAPH_VERIFY_FAILED"):
        run_feedback_sync(SyncDeps(source, BadReplay()), verify=True)
    assert source.writes == []


def test_feedback_dependency_selection_cleanup_and_sample_rejection(monkeypatch):
    from contextlib import ExitStack

    from beautyads.pipeline.sync import _live_deps
    from beautyads.store.feedback_source import PostgresFeedbackSource

    connection, graph = Mock(), Mock()
    monkeypatch.setattr("beautyads.pipeline.sync.connect", lambda *args: connection)
    monkeypatch.setattr("beautyads.pipeline.sync.connect_graph", lambda **kwargs: graph)
    with ExitStack() as stack:
        deps = _live_deps(environ=ENV, env_file=None, stack=stack, layers="3")
        assert isinstance(deps.source, PostgresFeedbackSource)
        assert deps.source.conn is connection and deps.graph is graph
    connection.close.assert_called_once_with()
    graph.close.assert_called_once_with()
    factory = Mock()
    assert (
        main(
            ["--layers", "3", "--sample", "2"],
            environ=ENV,
            out=io.StringIO(),
            deps_factory=factory,
        )
        == 2
    )
    factory.assert_not_called()
