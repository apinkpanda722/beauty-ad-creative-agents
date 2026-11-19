"""Read-only preregistration and code guards for development and final runs."""

import hashlib
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from beautyads.agents import evaluation, planning
from beautyads.domain import evaluation as domain_evaluation
from beautyads.domain import supervisor
from beautyads.eval.evalset import (
    ANSWERS_PATH,
    QUESTIONS_PATH,
    REQUESTS_PATH,
    WORKSPACES_PATH,
    question_set_hash,
    read_jsonl,
    request_set_hash,
    validate_set,
)
from beautyads.eval.p5_compare import preregistration_committed

PREREG_PATH = Path("docs/results/p6_preregistration.md")
PREREG_LINE_FORMAT = "{label}: {value}"
REQUEST_HASH_LABEL = "세트 해시 요청"
QUESTION_HASH_LABEL = "세트 해시 질문"
PLANNING_PROMPT_VERSION_LABEL = "동결 기획 프롬프트 버전"
EVALUATION_PROMPT_VERSION_LABEL = "동결 평가 프롬프트 버전"
MIN_DOMINANT_SHARE_LABEL = "동결 MIN_DOMINANT_SHARE"
THIN_POOL_MAX_LABEL = "동결 THIN_POOL_MAX"
PASS_MIN_SCORE_LABEL = "동결 PASS_MIN_SCORE"
PLANNING_SYSTEM_HASH_LABEL = "동결 기획 _SYSTEM sha256"
EVALUATION_SYSTEM_HASH_LABEL = "동결 평가 _SYSTEM sha256"


class FreezeError(Exception):
    """Only fixed guard codes cross the runner boundary."""

    def __init__(
        self,
        code: Literal[
            "PREREG_NOT_COMMITTED",
            "EVALSET_HASH_MISMATCH",
            "FROZEN_VALUE_MISMATCH",
            "WORKSPACE_GROUP_INVALID",
        ],
    ):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class RunIdentity:
    code_commit: str | None
    prereg_commit: str | None
    request_hash: str | None
    question_hash: str | None


def frozen_values() -> dict[str, str]:
    return {
        PLANNING_PROMPT_VERSION_LABEL: str(planning.PLANNING_PROMPT_VERSION),
        EVALUATION_PROMPT_VERSION_LABEL: str(evaluation.EVALUATION_PROMPT_VERSION),
        MIN_DOMINANT_SHARE_LABEL: str(supervisor.MIN_DOMINANT_SHARE),
        THIN_POOL_MAX_LABEL: str(supervisor.THIN_POOL_MAX),
        PASS_MIN_SCORE_LABEL: str(domain_evaluation.PASS_MIN_SCORE),
        PLANNING_SYSTEM_HASH_LABEL: hashlib.sha256(
            planning._SYSTEM.encode("utf-8")
        ).hexdigest(),
        EVALUATION_SYSTEM_HASH_LABEL: hashlib.sha256(
            evaluation._SYSTEM.encode("utf-8")
        ).hexdigest(),
    }


def parse_preregistration(text: str) -> dict[str, str]:
    values = {}
    for line in text.splitlines():
        label, separator, value = line.strip().partition(":")
        if not separator:
            continue
        label, value = label.strip(), value.strip()
        if label in values:
            raise FreezeError("FROZEN_VALUE_MISMATCH")
        values[label] = value
    return values


def _git(args, *, run):
    try:
        result = run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _commit(args, *, run):
    value = _git(args, run=run)
    return value if value and re.fullmatch(r"[a-f0-9]{40,64}", value) else None


def run_identity(
    *,
    prereg_path: Path = PREREG_PATH,
    request_hash: str | None = None,
    question_hash: str | None = None,
    run=subprocess.run,
) -> RunIdentity:
    return RunIdentity(
        code_commit=_commit(["rev-parse", "HEAD"], run=run),
        prereg_commit=_commit(
            ["log", "-1", "--format=%H", "--", str(prereg_path)], run=run
        ),
        request_hash=request_hash,
        question_hash=question_hash,
    )


def check_run(
    *,
    mode,
    groups,
    requests_path: Path = REQUESTS_PATH,
    questions_path: Path = QUESTIONS_PATH,
    answers_path: Path = ANSWERS_PATH,
    extra=None,
    prereg_path: Path = PREREG_PATH,
    committed_fn=preregistration_committed,
    run=subprocess.run,
    workspaces_path: Path = WORKSPACES_PATH,
) -> RunIdentity:
    if mode == "dev":
        if "test" in groups:
            raise FreezeError("WORKSPACE_GROUP_INVALID")
        return run_identity(prereg_path=prereg_path, run=run)
    if mode != "final":
        raise FreezeError("WORKSPACE_GROUP_INVALID")
    try:
        # The shared P5 default must use the same injected git runner. Custom
        # checkers can be path-only callables or partials with their own runner.
        committed = (
            committed_fn(prereg_path, run=run)
            if committed_fn is preregistration_committed
            else committed_fn(prereg_path)
        )
        if not committed or not prereg_path.is_file():
            raise FreezeError("PREREG_NOT_COMMITTED")
        text = prereg_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError, subprocess.TimeoutExpired):
        raise FreezeError("PREREG_NOT_COMMITTED") from None
    values = parse_preregistration(text)
    requests, questions, answers = (
        read_jsonl(path) for path in (requests_path, questions_path, answers_path)
    )
    validate_set(
        requests, questions, answers, final=True, workspaces_path=workspaces_path
    )
    request_hash = request_set_hash(requests)
    question_hash = question_set_hash(questions, answers)
    if (
        values.get(REQUEST_HASH_LABEL) != request_hash
        or values.get(QUESTION_HASH_LABEL) != question_hash
    ):
        raise FreezeError("EVALSET_HASH_MISMATCH")
    # Check both mappings independently; extra cannot override a code value.
    for expected in (frozen_values(), extra or {}):
        if any(values.get(label) != value for label, value in expected.items()):
            raise FreezeError("FROZEN_VALUE_MISMATCH")
    if (
        _git(["status", "--porcelain", "--", "src", "config", "data/evalset"], run=run)
        != ""
    ):
        raise FreezeError("FROZEN_VALUE_MISMATCH")
    identity = run_identity(
        prereg_path=prereg_path,
        request_hash=request_hash,
        question_hash=question_hash,
        run=run,
    )
    if identity.code_commit is None:
        raise FreezeError("FROZEN_VALUE_MISMATCH")
    if identity.prereg_commit is None:
        raise FreezeError("PREREG_NOT_COMMITTED")
    return identity
