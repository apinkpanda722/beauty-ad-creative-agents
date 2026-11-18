"""Research subgraph exercises only injected, synthetic local boundaries."""

import json
from copy import deepcopy
from datetime import date

import pytest
from pydantic import ValidationError

from beautyads.agents.research import (
    RESEARCH_REASONING_EFFORT,
    ResearchState,
    build_research_graph,
    initial_research_state,
    run_research,
)
from beautyads.agents.state import AgentState
from beautyads.agents.tool_messages import (
    PARTIAL_RESULT_RULE,
    TOOL_DATA_RULE,
    tool_result_payload,
)
from beautyads.agents.tools import TOOLS
from beautyads.domain.research import ResearchHandoff, ResearchHandoffDraft
from beautyads.domain.tenant import TenantContextMissing
from beautyads.domain.tools import ToolContext, ToolFailure, ToolResult
from beautyads.llm.chat import ChatResult, ToolCall
from beautyads.llm.structured import (
    JsonSchemaStructured,
    StructuredFailure,
    StructuredResult,
    StructuredStats,
)

EXAMPLE = "find_example_creatives"
COMPARE = "compare_axis_by_category"
CTX = ToolContext(tenant_id="synthetic-a", as_of=date(2026, 1, 2))


def brief(limit=6):
    return {
        "goal": "synthetic task",
        "category": "mask_pack",
        "output": "both",
        "max_tool_calls": limit,
    }


def reply(calls=(), text=None):
    return ChatResult(text, list(calls), "stop", {}, 0, "price_table", {})


def call(name=EXAMPLE, arguments=None):
    return ToolCall(
        "synthetic-call",
        name,
        arguments if arguments is not None else {"category": "mask_pack"},
        None,
    )


def result(
    name=EXAMPLE, *, ids=("yt:a",), empty=False, summary="synthetic summary", raw_size=1
):
    # The UI branch holds the full payload; top_rows is the bounded model view.
    return ToolResult(
        tool=name,
        kind="lookup",
        summary=summary,
        top_rows=[{"creative_id": "yt:a", "preview": "synthetic-preview"}],
        row_count=raw_size,
        evidence_ids=list(ids),
        no_evidence=empty,
        ui_command={
            "kind": "show_evidence_cards",
            "data": {"full": "raw-only-" * raw_size},
        },
    )


def draft(ids=("yt:a",)):
    return {
        "conclusion": "synthetic conclusion",
        "evidence_ids": list(ids),
        "aggregates": [{"name": "n", "value": "1"}],
        "confidence": "medium",
        "unresolved": [],
    }


class Chat:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        return next(self.responses)


class Structured:
    def __init__(self, value=None, *, ok=True):
        self.value = draft() if value is None else value
        self.ok = ok
        self.calls = []
        self.stats = StructuredStats()

    def generate(self, spec, **kwargs):
        self.calls.append((spec, deepcopy(kwargs)))
        self.stats.calls += 1
        self.stats.failed_after_retry += int(not self.ok)
        return StructuredResult(
            self.ok,
            spec.validate(self.value) if self.ok else None,
            None if self.ok else StructuredFailure.SCHEMA_VIOLATION,
            1,
            0,
            [],
        )


def execute(chat, runner, structured, *, limit=6, raw_store=None):
    return run_research(
        brief(limit),
        ctx=CTX,
        chat=chat,
        tool_runner=runner,
        structured=structured,
        raw_store=raw_store,
    )


def primitive(value):
    if type(value) is dict:
        return all(type(k) is str and primitive(v) for k, v in value.items())
    if type(value) is list:
        return all(primitive(v) for v in value)
    return type(value) in (str, int, float, bool, type(None))


@pytest.mark.parametrize("inconsistent_pool", [False, True])
def test_no_evidence_does_not_generate(inconsistent_pool):
    structured = Structured()
    chat = Chat([reply([call()]), reply()])
    output = execute(
        chat,
        lambda *args: result(empty=True, ids=["yt:a"] if inconsistent_pool else []),
        structured,
    )
    assert structured.calls == []
    assert output["status"] == "no_evidence"
    assert (
        output["conclusion"] == "조건에 맞는 근거 소재가 없다. 근거를 지어내지 않는다."
    )
    assert output["evidence_ids"] == []
    assert output["no_evidence_tools"] == [EXAMPLE]
    assert output["structured_failure_rate"] is None


