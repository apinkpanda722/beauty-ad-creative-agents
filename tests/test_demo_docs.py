"""Offline demo contracts: read source files only, never start services."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROMPTS = {
    "test-isntree": (
        "보습을 내세운 세럼 광고 기획안 1안을 만들어 주세요.",
        "진정 효과를 내세운 세럼 광고 기획안 1안을 만들어 주세요.",
        "이 세럼의 광고 기획안 1안을 만들어 주세요.",
    ),
    "test-bojoseon": (
        "자외선 차단을 내세운 선케어 광고 기획안 1안을 만들어 주세요.",
        "모공과 피지 관리를 내세운 선케어 광고 기획안 1안을 만들어 주세요.",
        "이 선세럼 제품의 광고 기획안 1안을 만들어 주세요.",
    ),
}
HEADINGS = (
    "한 줄로 시연 환경 띄우기",
    "시연 구성과 비용",
    "장면별 절차",
    "촬영 안내",
    "촬영 전 점검 목록",
    "리허설 확인",
)


def read(relative):
    return (ROOT / relative).read_text(encoding="utf-8")


def chip_messages(source, workspace):
    binding = re.search(rf'"{re.escape(workspace)}"\s*:\s*(\w+)', source)
    assert binding, f"missing workspace: {workspace}"
    array = re.search(
        rf"const\s+{binding.group(1)}\s*=\s*\[(.*?)\];", source, re.DOTALL
    )
    assert array, f"missing chip array: {workspace}"
    messages = re.findall(r'message:\s*"([^"]+)"', array.group(1))
    assert messages, "B-FP-069: zero checked messages must fail"
    return tuple(messages)


@pytest.mark.parametrize("workspace", PROMPTS)
def test_confirmed_prompts_match_workspace_chips(workspace):
    messages = chip_messages(read("web/lib/examples.ts"), workspace)
    assert messages == PROMPTS[workspace]
    for message in messages:
        assert message in read("DEMO.md")


@pytest.mark.parametrize("source", ["", '"test-isntree": serum, const serum = [];'])
def test_chip_check_rejects_empty_synthetic_input(source):
    with pytest.raises(AssertionError):
        chip_messages(source, "test-isntree")


def test_demo_sections_scenes_and_normal_flow():
    demo = read("DEMO.md")
    headings = re.findall(r"^## (.+)$", demo, re.MULTILINE)
    assert headings == list(HEADINGS)
    assert re.findall(r"^### 장면 (\d+)[ .:]", demo, re.MULTILINE) == list("1234567")
    for forbidden in ("장애 주입", "표식 조회", "격리 검사"):
        assert forbidden not in demo
    rehearsal = demo.split("## 리허설 확인", 1)[1]
    checks = re.findall(r"^- \[ \] (.+)$", rehearsal, re.MULTILINE)
    assert len(checks) == 10
    assert all("결과 기록:" in check for check in checks)
    assert "사용자가 live로" in rehearsal


@pytest.mark.parametrize(
    "relative", ["DEMO.md", "README.md", "docs/portfolio/DETAIL_PAGE.md"]
)
def test_langfuse_claim_is_conditional(relative):
    claims = [line for line in read(relative).splitlines() if "관측했다" in line]
    assert claims, "keep the reviewable, conditional wording"
    assert all("[Langfuse 타임라인 확인 후 사용]" in line for line in claims)


def test_detail_numbers_have_closed_kinds_and_existing_sources():
    detail = read("docs/portfolio/DETAIL_PAGE.md")
    table = detail.split("| 값 | 종류 | 기준일 | 측정 조건 | 출처 |\n", 1)[1]
    rows = []
    for line in table.splitlines()[1:]:
        if not line.startswith("|"):
            break
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        assert len(cells) == 5
        value, kind, date, conditions, source = cells
        assert value and date and conditions
        assert kind in {"측정값", "관측값", "설계 추정"}
        reference = re.search(
            r"`(docs/results/[\w.-]+\.md|src/beautyads/agents/tools\.py)` §([\w.]+)",
            source,
        )
        assert reference, source
        path, section = reference.groups()
        assert (ROOT / path).is_file()
        if path.startswith("docs/results/"):
            assert re.search(
                rf"^##+ {re.escape(section)}[. ]", read(path), re.MULTILINE
            )
        rows.append(cells)
    assert rows, "zero checked numerical rows must fail"
    for forbidden in ("그래프가 벡터", "정답률이 높", "더 낫다"):
        assert forbidden not in detail


def test_demo_target_is_separate_and_keeps_verify_offline():
    makefile = read("Makefile")
    assert "\n.PHONY: demo-up\ndemo-up:\n" in makefile
    verify = makefile.split("verify:\n", 1)[1].split("\n\n", 1)[0]
    assert "demo-up" not in verify
    recipe = makefile.split("\ndemo-up:\n", 1)[1]
    for expected in (
        "$(MAKE) db-up",
        'trap "kill 0" EXIT',
        "BEAUTYADS_GROUP=test",
        "BEAUTYADS_EVAL_MODEL=claude-sonnet-5-5",
        "BEAUTYADS_WITH_IMAGE=1",
        "uv run python -m beautyads.api.main",
        "cd web && pnpm build && pnpm start",
        "& wait",
    ):
        assert expected in recipe


def test_p7_decision_and_actual_problem_entries_exist():
    phases = read("docs/PHASES.md")
    assert re.search(r"^\| 58 \| .*P7.*sonnet.*7a.*7b", phases, re.MULTILINE)
    for item in (
        "show_cost",
        "typescript 6.0.3",
        "eslint 9.39.5",
        "vite 7.3.8",
        "ingestion",
    ):
        assert item in phases
    log = read("docs/TROUBLESHOOTING_LOG.md")
    for title, evidence in (
        (
            "P7 클린 클론의 키 의존 테스트",
            "test_model_contract_cost_summary_and_bytes_never_written",
        ),
        ("P7 웹 의존성 버전 조정", "typescript 7.0.2"),
        ("P7 step 파일의 요구와 금지사항 충돌", "스키마 레이블"),
    ):
        entry = log.split(f"## 2026-11-20 {title}", 1)[1].split("\n## ", 1)[0]
        assert evidence in entry
        for label in ("문제", "원인", "해결", "결과", "근거"):
            assert f"**{label}**:" in entry
