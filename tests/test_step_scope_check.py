"""범위 점검은 합성 저장소만 읽으며 경고가 실행을 차단하지 않는다."""

import ast
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import step_scope_check as checks


def put(root, path, source):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8")
    return target


def step(body="", *, allowed="(없음)", review="", new=""):
    return f"""## 설계 검토 기록
{review}

## 작업
열람 금지 경로: (없음)
수정 허용 경로: {allowed}
{new}

{body}
"""


@pytest.mark.parametrize("section", ["work", "review"])
def test_missing_path_must_be_allowed(tmp_path, section):
    body = "새 파일 `scripts/new.py`를 만든다."
    text = step(body) if section == "work" else step(review=body)
    warnings = checks.check_step(text, tmp_path)
    assert len(warnings) == 1
    assert "scripts/new.py" in warnings[0] and "허용" in warnings[0]
    allowed = step(body, allowed="`scripts/`")
    assert checks.check_step(allowed, tmp_path) == []


def test_existing_paths_only_warn_for_actual_modify_targets(tmp_path):
    put(tmp_path, "scripts/old.py", "# existing\n")
    put(tmp_path, "scripts/read.py", "# reference\n")
    text = step(
        "**수정할 파일**: `scripts/old.py` (참고: `scripts/read.py`).\n\n"
        "`scripts/read.py`는 읽기 전용이다."
    )
    warnings = checks.check_step(text, tmp_path)
    assert len(warnings) == 1 and "scripts/old.py" in warnings[0]
    assert checks.check_step(step("`scripts/old.py`는 읽기 전용이다."), tmp_path) == []
    assert checks.check_step(text, tmp_path) == warnings
    assert (
        checks.check_step(
            step("**수정할 파일**: `scripts/old.py`", allowed="`scripts/old.py`"),
            tmp_path,
        )
        == []
    )


def test_machine_scope_and_other_sections_are_not_new_paths(tmp_path):
    text = step("열람 금지의 범위: `data/private/`는 직접 읽지 않는다.")
    text = text.replace("열람 금지 경로: (없음)", "열람 금지 경로: `data/private/`")
    text += "\n## 읽어야 할 파일\n`docs/missing.md`\n"
    assert checks.check_step(text, tmp_path) == []


@pytest.mark.parametrize("coordinate", ["2", "2-4", "2·4"])
def test_valid_coordinate_forms(tmp_path, coordinate):
    put(tmp_path, "src/x.py", "\n" * 4)
    assert checks.check_step(step(f"- `src/x.py:{coordinate}`"), tmp_path) == []


@pytest.mark.parametrize("coordinate", ["0", "5", "2-5", "2·5"])
def test_coordinate_out_of_bounds(tmp_path, coordinate):
    put(tmp_path, "src/x.py", "\n" * 4)
    warnings = checks.check_step(step(f"- `src/x.py:{coordinate}`"), tmp_path)
    assert len(warnings) == 1 and "좌표" in warnings[0]


def test_missing_coordinate_file(tmp_path):
    warnings = checks.check_step(
        step("- `src/missing.py:1`", allowed="`src/missing.py`"), tmp_path
    )
    assert len(warnings) == 1 and "좌표" in warnings[0]


@pytest.mark.parametrize("offset, mismatch", [(0, False), (15, False), (16, True)])
def test_coordinate_identifier_window(tmp_path, offset, mismatch):
    lines = ["# line"] * 50
    lines[19 + offset] = "def known_symbol(): pass"
    put(tmp_path, "src/x.py", "\n".join(lines))
    text = step("- `src/x.py:20`의\n  `known_symbol`을 확인한다.")
    warnings = checks.check_step(text, tmp_path)
    assert bool(warnings) is mismatch
    if mismatch:
        assert len(warnings) == 1 and "좌표 불일치" in warnings[0]


def test_coordinate_checks_all_numbers_and_same_bullet_only(tmp_path):
    lines = ["# line"] * 70
    lines[49] = "known_symbol = 1"
    put(tmp_path, "src/x.py", "\n".join(lines))
    assert checks.check_step(step("- `src/x.py:2·50`의 `known_symbol`"), tmp_path) == []
    assert (
        checks.check_step(
            step("- `src/x.py:2`\n- `known_symbol`은 별도 불릿이다."), tmp_path
        )
        == []
    )


def test_coordinate_identifiers_include_plain_python_names(tmp_path):
    put(tmp_path, "src/x.py", "# no identifier\n" * 40 + "def section(): pass\n")
    warnings = checks.check_step(step("- `src/x.py:2`의 `section`"), tmp_path)
    assert len(warnings) == 1 and "좌표 불일치" in warnings[0]


