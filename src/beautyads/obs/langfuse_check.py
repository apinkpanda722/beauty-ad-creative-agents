"""User-run synthetic ingestion/readback check. Never run as part of verify."""

import sys
from datetime import UTC, datetime, timedelta
from math import isclose
from time import monotonic, sleep

from langfuse import Langfuse

from beautyads.obs.langfuse_sink import build_timeline, export_trace
from beautyads.obs.trace import TraceRecord
from beautyads.settings import DEFAULT_ENV_FILE, get_setting, langfuse_settings

OBS_REQUIRED_ENV = (
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_INIT_USER_EMAIL",
    "LANGFUSE_INIT_USER_PASSWORD",
    "LANGFUSE_NEXTAUTH_SECRET",
    "LANGFUSE_SALT",
    "LANGFUSE_ENCRYPTION_KEY",
    "LANGFUSE_PG_PASSWORD",
    "LANGFUSE_CLICKHOUSE_PASSWORD",
    "LANGFUSE_REDIS_AUTH",
    "LANGFUSE_MINIO_PASSWORD",
)


def _synthetic_trace() -> TraceRecord:
    start = datetime.now(UTC) - timedelta(seconds=10)
    return TraceRecord(
        tenant_id="obs-check",
        started_at=start,
        duration_ms=10000,
        outcome="ok",
        kind="plan",
        intent="plan",
        message_chars=0,
        cost_total_usd=0.003,
        text_spent_usd=0.003,
        steps=[
            {
                "agent": agent,
                "phase": phase,
                "status": "ok",
                "at": start + timedelta(seconds=offset),
            }
            for agent, phase, offset in [
                ("supervisor", "end", 1),
                ("research", "end", 3),
                ("planning", "start", 4),
                ("evaluation", "end", 8),
            ]
        ],
        calls=[
            {
                "purpose": purpose,
                "model": "synthetic-obs-check",
                "reasoning_effort": "low",
                "input_tokens": 10,
                "output_tokens": 5,
                "cost_usd": cost,
                "cost_source": "computed",
                "duration_ms": duration,
                "ended_at": start + timedelta(seconds=offset),
            }
            for purpose, cost, duration, offset in [
                ("research", 0.001, 1000, 2),
                ("planning", 0.002, 2000, 7),
            ]
        ],
    )


def _as_dict(value):
    return value if isinstance(value, dict) else value.dict(by_alias=True)


def _timestamp(value):
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return value


def _readback_matches(response, expected):
    rows = _as_dict(response).get("observations") or []
    observations = {_as_dict(row).get("id"): _as_dict(row) for row in rows}
    for item in expected:
        row = observations.get(item["id"], {})
        if row.get("type") != item["kind"].upper():
            return False
        if row.get("parentObservationId") != item["parent_id"]:
            return False
        for key, value in (("startTime", item["start"]), ("endTime", item["end"])):
            actual = _timestamp(row.get(key))
            # REST timestamps have millisecond precision.
            if actual is None or abs((actual - value).total_seconds()) >= 0.001:
                return False
        latency = row.get("latency")
        if latency is None or not isclose(
            latency, (item["end"] - item["start"]).total_seconds(), abs_tol=0.002
        ):
            return False
        if item["kind"] == "generation":
            actual = (row.get("costDetails") or {}).get("total")
            if actual is None or not isclose(
                actual, item["attrs"]["cost_details"]["total"], abs_tol=1e-10
            ):
                return False
    return bool(expected)


def main(
    argv=None,
    *,
    environ=None,
    env_file=DEFAULT_ENV_FILE,
    client_factory=Langfuse,
    clock=monotonic,
    sleep_fn=sleep,
) -> int:
    args = sys.argv[1:] if argv is None else argv
    config = {"environ": environ, "env_file": env_file}
    if args == ["preflight"]:
        missing = [
            name for name in OBS_REQUIRED_ENV if get_setting(name, **config) is None
        ]
        for name in missing:
            print(f"PREFLIGHT_FAILED OBS_ENV_MISSING:{name}")
        return 2 if missing else 0
    if args:
        print("OBS_CHECK_FAILED ARGUMENTS")
        return 3
    try:
        settings = langfuse_settings(**config)
        if settings is None:
            print("OBS_CHECK_FAILED SETTINGS_MISSING")
            return 3
        record = _synthetic_trace()
        if not export_trace(record, settings=settings, client_factory=client_factory):
            print("OBS_CHECK_FAILED EXPORT")
            return 3
        client = client_factory(
            public_key=settings.public_key,
            secret_key=settings.secret_key,
            host=settings.host,
            tracing_enabled=False,
            timeout=3,
        )
        expected = build_timeline(record)
        deadline = clock() + 15
        for _ in range(16):
            remaining = deadline - clock()
            if remaining <= 0:
                break
            try:
                response = client.api.trace.get(
                    record.trace_id,
                    request_options={
                        "timeout_in_seconds": min(3, remaining),
                        "max_retries": 0,
                    },
                )
                if _readback_matches(response, expected):
                    for item in expected:
                        print(
                            f"{item['kind']} {item['name']} startTime=ok endTime=ok latency=ok "
                            f"costDetails={'ok' if item['kind'] == 'generation' else 'n/a'} parent=ok"
                        )
                    print(
                        "OBS_CHECK_OK synthetic trace fields verified; confirm timeline in UI"
                    )
                    return 0
            except Exception:  # noqa: BLE001, S110 -- incomplete ingestion and SDK errors contain private diagnostics
                pass
            remaining = deadline - clock()
            if remaining <= 0:
                break
            sleep_fn(min(1, remaining))
    except Exception:  # noqa: BLE001, S110 -- never print configuration or SDK diagnostics
        pass
    print("OBS_CHECK_FAILED READBACK")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
