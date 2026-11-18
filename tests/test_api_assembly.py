"""Full assembly uses only synthetic connections, stores and model functions."""

import asyncio
import json
import traceback
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from beautyads.agents.planning import PLANNING_REASONING_EFFORT
from beautyads.api import assembly
from beautyads.domain.tenant import price_band
from beautyads.domain.tools import ToolContext, ToolResult
from beautyads.graph.evidence_queries import product_unit_price_query
from beautyads.llm.chat import ChatResult, ToolCall
from beautyads.llm.image import ImageOutcome
from beautyads.llm.structured import StructuredResult, StructuredStats
from beautyads.obs.ledger import CostCapExceeded, LedgerEntry, append_entry
from beautyads.settings import Settings
from beautyads.sources.workspaces import load_workspaces

EID = "youtube:synthetic"
COLLECTED = datetime(2026, 1, 2, tzinfo=UTC)


def record(path, purpose, cost=0.001, provider="openai"):
    append_entry(
        path,
        LedgerEntry(
            ts=COLLECTED,
            provider=provider,
            model="synthetic",
            purpose=purpose,
            cost_usd=cost,
            cost_source="price_table",
        ),
    )


def synthetic_plan():
    return {
        "title": "synthetic",
        "hook_type": "question",
        "hook_text": "synthetic",
        "scenes": ["synthetic"],
        "copy_lines": [],
        "image_brief": "synthetic",
        "cta_type": "none",
        "angle": "how_to",
        "format": "demo",
        "category": "mask_pack",
        "product_url": None,
        "claimed_efficacy": [],
        "evidence_ids": [EID],
    }


