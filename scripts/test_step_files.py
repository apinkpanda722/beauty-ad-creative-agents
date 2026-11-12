"""step 파일의 공통 금지사항 블록은 /harness 양식의 블록을 수정 없이 복사해야 한다.

이 저장소는 첫 phase부터 모든 step 파일이 검사 대상이다(소급 예외가 없다).
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = (ROOT / ".claude/commands/harness.md").read_text()
MATCH = re.search(
    r"<!-- common-block:start -->\n(.*?)\n<!-- common-block:end -->",
    TEMPLATE,
    re.DOTALL,
)


def canonical_block() -> str:
    assert MATCH, "harness.md에 common-block 표식이 없다"
    return MATCH.group(1).strip()


def all_step_files():
    return sorted((ROOT / "phases").glob("*/step*.md"))


def step_files_with_common_block():
    return [p for p in all_step_files() if "## 공통 금지사항" in p.read_text()]


def test_every_step_file_has_the_common_block():
    # 검사 대상에서 조용히 빠지는 step 파일이 없어야 한다(공허한 통과 방지).
    missing = [p for p in all_step_files() if p not in step_files_with_common_block()]
    assert missing == [], f"공통 금지사항 블록이 없는 step 파일: {missing}"


def test_template_block_starts_with_pre_check():
    first = canonical_block().splitlines()[0]
    assert first.startswith("- **선점검**")
    assert "blocked" in first and "두 문장" in first


def test_template_block_covers_four_rules():
    block = canonical_block()
    for marker in ("**실제 서비스**", "**계층 경계**", "**읽기 전용**", "**비밀 값**"):
        assert marker in block


def test_step_files_copy_the_common_block_verbatim():
    for path in step_files_with_common_block():
        text = path.read_text()
        assert canonical_block() in text, f"{path}: 공통 금지사항 블록이 수정됐다"
        # 제목 바로 아래에 블록이 있고, 선점검이 그 맨 앞 항목이다.
        section = text.split("## 공통 금지사항", 1)[1].lstrip()
        assert section.startswith("<!-- common-block:start -->"), path
        assert canonical_block().splitlines()[0] in section.splitlines()[1], path


# ---- 형식 v2 기계 검사(열람 금지·실행 금지 대상·수정 허용 경로·소비자 테스트 경고) ----

import sys  # noqa: E402
import warnings  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import step_file_checks as checks  # noqa: E402


def v2_step_files():
    return [
        p
        for p in step_files_with_common_block()
        if checks.format_required(p.parent.name)
    ]


def make_step(
    *,
    forbidden="(없음)",
    allowed="`src/app/x.py`",
    reading="- `/docs/ADR.md`",
    para="**수정할 파일**(이 목록이 전부다): `src/app/x.py`(신규).",
    ac="make verify",
    bans="- 아무것도 하지 마라.",
    scope="",
):
    return f"""# Step 0: sample

## 읽어야 할 파일

{reading}

## 작업

{para}

열람 금지 경로: {forbidden}
수정 허용 경로: {allowed}
{scope}
본문.

## Acceptance Criteria

