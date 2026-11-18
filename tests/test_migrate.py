"""Migration CLI contracts use synthetic settings and injected connections only."""

from io import StringIO
from urllib.parse import urlsplit

import pytest

from beautyads.pipeline import migrate

PASSWORD = "synthetic-migration-password"
HOST = "127.0.0.1"
ENV = {"POSTGRES_PASSWORD": PASSWORD, "BEAUTYADS_POSTGRES_PORT": "6543"}


class Connection:
    def __init__(self):
        self.closes = 0

    def close(self):
        self.closes += 1


def forbidden(*args, **kwargs):
    pytest.fail("unexpected dependency call")


@pytest.fixture
def output(capsys, caplog):
    out = StringIO()
    yield out
    captured = capsys.readouterr()
    text = out.getvalue() + captured.out + captured.err + caplog.text
    for value in (PASSWORD, "postgresql://", HOST):
        assert value not in text


@pytest.mark.parametrize("versions", [[4, 5, 6, 7], []])
def test_success_reports_only_applied_versions_and_closes(versions, output):
    conn = Connection()
    calls = []

    def connect(dsn):
        parsed = urlsplit(dsn)
        assert parsed.password == PASSWORD
        assert parsed.hostname == HOST and parsed.port == 6543
        calls.append("connect")
        return conn

    def apply(connection):
        assert connection is conn and conn.closes == 0
        calls.append("apply")
        return versions

    assert (
        migrate.main(
            [],
            environ=ENV,
            env_file=None,
            out=output,
            connect_fn=connect,
            apply_fn=apply,
        )
        == 0
    )
    assert output.getvalue() == f"MIGRATIONS_APPLIED {versions}\n"
    assert calls == ["connect", "apply"]
    assert conn.closes == 1


@pytest.mark.parametrize("password", [None, "", "   ", "\t\n"])
def test_missing_password_stops_before_connection(password, output):
    environ = {} if password is None else {"POSTGRES_PASSWORD": password}
    assert (
        migrate.main(
            [],
            environ=environ,
            env_file=None,
            out=output,
            connect_fn=forbidden,
            apply_fn=forbidden,
        )
        == 2
    )
    assert output.getvalue() == "PREFLIGHT_FAILED ENV_MISSING:POSTGRES_PASSWORD\n"


@pytest.mark.parametrize("error_type", [RuntimeError, OSError, ValueError])
def test_connection_failure_hides_driver_details(error_type, output):
    def connect(dsn):
        raise error_type(f"synthetic connection failure {PASSWORD} {dsn}")

    assert (
        migrate.main(
            [],
            environ=ENV,
            env_file=None,
            out=output,
            connect_fn=connect,
            apply_fn=forbidden,
        )
        == 2
    )
    assert output.getvalue() == "PREFLIGHT_FAILED POSTGRES_UNREACHABLE\n"
    assert error_type.__name__ not in output.getvalue()


def test_migration_failure_propagates_and_closes(output):
    conn = Connection()
    failure = RuntimeError("synthetic migration failure")

    def apply(connection):
        assert connection is conn
        raise failure

    with pytest.raises(RuntimeError) as caught:
        migrate.main(
            [],
            environ=ENV,
            env_file=None,
            out=output,
            connect_fn=lambda dsn: conn,
            apply_fn=apply,
        )
    assert caught.value is failure
    assert output.getvalue() == ""
    assert conn.closes == 1


def test_settings_can_come_from_synthetic_file(tmp_path, output):
    env_file = tmp_path / "synthetic.env"
    env_file.write_text(f"POSTGRES_PASSWORD={PASSWORD}\n", encoding="utf-8")
    conn = Connection()

    def connect(dsn):
        assert urlsplit(dsn).password == PASSWORD
        return conn

    assert (
        migrate.main(
            [],
            environ={"POSTGRES_PASSWORD": " "},
            env_file=env_file,
            out=output,
            connect_fn=connect,
            apply_fn=lambda connection: [],
        )
        == 0
    )
    assert output.getvalue() == "MIGRATIONS_APPLIED []\n"
    assert conn.closes == 1


def test_default_output_is_stdout(capsys):
    assert (
        migrate.main(
            [], environ={}, env_file=None, connect_fn=forbidden, apply_fn=forbidden
        )
        == 2
    )
    captured = capsys.readouterr()
    assert captured.out == "PREFLIGHT_FAILED ENV_MISSING:POSTGRES_PASSWORD\n"
    assert captured.err == ""


def test_repeated_runs_delegate_idempotence_to_store(output):
    from test_store import FakeConnection, FakeCursor

    from beautyads.store.schema import apply_migrations

    class MigrationConnection(FakeConnection):
        def close(self):
            self.closed = True

    connections = [
        MigrationConnection([FakeCursor(), FakeCursor([(1,), (2,), (3,)])]),
        MigrationConnection([FakeCursor(), FakeCursor([(v,) for v in range(1, 8)])]),
    ]
    pending = iter(connections)
    for _ in range(2):
        assert (
            migrate.main(
                [],
                environ=ENV,
                env_file=None,
                out=output,
                connect_fn=lambda dsn: next(pending),
                apply_fn=apply_migrations,
            )
            == 0
        )
    assert output.getvalue() == (
        "MIGRATIONS_APPLIED [4, 5, 6, 7]\nMIGRATIONS_APPLIED []\n"
    )
    assert all(conn.closed for conn in connections)