@pytest.fixture
def rig(monkeypatch, tmp_path):
    seen, calls, queries, profiles, seeds = [], [], [], {}, []
    settings = Settings(ledger_path=tmp_path / "ledger.jsonl")

    class Conn:
        def execute(self, query, params):
            queries.append((query, params))
            return SimpleNamespace(
                fetchall=lambda: [
                    (
                        "youtube",
                        "https://example.invalid/item",
                        "synthetic",
                        "title",
                        COLLECTED,
                        123,
                        None,
                    )
                ]
            )

        def rollback(self):
            seen.append("rollback")

        def close(self):
            seen.append("postgres-close")

    class Graph:
        price, basis = 100.0, "list_price"

        def run(self, query, params):
            queries.append((query, params))
            if query == product_unit_price_query():
                rows = [{"unit_list_price": self.price, "price_basis": self.basis}]
            else:
                rows = [{"creative_id": EID}]
            return SimpleNamespace(records=rows)

        def close(self):
            seen.append("graph-close")

    conn, graph = Conn(), Graph()

    def connect(dsn):
        seen.append("postgres-open")
        return conn

    def connect_graph(**kwargs):
        seen.append("graph-open")
        return graph

    async def saver(dsn):
        seen.append("saver-open")
        result = InMemorySaver()

        async def close():
            seen.append("saver-close")

        result.conn = SimpleNamespace(close=close)
        return result

    async def setup(value):
        seen.append("saver-setup")

    class Tenants:
        def __init__(self, conn):
            pass

        def save_profile(self, tenant_id, profile):
            seeds.append(tenant_id)
            profiles[tenant_id] = profile.model_dump(mode="json")

    def chat(**options):
        calls.append(("chat", options))
        record(settings.ledger_path, options["purpose"])
        payload = json.loads(options["messages"][-1]["content"])
        tools = (
            []
            if payload.get("observations")
            else [
                ToolCall(
                    "call", "find_example_creatives", {"category": "mask_pack"}, None
                )
            ]
        )
        return ChatResult(None, tools, "stop", {}, 0.001, "price_table", {})

    class Structured:
        def __init__(self, model):
            self.model, self.stats = model, StructuredStats()

        def generate(self, spec, **options):
            calls.append((spec.name, {"model": self.model, **options}))
            record(
                settings.ledger_path,
                options["purpose"],
                provider=("anthropic" if self.model.startswith("claude") else "openai"),
            )
            if spec.name == "supervisor_decision":
                data = {
                    "intent": "plan",
                    "category": "mask_pack",
                    "claim": None,
                    "hook_type": None,
                    "angle": None,
                    "format": None,
                    "skin_concern": None,
                    "plan_count": 1,
                    "goal": "synthetic",
                }
            elif spec.name == "research_handoff":
                data = {
                    "conclusion": "synthetic",
                    "evidence_ids": [EID],
                    "aggregates": [],
                    "confidence": "low",
                    "unresolved": [],
                }
            elif spec.name == "plan":
                data = synthetic_plan()
            else:
                data = {"differentiation": 5, "fit": 5, "rationale": "synthetic"}
            value = spec.validate(data)
            self.stats.calls += 1
            return StructuredResult(True, value, None, 1, 0.001, [])

    def image(**options):
        calls.append(("image", options))
        record(settings.ledger_path, "image-plan", 0.04, "gemini")
        payload = b"\x89PNG\r\n\x1a\nsynthetic"
        return ImageOutcome(
            True,
            payload,
            "image/png",
            len(payload),
            sha256(payload).hexdigest(),
            0.04,
            "synthetic",
            None,
        )

    def tool(name, arguments, ctx, *, graph):
        return ToolResult(
            tool=name,
            kind="lookup",
            summary="synthetic",
            top_rows=[],
            row_count=1,
            evidence_ids=[EID],
            no_evidence=False,
        )

    monkeypatch.setattr(assembly, "setup_checkpointer", setup)
    monkeypatch.setattr(assembly, "PostgresTenantRepository", Tenants)
    monkeypatch.setattr(
        assembly,
        "PostgresCreativeStore",
        lambda conn: SimpleNamespace(
            collection_stats=lambda: [
                SimpleNamespace(last_collected_at=None),
                SimpleNamespace(last_collected_at=COLLECTED),
            ]
        ),
    )
    monkeypatch.setattr(assembly, "run_tool", tool)

    async def start(**kwargs):
        model_overrides = kwargs.pop("models", {})
        return await assembly.assemble_full(
            **{
                "settings": settings,
                "connect_fn": connect,
                "graph_fn": connect_graph,
                "saver_fn": saver,
                "models": {
                    "chat": chat,
                    "structured": Structured,
                    "image": image,
                    **model_overrides,
                },
                "environ": {"POSTGRES_PASSWORD": "synthetic-password"},
                "env_file": None,
                **kwargs,
            }
        )

    return SimpleNamespace(
        start=start,
        seen=seen,
        calls=calls,
        queries=queries,
        profiles=profiles,
        seeds=seeds,
        graph=graph,
        conn=conn,
        settings=settings,
        tmp_path=tmp_path,
        image=image,
    )


def invoke(services, *, with_image=False, on_event=None):
    tenant_id = next(iter(services.allowed_tenants))
    return services.ask(
        "synthetic",
        ToolContext(tenant_id=tenant_id, as_of=services.as_of),
        services.workspaces[tenant_id],
        {},
        with_image,
        on_event=on_event,
    )


def test_owned_resources_and_skeleton_compatibility(rig):
    async def run():
        services = await rig.start()
        assert services.graph is not None and callable(services.chat)
        assert rig.calls == []
        assert (
            callable(services.tool_runner) and services.last_collected_at == COLLECTED
        )
        assert services.as_of == datetime.now(UTC).date()
        assert rig.seen == ["postgres-open", "graph-open", "saver-open", "saver-setup"]
        await services.close()
        await services.close()
        assert rig.seen[-3:] == ["saver-close", "graph-close", "postgres-close"]

    asyncio.run(run())


