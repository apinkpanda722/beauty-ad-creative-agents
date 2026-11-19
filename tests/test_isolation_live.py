"""Synthetic isolation measurements; no stored live results or service access."""

import hashlib
import json
import re
from collections import Counter
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_api_chat import Tenants
from test_evalset import workspaces_path as workspace_config  # noqa: F401 -- shared fixture
from test_freeze_guard import frozen_run  # noqa: F401 -- shared synthetic freeze fixture

from beautyads.api import chat_client
from beautyads.api.app import Assembly, create_app
from beautyads.domain.tenant import TenantMismatch
from beautyads.eval import isolation_live as iso
from beautyads.eval.evalset import request_set_hash
from beautyads.eval.freeze_guard import FreezeError, RunIdentity
from beautyads.settings import Settings
from beautyads.sources.workspaces import load_workspaces

NOW = datetime(2026, 11, 19, tzinfo=UTC)
IDENTITY = RunIdentity("a" * 40, "b" * 40, None, None)


class Memory(Tenants):
    def __init__(self):
        super().__init__()
        self.plans, self.feedback = {}, []

    def save_plan(self, tenant, plan):
        assert plan.tenant_id == tenant
        self.plans[tenant, plan.plan_id] = plan

    def get_plan(self, tenant, plan_id):
        return self.plans.get((tenant, plan_id))

    def add_feedback(self, tenant, feedback):
        assert tenant == feedback.tenant_id
        self.feedback.append(feedback)

    def list_feedback(self, tenant, *, limit):
        return [f for f in self.feedback if f.tenant_id == tenant][-limit:]


@pytest.fixture
def rig(tmp_path):
    calls, builds = [], []
    tenants = Memory()
    value = Assembly(
        graph=None,
        tenants=tenants,
        allowed_tenants=frozenset(iso.ISOLATION_TENANTS),
        as_of=NOW.date(),
        last_collected_at=None,
        chat=None,
        tool_runner=None,
        close=lambda: None,
        workspaces={t: {"brand": "synthetic"} for t in iso.ISOLATION_TENANTS},
    )

    def ask(*args, **kwargs):
        calls.append(args)
        return {"kind": "research", "handoff": {"conclusion": "synthetic"}}

    value.ask = ask

    async def assemble(**kwargs):
        builds.append(kwargs)
        return value

    settings = Settings(ledger_path=tmp_path / "costs.jsonl")
    root = tmp_path / "runs"
    state = tmp_path / "setup.json"
    requests = tmp_path / "requests.jsonl"

    def cli(args, **kwargs):
        out = StringIO()
        code = iso.main(
            args,
            out=out,
            settings=settings,
            assemble=assemble,
            check=list,
            root=root,
            setup_path=state,
            requests_path=requests,
            **kwargs,
        )
        return code, out.getvalue()

    return SimpleNamespace(**locals())


def test_request_set_shape_types_hash_and_thread_ownership():
    rows = iso.isolation_request_set()
    assert Counter(r["path"] for r in rows) == dict.fromkeys(iso.PATHS, 50)
    assert len({r["id"] for r in rows}) == 200
    assert {r["tenant_id"] for r in rows} == {iso.ISOLATION_TENANTS[1]}
    for path in iso.PATHS:
        selected = [r for r in rows if r["path"] == path]
        assert sum(r["request_type"] == "normal" for r in selected) == 25
        assert {r["intent"] for r in selected} <= {"plan", "research"}
    thread = [r for r in rows if r["path"] == "thread"]
    assert sum(r["foreign_thread"] for r in thread) == 25
    assert all(r["intent"] == "plan" for r in rows if r["path"] == "feedback_memory")
    assert Counter(r["intent"] for r in rows if r["path"] == "final_response") == {
        "plan": 25,
        "research": 25,
    }
    assert iso.isolation_request_hash() == request_set_hash(rows)
    assert iso.isolation_request_hash() == iso.isolation_request_hash()


