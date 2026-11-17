"""Tool contracts tested with synthetic records and no service connections."""

import ast
import json
from dataclasses import FrozenInstanceError
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from beautyads.agents.tools import TOOLS, get_tool, run_tool, tool_definitions
from beautyads.domain.labels import Category, Claim
from beautyads.domain.skin import SkinConcern, SkinType
from beautyads.domain.tools import (
    PriceBand,
    ToolContext,
    ToolErrorCode,
    ToolFailure,
    ToolKind,
    ToolResult,
)
from beautyads.graph.connection import GraphConnection, GraphError, GraphResult
from beautyads.graph.queries import QUESTIONS, question_parameters

QUESTION_IDS = {
    "lookup_products_by_efficacy": "CQ-01",
    "lookup_products_by_concern": "CQ-02",
    "lookup_certified_products": "CQ-03",
    "count_claim_supported_ads": "CQ-04",
    "top_claims_of_ingredient_ads": "CQ-05",
    "compare_hooks_by_category": "CQ-06",
    "ad_angles_formats_by_skin_type": "CQ-08",
    "compare_competitor_claims": "CQ-13",
    "unclaimed_efficacy_gaps": "CQ-14",
    "ingredient_ad_trend": "CQ-15",
    "compare_price_band_competitors": "CQ-16",
}
LINKED_QUESTIONS = {
    "CQ-04",
    "CQ-05",
    "CQ-06",
    "CQ-08",
    "CQ-13",
    "CQ-14",
    "CQ-15",
    "CQ-16",
}
DISPLAY_INPUTS = {
    "show_evidence_cards": {"evidence_ids": ["youtube:synthetic-_A"]},
    "show_graph_fragment": {"evidence_ids": ["youtube:synthetic-_A"]},
    "show_distribution": {
        "axis": "hook_type",
        "evidence_ids": ["youtube:synthetic-_A"],
    },
    "show_plan": {"plan_id": "synthetic-plan"},
}


class FakeGraph:
    def __init__(self, records=(), error=None):
        self.records = list(records)
        self.error = error
        self.calls = []

    def run(self, query, params=None):
        self.calls.append((query, params))
        if self.error is not None:
            raise self.error
        return SimpleNamespace(records=self.records)


class ForbiddenGraph:
    def run(self, query, params=None):
        pytest.fail("This tool must not call the graph")


@pytest.fixture
def ctx():
    return ToolContext(
        tenant_id="synthetic-workspace",
        as_of=date(2025, 4, 19),
        last_collected_at=None,
        price_band=PriceBand(price_min=10.0, price_max=25.0),
    )


def valid_inputs(tool):
    values = {
        "category": Category.serum_ampoule.value,
        "claim": Claim.soothing.value,
        "concern": SkinConcern.dryness.value,
        "skin_type": SkinType.dry.value,
    }
    if tool.kind == ToolKind.display:
        return DISPLAY_INPUTS[tool.name]
    return {name: values[name] for name in QUESTIONS[tool.question_id].inputs}


def assert_failure(result, code, *, retryable=False):
    assert isinstance(result, ToolFailure)
    assert result.code == code
    assert result.retryable is retryable
    assert not hasattr(result, "no_evidence")


def test_registry_is_stable_described_and_closed():
    names = [tool.name for tool in TOOLS]
    assert names and names == sorted(set(names))
    assert {tool.kind for tool in TOOLS} == set(ToolKind)
    definitions = tool_definitions()
    assert definitions == tool_definitions()
    assert [definition["name"] for definition in definitions] == names
    forbidden = {"tenant", "user", "date", "today", "time"}
    for tool, definition in zip(TOOLS, definitions, strict=True):
        assert get_tool(tool.name) is tool
        assert tool.description.splitlines()[0].startswith("쓰는 때:")
        assert tool.description.splitlines()[1].startswith("쓰지 않는 때:")
        assert tool.input_model.model_config["extra"] == "forbid"
        assert definition == {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_model.model_json_schema(),
        }
        schema = definition["parameters"]
        assert schema["additionalProperties"] is False
        for name, field in schema.get("properties", {}).items():
            assert field.get("description")
            assert not forbidden.intersection(name.split("_"))
        if tool.kind != ToolKind.display:
            assert tool.question_id == QUESTION_IDS[tool.name]
            assert set(schema["properties"]) == set(QUESTIONS[tool.question_id].inputs)
    assert get_tool("unknown-tool") is None
    with pytest.raises(FrozenInstanceError):
        TOOLS[0].name = "changed"


def test_context_is_frozen_and_top_rows_are_bounded(ctx):
    with pytest.raises(ValidationError):
        ctx.tenant_id = "changed"
    with pytest.raises(ValidationError):
        ToolResult(
            tool="test",
            kind=ToolKind.lookup,
            summary="test",
            top_rows=[{} for _ in range(6)],
            row_count=6,
            evidence_ids=[],
            no_evidence=False,
        )