def test_no_tool_calls_or_empty_pool_skips_structured():
    for responses, tool_result in [
        ([reply()], None),
        ([reply([call()]), reply()], result(ids=[])),
    ]:
        structured = Structured()
        output = execute(
            Chat(responses), lambda *args, value=tool_result: value, structured
        )
        assert output["status"] == "no_evidence" and not structured.calls


def test_mixed_evidence_restricts_ids_and_preserves_basis_notes():
    notes = [
        "category_basis=creative_label: 모델 라벨 기준(E1 채점 전).",
        "category_basis=product_link: 제품 연결 기준(연결된 소재만). 연결된 소재 기준.",
    ]
    results = iter(
        [
            result(empty=True, ids=[], summary=notes[0]),
            result(COMPARE, summary=notes[1]),
        ]
    )
    structured = Structured(draft(["yt:outside", "yt:a", "yt:a"]))
    output = execute(
        Chat(
            [
                reply(
                    [
                        call(),
                        call(
                            COMPARE,
                            {
                                "category": "mask_pack",
                                "source": "youtube",
                                "axis": "hook_type",
                            },
                        ),
                    ]
                ),
                reply(),
            ]
        ),
        lambda *args: next(results),
        structured,
    )
    assert output["status"] == "ok" and output["no_evidence_tools"] == [EXAMPLE]
    assert output["evidence_ids"] == ["yt:a"]
    assert any(
        "근거 풀 밖 ID 제거" in value and "yt:outside" in value
        for value in output["unresolved"]
    )
    for note in ("모델 라벨 기준(E1 채점 전)", "제품 연결 기준", "연결된 소재 기준"):
        assert any(note in value for value in output["basis_notes"])
    # Preserve source wording, including punctuation and parenthetical caveats.
    assert all(
        any(value in source for source in notes) for value in output["basis_notes"]
    )
    assert output["structured_failure_rate"] == 0
    ResearchHandoff.model_validate(output)


def test_tool_failure_is_recorded_and_next_tool_runs():
    seen = []

    def runner(name, arguments, ctx):
        seen.append(ctx)
        return (
            ToolFailure(
                code="GRAPH_UNAVAILABLE", retryable=True, message="private-diagnostic"
            )
            if len(seen) == 1
            else result()
        )

    chat = Chat([reply([call()]), reply([call()]), reply()])
    output = execute(chat, runner, Structured())
    assert len(seen) == 2 and all(ctx is CTX for ctx in seen)
    assert output["status"] == "ok"
    assert any("GRAPH_UNAVAILABLE" in item for item in output["unresolved"])
    assert "private-diagnostic" not in json.dumps(output) + str(chat.calls)


@pytest.mark.parametrize("limit", [1, 3, 10])
def test_counter_caps_parallel_and_repeated_tool_calls(limit):
    count = []
    chat = Chat([reply([call(), call()])] * 10)
    store = {}
    graph = build_research_graph(
        ctx=CTX,
        chat=chat,
        tool_runner=lambda *args: count.append(1) or result(),
        structured=Structured(),
        raw_store=store,
    )
    state = graph.invoke(initial_research_state(brief(limit)), {"recursion_limit": 32})
    assert state["research_step_count"] == len(count) == limit
    assert len(chat.calls) == (limit + 1) // 2
    assert state["handoff"]["status"] == "ok"


@pytest.mark.parametrize(
    "tool_call,code",
    [
        (call("show_plan"), "TOOL_UNKNOWN"),
        (ToolCall("x", EXAMPLE, None, "invalid"), "INPUT_INVALID"),
        (call(arguments={"tenant_id": "other"}), "INPUT_INVALID"),
    ],
)
def test_invalid_calls_do_not_dispatch(tool_call, code):
    def forbidden(*args):
        pytest.fail("must not dispatch")

    output = execute(Chat([reply([tool_call]), reply()]), forbidden, Structured())
    assert any(code in item for item in output["unresolved"])


