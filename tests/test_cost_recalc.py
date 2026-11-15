"""Read-only cost reports use synthetic ledgers, never repository data."""

import ast
import json
from io import StringIO
from pathlib import Path
from unittest.mock import Mock

import pytest

from beautyads.eval import cost_recalc as recalc
from beautyads.obs.ledger import read_entries
from beautyads.settings import Settings


def entry(purpose, cost, tokens=2000, **extra):
    return {
        "ts": "2026-11-13T00:00:00Z",
        "provider": "gemini",
        "model": "synthetic",
        "purpose": purpose,
        "input_tokens": tokens,
        "cost_usd": cost,
        "cost_source": "response_cost",
        **extra,
    }


def pilot_rows():
    # Two items, one product: one short call and three segment calls per tag.
    return [
        entry("pilot-minimal", 0.1, 1000, output_tokens=10, thought_tokens=0),
        entry("pilot-minimal", 0.2, 2000, output_tokens=20, thought_tokens=20),
        entry("pilot-minimal", 0.4, 3000, output_tokens=30, thought_tokens=40),
        entry("pilot-minimal", 0.6, 4000, output_tokens=40, thought_tokens=60),
        entry("pilot-default", 0.2, 500, cached_tokens=100),
        entry("pilot-default", 0.4),
        entry("pilot-default", 0.8),
        entry("pilot-default-retry", 1.2, cost_source="computed"),
    ]


def ledger(tmp_path, rows=None):
    path = tmp_path / "synthetic.jsonl"
    path.write_text(
        "".join(
            json.dumps(row) + "\n" for row in (pilot_rows() if rows is None else rows)
        ),
        encoding="utf-8",
    )
    return path


def cli(path, *args):
    out = StringIO()
    code = recalc.main(
        ["--ledger", str(path), "--items", "10", "--pilot-items", "2", *args],
        out=out,
        environ={},
    )
    output = out.getvalue()
    documents = [line for line in output.splitlines() if line.startswith("{")]
    assert len(documents) == 1
    return code, output, json.loads(documents[0])


def test_tag_totals_retry_other_and_provider_filter(tmp_path):
    path = ledger(
        tmp_path,
        [
            *pilot_rows(),
            entry("live-slice-hook", 0.5),
            entry("pilot-minimal-extra", 0.25),
            entry("pilot-default", 9, provider="openai"),
        ],
    )
    reader = read_entries(path)
    assert reader.skipped_lines == 0
    code, output, report = cli(path)
    assert code == 0
    assert report["pilots"]["minimal"]["calls"] == 4
    assert report["pilots"]["default"]["calls"] == 4
    assert report["pilots"]["minimal"]["cost_usd"] == pytest.approx(1.3)
    assert report["pilots"]["default"]["cost_usd"] == pytest.approx(2.6)
    assert report["other"]["calls"] == 2
    assert report["other"]["cost_usd"] == pytest.approx(0.75)
    assert report["budget"]["cumulative_usd"]["value"] == pytest.approx(4.65)
    assert report["pilots"]["default"]["estimated_cost_entries"] == 1
    assert "비용 추정치" in output
    assert report["ratios"]["per_call_default_over_minimal"] == 2
    assert report["ratios"]["per_item_default_over_minimal"] == 2
    assert report["pilots"]["default"]["stats"]["cached_tokens"]["max"] == 100


def test_distributions_are_hand_calculated(tmp_path):
    _, _, report = cli(ledger(tmp_path))
    stats = report["pilots"]["minimal"]["stats"]
    assert stats["input_tokens"] == {
        "mean": 2500,
        "p50": 2500,
        "p90": 3700,
        "max": 4000,
    }
    assert stats["output_tokens"] == {"mean": 25, "p50": 25, "p90": 37, "max": 40}
    assert stats["thought_tokens"] == {"mean": 30, "p50": 30, "p90": 54, "max": 60}
    assert stats["cost_usd"] == pytest.approx(
        {"mean": 0.325, "p50": 0.3, "p90": 0.54, "max": 0.6}
    )
    assert recalc.distribution([7]) == {"mean": 7, "p50": 7, "p90": 7, "max": 7}
    assert recalc.distribution([]) is None


def test_scenarios_use_both_cost_groups_and_label_every_number(tmp_path):
    code, output, report = cli(ledger(tmp_path), "--product-shares", "0,0.5,1")
    assert code == 0
    minimal = report["pilots"]["minimal"]
    assert minimal["split"]["short"]["calls"] == 1  # threshold is inclusive
    assert minimal["split"]["segment"]["calls"] == 3
    assert minimal["split"]["short"]["stats"]["cost_usd"]["mean"] == 0.1
    assert minimal["split"]["segment"]["stats"]["cost_usd"]["p90"] == pytest.approx(
        0.56
    )
    # Segment mean=.4, short mean=.1: 10*.4 + 10*s*(.4+.1).
    assert [s["mean_usd"] for s in minimal["scenarios"]] == pytest.approx([4, 6.5, 9])
    assert [s["p90_usd"] for s in minimal["scenarios"]] == pytest.approx(
        [5.6, 8.9, 12.2]
    )
    assert minimal["pilot_reference"]["product_share"] == 0.5
    assert "가정(미실측)" in output and "측정값" in output
    assert "종류별 측정 없음" in output
    assert "시범 표본이 작다" in output.splitlines()[-1]
    assert (
        "정확한 종류별 비용은 `analyze-target`의 첫 실행에서 측정한다"
        in output.splitlines()[-1]
    )

    def check_basis(value, basis=None):
        if isinstance(value, dict):
            basis = value.get("basis", basis)
            for key, child in value.items():
                if key != "basis":
                    check_basis(child, basis)
        elif isinstance(value, list):
            for child in value:
                check_basis(child, basis)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            assert basis and ("측정값" in basis or "가정" in basis)

    check_basis(report)


