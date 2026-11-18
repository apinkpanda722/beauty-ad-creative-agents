"""Offline ask SSE, ownership checks, local designs, and real-time ASGI gates."""

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256

import pytest
from fastapi.testclient import TestClient
from test_api_chat import assembly
from test_api_feedback import FeedbackTenants
from test_ask_view import result

from beautyads.api.app import create_app
from beautyads.api.chat_client import parse_sse


class AskTenants(FeedbackTenants):
    def __init__(self):
        super().__init__()
        self.saved = []

    def save_plan(self, tenant, plan):
        self.saved.append((tenant, plan))
        self.plans[tenant, plan.plan_id] = plan


def services(ask=None):
    value = assembly()
    value.tenants = AskTenants()
    value.workspaces = {"demo-a": {"brand": "synthetic"}, "demo-b": {"brand": "other"}}
    value.price_bands = {"demo-a": {"price_min": 1, "price_max": 7}}
    value.ask = ask or (lambda *args, **kwargs: {"kind": "no_evidence"})
    value.hydrate = lambda ids: []
    return value


def post(client, *, tenant="demo-a", **body):
    return client.post(
        "/ask",
        headers={"X-Tenant-Id": tenant} if tenant else {},
        json={"message": "synthetic", **body},
    )


@pytest.mark.parametrize(
    "tenant,body,status,detail",
    [
        (None, {}, 400, "TENANT_CONTEXT_MISSING"),
        ("outside", {}, 403, "TENANT_NOT_ALLOWED"),
        ("demo-a", {"thread_id": "demo-b:thread"}, 403, "TENANT_MISMATCH"),
        ("demo-a", {"tenant_id": "demo-b"}, 422, None),
        ("demo-a", {"as_of": "2026-01-01"}, 422, None),
        ("demo-a", {"price_band": {}}, 422, None),
        ("demo-a", {"with_image": True}, 400, "IMAGE_DISABLED"),
        ("demo-a", {"message": ""}, 422, None),
        ("demo-a", {"message": "a" * 2001}, 422, None),
    ],
)
def test_rejected_before_ask(tenant, body, status, detail):
    calls = []
    initial = services(lambda *a, **kw: calls.append(a))
    with TestClient(create_app(lambda: initial)) as client:
        response = post(client, tenant=tenant, **body)
    assert response.status_code == status and calls == []
    if detail:
        assert response.json()["detail"] == detail


def test_workspace_missing_fails_closed():
    calls = []
    initial = services(lambda *a, **kw: calls.append(a))
    initial.workspaces = {}
    with TestClient(create_app(lambda: initial)) as client:
        response = post(client)
    assert (
        response.status_code == 403 and response.json()["detail"] == "WORKSPACE_MISSING"
    )
    assert calls == []


def test_lifespan_current_services_context_feedback_and_plan_storage():
    calls, built = [], []
    raw = result()

    def ask(message, ctx, profile, feedback, with_image, on_event):
        calls.append((message, ctx, profile, feedback, with_image))
        on_event(
            {
                "event": "step",
                "agent": "supervisor",
                "phase": "start",
                "status": "running",
            }
        )
        on_event(
            {"event": "tool_start", "name": "find_example_creatives", "kind": "lookup"}
        )
        on_event(
            {"event": "step", "agent": "supervisor", "phase": "end", "status": "plan"}
        )
        return raw

    initial = services(ask)

    def assemble():
        built.append(True)
        return initial

    app = create_app(assemble=assemble)
    assert built == []
    with TestClient(app) as client:
        assert built == [True]
        response = post(client)
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["X-Thread-Id"].startswith("demo-a:")
        events = parse_sse(response.text)
        assert {name for name, _ in events} <= {
            "step",
            "tool_start",
            "ui_command",
            "token",
            "error",
        }
        assert [body["phase"] for name, body in events if name == "step"] == [
            "start",
            "end",
        ]
        assert next(body for name, body in events if name == "tool_start") == {
            "name": raw["handoff"]["result_counts"][0]["tool"],
            "kind": "lookup",
        }
        cards = [
            body["data"]
            for name, body in events
            if name == "ui_command" and body["kind"] == "show_plan"
        ]
        tenant, record = initial.tenants.saved[0]
        assert cards[0]["plan_id"] == record.plan_id and len(record.plan_id) == 32
        assert tenant == record.tenant_id == calls[0][1].tenant_id == "demo-a"
        assert record.thread_id == response.headers["X-Thread-Id"]
        assert calls[0][1].price_band.model_dump() == initial.price_bands["demo-a"]
        assert calls[0][1].as_of == initial.as_of
        assert (
            calls[0][2] == initial.workspaces["demo-a"]
            and calls[0][3]["approved"]["count"] == 0
        )
        assert calls[0][4] is False
        assert "private" not in json.dumps(record.payload)
        app.state.assembly.ask = lambda *a, **kw: {"kind": "out_of_scope"}
        app.state.assembly.hydrate = lambda ids: pytest.fail(
            "out-of-scope has no cards"
        )
        assert post(client).status_code == 200 and len(calls) == 1