def test_structured_failure_returns_bounded_pool():
    ids = [f"yt:{i:02d}" for i in range(30)]
    structured = Structured(ok=False)
    output = execute(
        Chat([reply([call()]), reply()]),
        lambda *args: result(ids=ids[::-1]),
        structured,
    )
    assert output["status"] == "failed"
    assert output["conclusion"] == "구조화 실패로 결론을 만들지 못했다."
    assert output["evidence_ids"] == sorted(ids)[:20]
    assert output["structured_failure_rate"] == 1


def test_isolated_primitive_state_and_raw_storage():
    assert set(ResearchState.__annotations__).isdisjoint(AgentState.__annotations__)
    sizes = []
    for size in [1, 100_000]:
        store = {}
        structured = Structured()
        chat = Chat([reply([call()]), reply()])
        graph = build_research_graph(
            ctx=CTX,
            chat=chat,
            tool_runner=lambda *args, size=size: result(raw_size=size),
            structured=structured,
            raw_store=store,
        )
        snapshots = list(
            graph.stream(initial_research_state(brief()), stream_mode="values")
        )
        assert all(primitive(state) for state in snapshots)
        state = snapshots[-1]
        assert len(store) == len(state["raw_refs"]) == 1
        assert (
            store[state["raw_refs"][0]]["ui_command"]["data"]["full"]
            == "raw-only-" * size
        )
        serialized = json.dumps(snapshots)
        assert "raw-only-" not in serialized
        assert "raw-only-" not in str(chat.calls) + str(structured.calls)
        for options in [chat.calls[1], structured.calls[0][1]]:
            observations = json.loads(options["messages"][1]["content"])["observations"]
            assert observations == [{"tool": EXAMPLE, "summary": "synthetic summary"}]
            assert "synthetic-preview" not in str(options)
        sizes.append(len(serialized))
    assert sizes[1] < sizes[0] + 100


def test_call_options_and_model_schema():
    chat, structured = Chat([reply([call()]), reply()]), Structured()
    execute(chat, lambda *args: result(), structured)
    assert RESEARCH_REASONING_EFFORT == "none"
    advertised = {tool.name for tool in TOOLS if tool.kind != "display"}
    for options in chat.calls:
        assert options["model"] == "gpt-6-luna"
        assert options["reasoning_effort"] == "none" and "temperature" not in options
        assert {d["function"]["name"] for d in options["tools"]} == advertised
        for definition in options["tools"]:
            fields = definition["function"]["parameters"]["properties"]
            assert not any(
                set(name.split("_")) & {"tenant", "user", "date", "today"}
                for name in fields
            )
    spec, options = structured.calls[0]
    assert options["reasoning_effort"] == "none" and "temperature" not in options
    assert set(spec.schema["properties"]) == set(ResearchHandoffDraft.model_fields)


@pytest.mark.parametrize("corrected", [False, True])
def test_real_structured_adapter_validates_and_corrects_once_without_network(corrected):
    class LocalStructured(JsonSchemaStructured):
        def __init__(self):
            super().__init__("gpt-6-luna")
            self.requests = []

        def _complete(self, spec, messages, options):
            self.requests.append(deepcopy(messages))
            return reply(
                text=json.dumps(
                    draft()
                    if corrected and len(self.requests) == 2
                    else {"invalid": True}
                )
            )

    structured = LocalStructured()
    output = execute(
        Chat([reply([call()]), reply()]), lambda *args: result(), structured
    )
    assert output["status"] == ("ok" if corrected else "failed")
    assert len(structured.requests) == 2
    assert structured.stats.calls == 1
    assert (
        structured.stats.first_attempt_failures[StructuredFailure.SCHEMA_VIOLATION] == 1
    )