```bash
{ac}   # 설명
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.

## 이 step의 금지사항

{bans}
"""


def test_format_v2_is_required_for_every_phase():
    assert checks.format_required("any-phase")
    assert checks.scope_required("any-phase")
    assert v2_step_files() == step_files_with_common_block()


def test_every_v2_step_file_has_machine_lines_and_passes_all_checks():
    for path in v2_step_files():
        text = path.read_text()
        for name in (
            "format_violations",
            "read_list_violations",
            "command_violations",
            "declared_path_violations",
        ):
            assert getattr(checks, name)(text) == [], f"{path}: {name}"


def test_every_v2_step_file_has_the_scope_paragraph():
    for path in v2_step_files():
        problems = checks.scope_paragraph_violations(path.read_text())
        assert problems == [], f"{path}: {problems}"


def test_consumer_test_warnings_are_reported_but_do_not_fail():
    for path in v2_step_files():
        for warning in checks.consumer_warnings(path.read_text()):
            warnings.warn(f"{path.parent.name}/{path.name}: {warning}", stacklevel=1)


def test_format_requires_both_machine_lines():
    assert checks.format_violations("## 작업\n\n본문\n")
    assert checks.machine_lines(make_step()) == {
        "forbidden": [],
        "allowed": ["src/app/x.py"],
    }


def test_read_list_inside_forbidden_path_fails():
    text = make_step(
        forbidden="`src/app/guardrails/rules_v1.json`, `data/eval/`",
        reading="- `/data/eval/meta.json`\n- `/src/app/guardrails/rules_v1.json`",
    )
    problems = checks.read_list_violations(text)
    assert len(problems) == 2


def test_read_list_parent_dir_listing_the_forbidden_name_fails_unless_negated():
    # 프로젝트 B에서 실제로 막힌 형태: 상위 디렉터리와 금지 파일 이름을 함께 지정.
    original = "- `/src/app/guardrails/`(`registry.py`·`injection.py`·`screen.py`·`rules_v1.json`)"
    forbidden = "`src/app/guardrails/rules_v1.json`"
    assert checks.read_list_violations(make_step(forbidden=forbidden, reading=original))
    narrowed = "- `/src/app/guardrails/`(`registry.py`만. `rules_v1.json` 내용은 열람하지 않는다)"
    assert (
        checks.read_list_violations(make_step(forbidden=forbidden, reading=narrowed))
        == []
    )


def test_read_list_unrelated_paths_pass():
    text = make_step(
        forbidden="`data/eval/`",
        reading="- `/docs/ADR.md`, `/src/app/eval/redteam.py`",
    )
    assert checks.read_list_violations(text) == []


def test_command_prohibition_must_name_targets_not_categories():
    category = "- 이 step 안에서 smoke·dev 러너·live 타깃을 실행하지 마라."
    assert any("범주" in p for p in checks.command_violations(make_step(bans=category)))
    make_category = "- 이 step 안에서 `make` 타깃을 실행하지 마라."
    assert checks.command_violations(make_step(bans=make_category))
    glob = "- `make smoke-*`를 실행하지 마라."
    assert any("글롭" in p for p in checks.command_violations(make_step(bans=glob)))
    unnamed = "- 외부 서비스를 실행하지 마라."
    assert any(
        "명시되지" in p for p in checks.command_violations(make_step(bans=unnamed))
    )


def test_command_prohibition_overlapping_the_ac_fails():
    bans = "- `make verify`를 실행하지 마라."
    problems = checks.command_violations(make_step(bans=bans, ac="make verify"))
    assert any("겹친다" in p for p in problems)
    # AC 명령에 인자가 붙어도 겹친다.
    assert checks.command_violations(make_step(bans=bans, ac="make verify -j4"))


def test_command_prohibition_with_explicit_names_passes():
    bans = (
        "- `make smoke-guardrail`·`make eval-run-dev`를 실행하지 마라.\n"
        "- AC의 `make verify`는 이 step에서 실행한다."
    )
    assert checks.command_violations(make_step(bans=bans)) == []


def test_non_execution_bullets_are_not_treated_as_prohibitions():
    bans = "- 병렬 실행은 CPU 경합을 만든다. 시간 단언을 하지 마라."
    assert checks.command_violations(make_step(bans=bans)) == []


def test_declared_paths_must_be_in_the_allowed_line():
    text = make_step(
        para="**수정할 파일**(이 목록이 전부다): `src/app/x.py`, `tests/test_x.py`.",
        allowed="`src/app/x.py`",
    )
    assert checks.declared_path_violations(text) == [
        "수정할 파일 `tests/test_x.py`가 `수정 허용 경로` 줄에 없다"
    ]


def test_modify_targets_skip_negated_parenthesized_glob_and_layer_text():
    paragraph = (
        "**수정할 파일**: `a/x.py`(보조 `b/y.py` 포함), `c/z.py`는 읽기만 한다, "
        "`d/g*.py`, `e/w.py`. 계층: `f/q.py`를 import할 수 없다."
    )
    assert checks.modify_targets(paragraph) == ["a/x.py", "e/w.py"]


def build_repo(tmp_path):
    (tmp_path / "src/app/mocks").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "src/app/mocks/seed.py").write_text(
        "TICKET_FIELDS = 1\n\n\ndef load_tickets():\n    return []\n"
    )
    (tmp_path / "src/app/eval").mkdir()
    (tmp_path / "tests/test_seed.py").write_text(
        "from app.mocks.seed import load_tickets\n"
    )
    (tmp_path / "tests/test_listing.py").write_text(
        "def test_x(tmp_path):\n"
        "    files = list((ROOT / 'src/app/eval').glob('redteam*.py'))\n"
        "    assert len(files) == 2\n"
    )
    (tmp_path / "tests/test_other.py").write_text("assert True\n")
    return tmp_path


def test_consumer_warning_lists_tests_missing_from_the_allowed_line(tmp_path):
    root = build_repo(tmp_path)
    text = make_step(allowed="`src/app/mocks/seed.py`")
    found = checks.consumer_warnings(text, root)
    assert any("tests/test_seed.py" in w for w in found)
    assert not any("test_other.py" in w for w in found)
    covered = make_step(allowed="`src/app/mocks/seed.py`, `tests/test_seed.py`")
    assert checks.consumer_warnings(covered, root) == []


def test_consumer_warning_finds_glob_and_count_tests_for_a_new_file(tmp_path):
    root = build_repo(tmp_path)
    text = make_step(allowed="`src/app/eval/redteam_cards.py`")
    found = checks.consumer_warnings(text, root)
    assert any("tests/test_listing.py" in w and "glob" in w for w in found)


def test_format_required_does_not_depend_on_the_phase_index(tmp_path):
    # phases/index.json이 없어도(첫 phase 설계 전) 필수 판정이 죽지 않는다.
    assert checks.format_required("first-phase", tmp_path)
    assert checks.scope_required("first-phase", tmp_path)


SCOPE = "\n열람 금지의 범위: Codex의 직접 열람만 금지한다. 코드의 런타임 접근은 대상이 아니다.\n"


def test_scope_paragraph_required_when_a_path_is_forbidden():
    text = make_step(forbidden="`data/interim/`")
    assert len(checks.scope_paragraph_violations(text)) == 1
    assert (
        checks.scope_paragraph_violations(
            make_step(forbidden="`data/interim/`", scope=SCOPE)
        )
        == []
    )


def test_scope_paragraph_not_required_when_nothing_is_forbidden():
    assert checks.scope_paragraph_violations(make_step(forbidden="(없음)")) == []


def test_scope_paragraph_must_have_a_body_and_sit_in_the_work_section():
    empty = make_step(forbidden="`data/interim/`", scope="\n열람 금지의 범위:\n")
    assert checks.scope_paragraph_violations(empty)
    outside = (
        make_step(forbidden="`data/interim/`")
        + "\n열람 금지의 범위: 작업 절 밖에 둔 문단이다.\n"
    )
    assert checks.scope_paragraph_violations(outside)