def test_coordinate_range_includes_its_interior(tmp_path):
    lines = ["# line"] * 80
    lines[39] = "known_symbol = 1"
    put(tmp_path, "src/x.py", "\n".join(lines))
    assert checks.check_step(step("- `src/x.py:2-78`의 `known_symbol`"), tmp_path) == []


@pytest.mark.parametrize("name", ["missing_name", "MissingType", "MISSING_LIMIT"])
def test_unknown_identifiers_and_explicit_new_names(tmp_path, name):
    warnings = checks.check_step(step(f"`{name}`을 확인한다."), tmp_path)
    assert len(warnings) == 1 and "식별자" in warnings[0] and name in warnings[0]
    assert (
        checks.check_step(
            step(f"`{name}`을 만든다.", new=f"새 식별자: `{name}`"), tmp_path
        )
        == []
    )
    # 선언은 작업 절에서만 유효하다.
    assert checks.check_step(step(f"`{name}`", review=f"새 식별자: `{name}`"), tmp_path)


@pytest.mark.parametrize("folder", ["src", "tests", "scripts"])
def test_identifiers_use_word_boundaries_and_all_source_roots(tmp_path, folder):
    put(tmp_path, f"{folder}/x.py", "known_name = 1\n")
    assert checks.check_step(step("`known_name` `plain` `not-a-name`"), tmp_path) == []
    warnings = checks.check_step(step("`known` `known_names`"), tmp_path)
    assert len(warnings) == 1 and "known_names" in warnings[0]


def test_identifier_search_is_not_limited_to_python_files(tmp_path):
    put(tmp_path, "scripts/helper.sh", "echo known_name\n")
    assert checks.check_step(step("`known_name`"), tmp_path) == []


def test_new_names_do_not_hide_other_checks(tmp_path):
    text = step("`src/new.py`와 `new_name`", new="새 식별자: `new_name`")
    warnings = checks.check_step(text, tmp_path)
    assert len(warnings) == 1 and "src/new.py" in warnings[0]


@pytest.mark.parametrize(
    "assignment", ["LIMIT = 2", "LIMIT: int = 2", "OTHER = LIMIT = 2"]
)
def test_module_constants_report_assertion_consumers(tmp_path, assignment):
    put(tmp_path, "src/x.py", assignment + "\n")
    put(tmp_path, "tests/test_x.py", "assert LIMIT == 2\n")
    warnings = checks.check_step(step("`LIMIT`"), tmp_path)
    assert len(warnings) == 1
    assert "상수 단언 1곳" in warnings[0]
    assert "허용 목록 밖: tests/test_x.py:1" in warnings[0]
    assert checks.check_step(step("`LIMIT`", allowed="`tests/`"), tmp_path) == []


@pytest.mark.parametrize(
    "expression",
    ["assert LIMIT", "LIMIT == 2", "LIMIT <= 2", "LIMIT >= 2", "Fraction(LIMIT)"],
)
def test_all_constant_assertion_markers(tmp_path, expression):
    put(tmp_path, "src/x.py", "LIMIT = 2\n")
    put(tmp_path, "tests/test_x.py", expression + "\n")
    assert "상수 단언 1곳" in checks.check_step(step("`LIMIT`"), tmp_path)[0]


def test_only_module_assignments_and_same_line_assertions_count(tmp_path):
    put(tmp_path, "src/x.py", "def f():\n    LOCAL = 1\nLIMIT = 2\n")
    put(tmp_path, "tests/test_x.py", "assert LOCAL == 1\nvalue = LIMIT\nassert value\n")
    assert checks.check_step(step("`LOCAL` `LIMIT`"), tmp_path) == []


def test_constant_locations_are_sorted_and_limited(tmp_path):
    put(tmp_path, "src/x.py", "LIMIT = 2\n")
    put(tmp_path, "tests/test_z.py", "assert LIMIT == 2\n" * 15)
    put(tmp_path, "tests/test_a.py", "assert LIMIT == 2\n")
    warning = checks.check_step(step("`LIMIT`"), tmp_path)[0]
    assert "상수 단언 16곳" in warning
    assert warning.index("tests/test_a.py:1") < warning.index("tests/test_z.py:1")
    assert "tests/test_z.py:11" in warning
    assert "tests/test_z.py:12" not in warning


