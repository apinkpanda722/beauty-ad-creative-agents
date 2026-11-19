"""Offline guards for the schemas and messages actually submitted by agents."""

# Source: https://platform.openai.com/docs/guides/structured-outputs
# Retrieved 2026-11-18, as recorded in docs/CONTRACTS.md; the page had no date.
# Only the documented rules requested here are checked:
# (1) object root, no root anyOf; (2) additionalProperties=false on every object,
# all properties required; (3) <=5,000 properties, <=10 nesting levels,
# <=1,000 enum values; (4) no allOf/not/dependentRequired/dependentSchemas/
# if/then/else; (5) local $defs references, including recursive definitions.
# No fine-tuned-model restrictions or inferred keyword restrictions are added.

import ast
import asyncio
from copy import deepcopy
from pathlib import Path

import pytest
from test_evaluation import Support
from test_plan_checks import FakeCerts, FakeEvidence, plan_data
from test_research_agent import CTX, Chat, brief, call, execute, reply, result

from beautyads.agents.evaluation import evaluate_plan
from beautyads.agents.planning import make_plan
from beautyads.agents.skeleton import TOOL_NAME, build_graph
from beautyads.domain.research import ResearchHandoffDraft
from beautyads.llm.structured import (
    StructuredFailure,
    StructuredResult,
    StructuredStats,
)

ROOT = Path(__file__).resolve().parents[1]
GUARDED_MODULES = {
    "eval/e2_scoring.py",
    "eval/single_agent.py",
    "agents/research.py",
    "agents/planning.py",
    "agents/evaluation.py",
    "agents/supervisor.py",
}
FORBIDDEN = {
    "allOf",
    "not",
    "dependentRequired",
    "dependentSchemas",
    "if",
    "then",
    "else",
}


def strict_violations(schema):
    """Return (JSON pointer, reason) pairs, without expanding recursive cycles."""
    errors = []
    properties = enums = 0

    def pointer(value):
        return str(value).replace("~", "~0").replace("/", "~1")

    def children(node, path, *, definitions=True):
        for key in ("properties", "$defs") if definitions else ("properties",):
            for name, child in node.get(key, {}).items():
                yield child, f"{path}/{key}/{pointer(name)}"
        if isinstance(node.get("items"), dict):
            yield node["items"], f"{path}/items"
        for key in ("anyOf", *sorted(FORBIDDEN)):
            value = node.get(key)
            if isinstance(value, list):
                for index, child in enumerate(value):
                    yield child, f"{path}/{key}/{index}"
            elif isinstance(value, dict):
                yield value, f"{path}/{key}"

    def resolve(ref):
        if not isinstance(ref, str) or not ref.startswith("#/$defs/"):
            return None
        target = schema
        for part in ref[2:].split("/"):
            if not isinstance(target, dict):
                return None
            target = target.get(part.replace("~1", "/").replace("~0", "~"))
        return target if isinstance(target, dict) else None

    def walk(node, path):
        nonlocal properties, enums
        if not isinstance(node, dict):
            return
        types = node.get("type")
        if types == "object" or isinstance(types, list) and "object" in types:
            fields = node.get("properties", {})
            properties += len(fields)
            if node.get("additionalProperties") is not False:
                errors.append((path, "additionalProperties must be false"))
            required = node.get("required")
            if not isinstance(required, list) or not set(fields) <= set(required):
                errors.append((path, "all properties must be required"))
        enums += len(node.get("enum", []))
        for keyword in sorted(FORBIDDEN & node.keys()):
            errors.append((f"{path}/{keyword}", "unsupported keyword"))
        if "$ref" in node and resolve(node["$ref"]) is None:
            errors.append((f"{path}/$ref", "$ref must resolve inside $defs"))
        for child, child_path in children(node, path):
            walk(child, child_path)

    def depth(node, path, level=0, active=frozenset()):
        if not isinstance(node, dict):
            return
        types = node.get("type")
        containers = {"object", "array"}
        nested = (
            types in containers
            if isinstance(types, str)
            else bool(containers.intersection(types or []))
        )
        level += int(nested)
        if level > 10:
            errors.append((path, "nesting exceeds 10 levels"))
            return
        ref = node.get("$ref")
        target = resolve(ref)
        if target is not None and ref not in active:
            depth(target, f"{path}/$ref", level, active | {ref})
        for child, child_path in children(node, path, definitions=False):
            depth(child, child_path, level, active)

    if schema.get("type") != "object":
        errors.append(("#", "root must be an object"))
    if "anyOf" in schema:
        errors.append(("#/anyOf", "root must not use anyOf"))
    walk(schema, "#")
    depth(schema, "#")
    for name, definition in schema.get("$defs", {}).items():
        depth(definition, f"#/$defs/{pointer(name)}")
    if properties > 5000:
        errors.append(("#", "total properties exceeds 5000"))
    if enums > 1000:
        errors.append(("#", "total enum values exceeds 1000"))
    return errors