def test_workspace_append_only_and_dev_selection():
    path = Path("config/workspaces.yaml")
    data = path.read_bytes()
    original = data.split(b"- tenant_id: iso-alpha", 1)[0]
    # Original four records are frozen byte-for-byte, independently of new profiles.
    assert (
        hashlib.sha256(original).hexdigest()
        == "c2e566e7f7121821c963e7d9222ffa8309077120d727e5d28af4c7d362747815"
    )
    items = load_workspaces(path)
    dev = {w.tenant_id for w in items if w.group == "dev"}
    assert not dev.intersection(iso.ISOLATION_TENANTS)
    selected = [w for w in items if w.group == "isolation"]
    assert {w.tenant_id for w in selected} == set(iso.ISOLATION_TENANTS)
    dev_profiles = [w for w in items if w.group == "dev"]
    for w in selected:
        assert w.forbidden_terms == [iso.MARKERS[w.tenant_id]["forbidden"]]
        assert any(
            w.own_product_url == d.own_product_url and w.tone == d.tone
            for d in dev_profiles
        )
    markers = [m for values in iso.MARKERS.values() for m in values.values()]
    assert len(set(markers)) == 6
    assert all(
        re.fullmatch(r"ISO[AB]-(forbidden|feedback|plan)-[0-9a-f]{8}", m)
        for m in markers
    )
    assert all(a not in b for a in markers for b in markers if a != b)


@pytest.mark.parametrize("obj", [{}, [], [1, None, False]])
def test_empty_scan_fails(obj):
    with pytest.raises(iso.IsolationError, match="SCAN_EMPTY"):
        iso.find_markers(obj, ["SYNTHETIC-MARKER"])


def test_recursive_exact_scan_and_self_exclusion():
    own, other = "SYNTHETIC-OWN", "SYNTHETIC-OTHER"
    obj = {
        "plans": [{"copy": f"before {other} after"}],
        "tool_outputs": [own],
        "other": "synthetic-other",
    }
    assert len(iso.find_markers(obj, [other])) == 1
    assert iso.find_markers({"value": own}, [other]) == []
    assert iso.find_markers({"value": "synthetic"}, [other]) == []
    assert iso.find_markers({other: "safe"}, [other])
    assert all(other not in p for p in iso.find_markers(obj, [other]))


@pytest.mark.parametrize(
    "code", ["PREREG_NOT_COMMITTED", "EVALSET_HASH_MISMATCH", "FROZEN_VALUE_MISMATCH"]
)
def test_final_guard_stops_before_connection_or_requests(rig, code):
    seen = []

    def guard(**kwargs):
        seen.append(kwargs)
        raise FreezeError(code)

    status, output = rig.cli(["run", "--final"], guard=guard)
    assert status != 0 and code in output
    assert rig.builds == rig.calls == []
    assert seen[0]["mode"] == "final" and seen[0]["groups"] == {"isolation"}
    assert seen[0]["extra"] == {"격리 요청 세트 해시": iso.isolation_request_hash()}


def test_dry_run_no_connections_no_guard_in_smoke(rig):
    def forbidden(**kwargs):
        pytest.fail("smoke must not consume final guard")

    status, output = rig.cli(["run", "--dry-run", "--smoke", "2"], guard=forbidden)
    assert status == 0 and rig.calls == rig.builds == []
    summary = json.loads(output)
    assert summary["selected"] == 8
    assert summary["groups"] == ["isolation"]


def test_setup_and_positive_control_and_limits(rig):
    status, output = rig.cli(["setup"])
    assert status == 0
    assert len(rig.calls) == 1
    assert iso.positive_control(rig.value, json.loads(rig.state.read_text()))
    assert len(rig.tenants.feedback) == 2 and len(rig.tenants.plans) == 2
    assert (
        request_set_hash([json.loads(x) for x in rig.requests.read_text().splitlines()])
        == iso.isolation_request_hash()
    )
    limits = rig.builds[0]["limits"]
    assert limits.max_plans == 1 and limits.max_reworks == 0
    assert limits.max_text_cost_usd == 0.30
    assert rig.builds[0]["group"] == "isolation"
    assert rig.builds[0]["with_image_enabled"] is False
    assert not any(m in output for v in iso.MARKERS.values() for m in v.values())


