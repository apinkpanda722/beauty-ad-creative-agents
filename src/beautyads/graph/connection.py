"""Neo4j SDK boundary with credential-free public errors."""

from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from neo4j import GraphDatabase
from neo4j.exceptions import AuthError, ConstraintError, ServiceUnavailable

from beautyads.settings import DEFAULT_ENV_FILE, neo4j_password, neo4j_uri


class GraphError(Exception):
    def __init__(self, code: str):
        self.code = code
        message = code
        if code == "NEO4J_AUTH_VOLUME_STALE":
            message += (
                ": 비밀번호는 데이터 볼륨을 처음 만들 때만 적용된다. "
                "원래 비밀번호를 확인하거나 make graph-reset CONFIRM=yes 후 make db-up"
            )
        super().__init__(message)


@contextmanager
def _translate_errors():
    try:
        yield
    except AuthError:
        raise GraphError("NEO4J_AUTH_VOLUME_STALE") from None
    except ServiceUnavailable:
        raise GraphError("NEO4J_UNREACHABLE") from None
    except ConstraintError:
        raise GraphError("NEO4J_CONSTRAINT_VIOLATION") from None


@dataclass(frozen=True)
class GraphResult:
    records: list[dict[str, Any]]
    nodes_created: int
    relationships_created: int


class GraphConnection:
    def __init__(self, driver):
        self.driver = driver

    def run(self, query: str, params: Mapping[str, Any] | None = None) -> GraphResult:
        with _translate_errors():
            result = self.driver.execute_query(
                query, parameters_=dict(params or {}), database_="neo4j"
            )
            counters = result.summary.counters
            return GraphResult(
                [dict(record) for record in result.records],
                counters.nodes_created,
                counters.relationships_created,
            )

    def close(self) -> None:
        with _translate_errors():
            self.driver.close()


def connect_graph(
    *,
    environ: Mapping[str, str] | None = None,
    env_file: Path | None = DEFAULT_ENV_FILE,
    driver_factory: Callable[..., Any] | None = None,
) -> GraphConnection:
    factory = GraphDatabase.driver if driver_factory is None else driver_factory
    driver = None
    with _translate_errors():
        try:
            driver = factory(
                neo4j_uri(environ=environ, env_file=env_file),
                auth=("neo4j", neo4j_password(environ=environ, env_file=env_file)),
                notifications_min_severity="OFF",
            )
            driver.verify_connectivity()
        except Exception:
            if driver is not None:
                driver.close()
            raise
    return GraphConnection(driver)