def message_violations(messages):
    """Require contiguous tool replies for all calls, with no orphan replies."""
    errors, pending = [], []
    for index, message in enumerate(messages):
        path = f"#/{index}"
        role = message.get("role")
        if role not in {"system", "user", "assistant", "tool"}:
            errors.append((path, "unsupported role"))
        if pending and role != "tool":
            errors.append((path, "tool replies must immediately follow tool_calls"))
            pending = []
        if role == "tool":
            call_id = message.get("tool_call_id")
            if call_id not in pending:
                errors.append((path, "orphan or mismatched tool reply"))
            else:
                pending.remove(call_id)
        elif role == "assistant":
            pending = [call.get("id") for call in message.get("tool_calls") or []]
    if pending:
        errors.append(("#", "missing tool replies"))
    return errors


def obj(**properties):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def test_research_draft_schema_is_strict():
    assert strict_violations(ResearchHandoffDraft.model_json_schema()) == []


@pytest.mark.parametrize(
    "invalid,path,reason",
    [
        ({"type": "object", "additionalProperties": True}, "#", "additionalProperties"),
        ({"type": "object", "properties": {}}, "#", "additionalProperties"),
        ({**obj(x={"type": "string"}), "required": []}, "#", "required"),
        ({"type": "object", "additionalProperties": False}, "#", "required"),
        ({"anyOf": [obj()]}, "#", "root"),
        ({**obj(), "anyOf": [obj()]}, "#/anyOf", "root"),
        ({"type": "array", "items": obj()}, "#", "root"),
        (
            obj(x={"$ref": "https://example.invalid/schema"}),
            "#/properties/x/$ref",
            "$ref",
        ),
        (obj(x={"$ref": "#/$defs/missing"}), "#/properties/x/$ref", "$ref"),
        (obj(x={"$ref": "#/properties/x"}), "#/properties/x/$ref", "$ref"),
    ],
)
def test_strict_validator_rejects_documented_violations(invalid, path, reason):
    assert any(p == path and reason in r for p, r in strict_violations(invalid))


@pytest.mark.parametrize("keyword", sorted(FORBIDDEN))
def test_strict_validator_rejects_each_unsupported_keyword(keyword):
    assert (f"#/properties/x/{keyword}", "unsupported keyword") in strict_violations(
        obj(x={"type": "string", keyword: {}})
    )


@pytest.mark.parametrize("levels", [10, 11])
def test_strict_validator_depth_boundary(levels):
    schema = obj()
    for _ in range(levels - 1):
        schema = obj(child=schema)
    violations = strict_violations(schema)
    assert bool(violations) == (levels > 10)
    assert all("nesting" in reason for _, reason in violations)


@pytest.mark.parametrize("count", [1000, 1001])
def test_strict_validator_total_enums(count):
    schema = obj(a={"enum": list(range(500))}, b={"enum": list(range(count - 500))})
    assert strict_violations(schema) == (
        [("#", "total enum values exceeds 1000")] if count > 1000 else []
    )


