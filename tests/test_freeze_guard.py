"""Freeze boundaries use synthetic files and injected, read-only git runners."""

import hashlib
import inspect
import subprocess
from functools import partial
from types import SimpleNamespace

import pytest
from test_evalset import synthetic_set
from test_evalset import workspaces_path as workspace_config  # noqa: F401 -- shared fixture

from beautyads.agents import evaluation, planning
from beautyads.domain import evaluation as domain_evaluation
from beautyads.domain import supervisor
from beautyads.eval import evalset as sets
from beautyads.eval import freeze_guard as guard
from beautyads.eval import p5_compare

CODE_COMMIT = "a" * 40
PREREG_COMMIT = "b" * 40


class FakeGit:
    def __init__(self):
        self.calls = []
        self.prereg_dirty = ""
        self.source_dirty = ""
        self.history = PREREG_COMMIT
        self.code = CODE_COMMIT
        self.returncode = 0

    def __call__(self, args, **options):
        self.calls.append(args)
        assert options == {
            "capture_output": True,
            "text": True,
            "timeout": 5,
            "check": False,
        }
        assert args[0] == "git"
        if args[1:] == ["rev-parse", "HEAD"]:
            value = self.code
        elif args[1] == "log":
            value = self.history
        else:
            assert args[1:4] == ["status", "--porcelain", "--"]
            value = (
                self.source_dirty
                if args[4:] == ["src", "config", "data/evalset"]
                else self.prereg_dirty
            )
        return SimpleNamespace(returncode=self.returncode, stdout=value)


@pytest.fixture
def frozen_run(tmp_path, request):
    config_path = request.getfixturevalue("workspace_config")
    rows = synthetic_set()
    paths = [
        tmp_path / name
        for name in ("requests.jsonl", "questions.jsonl", "answers.jsonl")
    ]
    for path, collection in zip(paths, rows, strict=True):
        sets.write_jsonl(path, collection)
    document = {
        guard.REQUEST_HASH_LABEL: sets.request_set_hash(rows[0]),
        guard.QUESTION_HASH_LABEL: sets.question_set_hash(rows[1], rows[2]),
        **guard.frozen_values(),
        "동결 합성 실행기": "SENTINEL_EXTRA",
    }
    prereg_path = tmp_path / "prereg.md"
    git = FakeGit()
    options = {
        "mode": "final",
        "groups": {"test"},
        "requests_path": paths[0],
        "questions_path": paths[1],
        "answers_path": paths[2],
        "prereg_path": prereg_path,
        "workspaces_path": config_path,
        "extra": {"동결 합성 실행기": "SENTINEL_EXTRA"},
        "run": git,
        "committed_fn": partial(p5_compare.preregistration_committed, run=git),
    }
    checked = []

    def write_document():
        prereg_path.write_text(
            "# Synthetic preregistration\n\n"
            + "\n".join(
                guard.PREREG_LINE_FORMAT.format(label=label, value=value)
                for label, value in document.items()
            ),
            encoding="utf-8",
        )

    def check(**overrides):
        checked.append(True)
        return guard.check_run(**{**options, **overrides})

    write_document()
    yield SimpleNamespace(
        rows=rows,
        paths=paths,
        document=document,
        git=git,
        options=options,
        prereg_path=prereg_path,
        write=write_document,
        check=check,
    )
    assert len(checked) > 0, "Every scenario must invoke the guard"


def assert_error(frozen_run, code, **overrides):
    with pytest.raises(guard.FreezeError) as caught:
        frozen_run.check(**overrides)
    assert caught.value.code == code
    assert str(caught.value) == code
    assert "SENTINEL_" not in str(caught.value)
    assert set(vars(caught.value)) == {"code"}


def test_default_commit_checker_is_the_unchanged_p5_function(frozen_run):
    default = inspect.signature(guard.check_run).parameters["committed_fn"].default
    assert default is p5_compare.preregistration_committed
    assert frozen_run.check(committed_fn=default).code_commit == CODE_COMMIT
    assert frozen_run.git.calls
    assert [
        "git",
        "log",
        "-1",
        "--",
        str(frozen_run.prereg_path),
    ] in frozen_run.git.calls