@pytest.mark.parametrize(
    "code,expected",
    [("SAFE_CODE:1", "SAFE_CODE:1"), ("synthetic private value!", None), (None, None)],
)
def test_error_has_only_class_and_safe_code(code, expected, caplog):
    class SyntheticError(Exception):
        pass

    def ask(*a, **kw):
        exc = SyntheticError("synthetic-private-message")
        exc.code = code
        raise exc

    with TestClient(create_app(lambda: services(ask))) as client:
        response = post(client)
    events = parse_sse(response.text)
    error = {"code": "AGENT_INTERNAL_ERROR", "detail": "SyntheticError"}
    if expected:
        error["error_code"] = expected
    assert events == [("error", error)]
    assert "synthetic-private" not in response.text + caplog.text


def test_design_tenant_scope_bytes_and_no_paths(tmp_path):
    raw = result()
    image = raw["plans"][0]["image"]
    directory = tmp_path / sha256(image["request_key"].encode()).hexdigest()[:16]
    directory.mkdir()
    (directory / "00.png").write_bytes(b"synthetic-png")
    initial = services(lambda *a, **kw: raw)
    initial.design_dir = tmp_path
    with TestClient(create_app(lambda: initial)) as client:
        post(client)
        url = "/design/request/0"
        response = client.get(url, headers={"X-Tenant-Id": "demo-a"})
        assert response.status_code == 200 and response.content == b"synthetic-png"
        assert response.headers["content-type"] == "image/png"
        assert response.headers["cache-control"] == "no-store"
        assert client.get(url).status_code == 400
        for path in (
            url,
            "/design/absent/0",
            "/design/..%2Foutside/0",
            "/design/" + initial.tenants.saved[0][1].plan_id + "/0",
        ):
            assert (
                client.get(path, headers={"X-Tenant-Id": "demo-b"}).status_code == 404
            )
        assert (
            client.get(
                "/design/request/1", headers={"X-Tenant-Id": "demo-a"}
            ).status_code
            == 404
        )
        initial.tenants.plans.clear()
        assert client.get(url, headers={"X-Tenant-Id": "demo-a"}).status_code == 404