@pytest.mark.parametrize("stage", ["graph", "saver", "setup", "profiles"])
def test_partial_startup_closes_resources_and_sanitizes_errors(
    rig, monkeypatch, caplog, stage
):
    secret = "synthetic-private-dsn-and-key"

    def fail(*args, **kwargs):
        raise RuntimeError(secret)

    async def async_fail(*args, **kwargs):
        fail()

    options = {}
    if stage == "graph":
        options["graph_fn"] = fail
    elif stage == "saver":
        options["saver_fn"] = async_fail
    elif stage == "setup":
        monkeypatch.setattr(assembly, "setup_checkpointer", async_fail)
    else:
        monkeypatch.setattr(assembly, "load_workspaces", fail)
    with pytest.raises(RuntimeError, match="ASSEMBLY_FAILED") as caught:
        asyncio.run(rig.start(**options))
    rendered = "".join(traceback.format_exception(caught.value)) + caplog.text
    assert secret not in rendered
    expected = (
        ["postgres-close"] if stage == "graph" else ["graph-close", "postgres-close"]
    )
    if stage in {"setup", "profiles"}:
        expected.insert(0, "saver-close")
    assert [name for name in rig.seen if name.endswith("-close")] == expected


@pytest.mark.parametrize("group", [None, "test"])
def test_group_selection_profile_seeding_and_price_bands(rig, group):
    workspaces = load_workspaces(Path("config/workspaces.yaml"))
    selected = [w for w in workspaces if w.group == (group or "dev")]
    other = {w.tenant_id for w in workspaces if w.group != (group or "dev")}

    async def run():
        kwargs = {} if group is None else {"group": group}
        for _ in range(2):
            services = await rig.start(**kwargs)
            assert services.allowed_tenants == frozenset(w.tenant_id for w in selected)
            assert not services.allowed_tenants & other
            assert set(services.workspaces) == services.allowed_tenants
            for workspace in selected:
                profile = workspace.model_dump(mode="json", exclude={"group"})
                assert rig.profiles[workspace.tenant_id] == profile
                assert services.workspaces[workspace.tenant_id] == profile
                assert services.price_bands[workspace.tenant_id] == price_band(
                    100, workspace.price_band_pct
                ).model_dump(mode="json")
            await services.close()
        assert sorted(rig.seeds) == sorted([w.tenant_id for w in selected] * 2)

    asyncio.run(run())


@pytest.mark.parametrize(
    "price,basis", [(None, "list_price"), (100, "sale_price"), (None, None)]
)
def test_missing_or_non_list_price_is_empty(rig, price, basis):
    rig.graph.price, rig.graph.basis = price, basis

    async def run():
        services = await rig.start()
        assert services.price_bands == {}
        await services.close()

    asyncio.run(run())


@pytest.mark.parametrize("model", [None, "claude-sonnet-5-5"])
def test_ask_runs_real_subgraphs_with_explicit_efforts_and_request_local_costs(
    rig, model
):
    async def run():
        services = await rig.start(
            **({} if model is None else {"evaluation_model": model})
        )
        record(rig.settings.ledger_path, "previous-request", 1)
        for _ in range(2):
            events = []
            result = invoke(services, on_event=events.append)
            json.dumps(result, allow_nan=False)
            assert result["kind"] == "plan" and result["plans"][0]["status"] == "done"
            assert result["limits"]["text_spent_usd"] == pytest.approx(0.006)
            assert events and result["plans"][0]["attempts"][0][
                "cost_usd"
            ] == pytest.approx(0.002)
        for name, options in rig.calls:
            expected = (
                PLANNING_REASONING_EFFORT
                if name == "plan"
                else None
                if name == "evaluation_scores"
                else "none"
            )
            assert options["reasoning_effort"] == expected
            assert "temperature" not in options
            assert options["ledger_path"] == rig.settings.ledger_path
            if name == "evaluation_scores":
                assert options["model"] == (model or "claude-haiku-5-5")
        await services.close()

    asyncio.run(run())


def test_unknown_evaluation_model_rejected_before_connect(rig):
    with pytest.raises(ValueError, match="EVALUATION_MODEL_INVALID"):
        asyncio.run(rig.start(evaluation_model="unknown"))
    assert rig.seen == []