def test_frozen_values_follow_current_code():
    values = guard.frozen_values()
    assert values == {
        guard.PLANNING_PROMPT_VERSION_LABEL: planning.PLANNING_PROMPT_VERSION,
        guard.EVALUATION_PROMPT_VERSION_LABEL: evaluation.EVALUATION_PROMPT_VERSION,
        guard.MIN_DOMINANT_SHARE_LABEL: str(supervisor.MIN_DOMINANT_SHARE),
        guard.THIN_POOL_MAX_LABEL: str(supervisor.THIN_POOL_MAX),
        guard.PASS_MIN_SCORE_LABEL: str(domain_evaluation.PASS_MIN_SCORE),
        guard.PLANNING_SYSTEM_HASH_LABEL: hashlib.sha256(
            planning._SYSTEM.encode("utf-8")
        ).hexdigest(),
        guard.EVALUATION_SYSTEM_HASH_LABEL: hashlib.sha256(
            evaluation._SYSTEM.encode("utf-8")
        ).hexdigest(),
    }


def test_parse_lines_and_reject_duplicates():
    label = guard.REQUEST_HASH_LABEL
    assert guard.parse_preregistration(
        f"# Title\n  {label}: SENTINEL_HASH  \nOther: value: detail\n"
    ) == {
        label: "SENTINEL_HASH",
        "Other": "value: detail",
    }
    with pytest.raises(guard.FreezeError, match="^FROZEN_VALUE_MISMATCH$"):
        guard.parse_preregistration(f"{label}: SENTINEL_ONE\n {label}: SENTINEL_TWO\n")


@pytest.mark.parametrize("value", ["", "SENTINEL_DUPLICATE"])
def test_empty_values_do_not_hide_duplicate_labels(value):
    label = guard.QUESTION_HASH_LABEL
    with pytest.raises(guard.FreezeError, match="^FROZEN_VALUE_MISMATCH$"):
        guard.parse_preregistration(f"{label}: SENTINEL_FIRST\n{label}: {value}\n")


@pytest.mark.parametrize(
    "failure",
    [
        "uncommitted",
        "modified",
        "absent",
        "unreadable",
        "bad_encoding",
        "history_missing",
    ],
)
def test_preregistration_must_be_committed_and_readable(frozen_run, failure):
    overrides = {}
    if failure == "uncommitted":
        overrides["committed_fn"] = lambda path: False
    elif failure == "modified":
        frozen_run.git.prereg_dirty = " M SENTINEL_PREREG"
    elif failure == "history_missing":
        frozen_run.git.history = ""
    else:
        frozen_run.prereg_path.unlink()
        if failure == "unreadable":
            frozen_run.prereg_path.mkdir()
        elif failure == "bad_encoding":
            frozen_run.prereg_path.write_bytes(b"\xff")
        overrides["committed_fn"] = lambda path: True
    assert_error(frozen_run, "PREREG_NOT_COMMITTED", **overrides)
    assert not any(call[1] == "rev-parse" for call in frozen_run.git.calls)


@pytest.mark.parametrize("label", [guard.REQUEST_HASH_LABEL, guard.QUESTION_HASH_LABEL])
@pytest.mark.parametrize("missing", [False, True])
def test_set_hash_mismatch_and_missing_line(frozen_run, label, missing):
    if missing:
        frozen_run.document.pop(label)
    else:
        frozen_run.document[label] = "SENTINEL_BAD_HASH"
    frozen_run.write()
    assert_error(frozen_run, "EVALSET_HASH_MISMATCH")


@pytest.mark.parametrize("collection", [0, 1, 2])
def test_actual_set_change_is_detected(frozen_run, collection):
    row = frozen_run.rows[collection][0]
    field, value = [
        ("message", "SENTINEL_CHANGED"),
        ("text", "SENTINEL_CHANGED"),
        ("value", 99),
    ][collection]
    row[field] = value
    sets.write_jsonl(frozen_run.paths[collection], frozen_run.rows[collection])
    assert_error(frozen_run, "EVALSET_HASH_MISMATCH")


@pytest.mark.parametrize(
    "label",
    [
        guard.PLANNING_PROMPT_VERSION_LABEL,
        guard.EVALUATION_PROMPT_VERSION_LABEL,
        guard.MIN_DOMINANT_SHARE_LABEL,
        guard.THIN_POOL_MAX_LABEL,
        guard.PASS_MIN_SCORE_LABEL,
        guard.PLANNING_SYSTEM_HASH_LABEL,
        guard.EVALUATION_SYSTEM_HASH_LABEL,
        "동결 합성 실행기",
    ],
)
@pytest.mark.parametrize("missing", [False, True])
def test_each_frozen_value_and_extra_is_required(frozen_run, label, missing):
    if missing:
        frozen_run.document.pop(label)
    else:
        frozen_run.document[label] = "SENTINEL_CHANGED"
    frozen_run.write()
    assert_error(frozen_run, "FROZEN_VALUE_MISMATCH")