def test_realtime_gate_and_concurrent_request_queues():
    # TestClient buffers StreamingResponse. Observe actual ASGI SSE body frames
    # before releasing the worker, so completion-time batching deadlocks/fails.
    gates = {name: threading.Event() for name in ("first", "second")}

    def ask(message, ctx, profile, feedback, with_image, on_event):
        on_event(
            {
                "event": "step",
                "agent": "supervisor",
                "phase": "start",
                "status": message,
            }
        )
        assert gates[message].wait(3), "SSE was buffered until worker completion"
        on_event(
            {"event": "step", "agent": "supervisor", "phase": "end", "status": message}
        )
        return {"kind": "no_evidence"}

    app = create_app(lambda: services(ask))

    async def exercise():
        async with app.router.lifespan_context(app):

            async def request(message):
                frames = []
                received = False

                async def receive():
                    nonlocal received
                    if not received:
                        received = True
                        return {
                            "type": "http.request",
                            "body": json.dumps({"message": message}).encode(),
                            "more_body": False,
                        }
                    await asyncio.Future()

                async def send(frame):
                    if frame["type"] == "http.response.body":
                        frames.append(frame.get("body", b""))
                        if b'"phase": "start"' in frames[-1]:
                            gates[message].set()

                scope = {
                    "type": "http",
                    "asgi": {"version": "3.0", "spec_version": "2.4"},
                    "http_version": "1.1",
                    "method": "POST",
                    "scheme": "http",
                    "path": "/ask",
                    "raw_path": b"/ask",
                    "query_string": b"",
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"x-tenant-id", b"demo-a"),
                    ],
                    "client": ("127.0.0.1", 1),
                    "server": ("test", 80),
                    "root_path": "",
                }
                await asyncio.wait_for(app(scope, receive, send), 5)
                return parse_sse(b"".join(frames).decode())

            outcomes = await asyncio.gather(request("first"), request("second"))
            for message, events in zip(gates, outcomes, strict=True):
                steps = [body for name, body in events if name == "step"]
                assert [body["phase"] for body in steps] == ["start", "end"]
                assert {body["status"] for body in steps} == {message}
                assert not any(name == "error" for name, _ in events)

    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(lambda: asyncio.run(exercise())).result(timeout=8)


@pytest.mark.parametrize("parameter", ["tenant_id", "as_of", "price_band"])
def test_server_context_cannot_be_supplied_in_query(parameter):
    calls = []
    with TestClient(
        create_app(lambda: services(lambda *a, **kw: calls.append(a)))
    ) as client:
        response = client.post(
            f"/ask?{parameter}=synthetic",
            headers={"X-Tenant-Id": "demo-a"},
            json={"message": "synthetic"},
        )
    assert response.status_code == 422 and calls == []


def test_event_callback_failure_and_registry_kind_are_isolated(monkeypatch):
    from beautyads.agents.tools import get_tool
    from beautyads.api import ask as ask_module

    actual = ask_module._event

    def flaky(event):
        if event.get("fail"):
            raise RuntimeError("synthetic-private-callback")
        return actual(event)

    monkeypatch.setattr(ask_module, "_event", flaky)
    names = ["compare_axis_by_category", "find_example_creatives"]

    def ask(*args, on_event, **kwargs):
        on_event({"fail": True})
        on_event(
            {
                "event": "step",
                "agent": "supervisor",
                "phase": "start",
                "status": "running",
                "raw": "synthetic-private",
            }
        )
        for name in names:
            on_event(
                {
                    "event": "tool_start",
                    "name": name,
                    "kind": "wrong",
                    "raw": "synthetic-private",
                }
            )
        on_event({"event": "ui_command", "data": {"raw": "synthetic-private"}})
        on_event(
            {"event": "step", "agent": "supervisor", "phase": "end", "status": "ok"}
        )
        return {
            "kind": "research",
            "handoff": {
                "result_counts": [
                    {"tool": name, "row_count": 3, "shown_count": 3} for name in names
                ]
            },
        }

    with TestClient(create_app(lambda: services(ask))) as client:
        response = post(client)
    events = parse_sse(response.text)
    assert [body for name, body in events if name == "tool_start"] == [
        {"name": tool, "kind": get_tool(tool).kind.value} for tool in names
    ]
    assert [name for name, _ in events] == [
        "step",
        "tool_start",
        "tool_start",
        "step",
        "token",
    ]
    assert "private" not in response.text