def test_spent_function_reads_all_providers_excludes_only_image_prefix(
    rig, monkeypatch
):
    def request(**options):
        spent = options["spent_fn"]
        assert spent() == 0
        options["decide_fn"]("synthetic")
        assert spent() == pytest.approx(0.001)
        record(rig.settings.ledger_path, "image", 2, "gemini")
        record(rig.settings.ledger_path, "image-plan", 2, "gemini")
        record(rig.settings.ledger_path, "imagery", 0.1, "anthropic")
        assert spent() == pytest.approx(0.101)
        return {}

    monkeypatch.setattr(assembly, "run_request", request)

    async def run():
        services = await rig.start()
        assert not rig.settings.ledger_path.exists()
        invoke(services)
        await services.close()

    asyncio.run(run())


@pytest.mark.parametrize("enabled", [False, True])
def test_optional_text_only_image_and_safe_local_reference(rig, monkeypatch, enabled):
    saved = []
    monkeypatch.setattr(
        assembly,
        "save_design_image",
        lambda outcome, **kw: (
            saved.append(kw)
            or SimpleNamespace(
                mime=outcome.mime, size=outcome.size, sha256=outcome.sha256
            )
        ),
    )
    real_loop = assembly.run_plan_eval

    def loop(**options):
        assert (options["image_fn"] is not None) is enabled
        return real_loop(**options)

    monkeypatch.setattr(assembly, "run_plan_eval", loop)

    async def run():
        services = await rig.start(with_image_enabled=enabled)
        assert services.image_enabled is enabled
        result = invoke(services, with_image=True)
        assert result["limits"]["text_spent_usd"] == pytest.approx(0.006)
        image_calls = [kw for name, kw in rig.calls if name == "image"]
        if enabled:
            assert len(image_calls) == len(saved) == 1
            assert isinstance(image_calls[0]["prompt"], str)
            assert (
                not {"images", "image_url", "reference_images"} & image_calls[0].keys()
            )
            assert image_calls[0]["purpose_caps"]["image"] == 3.5
            image = result["plans"][0]["image"]
            assert image["ok"] and image["request_key"] == saved[0]["request_key"]
            assert image["index"] == saved[0]["index"]
            assert saved[0]["base_dir"] == services.design_dir
            assert "path" not in image
        else:
            assert image_calls == saved == []
        await services.close()

    asyncio.run(run())


@pytest.mark.parametrize("cap", ["gemini", "purpose:image"])
def test_image_caps_return_structured_result_and_supervisor_image_limit(rig, cap):
    def capped(**options):
        raise CostCapExceeded(cap, 4, 3.5)

    async def run():
        services = await rig.start(with_image_enabled=True, models={"image": capped})
        result = invoke(services, with_image=True)
        assert result["plans"][0]["image"] == {
            "ok": False,
            "code": "IMAGE_CAP_REACHED",
            "cap": "provider:gemini" if cap == "gemini" else cap,
        }
        assert result["limit_kinds"] == ["image"]
        await services.close()

    asyncio.run(run())


def test_hydrate_uses_seven_columns_and_bound_keys_and_json_dates(rig):
    async def run():
        services = await rig.start()
        rig.queries.clear()
        value = services.hydrate([EID])
        json.dumps(value, allow_nan=False)
        assert value[0]["evidence_id"] == EID
        assert value[0]["published_at"] == COLLECTED.isoformat()
        assert value[0]["view_count"] == 123 and value[0]["like_count"] is None
        assert len(rig.queries) == 1
        query, params = rig.queries[0]
        columns = query.split("SELECT", 1)[1].split("FROM", 1)[0]
        assert [s.strip() for s in columns.split(",")] == [
            "source",
            "url",
            "brand",
            "title",
            "published_at",
            "latest_view_count",
            "latest_like_count",
        ]
        assert params == ("youtube", "synthetic")
        assert "synthetic" not in query and "%s" in query
        await services.close()

    asyncio.run(run())