def test_extra_cannot_override_code_values(frozen_run):
    label = guard.PLANNING_PROMPT_VERSION_LABEL
    frozen_run.document[label] = "SENTINEL_OVERRIDE"
    frozen_run.write()
    assert_error(
        frozen_run, "FROZEN_VALUE_MISMATCH", extra={label: "SENTINEL_OVERRIDE"}
    )


@pytest.mark.parametrize(
    "status",
    [" M src/SENTINEL.py", "M  config/SENTINEL.yaml", "?? data/evalset/SENTINEL.jsonl"],
)
def test_dirty_frozen_tree_is_rejected(frozen_run, status):
    frozen_run.git.source_dirty = status
    assert_error(frozen_run, "FROZEN_VALUE_MISMATCH")
    assert [
        "git",
        "status",
        "--porcelain",
        "--",
        "src",
        "config",
        "data/evalset",
    ] in frozen_run.git.calls


def test_final_set_validation_precedes_hash_check(frozen_run):
    frozen_run.rows[0][0]["reviewed"] = False
    sets.write_jsonl(frozen_run.paths[0], frozen_run.rows[0])
    with pytest.raises(sets.EvalsetError, match="^EVALSET_NOT_REVIEWED$"):
        frozen_run.check()


def test_all_checks_match_and_return_run_identity(frozen_run):
    identity = frozen_run.check()
    assert isinstance(identity, guard.RunIdentity)
    assert identity.code_commit == CODE_COMMIT
    assert identity.prereg_commit == PREREG_COMMIT
    assert identity.request_hash == frozen_run.document[guard.REQUEST_HASH_LABEL]
    assert identity.question_hash == frozen_run.document[guard.QUESTION_HASH_LABEL]
    assert [
        "git",
        "log",
        "-1",
        "--format=%H",
        "--",
        str(frozen_run.prereg_path),
    ] in frozen_run.git.calls


def test_dev_needs_no_preregistration_or_set(frozen_run):
    frozen_run.prereg_path.unlink()
    for path in frozen_run.paths:
        path.unlink()
    frozen_run.git.history = ""
    identity = frozen_run.check(
        mode="dev",
        groups={"dev"},
        committed_fn=lambda path: pytest.fail("dev prereg check"),
    )
    assert identity.code_commit == CODE_COMMIT
    assert identity.prereg_commit is None
    assert identity.request_hash is identity.question_hash is None
    assert not any(call[1] == "status" for call in frozen_run.git.calls)


@pytest.mark.parametrize("groups", [{"test"}, {"dev", "test"}])
def test_dev_rejects_test_workspaces(frozen_run, groups):
    assert_error(frozen_run, "WORKSPACE_GROUP_INVALID", mode="dev", groups=groups)
    assert frozen_run.git.calls == []


@pytest.mark.parametrize("failure", ["exit", "os", "timeout"])
def test_git_status_failure_is_closed(frozen_run, failure):
    git = frozen_run.git

    def failed(args, **options):
        if args[1:4] == ["status", "--porcelain", "--"]:
            if failure == "exit":
                return SimpleNamespace(returncode=1, stdout="SENTINEL_GIT")
            if failure == "os":
                raise OSError("SENTINEL_GIT")
            raise subprocess.TimeoutExpired(args, 5)
        return git(args, **options)

    assert_error(
        frozen_run, "FROZEN_VALUE_MISMATCH", committed_fn=lambda path: True, run=failed
    )


def test_error_code_set_is_exact_and_messages_are_safe(frozen_run):
    observed = set()
    scenarios = [
        ("PREREG_NOT_COMMITTED", {"committed_fn": lambda path: False}),
        ("WORKSPACE_GROUP_INVALID", {"mode": "dev", "groups": {"test"}}),
        ("EVALSET_HASH_MISMATCH", {}),
        ("FROZEN_VALUE_MISMATCH", {}),
    ]
    for expected, options in scenarios:
        if expected == "EVALSET_HASH_MISMATCH":
            frozen_run.document[guard.REQUEST_HASH_LABEL] = "SENTINEL_HASH"
        elif expected == "FROZEN_VALUE_MISMATCH":
            frozen_run.document[guard.REQUEST_HASH_LABEL] = sets.request_set_hash(
                frozen_run.rows[0]
            )
            frozen_run.document[guard.PLANNING_SYSTEM_HASH_LABEL] = "SENTINEL_SYSTEM"
        frozen_run.write()
        with pytest.raises(guard.FreezeError) as caught:
            frozen_run.check(**options)
        assert str(caught.value) == expected
        observed.add(caught.value.code)
    assert len(scenarios) > 0
    assert observed == {
        "PREREG_NOT_COMMITTED",
        "EVALSET_HASH_MISMATCH",
        "FROZEN_VALUE_MISMATCH",
        "WORKSPACE_GROUP_INVALID",
    }