@pytest.mark.parametrize("tool", TOOLS, ids=lambda tool: tool.name)
@pytest.mark.parametrize("tenant", [None, "", "   "])
def test_tenant_check_precedes_name_arguments_and_graph(tool, tenant, ctx):
    context = None if tenant is None else ctx.model_copy(update={"tenant_id": tenant})
    assert_failure(
        run_tool(tool.name, "not JSON", context, ForbiddenGraph()),
        ToolErrorCode.TENANT_CONTEXT_MISSING,
    )
    assert_failure(
        run_tool("unknown", {}, context, ForbiddenGraph()),
        ToolErrorCode.TENANT_CONTEXT_MISSING,
    )


@pytest.mark.parametrize(
    "arguments",
    [
        {"category": "other", "claim": "soothing"},
        {"category": "serum_ampoule", "claim": "invented"},
        {"category": "serum_ampoule"},
        "{bad JSON",
        "[]",
        "null",
        "42",
    ],
)
def test_invalid_inputs_do_not_query(arguments, ctx):
    assert_failure(
        run_tool("lookup_products_by_efficacy", arguments, ctx, ForbiddenGraph()),
        ToolErrorCode.INPUT_INVALID,
    )


@pytest.mark.parametrize("tool", TOOLS, ids=lambda tool: tool.name)
@pytest.mark.parametrize("field", ["tenant_id", "user_id", "as_of", "today", "time"])
def test_invented_server_fields_rejected(tool, field, ctx):
    assert_failure(
        run_tool(
            tool.name, {**valid_inputs(tool), field: "invented"}, ctx, ForbiddenGraph()
        ),
        ToolErrorCode.INPUT_INVALID,
    )


def test_unknown_tool(ctx):
    assert_failure(
        run_tool("unknown", {}, ctx, ForbiddenGraph()), ToolErrorCode.TOOL_UNKNOWN
    )


@pytest.mark.parametrize(
    "tool", [t for t in TOOLS if t.question_id], ids=lambda t: t.name
)
def test_frozen_query_parameters_and_result_processing(tool, ctx):
    rows = [
        {
            "value": i,
            "creative_ids": [f"youtube:synthetic_{i}", "youtube:shared"],
            "creative_id": f"instagram:synthetic_{i}",
        }
        for i in range(8)
    ]
    graph = FakeGraph(rows)
    arguments = valid_inputs(tool)
    result = run_tool(tool.name, json.dumps(arguments), ctx, graph)
    assert isinstance(result, ToolResult)
    assert result.tool == tool.name and result.kind == tool.kind
    assert result.top_rows == rows[:5]
    assert result.row_count == len(rows)
    expected_ids = sorted(
        {item for row in rows for item in [*row["creative_ids"], row["creative_id"]]}
    )
    assert result.evidence_ids == expected_ids
    assert all(evidence not in result.summary for evidence in expected_ids)
    assert not result.no_evidence
    if tool.question_id in LINKED_QUESTIONS:
        assert result.linked_creative_count == len(expected_ids)
        assert "연결된 소재 기준" in result.summary
    else:
        assert result.linked_creative_count is None
        assert "연결된 소재 기준" not in result.summary
    context = {"tenant_id": ctx.tenant_id}
    if tool.question_id == "CQ-16":
        context.update(ctx.price_band.model_dump())
    question = QUESTIONS[tool.question_id]
    assert graph.calls == [
        (
            question.cypher,
            question_parameters(
                question, as_of=ctx.as_of, inputs=arguments, context=context
            ),
        )
    ]


def test_evidence_is_taken_from_all_rows_sorted_deduplicated_and_capped(ctx):
    rows = [{"creative_id": f"youtube:synthetic_{i:03d}"} for i in range(70)]
    rows += [{"creative_ids": ["youtube:synthetic_000", "youtube:synthetic_069"]}, {}]
    result = run_tool("ingredient_ad_trend", {}, ctx, FakeGraph(rows))
    assert isinstance(result, ToolResult)
    assert result.row_count == len(rows)
    assert result.top_rows == rows[:5]
    assert result.evidence_ids == sorted({row["creative_id"] for row in rows[:-2]})[:50]
    assert result.linked_creative_count == len(result.evidence_ids)


@pytest.mark.parametrize(
    "tool", [t for t in TOOLS if t.question_id], ids=lambda t: t.name
)
def test_empty_records_mean_no_evidence_without_guessing(tool, ctx):
    result = run_tool(tool.name, valid_inputs(tool), ctx, FakeGraph())
    assert isinstance(result, ToolResult)
    assert result.no_evidence and not result.top_rows and not result.evidence_ids
    assert "근거 없음" in result.summary
    assert "데이터 부재" not in result.summary
    assert ("연결된 소재 기준" in result.summary) == (
        tool.question_id in LINKED_QUESTIONS
    )


