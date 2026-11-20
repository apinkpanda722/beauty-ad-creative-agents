"""Offline drift checks for the browser's server event contract."""

import ast
import json
import re
from pathlib import Path
from typing import get_args

from beautyads.api.sse import EventName
from beautyads.domain.labels import Claim

ROOT = Path(__file__).resolve().parents[1]


def test_browser_claim_values_match_domain_in_both_directions():
    text = (ROOT / "web/lib/claim.ts").read_text(encoding="utf-8")
    body = re.search(r"export const CLAIM_VALUES = \[(.*?)\] as const", text, re.DOTALL)
    assert body is not None
    values = set(re.findall(r'"([a-z_]+)"', body.group(1)))
    assert values
    assert values == {member.value for member in Claim}


def test_browser_plan_intro_matches_server_plan_branch():
    text = (ROOT / "web/lib/text.ts").read_text(encoding="utf-8")
    intro = re.search(r'export const PLAN_INTRO_TEXT = ("[^"\n]+")', text)
    assert intro is not None
    server = ast.parse(
        (ROOT / "src/beautyads/api/ask_view.py").read_text(encoding="utf-8")
    )
    branches = [
        node
        for node in ast.walk(server)
        if isinstance(node, ast.If) and ast.unparse(node.test) == "kind == 'plan'"
    ]
    assert len(branches) == 1
    strings = [
        node.value
        for statement in branches[0].body
        for node in ast.walk(statement)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    assert strings == [json.loads(intro.group(1))]


def test_next_disables_agent_rule_generation():
    text = (ROOT / "web/next.config.ts").read_text(encoding="utf-8")
    assert re.search(r"^\s*agentRules:\s*false\s*,", text, re.MULTILINE)


def test_server_event_names_match_browser_discriminants():
    types = (ROOT / "web/lib/types.ts").read_text(encoding="utf-8")
    names = set(re.findall(r'event:\s*"([a-z_]+)"', types))
    assert names
    assert names == set(get_args(EventName))


def test_screen_command_names_match_browser_discriminants():
    server = (ROOT / "src/beautyads/api/ask_view.py").read_text(encoding="utf-8")
    types = (ROOT / "web/lib/types.ts").read_text(encoding="utf-8")
    server_names = set(re.findall(r'"kind":\s*"(show_[a-z_]+)"', server))
    browser_names = set(re.findall(r'kind:\s*"(show_[a-z_]+)"', types))
    assert server_names
    assert browser_names
    assert browser_names == server_names


def test_web_dependencies_are_pinned():
    package = json.loads((ROOT / "web/package.json").read_text(encoding="utf-8"))
    for group in ("dependencies", "devDependencies"):
        assert package[group]
        for version in package[group].values():
            assert not any(marker in version for marker in ("^", "~", "latest", "*"))


def test_verify_checks_web_without_installing():
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    verify = text.split("verify:\n", 1)[1].split("\n\n", 1)[0]
    assert "pnpm install" not in verify
    for required in ("WEB_DEPS_MISSING", "pnpm lint", "pnpm typecheck", "pnpm test"):
        assert required in verify


def test_web_lockfile_exists():
    assert (ROOT / "web/pnpm-lock.yaml").is_file()


def test_browser_static_talent_and_cta_keys_match_domain():
    from beautyads.domain.labels import CtaType, Talent

    text = (ROOT / "web/lib/taxonomy.ts").read_text(encoding="utf-8")
    for table, enum in (("TALENT_NAMES", Talent), ("CTA_NAMES", CtaType)):
        body = re.search(rf"export const {table} = \{{(.*?)\}}", text, re.DOTALL)
        assert body is not None
        keys = set(re.findall(r'^\s*([a-z_]+):\s*"', body.group(1), re.MULTILINE))
        assert keys
        assert keys == {member.value for member in enum}


def test_browser_evidence_card_fields_match_server_projection():
    import ast

    server = ast.parse(
        (ROOT / "src/beautyads/api/ask_view.py").read_text(encoding="utf-8")
    )
    fields = next(
        ast.literal_eval(node.value)
        for node in server.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(t, ast.Name) and t.id == "_CARD_FIELDS" for t in node.targets
        )
    )
    text = (ROOT / "web/lib/types.ts").read_text(encoding="utf-8")
    card = re.search(r"export type EvidenceCard = \{(.*?)\};", text, re.DOTALL)
    assert card is not None
    keys = set(re.findall(r"^\s*([a-z_]+):", card.group(1), re.MULTILINE))
    assert keys
    assert keys == set(fields)
