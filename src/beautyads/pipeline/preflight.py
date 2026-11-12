"""Bounded local checks before constructing any live dependencies."""

import socket
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import NamedTuple

from beautyads.obs import CostCapExceeded, check_cap
from beautyads.settings import DEFAULT_ENV_FILE, get_setting


class Problem(NamedTuple):
    code: str


def docker_running() -> bool:
    try:
        result = subprocess.run(
            ["docker", "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def tcp_reachable(host: str, port: int, timeout_s: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


def preflight(
    *,
    environ: Mapping[str, str] | None = None,
    env_file: Path | None = DEFAULT_ENV_FILE,
    ledger_path: Path,
    caps: Mapping[str, float],
    docker_check: Callable[[], bool] = docker_running,
    tcp_check: Callable[[str, int, float], bool] = tcp_reachable,
) -> list[Problem]:
    problems = []
    for name in ("YOUTUBE_API_KEY", "GEMINI_API_KEY", "POSTGRES_PASSWORD"):
        if get_setting(name, environ=environ, env_file=env_file) is None:
            problems.append(Problem(f"ENV_MISSING:{name}"))
    if not docker_check():
        problems.append(Problem("DOCKER_DOWN"))
    value = get_setting(
        "BEAUTYADS_POSTGRES_PORT", "5433", environ=environ, env_file=env_file
    )
    try:
        port = int(value)
        reachable = 1 <= port <= 65535 and tcp_check("127.0.0.1", port, 1.0)
    except (TypeError, ValueError, OSError):
        reachable = False
    if not reachable:
        problems.append(Problem("POSTGRES_UNREACHABLE"))

    ledger_writable = True
    try:
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=ledger_path.parent) as probe:
            probe.write(b"probe")
            probe.flush()
        # A writable parent does not imply an existing ledger can be appended.
        if ledger_path.exists():
            with ledger_path.open("a", encoding="utf-8"):
                pass
    except OSError:
        ledger_writable = False
    try:
        check_cap(ledger_path, "gemini", caps)
    except CostCapExceeded:
        problems.append(Problem("COST_CAP:gemini"))
    except (OSError, UnicodeError):
        ledger_writable = False
    if not ledger_writable:
        problems.append(Problem("LEDGER_NOT_WRITABLE"))
    return problems