@pytest.mark.parametrize("count", [5000, 5001])
def test_strict_validator_total_properties(count):
    schema = obj(**{f"x{i}": {"type": "string"} for i in range(count - 2)})
    schema["$defs"] = {"extra": obj(a={"type": "string"}, b={"type": "string"})}
    assert strict_violations(schema) == (
        [("#", "total properties exceeds 5000")] if count > 5000 else []
    )


def test_strict_validator_accepts_definitions_recursion_nullable_and_metadata():
    schema = obj(head={"$ref": "#/$defs/node"}, title={"type": ["string", "null"]})
    schema["$defs"] = {
        "node": obj(next={"anyOf": [{"$ref": "#/$defs/node"}, {"type": "null"}]})
    }
    schema["description"] = "allOf is a word here, not a schema keyword"
    schema["properties"]["title"]["minLength"] = 0
    assert strict_violations(schema) == []
    assert strict_violations(obj(**{"if": {"type": "string"}})) == []


def test_strict_validator_checks_referenced_depth_and_nested_objects():
    schema = obj(head={"$ref": "#/$defs/deep"})
    nested = obj()
    for _ in range(9):
        nested = obj(child=nested)
    schema["$defs"] = {"deep": nested}
    assert any("nesting" in reason for _, reason in strict_violations(schema))
    assert (
        "#/properties/x",
        "additionalProperties must be false",
    ) in strict_violations(obj(x={"type": "object", "additionalProperties": True}))


class CaptureStructured:
    def __init__(self, model):
        self.model, self.calls = model, []
        self.stats = StructuredStats()

    def generate(self, spec, **options):
        self.calls.append((spec, deepcopy(options)))
        return StructuredResult(
            False, None, StructuredFailure.SCHEMA_VIOLATION, 1, 0, []
        )


def guard_specs(generators):
    checked = 0
    for generator in generators:
        assert generator.calls, f"No specs captured for {generator.model}"
        for spec, _ in generator.calls:
            assert spec.schema.get("type") == "object"
            if generator.model in {"gpt-6-luna", "gpt-6.1-terra"}:
                assert strict_violations(spec.schema) == [], spec.name
            checked += 1
    assert checked > 0, "No captured specs were validated"
    return checked


def test_actual_agent_specs_are_guarded():
    research = CaptureStructured("gpt-6-luna")
    execute(Chat([reply([call()]), reply()]), lambda *args: result(), research)
    planning = CaptureStructured("gpt-6.1-terra")
    make_plan(
        brief=brief(),
        handoff={},
        profile={},
        feedback=None,
        rework=None,
        structured=planning,
    )
    evaluators = []
    for model in ("claude-haiku-5-5", "claude-sonnet-5-5"):
        scoring = CaptureStructured(model)
        evaluate_plan(
            plan=plan_data(),
            brief=brief(),
            handoff={},
            rules=[],
            evidence_index=FakeEvidence(),
            support=Support(),
            certs=FakeCerts(),
            structured=scoring,
            model=model,
        )
        evaluators.append(scoring)
    assert [g.calls[0][0].name for g in [research, planning, *evaluators]] == [
        "research_handoff",
        "plan",
        "evaluation_scores",
        "evaluation_scores",
    ]
    assert guard_specs([research, planning, *evaluators]) == 4


def test_no_new_structured_spec_module_without_a_guard():
    package = ROOT / "src" / "beautyads"
    found = set()
    for path in package.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {"StructuredSpec"}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                names.update(
                    alias.asname or alias.name
                    for alias in node.names
                    if alias.name == "StructuredSpec"
                )
        if any(
            isinstance(node, ast.Call)
            and (
                isinstance(node.func, ast.Name)
                and node.func.id in names
                or isinstance(node.func, ast.Attribute)
                and node.func.attr == "StructuredSpec"
            )
            for node in ast.walk(tree)
        ):
            found.add(path.relative_to(package).as_posix())
    assert found == GUARDED_MODULES


def test_spec_guard_rejects_empty_capture():
    with pytest.raises(AssertionError, match="No captured specs"):
        guard_specs([])
    with pytest.raises(AssertionError, match="No specs captured"):
        guard_specs([CaptureStructured("gpt-6-luna")])