def test_pilot_share_is_reference_only(tmp_path):
    path = ledger(tmp_path)
    _, _, first = cli(path)
    # Same observed call costs but a different assumed number of pilot items.
    _, _, second = cli(path, "--pilot-items", "4")
    for tag in ("minimal", "default"):
        assert first["pilots"][tag]["scenarios"] == second["pilots"][tag]["scenarios"]
        assert (
            first["pilots"][tag]["pilot_reference"]
            != second["pilots"][tag]["pilot_reference"]
        )
    # Different sample composition with the same two group means also agrees.
    rows = [row for row in pilot_rows() if row["input_tokens"] <= 1000]
    rows += [
        entry(f"pilot-{tag}", cost)
        for tag, cost in [("minimal", 0.4), ("default", 0.8)]
    ]
    _, _, third = cli(ledger(tmp_path, rows))
    for tag in ("minimal", "default"):
        assert [
            s["mean_usd"] for s in first["pilots"][tag]["scenarios"]
        ] == pytest.approx([s["mean_usd"] for s in third["pilots"][tag]["scenarios"]])


def test_split_mismatch_warns_and_still_estimates(tmp_path):
    code, output, report = cli(ledger(tmp_path), "--hook-input-max", "2000")
    assert code == 0
    assert "COST_KIND_SPLIT_MISMATCH" in output
    assert report["pilots"]["minimal"]["split"]["reliable"] is False
    assert report["pilots"]["minimal"]["scenarios"][0]["mean_usd"] is not None
    assert "분리가 믿을 수 없음" in output


def test_empty_split_does_not_invent_zero_cost(tmp_path):
    code, output, report = cli(ledger(tmp_path), "--hook-input-max", "0")
    assert code == 0 and "COST_KIND_SPLIT_MISMATCH" in output
    assert report["pilots"]["minimal"]["scenarios"][0]["mean_usd"] is None
    assert "계산 불가" in output


def test_caps_compare_cumulative_plus_estimate_and_remain_unchanged(tmp_path):
    path = ledger(tmp_path)
    original = path.read_bytes()
    code, _, report = cli(path, "--product-shares", "0.5,1", "--candidate-cap", "13")
    assert code == 0
    half, full = report["pilots"]["minimal"]["scenarios"]
    assert half["mean_total_usd"] == pytest.approx(10.4)
    assert half["mean_within_current_cap"] is True
    assert half["p90_within_current_cap"] is False  # 3.9 + 8.9 = 12.8
    assert half["p90_within_candidate_cap"] is True
    assert full["mean_within_current_cap"] is False
    assert full["mean_within_candidate_cap"] is True  # 3.9 + 9 = 12.9
    assert path.read_bytes() == original
    assert Settings().provider_caps_usd["gemini"] == 12
    assert Settings().thinking_level == "minimal"


def test_cap_equality_matches_runtime_guard(tmp_path):
    # Cumulative=8, content-only estimate=4, exactly the configured cap of 12.
    path = ledger(tmp_path, [*pilot_rows(), entry("other", 4.1)])
    code, _, report = cli(path, "--product-shares", "0", "--candidate-cap", "12")
    assert code == 0
    scenario = report["pilots"]["minimal"]["scenarios"][0]
    assert scenario["mean_total_usd"] == 12
    assert scenario["mean_within_current_cap"] is False
    assert scenario["mean_within_candidate_cap"] is False


def test_call_and_item_ratios_have_different_denominators(tmp_path):
    path = ledger(tmp_path, [*pilot_rows(), entry("pilot-default-retry", 0.65)])
    code, _, report = cli(path)
    assert code == 0
    assert report["ratios"]["per_call_default_over_minimal"] == pytest.approx(2)
    assert report["ratios"]["per_item_default_over_minimal"] == pytest.approx(2.5)


def test_zero_cost_ratio_is_unknown_not_infinity(tmp_path):
    rows = pilot_rows()
    for row in rows:
        if row["purpose"] == "pilot-minimal":
            row["cost_usd"] = 0
    code, output, report = cli(ledger(tmp_path, rows))
    assert code == 0 and "계산 불가" in output
    assert report["ratios"]["per_call_default_over_minimal"] is None
    assert report["ratios"]["per_item_default_over_minimal"] is None