def test_every_plan_saved_and_image_enabled_forwarded():
    received = []
    raw = result()
    raw["plans"] = [
        raw["plans"][0],
        {"plan": None, "status": "failed"},
        raw["plans"][0],
    ]

    def ask(*args, **kwargs):
        received.append(args)
        return raw

    initial = services(ask)
    initial.image_enabled = True
    with TestClient(create_app(lambda: initial)) as client:
        response = post(client, with_image=True)
    assert received[0][-1] is True
    assert len(initial.tenants.saved) == 2
    ids = [record.plan_id for _, record in initial.tenants.saved]
    assert len(set(ids)) == 2
    cards = [
        body["data"]
        for name, body in parse_sse(response.text)
        if name == "ui_command" and body["kind"] == "show_plan"
    ]
    assert [card["plan_id"] for card in cards] == ids
    assert all(
        set(record.payload["image"])
        == {"request_key", "index", "mime", "size", "sha256"}
        for _, record in initial.tenants.saved
    )


def test_hydrator_is_resolved_at_request_time():
    raw = result()
    raw["plans"] = []
    initial = services(lambda *a, **kw: raw)
    app = create_app(lambda: initial)
    with TestClient(app) as client:
        first = post(client)
        app.state.assembly.hydrate = lambda ids: [
            {"evidence_id": ids[0], "title": "server-hydrated"}
        ]
        second = post(client)

    def cards(response):
        return next(
            body["data"]
            for name, body in parse_sse(response.text)
            if name == "ui_command" and body["kind"] == "show_evidence_cards"
        )

    assert cards(first)["cards"] == []
    assert cards(second)["cards"][0]["title"] == "server-hydrated"


def test_storage_failure_ends_with_safe_error():
    initial = services(lambda *a, **kw: result())

    def fail(*a):
        raise RuntimeError("synthetic-private-store")

    initial.tenants.save_plan = fail
    with TestClient(create_app(lambda: initial)) as client:
        response = post(client)
    assert parse_sse(response.text) == [
        ("error", {"code": "AGENT_INTERNAL_ERROR", "detail": "RuntimeError"})
    ]
    assert "private" not in response.text


@pytest.mark.parametrize(
    "mime,extension",
    [("image/png", "png"), ("image/jpeg", "jpg"), ("image/webp", "webp")],
)
def test_design_uses_stored_mime_and_rejects_missing_file(tmp_path, mime, extension):
    raw = result()
    raw["plans"][0]["image"]["mime"] = mime
    directory = tmp_path / sha256(b"request").hexdigest()[:16]
    directory.mkdir()
    path = directory / f"00.{extension}"
    path.write_bytes(b"synthetic")
    initial = services(lambda *a, **kw: raw)
    initial.design_dir = tmp_path
    with TestClient(create_app(lambda: initial)) as client:
        post(client)
        response = client.get("/design/request/0", headers={"X-Tenant-Id": "demo-a"})
        assert (
            response.content == b"synthetic"
            and response.headers["content-type"] == mime
        )
        path.unlink()
        assert (
            client.get(
                "/design/request/0", headers={"X-Tenant-Id": "demo-a"}
            ).status_code
            == 404
        )
        assert (
            client.get(
                "/design/request/0", headers={"X-Tenant-Id": "outside"}
            ).status_code
            == 403
        )


def test_design_never_reads_outside_root_even_for_authorized_reference(tmp_path):
    raw = result()
    raw["plans"][0]["image"]["request_key"] = ".."
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"synthetic-private-outside")
    root = tmp_path / "design"
    directory = root / sha256(b"..").hexdigest()[:16]
    directory.mkdir(parents=True)
    (directory / "00.png").symlink_to(outside)
    initial = services(lambda *a, **kw: raw)
    initial.design_dir = root
    with TestClient(create_app(lambda: initial)) as client:
        post(client)
        response = client.get("/design/%2E%2E/0", headers={"X-Tenant-Id": "demo-a"})
        assert response.status_code == 404 and b"private" not in response.content
        response = client.get(
            "/design/..%2Foutside/0", headers={"X-Tenant-Id": "demo-a"}
        )
        assert response.status_code == 404 and b"private" not in response.content
