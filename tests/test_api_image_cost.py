"""Image cost survives assembly but never enters the public image reference."""

import asyncio
import json
from types import SimpleNamespace

import pytest
import test_api_assembly
from test_api_assembly import invoke

from beautyads.api import assembly
from beautyads.api.ask_view import build_view

rig = test_api_assembly.rig


@pytest.mark.parametrize("with_image", [False, True])
def test_assembled_image_cost_reaches_cost_command_only(rig, monkeypatch, with_image):
    monkeypatch.setattr(
        assembly,
        "save_design_image",
        lambda outcome, **kwargs: SimpleNamespace(
            mime=outcome.mime, size=outcome.size, sha256=outcome.sha256
        ),
    )
    monkeypatch.setattr(
        assembly,
        "compose_design",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError()),
    )

    async def run():
        services = await rig.start(with_image_enabled=True)
        try:
            result = invoke(services, with_image=with_image)
            view = build_view(result, plan_ids=["synthetic-plan"], hydrate=None)
            cost = next(
                item["data"] for item in view.ui_commands if item["kind"] == "show_cost"
            )
            plan = next(
                item["data"] for item in view.ui_commands if item["kind"] == "show_plan"
            )
            if with_image:
                reference = result["plans"][0]["image"]
                assert reference["ok"] is True
                assert cost["image_cost_usd"] == reference["cost_usd"] == 0.04
                assert type(cost["image_cost_usd"]) is float
                assert list(plan["image"]) == [
                    "request_key",
                    "index",
                    "mime",
                    "size",
                    "sha256",
                ]
                assert "cost_usd" not in plan["image"]
            else:
                assert cost["image_cost_usd"] is None
                assert plan["image"] is None
            json.dumps(view.ui_commands, allow_nan=False)
        finally:
            await services.close()

    asyncio.run(run())