@pytest.mark.parametrize(
    ("error", "code", "retryable"),
    [
        (GraphError("NEO4J_UNREACHABLE"), ToolErrorCode.GRAPH_UNAVAILABLE, True),
        (
            GraphError("NEO4J_CONSTRAINT_VIOLATION"),
            ToolErrorCode.GRAPH_UNAVAILABLE,
            False,
        ),
        (
            RuntimeError("synthetic-sensitive-value"),
            ToolErrorCode.TOOL_INTERNAL_ERROR,
            False,
        ),
    ],
)
def test_errors_are_failures_without_leaking_values(error, code, retryable, ctx):
    result = run_tool("ingredient_ad_trend", {}, ctx, FakeGraph(error=error))
    assert_failure(result, code, retryable=retryable)
    assert "synthetic-sensitive-value" not in result.message
    if code == ToolErrorCode.TOOL_INTERNAL_ERROR:
        assert result.message == type(error).__name__


def test_price_band_only_comes_from_context(ctx):
    assert_failure(
        run_tool(
            "compare_price_band_competitors",
            {},
            ctx.model_copy(update={"price_band": None}),
            ForbiddenGraph(),
        ),
        ToolErrorCode.PRICE_BAND_MISSING,
    )
    graph = FakeGraph()
    run_tool("compare_price_band_competitors", {}, ctx, graph)
    assert graph.calls[0][1]["context"] == {
        "tenant_id": ctx.tenant_id,
        "price_min": ctx.price_band.price_min,
        "price_max": ctx.price_band.price_max,
    }
    assert_failure(
        run_tool(
            "compare_price_band_competitors",
            {"price_min": 1, "price_max": 2},
            ctx,
            ForbiddenGraph(),
        ),
        ToolErrorCode.INPUT_INVALID,
    )


@pytest.mark.parametrize("name", DISPLAY_INPUTS)
def test_display_only_sends_command_without_echoing_data(name, ctx):
    arguments = DISPLAY_INPUTS[name]
    result = run_tool(name, arguments, ctx, ForbiddenGraph())
    assert isinstance(result, ToolResult)
    assert result.kind == ToolKind.display
    assert result.ui_command.kind == name
    assert result.ui_command.data == arguments
    assert ctx.tenant_id not in json.dumps(result.ui_command.data)
    assert not result.top_rows and not result.evidence_ids
    for value in arguments.values():
        for item in value if isinstance(value, list) else [value]:
            assert item not in result.summary
    assert "표시 명령" in result.summary


@pytest.mark.parametrize(
    "name", ["show_evidence_cards", "show_graph_fragment", "show_distribution"]
)
@pytest.mark.parametrize(
    "ids",
    [
        [f"youtube:synthetic_{i}" for i in range(21)],
        ["YouTube:synthetic"],
        ["youtube:has space"],
        ["youtube:a:b"],
        ["youtube:"],
        ["youtube:" + "a" * 65],
        [123],
    ],
)
def test_display_evidence_validation(name, ids, ctx):
    arguments = {**DISPLAY_INPUTS[name], "evidence_ids": ids}
    assert_failure(
        run_tool(name, arguments, ctx, ForbiddenGraph()), ToolErrorCode.INPUT_INVALID
    )


@pytest.mark.parametrize("axis", ["hook_type", "angle", "format", "claim", "category"])
def test_distribution_closed_axes(axis, ctx):
    result = run_tool(
        "show_distribution", {"axis": axis, "evidence_ids": []}, ctx, ForbiddenGraph()
    )
    assert isinstance(result, ToolResult)
    assert result.ui_command.data["axis"] == axis


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("show_plan", {"plan_id": ""}),
        ("show_plan", {"plan_id": "  "}),
        ("show_distribution", {"axis": "invented", "evidence_ids": []}),
        ("ad_angles_formats_by_skin_type", {"skin_type": "invented"}),
        (
            "lookup_products_by_concern",
            {"category": "mask_pack", "concern": "invented"},
        ),
    ],
)
def test_other_invalid_closed_inputs(name, arguments, ctx):
    assert_failure(
        run_tool(name, arguments, ctx, ForbiddenGraph()), ToolErrorCode.INPUT_INVALID
    )


def test_graph_connection_satisfies_reader_without_a_real_connection(ctx):
    class FakeDriver:
        def execute_query(self, query, **kwargs):
            return SimpleNamespace(
                records=[],
                summary=SimpleNamespace(
                    counters=SimpleNamespace(nodes_created=0, relationships_created=0)
                ),
            )

    graph = GraphConnection(FakeDriver())
    assert isinstance(graph.run("synthetic-query"), GraphResult)
    assert isinstance(run_tool("ingredient_ad_trend", {}, ctx, graph), ToolResult)


def test_agents_only_use_domain_graph_and_no_query_literals():
    tree = ast.parse(Path("src/beautyads/agents/tools.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.startswith("beautyads."):
                assert module.split(".")[1] in {"domain", "graph"}
            assert module.split(".")[0] not in {"langgraph", "litellm"}
        if isinstance(node, ast.Import):
            assert all(
                n.name.split(".")[0] not in {"langgraph", "litellm"} for n in node.names
            )
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert "MATCH (" not in node.value and "RETURN " not in node.value
