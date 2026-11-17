import copy
import re
from datetime import timedelta, timezone

import pytest
from test_feedback_sync_domain import NOW, feedback

from beautyads.domain.labels import Claim, HookType
from beautyads.graph.connection import GraphResult
from beautyads.graph.feedback import FEEDBACK_STATE, REPLACE_FEEDBACK, load_feedback
from beautyads.graph.queries import QUESTIONS


class Graph:
    def __init__(self):
        self.calls, self.state = [], {}
        self.fail = False

    def run(self, query, params=None):
        params = copy.deepcopy(params or {})
        self.calls.append((query, params))
        if query == FEEDBACK_STATE:
            return GraphResult(
                [self.state.get((params["tenant_id"], params["feedback_id"]), {})], 0, 0
            )
        if query != REPLACE_FEEDBACK:
            return GraphResult([], 0, 0)
        if self.fail:
            raise RuntimeError("synthetic transaction failure")
        self.state[(params["tenant_id"], params["feedback_id"])] = params
        return GraphResult([], 0, 0)


def test_parameter_only_idempotent_write_and_cq12_properties():
    graph = Graph()
    item = feedback(plan_id="plan-'-$-synthetic")
    report = load_feedback(graph, [item])
    first = copy.deepcopy(graph.calls)
    load_feedback(graph, [item])
    assert (
        graph.calls == first * 2 and report["loaded"] == 1 and report["rejected"] == 0
    )
    query, params = first[0]
    assert not re.search(r"\bCREATE\b", query, re.IGNORECASE) and "MERGE" in query
    assert (
        "MERGE (f:Feedback {tenant_id: $tenant_id, feedback_id: $feedback_id})" in query
    )
    assert (
        params["tenant_id"] == item.tenant_id
        and params["feedback_id"] == item.feedback_id
    )
    assert item.plan_id not in query and params["plan_id"] == item.plan_id
    assert "reason" not in repr(graph.calls) and "payload" not in repr(graph.calls)
    reads = set(re.findall(r"\bf\.(\w+)", QUESTIONS["CQ-12"].cypher))
    writes = set(re.findall(r"\bf\.(\w+)\s*=", query)) | set(
        re.findall(r"(\w+): \$\w+", query.split("SET", 1)[0])
    )
    assert reads <= writes
    assert set(params) == {
        "tenant_id",
        "feedback_id",
        "plan_id",
        "decision",
        "created_at",
        "hooks",
        "claims",
    }


def test_about_replacement_is_one_transaction_scoped_to_composite_key():
    graph = Graph()
    load_feedback(
        graph, [feedback(), feedback(tenant_id="brand_b"), feedback(feedback_id="2")]
    )
    untouched = copy.deepcopy(graph.state)
    load_feedback(graph, [feedback(hook_type=None)])
    query, params = graph.calls[-1]
    assert len(graph.calls) == 4
    deletion = query.split("DELETE old", 1)[0]
    assert "tenant_id: $tenant_id, feedback_id: $feedback_id" in deletion
    assert "MATCH (f)-[old:ABOUT]->()" in deletion
    assert "DETACH" not in query and re.findall(r"DELETE\s+(\w+)", query) == ["old"]
    assert "MERGE (h:Hook {value: value})" in query
    assert "MERGE (e:Efficacy {value: value})" in query
    assert "MERGE (f)-[:ABOUT]->(h)" in query and "MERGE (f)-[:ABOUT]->(e)" in query
    assert params["hooks"] == [] and params["claims"] == ["hydration"]
    assert graph.state[("brand_b", "1")] == untouched[("brand_b", "1")]
    assert graph.state[("brand_a", "2")] == untouched[("brand_a", "2")]
    load_feedback(graph, [feedback(hook_type=None, claims=())])
    assert graph.calls[-1][1]["claims"] == []


@pytest.mark.parametrize(
    "changes",
    [
        {"hook_type": "unknown"},
        {"claims": ("hydration", "unknown")},
        {"decision": "unknown"},
        {"tenant_id": ""},
        {"tenant_id": "a"},
        {"tenant_id": "Brand"},
        {"tenant_id": "a.b"},
        {"tenant_id": "a" * 33},
        {"tenant_id": "aa\n"},
        {"tenant_id": None},
        {"hook_type": {"invalid": "json"}},
        {"claims": ({"invalid": "json"},)},
        {"claims": (None,)},
        {"claims": (1,)},
    ],
)
def test_invalid_feedback_is_rejected_as_whole_without_graph_writes(changes):
    graph = Graph()
    report = load_feedback(graph, [feedback(**changes), feedback(feedback_id="2")])
    assert report["rejected"] == 1 and report["loaded"] == 1
    assert report["errors"] == [{"code": "FEEDBACK_VALUE_INVALID", "feedback_id": "1"}]
    assert len(graph.calls) == 1 and graph.calls[0][1]["feedback_id"] == "2"


@pytest.mark.parametrize("decision", ["approved", "rejected"])
def test_all_closed_values_accepted_with_distinct_sorted_claims(decision):
    graph = Graph()
    for hook in HookType:
        report = load_feedback(
            graph,
            [
                feedback(
                    decision=decision,
                    hook_type=hook.value,
                    claims=tuple(c.value for c in Claim) * 2,
                )
            ],
        )
        assert report["loaded"] == 1 and report["rejected"] == 0
        assert graph.calls[-1][1]["claims"] == sorted(c.value for c in Claim)


@pytest.mark.parametrize(
    "created_at",
    [NOW.replace(tzinfo=None), NOW.astimezone(timezone(timedelta(hours=9)))],
)
def test_created_at_is_utc_iso(created_at):
    graph = Graph()
    load_feedback(graph, [feedback(created_at=created_at)])
    assert graph.calls[-1][1]["created_at"] == NOW.isoformat()


def test_failed_replacement_leaves_previous_feedback_and_other_tenants_intact():
    graph = Graph()
    load_feedback(graph, [feedback(), feedback(tenant_id="brand_b")])
    previous = copy.deepcopy(graph.state)
    graph.fail = True
    with pytest.raises(RuntimeError):
        load_feedback(graph, [feedback(hook_type=None, claims=())])
    assert graph.state == previous