@pytest.mark.parametrize("missing", ["all", "feedback", "plan", "thread"])
def test_positive_control_failure_zero_requests(rig, missing):
    if missing != "all":
        assert rig.cli(["setup"])[0] == 0
        if missing == "feedback":
            rig.tenants.feedback.clear()
        elif missing == "plan":
            rig.tenants.plans.clear()
        else:
            rig.tenants.threads.clear()
    rig.calls.clear()
    code, output = rig.cli(["run", "--smoke", "2"])
    assert code != 0 and "SETUP_INCOMPLETE" in output and rig.calls == []


def test_smoke_real_asgi_thread_rejection_and_pair_metrics(rig):
    assert rig.cli(["setup"])[0] == 0
    rig.calls.clear()
    code, output = rig.cli(["run", "--smoke", "50"])
    assert code == 0
    summary = json.loads(output)
    assert summary["status"] == "observed_zero"
    assert len(rig.calls) == 175
    for path in iso.PATHS:
        row = summary["paths"][path]
        assert row["attempted"] == 50 and row["normal_responses"] == 25
        assert row["normal_response_rate"] == 1 and row["exposures"] == 0
        assert len(row["request_types"]) >= 2
    thread = summary["paths"]["thread"]
    assert thread["rejected"] == 25 and thread["rejection_statuses"] == {"403": 25}
    report = list(rig.root.glob("*/summary.json"))
    assert len(report) == 1
    assert rig.cli(["report", "--run-id", report[0].parent.name])[0] == 0


@pytest.mark.parametrize(
    "surface", ["tool_outputs", "plans", "graph_fragment", "events", "feedback"]
)
def test_injected_exposure_report_is_value_free(rig, monkeypatch, surface):
    assert rig.cli(["setup"])[0] == 0
    marker = iso.MARKERS[iso.ISOLATION_TENANTS[0]]["feedback"]
    original = rig.value.ask

    def ask(*args, **kwargs):
        result = original(*args, **kwargs)
        if surface == "events":
            kwargs["on_event"]({"type": "step", "agent": marker, "phase": "start"})
        else:
            result[surface] = {"synthetic": [marker]}
        return result

    rig.value.ask = ask
    if surface == "feedback":
        original_feedback = iso.feedback_for_prompt

        def feedback(repo, tenant, as_of):
            value = original_feedback(repo, tenant, as_of)
            return (
                {**value, "injected": marker}
                if tenant == iso.ISOLATION_TENANTS[1]
                else value
            )

        monkeypatch.setattr(iso, "feedback_for_prompt", feedback)
    code, output = rig.cli(["run", "--smoke", "2"])
    assert code != 0
    summary = json.loads(output)
    assert summary["status"] == "exposure"
    assert summary["원인과 수정"]
    assert any(p["exposures"] for p in summary["paths"].values())
    stored = "".join(p.read_text() for p in rig.root.rglob("*.json"))
    assert marker not in output + stored
    assert summary["findings"] and all(
        {"path", "request_type", "locations"} <= f.keys() for f in summary["findings"]
    )


@pytest.mark.parametrize("tenant", ["dev-mixsoon", "test-isntree"])
def test_smoke_rejects_nonisolation_request_before_connection(rig, monkeypatch, tenant):
    original = iso.isolation_request_set()
    monkeypatch.setattr(
        iso, "isolation_request_set", lambda: [{**original[0], "tenant_id": tenant}]
    )
    code, output = rig.cli(["run"])
    assert code != 0 and "WORKSPACE_GROUP_INVALID" in output
    assert rig.calls == rig.builds == []