@pytest.mark.parametrize("boundary", ["chat", "hydrate", "close"])
def test_runtime_errors_do_not_expose_synthetic_credentials(
    rig, monkeypatch, caplog, boundary
):
    private = "synthetic-private-credential-diagnostic"

    def fail(*args, **kwargs):
        raise RuntimeError(private)

    async def run():
        services = await rig.start(models={"chat": fail})
        if boundary == "hydrate":
            monkeypatch.setattr(rig.conn, "execute", fail)
        elif boundary == "close":
            monkeypatch.setattr(rig.graph, "close", fail)
        with pytest.raises(RuntimeError) as caught:
            if boundary == "chat":
                services.chat(model="gpt-6-luna", messages=[], reasoning_effort="none")
            elif boundary == "hydrate":
                services.hydrate([EID])
            else:
                await services.close()
        assert (
            private
            not in "".join(traceback.format_exception(caught.value)) + caplog.text
        )
        if boundary != "close":
            await services.close()
        assert rig.seen[-1] == "postgres-close"

    asyncio.run(run())


@pytest.mark.parametrize("explicit_path", [False, True])
def test_ask_trace_is_one_line_with_request_ledger_and_model_stats(
    rig, monkeypatch, explicit_path
):
    from datetime import timedelta

    from beautyads.obs.trace import read_traces

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return COLLECTED

    monkeypatch.setattr(assembly, "datetime", Clock)
    monkeypatch.setattr(
        assembly,
        "save_design_image",
        lambda outcome, **kw: SimpleNamespace(
            mime=outcome.mime, size=outcome.size, sha256=outcome.sha256
        ),
    )
    append_entry(
        rig.settings.ledger_path,
        LedgerEntry(
            ts=COLLECTED - timedelta(microseconds=1),
            provider="openai",
            model="previous-model",
            purpose="previous-request",
            cost_usd=1,
            cost_source="price_table",
        ),
    )
    path = (
        rig.tmp_path / "custom" / "trace.jsonl"
        if explicit_path
        else rig.settings.ledger_path.with_name("traces.jsonl")
    )

    async def run():
        services = await rig.start(
            with_image_enabled=True,
            **({"trace_path": path} if explicit_path else {}),
        )
        assert not path.exists()
        for count in (1, 2):
            result = invoke(services, with_image=True)
            read = read_traces(path)
            assert read.skipped_lines == 0 and len(read.records) == count
            assert len(path.read_text().splitlines()) == count
            trace = read.records[-1]
            assert trace.tenant_id == next(iter(services.allowed_tenants))
            assert trace.outcome == "ok" and trace.kind == result["kind"]
            assert trace.started_at == COLLECTED and trace.duration_ms >= 0
            # Timestamp windows can overlap; this demo's limitation is explicit.
            assert len(trace.calls) == 7 * count
            assert "previous-request" not in trace.cost_by_purpose
            assert trace.cost_by_purpose["image-plan"] == pytest.approx(0.04 * count)
            assert any(call.purpose == "image-plan" for call in trace.calls)
            assert trace.text_spent_usd == pytest.approx(0.006)
            assert trace.cost_total_usd == pytest.approx(0.046 * count)
            assert {
                model: stats.calls for model, stats in trace.structured.items()
            } == {"gpt-6-luna": 2, "gpt-6.1-terra": 1, "claude-haiku-5-5": 1}
            assert all(
                stats.failed_after_retry == 0 for stats in trace.structured.values()
            )
        await services.close()

    asyncio.run(run())