def test_brief_validation_precedes_calls_and_context_fails_closed():
    def forbidden(*args, **kwargs):
        pytest.fail("invalid context/input must not invoke boundaries")

    with pytest.raises(ValidationError):
        run_research(
            {**brief(), "tenant_id": "other"},
            ctx=CTX,
            chat=forbidden,
            tool_runner=forbidden,
            structured=Structured(),
        )
    with pytest.raises(TenantContextMissing):
        run_research(
            brief(),
            ctx=ToolContext(tenant_id=" ", as_of=CTX.as_of),
            chat=forbidden,
            tool_runner=forbidden,
            structured=Structured(),
        )


def test_request_stores_do_not_share_refs():
    stores = [{}, {}]
    for store in stores:
        execute(
            Chat([reply([call()]), reply()]),
            lambda *args: result(),
            Structured(),
            raw_store=store,
        )
    assert len(stores[0]) == len(stores[1]) == 1
    assert set(stores[0]).isdisjoint(stores[1])


@pytest.mark.parametrize(
    "note", ["모델 라벨 기준(E1 채점 전)", "제품 연결 기준", "연결된 소재 기준"]
)
def test_basis_annotation_without_category_prefix_is_copied(note):
    output = execute(
        Chat([reply([call()]), reply()]),
        lambda *args: result(summary=f"조회 결과 1행. {note}"),
        Structured(),
    )
    assert output["basis_notes"] == [note]


def test_model_observations_use_shared_bounded_payload_from_raw_store():
    value = ToolResult(
        tool=EXAMPLE,
        kind="lookup",
        summary="synthetic summary",
        top_rows=[
            {"title": f"synthetic-row-{i}", "caption": "가" * 201, "count": i}
            for i in range(5)
        ],
        row_count=13,
        evidence_ids=[f"yt:{i}" for i in range(13)],
        no_evidence=False,
    )
    chat, structured, store = Chat([reply([call()]), reply()]), Structured(), {}
    output = execute(chat, lambda *args: value, structured, raw_store=store)
    raw = next(iter(store.values()))
    assert raw == value.model_dump(mode="json")
    expected = tool_result_payload(EXAMPLE, raw)
    for options in [chat.calls[1], structured.calls[0][1]]:
        observations = json.loads(options["messages"][1]["content"])["observations"]
        assert observations == [expected]
        assert len(observations[0]["rows"]) == 5
        assert observations[0]["rows"][0] == {
            "title": "synthetic-row-0",
            "caption": "가" * 200 + "…",
            "count": "0",
        }
        assert observations[0]["truncated"] == {
            "rows": True,
            "values": 5,
            "evidence_ids": True,
        }
        # Bounded observations must not reduce the independent evidence pool.
        assert json.loads(options["messages"][1]["content"])["evidence_pool"] == sorted(
            value.evidence_ids
        )
    for options in [*chat.calls, structured.calls[0][1]]:
        assert options["messages"][0]["role"] == "system"
        assert TOOL_DATA_RULE in options["messages"][0]["content"].splitlines()
        assert PARTIAL_RESULT_RULE in options["messages"][0]["content"].splitlines()
    assert output["status"] == "ok"
    assert output["evidence_ids"] == []  # The draft's yt:a lies outside this pool.


@pytest.mark.parametrize(
    "tool_call,code",
    [
        (call(), "GRAPH_UNAVAILABLE"),
        (call("show_plan"), "TOOL_UNKNOWN"),
        (ToolCall("x", EXAMPLE, None, "invalid"), "INPUT_INVALID"),
    ],
)
def test_failure_observations_are_structured_without_diagnostics(tool_call, code):
    failure = ToolFailure(
        code="GRAPH_UNAVAILABLE", retryable=True, message="synthetic private diagnostic"
    )
    chat = Chat([reply([tool_call]), reply()])
    output = execute(chat, lambda *args: failure, Structured())
    observations = json.loads(chat.calls[1]["messages"][1]["content"])["observations"]
    assert observations == [
        {
            "tool": EXAMPLE if code != "TOOL_UNKNOWN" else "unknown",
            "failure": code,
            "retryable": code == "GRAPH_UNAVAILABLE",
        }
    ]
    assert "synthetic private diagnostic" not in str(chat.calls)
    assert output["status"] == "no_evidence"