def test_foreign_thread_never_reaches_agent(rig):
    rig.tenants.register_thread(iso.ISOLATION_TENANTS[0], "iso-alpha:synthetic")
    with chat_client.TestClient(create_app(lambda: rig.value)) as client:
        response = client.post(
            "/ask",
            headers={"X-Tenant-Id": iso.ISOLATION_TENANTS[1]},
            json={"message": "synthetic", "thread_id": "iso-alpha:synthetic"},
        )
    assert response.status_code == 403 and rig.calls == []
    with pytest.raises(TenantMismatch):
        rig.tenants.assert_thread_access(
            iso.ISOLATION_TENANTS[1], "iso-alpha:synthetic"
        )


@pytest.mark.parametrize("kind", ["budget", "daily", "provider_cap"])
def test_batch_stops_after_swallowed_model_failure(rig, kind):
    from beautyads.llm.errors import ErrorKind, LlmCallError
    from beautyads.obs.ledger import CostCapExceeded, LedgerEntry, append_entry

    assert rig.cli(["setup"])[0] == 0
    rig.calls.clear()
    original = rig.value.ask
    expected = {
        "budget": "BUDGET_REACHED",
        "daily": "DAILY_LIMIT",
        "provider_cap": "COST_CAP_REACHED",
    }[kind]

    def complete(**kwargs):
        if kind == "provider_cap":
            raise CostCapExceeded("openai", 10, 10)
        if kind == "daily":
            raise LlmCallError(
                kind=ErrorKind.DAILY_LIMIT,
                code="SYNTHETIC",
                message="private diagnostic",
            )
        append_entry(
            rig.settings.ledger_path,
            LedgerEntry(
                ts=NOW,
                provider="openai",
                model="synthetic",
                purpose="synthetic",
                cost_usd=0.02,
                cost_source="price_table",
            ),
        )
        return SimpleNamespace(tool_calls=[])

    def ask(*args, **kwargs):
        result = original(*args, **kwargs)
        # Exercise the actual configured wrapper; the API sanitizes exceptions.
        rig.builds[-1]["models"]["chat"](model="synthetic")
        return result

    rig.value.ask = ask
    code, output = rig.cli(
        ["run", "--smoke", "3", "--budget-usd", "0.01"], chat=complete
    )
    assert code != 0
    summary = json.loads(output)
    assert summary["status"] == "incomplete" and summary["stopped"] == expected
    assert len(rig.calls) == 1
    assert "private diagnostic" not in output


@pytest.mark.parametrize("with_error", [True, False])
def test_fake_testclient_scans_full_sse_and_never_persists_text(rig, with_error):
    assert rig.cli(["setup"])[0] == 0
    rig.calls.clear()
    marker = iso.MARKERS[iso.ISOLATION_TENANTS[0]]["plan"]
    requests = []
    marker_json = json.dumps(marker)

    class FakeClient:
        def __init__(self, app):
            app.state.assembly = rig.value

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, *, headers, json):
            requests.append((url, headers, json))
            text = 'event: token\ndata: {"text":"synthetic"}\n\n'
            if with_error:
                text += 'event: error\ndata: {"code":"SYNTHETIC"}\n\n'
            else:
                text += (
                    'event: ui_command\ndata: {"kind":"synthetic","data":{"graph_fragment":'
                    + marker_json
                    + "}}\n\n"
                )
            return SimpleNamespace(status_code=200, text=text)

    code, output = rig.cli(["run", "--smoke", "1"], client_factory=FakeClient)
    summary = json.loads(output)
    assert code != 0
    assert summary["status"] == ("incomplete" if with_error else "exposure")
    assert len(requests) == 4
    assert all(
        url == "/ask"
        and headers == {"X-Tenant-Id": iso.ISOLATION_TENANTS[1]}
        and body["with_image"] is False
        for url, headers, body in requests
    )
    assert summary["paths"]["graph_tool"]["normal_responses"] == int(not with_error)
    assert marker not in output + "".join(
        p.read_text() for p in rig.root.rglob("*.json")
    )


def test_final_success_runs_all_200_and_records_guard_identity(rig):
    assert rig.cli(["setup"])[0] == 0
    rig.calls.clear()
    code, output = rig.cli(
        ["run", "--final", "--smoke", "1"], guard=lambda **kwargs: IDENTITY
    )
    summary = json.loads(output)
    assert code == 0 and summary["selected"] == 200 and summary["final"]
    assert summary["code_commit"] == IDENTITY.code_commit
    assert summary["prereg_commit"] == IDENTITY.prereg_commit
    assert len(rig.calls) == 175