def test_trace_merges_failure_kinds_without_sharing_requests(rig, monkeypatch):
    from beautyads.llm.structured import StructuredFailure
    from beautyads.obs.trace import read_traces

    class Generator:
        def __init__(self, model):
            self.model = model
            self.stats = StructuredStats(
                calls=2,
                failed_after_retry=1,
                first_attempt_failures={StructuredFailure.TOOL_NOT_CALLED: 1},
            )

        def generate(self, *args, **kwargs):
            return SimpleNamespace(cost_usd=0.01)

    def request(**options):
        options["decide_fn"]("synthetic")
        options["research_fn"]({}, {})
        return {}

    def decision(text, *, structured, **kwargs):
        structured.generate(None)
        return SimpleNamespace(ok=True, decision={})

    def research(*args, structured, **kwargs):
        structured.generate(None)
        return {}

    monkeypatch.setattr(assembly, "run_request", request)
    monkeypatch.setattr(assembly, "decide", decision)
    monkeypatch.setattr(assembly, "run_research", research)

    async def run():
        services = await rig.start(models={"structured": Generator})
        for _ in range(2):
            invoke(services)
        traces = read_traces(rig.settings.ledger_path.with_name("traces.jsonl"))
        assert len(traces.records) == 2
        for trace in traces.records:
            stats = trace.structured["gpt-6-luna"]
            assert stats.calls == 4 and stats.failed_after_retry == 2
            assert stats.first_attempt_failures == {"TOOL_NOT_CALLED": 2}
        await services.close()

    asyncio.run(run())


def test_assembly_merges_failure_details_by_model_per_request(rig, monkeypatch):
    from beautyads.obs.trace import read_traces, summarize_by_tenant

    key = "evaluation_scores|rationale|string_too_long"

    class Generator:
        def __init__(self, model):
            self.model = model
            self.stats = StructuredStats(
                calls=1, first_attempt_failure_details={key: 1}
            )

        def generate(self, *args, **kwargs):
            return SimpleNamespace(cost_usd=0.01)

    def request(**options):
        options["decide_fn"]("synthetic")
        options["research_fn"]({}, {})
        return {}

    def decision(text, *, structured, **kwargs):
        structured.generate(None)
        return SimpleNamespace(ok=True, decision={})

    def research(*args, structured, **kwargs):
        structured.generate(None)
        return {}

    monkeypatch.setattr(assembly, "run_request", request)
    monkeypatch.setattr(assembly, "decide", decision)
    monkeypatch.setattr(assembly, "run_research", research)

    async def run():
        services = await rig.start(models={"structured": Generator})
        try:
            invoke(services)
            invoke(services)
            path = rig.settings.ledger_path.with_name("traces.jsonl")
            records = read_traces(path).records
            assert len(records) == 2
            assert all(
                r.structured["gpt-6-luna"].first_attempt_failure_details == {key: 2}
                for r in records
            )
            assert next(iter(summarize_by_tenant(records).values()))[
                "first_attempt_failure_details"
            ] == {key: 4}
            assert "SYNTHETIC-SECRET-" not in path.read_text()
        finally:
            await services.close()

    asyncio.run(run())