@pytest.mark.parametrize("shares", ["-0.1", "1.1", "nan", "inf", "", "0.5,", "x"])
def test_bad_shares_are_input_errors(tmp_path, shares):
    code, _, report = cli(ledger(tmp_path), f"--product-shares={shares}")
    assert code == 2 and report["errors"]


@pytest.mark.parametrize(
    "option,value",
    [
        ("--items", "0"),
        ("--items", "-1"),
        ("--pilot-items", "0"),
        ("--hook-input-max", "-1"),
        ("--candidate-cap", "nan"),
        ("--candidate-cap", "-1"),
    ],
)
def test_bad_numeric_inputs(tmp_path, option, value):
    assert cli(ledger(tmp_path), option, value)[0] == 2


def test_items_required_before_ledger_read(monkeypatch):
    reader = Mock(side_effect=AssertionError("must not read a ledger"))
    monkeypatch.setattr(recalc, "read_entries", reader)
    assert recalc.main([], out=StringIO(), environ={}) == 2
    reader.assert_not_called()


@pytest.mark.parametrize(
    "damage,skipped",
    [("missing", 0), ("directory", 0), ("corrupt", 2), ("encoding", 0)],
)
def test_unreadable_ledgers_fail_closed(tmp_path, damage, skipped):
    path = ledger(tmp_path)
    if damage == "missing":
        path.unlink()
    elif damage == "directory":
        path.unlink()
        path.mkdir()
    elif damage == "corrupt":
        with path.open("a") as stream:
            stream.write('PRIVATE_CONTENT\n{"unknown": true}\n')
    else:
        path.write_bytes(b"\xff")
    code, output, report = cli(path)
    assert code == 2
    assert report["errors"] == ["LEDGER_UNREADABLE"]
    assert report["skipped_lines"]["value"] == skipped
    assert "PRIVATE_CONTENT" not in output


@pytest.mark.parametrize(
    "rows,missing",
    [
        ([], ["minimal", "default"]),
        ([entry("pilot-minimal", 1)], ["default"]),
        ([entry("live-slice-hook", 1)], ["minimal", "default"]),
    ],
)
def test_missing_pilot_tag(tmp_path, rows, missing):
    code, output, report = cli(ledger(tmp_path, rows))
    assert code == 3 and "COST_NO_PILOT_ENTRIES" in output
    assert report["missing_tags"] == missing


def test_measured_axis_costs_and_updated_scenarios(tmp_path):
    rows = [
        *pilot_rows(),
        entry("analyze-target-content_type", 0.3, thought_tokens=10),
        entry("analyze-target-hook", 0.1, 500),
        entry("analyze-target-full", 0.9, thought_tokens=30),
        entry("analyze-target-full", 1.1, thought_tokens=50),
    ]
    code, output, report = cli(ledger(tmp_path, rows), "--product-shares", "0.5")
    assert code == 0
    assert report["kinds"]["full"]["calls"] == 2
    assert report["kinds"]["full"]["cost_usd"] == 2
    assert report["kinds"]["full"]["stats"]["thought_tokens"]["mean"] == 40
    assert report["measured_kind_scenarios"][0]["mean_usd"] == pytest.approx(8.5)
    assert "종류별 측정값" in output


def test_settings_without_env_file_and_read_only_imports(tmp_path, monkeypatch):
    path = ledger(tmp_path)
    settings = Settings(ledger_path=path, provider_caps_usd={"gemini": 5})
    loader = Mock(return_value=settings)
    monkeypatch.setattr(recalc, "load_settings", loader)
    import beautyads.settings as settings_module

    monkeypatch.setattr(
        settings_module, "read_env_file", Mock(side_effect=AssertionError("no .env"))
    )
    out = StringIO()
    assert recalc.main(["--items", "10"], out=out, environ={}) == 0
    loader.assert_called_once_with(environ={}, env_file=None)
    monkeypatch.setattr(recalc, "load_settings", settings_module.load_settings)
    out = StringIO()
    assert (
        recalc.main(
            ["--items", "10"],
            out=out,
            environ={
                "BEAUTYADS_LEDGER_PATH": str(path),
                "BEAUTYADS_CAP_GEMINI_USD": "5",
            },
        )
        == 0
    )
    document = next(
        line for line in out.getvalue().splitlines() if line.startswith("{")
    )
    assert json.loads(document)["budget"]["current_cap_usd"]["value"] == 5
    tree = ast.parse(Path(recalc.__file__).read_text())
    imports = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    imports.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    assert imports == {
        "argparse",
        "json",
        "sys",
        "collections.abc",
        "math",
        "pathlib",
        "typing",
        "beautyads.obs.ledger",
        "beautyads.settings",
    }
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr
        in {"write_text", "write_bytes", "model_dump_json", "append_entry"}
        for node in ast.walk(tree)
    )


def test_make_target_is_manual_only():
    makefile = (Path(__file__).resolve().parents[1] / "Makefile").read_text()
    assert "cost-recalc" in makefile.splitlines()[0].split()
    assert (
        "cost-recalc:\n\tuv run python -m beautyads.eval.cost_recalc $(ARGS)\n"
        in makefile
    )
    verify = makefile.split("verify:\n", 1)[1].split("\n\n", 1)[0]
    assert "cost-recalc" not in verify