def test_setup_disables_response_trace_persistence(rig):
    import os

    assert rig.cli(["setup"])[0] == 0
    assert rig.builds[0]["trace_path"] == Path(os.devnull)


@pytest.mark.parametrize("field", ["--budget-usd", "--smoke"])
@pytest.mark.parametrize("value", ["0", "-1"])
def test_invalid_limits_are_call_free(rig, field, value):
    code, output = rig.cli(["run", field, value])
    assert code != 0 and "ARGUMENT_ERROR" in output
    assert rig.calls == rig.builds == []


@pytest.mark.parametrize(
    "mutation,expected",
    [
        ("prereg", "PREREG_NOT_COMMITTED"),
        ("set_hash", "EVALSET_HASH_MISMATCH"),
        ("frozen", "FROZEN_VALUE_MISMATCH"),
        ("isolation_hash", "FROZEN_VALUE_MISMATCH"),
    ],
)
def test_real_freeze_guard_consumption_uses_only_synthetic_files(
    rig, request, mutation, expected
):
    from beautyads.eval import freeze_guard

    frozen = request.getfixturevalue("frozen_run")
    frozen.document["격리 요청 세트 해시"] = iso.isolation_request_hash()
    if mutation == "prereg":
        frozen.git.prereg_dirty = " M synthetic"
    elif mutation == "set_hash":
        frozen.document[freeze_guard.REQUEST_HASH_LABEL] = "changed"
    elif mutation == "frozen":
        frozen.document[freeze_guard.MIN_DOMINANT_SHARE_LABEL] = "changed"
    else:
        frozen.document["격리 요청 세트 해시"] = "changed"
    frozen.write()
    status, output = rig.cli(["run", "--final"], guard=frozen.check)
    assert status != 0 and output.strip() == expected
    assert rig.builds == rig.calls == []


def test_own_marker_in_response_is_not_cross_tenant_exposure(rig):
    assert rig.cli(["setup"])[0] == 0
    original = rig.value.ask
    marker = iso.MARKERS[iso.ISOLATION_TENANTS[1]]["plan"]

    def ask(*args, **kwargs):
        result = original(*args, **kwargs)
        result["handoff"]["conclusion"] = marker
        return result

    rig.value.ask = ask
    code, output = rig.cli(["run", "--smoke", "2"])
    assert code == 0 and json.loads(output)["status"] == "observed_zero"
    assert marker not in output + "".join(
        p.read_text() for p in rig.root.rglob("*.json")
    )


def test_one_failed_request_continues_without_exception_text(rig):
    assert rig.cli(["setup"])[0] == 0
    rig.calls.clear()
    original = rig.value.ask

    def ask(*args, **kwargs):
        result = original(*args, **kwargs)
        if len(rig.calls) == 1:
            raise ValueError("SYNTHETIC-PRIVATE-DIAGNOSTIC")
        return result

    rig.value.ask = ask
    code, output = rig.cli(["run", "--smoke", "3"])
    summary = json.loads(output)
    assert code != 0 and summary["status"] == "incomplete"
    assert sum(p["attempted"] for p in summary["paths"].values()) == 12
    assert "SYNTHETIC-PRIVATE-DIAGNOSTIC" not in output


def test_empty_raw_result_stays_a_scan_failure_after_api_sanitization(rig):
    assert rig.cli(["setup"])[0] == 0
    rig.calls.clear()

    def ask(*args, **kwargs):
        rig.calls.append(args)
        return {}

    rig.value.ask = ask
    code, output = rig.cli(["run", "--smoke", "2"])
    assert code != 0 and json.loads(output)["status"] == "incomplete"
    records = json.loads(next(rig.root.glob("*/records.json")).read_text())
    assert any(row["failure"] == "SCAN_EMPTY" for row in records)