def assistant_calls(*ids):
    return {"role": "assistant", "tool_calls": [{"id": value} for value in ids]}


def tool_reply(value):
    return {"role": "tool", "tool_call_id": value, "content": "synthetic"}


@pytest.mark.parametrize(
    "messages",
    [
        [assistant_calls("a")],
        [assistant_calls("a"), {"role": "user"}, tool_reply("a")],
        [assistant_calls("a", "b"), tool_reply("a")],
        [assistant_calls("a"), tool_reply("b")],
        [tool_reply("a")],
        [assistant_calls("a"), tool_reply("a"), tool_reply("a")],
        [{"role": "developer", "content": "synthetic"}],
    ],
)
def test_message_validator_rejects_bad_sequences(messages):
    assert message_violations(messages)


def test_message_validator_accepts_all_replies_in_contiguous_block():
    assert (
        message_violations(
            [
                {"role": "system"},
                {"role": "user"},
                assistant_calls("a", "b"),
                tool_reply("b"),
                tool_reply("a"),
                {"role": "assistant"},
            ]
        )
        == []
    )


def guard_messages(calls):
    assert calls, "No captured chat messages were validated"
    for options in calls:
        assert options["messages"]
        assert message_violations(options["messages"]) == []


def test_message_guard_rejects_empty_capture():
    with pytest.raises(AssertionError, match="No captured chat messages"):
        guard_messages([])


def test_actual_research_chat_messages():
    chat = Chat([reply([call(), call()]), reply()])
    execute(chat, lambda *args: result(), CaptureStructured("gpt-6-luna"))
    assert len(chat.calls) == 2
    guard_messages(chat.calls)


def test_actual_skeleton_chat_messages():
    chat = Chat([reply([call(TOOL_NAME)]), reply(text="synthetic")])
    graph = build_graph(
        chat=chat, tool_runner=lambda *args: result(TOOL_NAME), checkpointer=None
    )
    state = {
        "messages": [{"role": "user", "content": "synthetic"}],
        "tenant_id": CTX.tenant_id,
        "thread_id": "synthetic-thread",
        "final_text": "",
        "tool_trace": [],
        "step_count": 0,
        "as_of": CTX.as_of.isoformat(),
        "last_collected_at": None,
    }
    asyncio.run(graph.ainvoke(state, context={"tool_context": CTX}))
    assert len(chat.calls) == 2
    assert any(m.get("tool_calls") for m in chat.calls[1]["messages"])
    guard_messages(chat.calls)


def test_actual_supervisor_specs_are_guarded():
    from beautyads.agents.supervisor import decide
    from beautyads.domain.supervisor import RequestLimits

    generator = CaptureStructured("gpt-6-luna")
    decide("synthetic", as_of=CTX.as_of, structured=generator, limits=RequestLimits())
    assert guard_specs([generator]) == 1


def test_actual_single_agent_specs_are_guarded():
    from test_single_agent import execute_single

    generator = CaptureStructured("gpt-6.1-terra")
    execute_single(Chat([reply([call()]), reply()]), generator)
    assert guard_specs([generator]) == 1
    assert generator.calls[0][0].name == "single_agent_plan"


def test_actual_single_agent_chat_messages():
    from test_single_agent import execute_single

    chat = Chat([reply([call(), call()]), reply()])
    execute_single(chat, CaptureStructured("gpt-6.1-terra"))
    assert len(chat.calls) == 2
    guard_messages(chat.calls)


def test_actual_e2_scoring_specs_are_strict(tmp_path):
    from test_e2_scoring import blind

    from beautyads.eval.e2_scoring import score_plans

    generator = CaptureStructured("claude-sonnet-5-5")
    items, _ = blind(1)
    score_plans(items, structured=generator, ledger_path=tmp_path / "ledger")
    assert generator.calls, "No E2 scoring specs captured"
    checked = 0
    for spec, _ in generator.calls:
        assert spec.name == "e2_scores"
        assert strict_violations(spec.schema) == []
        checked += 1
    assert checked > 0, "No E2 scoring specs validated"