@pytest.mark.parametrize("model_counts", [None, {"row_count": 999, "shown_count": 999}])
def test_handoff_counts_come_from_tool_rows_even_when_draft_aggregates_disagree(
    model_counts,
):
    from beautyads.domain.research import ResultCount

    value = result(raw_size=7).model_copy(
        # Deliberately supply unbounded synthetic rows at the injected boundary.
        update={"top_rows": [{"index": i} for i in range(7)], "ui_command": None}
    )
    model_draft = draft()
    if model_counts is not None:
        model_draft["aggregates"].extend(
            {"name": name, "value": str(value)} for name, value in model_counts.items()
        )
    structured = Structured(model_draft)
    chat = Chat([reply([call()]), reply()])
    graph = build_research_graph(
        ctx=CTX, chat=chat, tool_runner=lambda *args: value, structured=structured
    )
    snapshots = list(
        graph.stream(initial_research_state(brief()), stream_mode="values")
    )
    state = snapshots[-1]
    assert ResearchHandoff.model_validate(state["handoff"]).result_counts == [
        ResultCount(tool=EXAMPLE, row_count=7, shown_count=5, truncated=True)
    ]
    assert state["tool_log"] == [
        {
            "name": EXAMPLE,
            "summary": value.summary,
            "id_count": 1,
            "code": None,
            "no_evidence": False,
            "row_count": 7,
            "shown_count": 5,
        }
    ]
    assert set(state) == {
        "brief",
        "tool_log",
        "evidence_pool",
        "raw_refs",
        "research_step_count",
        "handoff",
    }
    assert all(primitive(snapshot) for snapshot in snapshots)
    assert PARTIAL_RESULT_RULE not in json.dumps(snapshots, ensure_ascii=False)
    assert "result_counts" not in structured.calls[0][0].schema["properties"]
    for options in [*chat.calls, structured.calls[0][1]]:
        assert PARTIAL_RESULT_RULE in options["messages"][0]["content"].splitlines()
    for options in [chat.calls[1], structured.calls[0][1]]:
        observation = json.loads(options["messages"][1]["content"])["observations"][0]
        assert observation["row_count"] == 7
        assert observation["shown_count"] == len(observation["rows"]) == 5


def test_result_counts_preserve_repeated_call_order_and_actual_available_rows():
    values = iter(
        [
            result(raw_size=13).model_copy(
                update={"top_rows": [{"index": 0}, {"index": 1}]}
            ),
            result(raw_size=3).model_copy(
                update={"top_rows": [{"index": i} for i in range(3)]}
            ),
        ]
    )
    output = execute(
        Chat([reply([call(), call()])]),
        lambda *args: next(values),
        Structured(),
        limit=2,
    )
    assert output["result_counts"] == [
        {"tool": EXAMPLE, "row_count": 13, "shown_count": 2, "truncated": True},
        {"tool": EXAMPLE, "row_count": 3, "shown_count": 3, "truncated": False},
    ]


def test_zero_evidence_result_has_zero_counts():
    value = result(ids=(), empty=True, raw_size=0).model_copy(update={"top_rows": []})
    structured = Structured()
    output = execute(Chat([reply([call()]), reply()]), lambda *args: value, structured)
    assert output["status"] == "no_evidence"
    assert output["result_counts"] == [
        {"tool": EXAMPLE, "row_count": 0, "shown_count": 0, "truncated": False}
    ]
    assert structured.calls == []


def test_finalize_converts_aggregate_items_without_changing_counts_or_status():
    value = draft()
    value["aggregates"] += [
        {"name": "n", "value": "later"},
        {"name": "row_count", "value": "999"},
    ]
    output = execute(
        Chat([reply([call()]), reply()]),
        lambda *args: result(raw_size=7),
        Structured(value),
    )
    assert output["aggregates"] == {"n": "1", "row_count": "999"}
    assert output["status"] == "ok"
    assert output["result_counts"] == [
        {"tool": EXAMPLE, "row_count": 7, "shown_count": 1, "truncated": True}
    ]
    assert output["unresolved"] == []


