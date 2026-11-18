"""FP-C16: configured budgets reach fake callers and real offline ledger guards."""

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
import test_api_assembly
from test_api_assembly import invoke, record

from beautyads.api import assembly
from beautyads.eval import live_agent, p5_compare
from beautyads.obs.ledger import CostCapExceeded, check_cap, check_purpose_cap
from beautyads.settings import Settings

ROOT = Path(__file__).resolve().parents[1] / "src" / "beautyads"
rig = test_api_assembly.rig
PROVIDER_LITERAL_FILES = {
    "settings.py",
    "agents/supervisor.py",
    "agents/research.py",
    "agents/planning.py",
    "agents/evaluation.py",
}


@pytest.mark.parametrize(
    "providers,purposes",
    [
        ({"gemini": 20.5, "openai": 20, "anthropic": 16}, {"image": 5.0}),
        ({"gemini": 5, "openai": 1, "anthropic": 1}, {"image": 1.0}),
    ],
)
def test_assembly_passes_configured_copies_to_every_model(
    rig, monkeypatch, providers, purposes
):
    monkeypatch.setattr(assembly, "_DESIGN_DIR", rig.tmp_path / "design")
    settings = Settings(
        ledger_path=rig.settings.ledger_path,
        provider_caps_usd=providers,
        purpose_caps_usd=purposes,
    )

    async def run():
        services = await rig.start(settings=settings, with_image_enabled=True)
        try:
            result = invoke(services, with_image=True)
            assert result["plans"][0]["image"]["ok"]
            assert {name for name, _ in rig.calls} == {
                "chat",
                "supervisor_decision",
                "research_handoff",
                "plan",
                "evaluation_scores",
                "image",
            }
            for name, options in rig.calls:
                assert options["caps"] == providers
                assert options["caps"] is not settings.provider_caps_usd
                if name == "image":
                    assert options["purpose_caps"] == purposes
                    assert options["purpose_caps"] is not settings.purpose_caps_usd
            # Mutating a caller's dictionaries must never mutate Settings.
            rig.calls[-1][1]["caps"]["gemini"] = 0
            rig.calls[-1][1]["purpose_caps"]["image"] = 0
            assert settings.provider_caps_usd == providers
            assert settings.purpose_caps_usd == purposes
        finally:
            await services.close()

    asyncio.run(run())


def test_fp_c16_synthetic_spend_uses_caps_received_by_image(rig):
    raised = Settings(
        ledger_path=rig.settings.ledger_path,
        provider_caps_usd={"gemini": 20.5, "openai": 20, "anthropic": 16},
        purpose_caps_usd={"image": 5},
    )
    record(raised.ledger_path, "analysis", 13.06, "gemini")
    record(raised.ledger_path, "image-plan", 3.6, "gemini")
    received = []

    def image(**options):
        received.append(options)
        return SimpleNamespace(ok=False)

    async def run():
        for settings in (raised, Settings(ledger_path=raised.ledger_path)):
            services = await rig.start(
                settings=settings, with_image_enabled=True, models={"image": image}
            )
            try:
                invoke(services, with_image=True)
            finally:
                await services.close()

    asyncio.run(run())
    assert len(received) == 2
    check_cap(raised.ledger_path, "gemini", received[0]["caps"])
    check_purpose_cap(raised.ledger_path, "image", received[0]["purpose_caps"]["image"])
    with pytest.raises(CostCapExceeded) as provider:
        check_cap(raised.ledger_path, "gemini", received[1]["caps"])
    assert provider.value.total_usd == pytest.approx(16.66)
    assert provider.value.cap_usd == 12
    with pytest.raises(CostCapExceeded) as purpose:
        check_purpose_cap(
            raised.ledger_path, "image", received[1]["purpose_caps"]["image"]
        )
    assert purpose.value.provider == "purpose:image"
    assert purpose.value.total_usd == 3.6 and purpose.value.cap_usd == 3.5


@pytest.mark.parametrize("factor", [0.5, 2])
def test_eval_call_options_follow_settings_and_do_not_alias(tmp_path, factor):
    providers = {
        name: cap * factor for name, cap in Settings().provider_caps_usd.items()
    }
    settings = Settings(ledger_path=tmp_path / "ledger", provider_caps_usd=providers)
    seen = []
    chat = live_agent.budgeted_chat(settings, 1, complete=lambda **kw: seen.append(kw))
    chat(model="gpt-6-luna", messages=[], tools=[])
    runtime = p5_compare._Runtime(
        command="inputs",
        settings=settings,
        environ={},
        env_file=None,
        structured_factory=lambda *args: None,
    )
    options = runtime.options("gpt-6-luna", "none")
    for caps in (seen[0]["caps"], options["caps"]):
        assert caps == providers and caps is not settings.provider_caps_usd
        caps["openai"] = 0
        assert settings.provider_caps_usd == providers


def cap_violations(source, file):
    violations = []
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "min"
            and any(
                "caps" in part.id.lower()
                if isinstance(part, ast.Name)
                else "caps" in part.attr.lower()
                if isinstance(part, ast.Attribute)
                else False
                for arg in [*node.args, *(kw.value for kw in node.keywords)]
                for part in ast.walk(arg)
            )
        ):
            violations.append((file, node.lineno, "MIN_CAPS"))
        if isinstance(node, ast.Dict):
            values = {
                key.value: value.value
                for key, value in zip(node.keys, node.values, strict=True)
                if isinstance(key, ast.Constant)
                and isinstance(value, ast.Constant)
                and type(value.value) in (int, float)
            }
            if set(Settings().provider_caps_usd) <= values.keys() and (
                file not in PROVIDER_LITERAL_FILES
                or values != Settings().provider_caps_usd
            ):
                violations.append((file, node.lineno, "PROVIDER_LITERAL"))
    return violations


def test_all_source_caps_have_one_configuration_source():
    files = sorted(ROOT.rglob("*.py"))
    assert files, "cap guard must inspect Python sources"
    assert [
        violation
        for path in files
        for violation in cap_violations(
            path.read_text(), path.relative_to(ROOT).as_posix()
        )
    ] == []


@pytest.mark.parametrize(
    "source,file,code",
    [
        ("min(caps['gemini'], 12)", "api/new.py", "MIN_CAPS"),
        ("min(12, settings.provider_caps_usd[name])", "eval/new.py", "MIN_CAPS"),
        ("min(HARD_CAPS.values())", "pipeline/new.py", "MIN_CAPS"),
        (
            'caps = {"gemini": 12, "openai": 10, "anthropic": 8}',
            "api/new.py",
            "PROVIDER_LITERAL",
        ),
        (
            'caps = {"gemini": 13, "openai": 10, "anthropic": 8}',
            "agents/planning.py",
            "PROVIDER_LITERAL",
        ),
    ],
)
def test_cap_scan_rejects_synthetic_regressions(source, file, code):
    assert cap_violations(source, file) == [(file, 1, code)]