def test_consumer_warnings_are_preserved_and_can_be_allowed(tmp_path):
    put(tmp_path, "src/app/service.py", "def existing_function(): pass\n")
    put(
        tmp_path, "tests/test_service.py", "from app.service import existing_function\n"
    )
    text = step(allowed="`src/app/service.py`")
    assert checks.check_step(text, tmp_path) == checks.consumer_warnings(text, tmp_path)
    assert len(checks.check_step(text, tmp_path)) == 1
    assert (
        checks.check_step(
            step(allowed="`src/app/service.py`, `tests/test_service.py`"), tmp_path
        )
        == []
    )


def test_five_checks_have_fixed_order(tmp_path):
    put(tmp_path, "src/app/x.py", "LIMIT = 2\n")
    put(tmp_path, "tests/test_x.py", "from app.x import LIMIT\nassert LIMIT == 2\n")
    text = step(
        "`scripts/new.py`\n- `src/app/x.py:99`\n`missing_name` `LIMIT`",
        allowed="`src/app/x.py`",
    )
    warnings = checks.check_step(text, tmp_path)
    assert len(warnings) == 5
    for warning, marker in zip(
        warnings, ["scripts/new.py", "좌표", "식별자", "상수 단언", "←"], strict=True
    ):
        assert marker in warning
    assert checks.check_step(text, tmp_path) == warnings


@pytest.mark.parametrize(
    "kind", ["path", "coordinate", "identifier", "constant", "consumer"]
)
def test_new_identifier_exclusion_preserves_each_other_check(tmp_path, kind):
    put(tmp_path, "src/app/x.py", "LIMIT = 2\n")
    put(tmp_path, "tests/test_x.py", "from app.x import LIMIT\nassert LIMIT == 2\n")
    bodies = {
        "path": "`scripts/new.py`",
        "coordinate": "- `src/app/x.py:99`",
        "identifier": "",
        "constant": "`LIMIT`",
        "consumer": "",
    }
    allowed = "`src/app/x.py`" if kind == "consumer" else "(없음)"
    body = bodies[kind] + "\n\n`future_identifier`를 만든다."
    baseline = checks.check_step(step(bodies[kind], allowed=allowed), tmp_path)
    assert len(baseline) == (0 if kind == "identifier" else 1)
    assert (
        len(checks.check_step(step(body, allowed=allowed), tmp_path))
        == len(baseline) + 1
    )
    assert (
        checks.check_step(
            step(
                body,
                allowed=allowed,
                new="새 식별자: `future_identifier`, `FutureType`",
            ),
            tmp_path,
        )
        == baseline
    )


def test_main_warns_but_returns_zero_and_sorts_input_files(tmp_path):
    first = put(tmp_path, "a.md", step("`missing_name`"))
    second = put(tmp_path, "b.md", step())
    out = io.StringIO()
    argv = [str(second), str(first), "--root", str(tmp_path)]
    assert checks.main(argv, out=out) == 0
    lines = out.getvalue().splitlines()
    assert lines[0].startswith(f"경고 {first}: ")
    assert f"{first}: 경고 1건" in lines[-2]
    assert f"{second}: 경고 0건" in lines[-1]
    other = io.StringIO()
    assert (
        checks.main([str(first), str(second), "--root", str(tmp_path)], out=other) == 0
    )
    assert other.getvalue() == out.getvalue()


def test_main_uses_sys_argv(tmp_path, monkeypatch):
    path = put(tmp_path, "step.md", step())
    monkeypatch.setattr(
        sys, "argv", ["step_scope_check.py", str(path), "--root", str(tmp_path)]
    )
    assert checks.main(out=io.StringIO()) == 0


@pytest.mark.parametrize("args", [[], ["--root"], ["missing.md"], ["--unknown"]])
def test_main_input_errors_return_two(tmp_path, args):
    assert checks.main([*args, "--root", str(tmp_path)], out=io.StringIO()) == 2


def test_main_unreadable_encoding_returns_two(tmp_path):
    path = tmp_path / "bad.md"
    path.write_bytes(b"\xff")
    assert checks.main([str(path)], out=io.StringIO()) == 2


def test_tool_is_read_only_and_standard_library_only():
    tree = ast.parse(Path(checks.__file__).read_text(encoding="utf-8"))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add((node.module or "").split(".")[0])
        elif isinstance(node, ast.Call):
            function = node.func
            name = (
                function.attr
                if isinstance(function, ast.Attribute)
                else getattr(function, "id", "")
            )
            assert name not in {"write_text", "write_bytes"}
            if name == "open":
                mode = node.args[1] if len(node.args) > 1 else None
                mode = next(
                    (kw.value for kw in node.keywords if kw.arg == "mode"), mode
                )
                if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
                    assert not any(flag in mode.value for flag in "wax+")
    assert not imports & {"subprocess", "socket"}
    assert imports <= sys.stdlib_module_names | {"step_file_checks"}