def test_failures_and_display_calls_have_no_result_counts():
    seen = []

    def runner(*args):
        seen.append(args)
        return ToolFailure(
            code="GRAPH_UNAVAILABLE", retryable=True, message="synthetic"
        )

    output = execute(
        Chat([reply([call(), call("show_plan")]), reply()]), runner, Structured()
    )
    assert len(seen) == 1
    assert output["result_counts"] == []


def test_display_result_is_excluded_even_if_injected_for_lookup():
    value = result().model_copy(update={"kind": "display"})
    output = execute(
        Chat([reply([call()]), reply()]), lambda *args: value, Structured()
    )
    assert output["result_counts"] == []


def test_structured_failure_still_preserves_successful_tool_counts():
    output = execute(
        Chat([reply([call()]), reply()]),
        lambda *args: result(raw_size=7),
        Structured(ok=False),
    )
    assert output["status"] == "failed"
    assert output["result_counts"] == [
        {"tool": EXAMPLE, "row_count": 7, "shown_count": 1, "truncated": True}
    ]


@pytest.mark.parametrize("name", [EXAMPLE, "ingredient_ad_trend"])
def test_actual_neo4j_rows_reach_raw_store_and_serializable_handoff(name):
    from types import SimpleNamespace

    from neo4j.time import Date, DateTime, Duration, Time

    from beautyads.agents.tools import run_tool

    row = {
        "creative_id": "youtube:synthetic",
        "published_at": DateTime(2025, 1, 1, 1, 2, 3),
        "date": Date(2025, 1, 1),
        "time": Time(1, 2, 3),
        "duration": Duration(seconds=5),
    }

    class Graph:
        def run(self, query, params=None):
            return SimpleNamespace(records=[row])

    arguments = {"category": "mask_pack"} if name == EXAMPLE else {}
    chat = Chat([reply([call(name, arguments)]), reply()])
    store, structured = {}, Structured(draft([row["creative_id"]]))
    graph = build_research_graph(
        ctx=CTX,
        chat=chat,
        tool_runner=lambda n, a, c: run_tool(n, a, c, Graph()),
        structured=structured,
        raw_store=store,
    )
    state = graph.invoke(initial_research_state(brief()))
    assert state["handoff"]["status"] == "ok"
    assert state["handoff"]["unresolved"] == []
    assert state["tool_log"][0]["code"] is None
    assert state["handoff"]["evidence_ids"] == [row["creative_id"]]
    json.dumps(state, allow_nan=False)
    json.dumps(store, allow_nan=False)
    raw = store[state["raw_refs"][0]]
    assert raw["top_rows"][0]["published_at"] == row["published_at"].iso_format()
    for options in (chat.calls[1], structured.calls[0][1]):
        observation = json.loads(options["messages"][1]["content"])["observations"][0]
        assert "failure" not in observation
        assert (
            observation["rows"][0]["published_at"] == row["published_at"].iso_format()
        )


@pytest.mark.parametrize(
    "value", ["synthetic-private-body", [], {"private": "synthetic-private-body"}]
)
def test_unknown_runner_shape_is_logged_and_handed_off_as_unreadable(value):
    store = {}
    chat = Chat([reply([call()]), reply()])
    graph = build_research_graph(
        ctx=CTX,
        chat=chat,
        tool_runner=lambda *args: value,
        structured=Structured(),
        raw_store=store,
    )
    state = graph.invoke(initial_research_state(brief()))
    assert next(iter(store.values())) == value
    assert state["tool_log"][0]["code"] == "TOOL_RESULT_UNREADABLE"
    assert state["handoff"]["unresolved"] == [f"{EXAMPLE}: TOOL_RESULT_UNREADABLE"]
    assert state["handoff"]["status"] == "no_evidence"
    assert state["handoff"]["result_counts"] == []
    assert state["evidence_pool"] == []
    observation = json.loads(chat.calls[1]["messages"][1]["content"])["observations"][0]
    assert observation == {
        "tool": EXAMPLE,
        "failure": "TOOL_RESULT_UNREADABLE",
        "retryable": False,
    }
    assert "synthetic-private-body" not in json.dumps(state) + str(chat.calls)