def test_trace_preserves_original_model_exception(rig, monkeypatch):
    from beautyads.obs.trace import read_traces

    failure = CostCapExceeded("openai", 10, 10)

    class Generator:
        def __init__(self, model):
            self.model, self.stats = model, StructuredStats()

        def generate(self, *args, **kwargs):
            raise failure

    def decision(text, *, structured, **kwargs):
        return structured.generate(None)

    monkeypatch.setattr(assembly, "decide", decision)
    monkeypatch.setattr(
        assembly, "run_request", lambda **kw: kw["decide_fn"]("synthetic")
    )

    async def run():
        services = await rig.start(models={"structured": Generator})
        with pytest.raises(CostCapExceeded) as caught:
            invoke(services)
        assert caught.value is failure
        traces = read_traces(rig.settings.ledger_path.with_name("traces.jsonl"))
        assert len(traces.records) == 1
        trace = traces.records[0]
        assert trace.outcome == "error" and trace.error_class == type(failure).__name__
        assert trace.error_code == failure.code
        assert trace.kind is None
        await services.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "failing_part", ["path", "build_trace", "append_trace", "read_entries", "stats"]
)
@pytest.mark.parametrize("raises", [False, True])
def test_trace_failures_never_change_result_or_original_error(
    rig, monkeypatch, caplog, capsys, failing_part, raises
):
    secret = "SYNTHETIC-SECRET-observation-error"
    outcome, failure = {"kind": "out_of_scope"}, RuntimeError(secret)

    def fail(*args, **kwargs):
        raise RuntimeError(secret)

    def request(**options):
        if failing_part == "stats":
            options["decide_fn"]("synthetic")
        if raises:
            raise failure
        return outcome

    monkeypatch.setattr(assembly, "run_request", request)
    kwargs = {}
    if failing_part == "path":
        # A file used as a parent is unwritable even when tests run as root.
        blocked = rig.tmp_path / "file-parent"
        blocked.write_text("synthetic")
        kwargs["trace_path"] = blocked / "traces.jsonl"
    elif failing_part == "stats":

        class Generator:
            model = "gpt-6-luna"

            @property
            def stats(self):
                fail()

            def generate(self, *args, **kwargs):
                return SimpleNamespace(cost_usd=0.001)

        monkeypatch.setattr(
            assembly,
            "decide",
            lambda *a, structured, **kw: (
                (structured.generate(None) or None)
                and SimpleNamespace(ok=True, decision={})
            ),
        )
        kwargs["models"] = {"structured": lambda model: Generator()}
    else:
        monkeypatch.setattr(assembly, failing_part, fail)

    async def run():
        services = await rig.start(**kwargs)
        if raises:
            with pytest.raises(RuntimeError) as caught:
                invoke(services)
            assert caught.value is failure
        else:
            assert invoke(services) is outcome
        await services.close()

    asyncio.run(run())
    assert secret not in caplog.text + str(capsys.readouterr())


@pytest.mark.parametrize(
    "provider,total,cap,expected",
    [
        ("gemini", 16.66, 12, "provider:gemini"),
        ("purpose:image", 3.6, 3.5, "purpose:image"),
        ("openai", 20, 10, "provider:openai"),
        ("synthetic-private secret/value", 1, 1, "provider:unknown"),
        ("purpose:other", 1, 1, "provider:unknown"),
        ("Gemini", 1, 1, "provider:unknown"),
        ("a" * 33, 1, 1, "provider:unknown"),
    ],
)
def test_image_cap_detail_reaches_supervisor_and_trace(
    rig, provider, total, cap, expected
):
    from beautyads.obs.trace import read_traces

    def image(**options):
        raise CostCapExceeded(provider, total, cap)

    async def run():
        services = await rig.start(with_image_enabled=True, models={"image": image})
        try:
            result = invoke(services, with_image=True)
            assert result["plans"][0]["image"] == {
                "ok": False,
                "code": "IMAGE_CAP_REACHED",
                "cap": expected,
            }
            detail = [{"kind": "image", "cap": expected}]
            assert result["limit_detail"] == detail
            assert result["limit_kinds"] == ["image"] and result["limit_hit"]
            trace = read_traces(rig.settings.ledger_path.with_name("traces.jsonl"))
            assert len(trace.records) == 1
            assert [
                item.model_dump() for item in trace.records[0].limit_detail
            ] == detail
            assert (
                "synthetic-private secret/value"
                not in trace.records[0].model_dump_json()
            )
        finally:
            await services.close()

    asyncio.run(run())


@pytest.mark.parametrize("raises", [False, True])
def test_image_failed_contract_stays_unchanged(rig, raises):
    def image(**options):
        if raises:
            raise RuntimeError("synthetic-private diagnostic")
        return SimpleNamespace(ok=False)

    async def run():
        services = await rig.start(with_image_enabled=True, models={"image": image})
        try:
            result = invoke(services, with_image=True)
            assert result["plans"][0]["image"] == {"ok": False, "code": "IMAGE_FAILED"}
            assert result["limit_kinds"] == result["limit_detail"] == []
            assert not result["limit_hit"]
        finally:
            await services.close()

    asyncio.run(run())
