import copy

import pytest
from test_links_domain import creative, product

from beautyads.domain.sync import SyncLabel
from beautyads.graph.connection import GraphResult
from beautyads.graph.layer2 import (
    LINK_STATE,
    REPLACE_LINKS,
    load_layer2,
    read_link_state,
)


class Graph:
    def __init__(self):
        self.calls = []
        self.state = {}
        self.fail = False

    def run(self, query, params=None):
        params = copy.deepcopy(params or {})
        self.calls.append((query, params))
        if query == LINK_STATE:
            return GraphResult(
                [
                    {"source": k[0], "source_id": k[1], **v}
                    for k, v in sorted(self.state.items())
                    if any(
                        r["source"] == k[0] and r["source_id"] == k[1]
                        for r in params["rows"]
                    )
                ],
                0,
                0,
            )
        if query != REPLACE_LINKS:
            return GraphResult([], 0, 0)
        if self.fail:
            raise RuntimeError("synthetic transaction failure")
        for row in params["rows"]:
            self.state[(row["source"], row["source_id"])] = {
                "promotes": row["promotes"],
                "claims": row["claims"],
                "mentions": row["mentions"],
            }
        return GraphResult([], 0, sum(len(row["promotes"]) for row in params["rows"]))


def load(graph, entries, products=(), **kwargs):
    return load_layer2(
        graph,
        entries,
        products=products,
        dev_brands=["dev"],
        test_brands=["test"],
        **kwargs,
    )


def test_promotes_replacement_is_atomic_and_limited_to_each_creative_key():
    a, b = product(), product("가상 금빛 앰플", url="b")
    graph = Graph()
    load(graph, [creative(a.name_ko), creative(a.name_ko, id="2")], [a, b])
    untouched = copy.deepcopy(graph.state[("youtube", "2")])
    load(graph, [creative(b.name_ko)], [a, b])
    assert graph.state[("youtube", "1")]["promotes"][0]["source_url"] == b.source_url
    assert graph.state[("youtube", "2")] == untouched
    # Deletion and MERGE are a single GraphConnection.run (one transaction).
    assert len(graph.calls) == 2 and all(q == REPLACE_LINKS for q, _ in graph.calls)
    deletion = REPLACE_LINKS.split("DELETE old", 1)[0]
    assert "source: row.source, source_id: row.source_id" in deletion
    assert "(c)-[old:PROMOTES]" in deletion
    assert "MERGE (c)-[r:PROMOTES]->(p)" in REPLACE_LINKS
    load(graph, [creative("no match")], [a, b])
    assert graph.state[("youtube", "1")]["promotes"] == []
    assert graph.state[("youtube", "2")] == untouched


def test_reclassification_and_ambiguity_remove_old_promotes():
    a, b = product("합성 세럼"), product("가상 앰플", url="b")
    graph = Graph()
    load(graph, [creative(a.name_ko)], [a, b])
    load(graph, [creative(a.name_ko + b.name_ko)], [a, b])
    assert graph.state[("youtube", "1")]["promotes"] == []
    load(graph, [creative(a.name_ko, content_type="other")], [a, b])
    assert graph.state[("youtube", "1")]["promotes"] == []


def test_product_only_change_recomputes_same_creative_and_keeps_other_sources():
    old = product("합성 세럼")
    c = creative("합성 세럼과 가상 긴 앰플")
    graph = Graph()
    other_source = creative(old.name_ko, source="instagram")
    load(graph, [c, other_source], [old])
    previous = copy.deepcopy(graph.state[("instagram", "1")])
    renamed = product("이름 바뀐 세럼")
    new = product("가상 긴 앰플", url="new")
    load(graph, [c], [renamed, new])
    assert graph.state[("youtube", "1")]["promotes"][0]["source_url"] == new.source_url
    assert graph.state[("instagram", "1")] == previous


def test_claims_mentions_counts_raw_properties_and_parameterization():
    raw = "합성 ' 표기 (1%)"
    jobs = [
        SyncLabel(
            "full@v1",
            "done",
            {"claims": ["hydration", "other"], "ingredients": [raw, "미해결"]},
        ),
        SyncLabel(
            "ingredient-matches@v1",
            "done",
            {
                "ingredients": [
                    {
                        "raw_name": raw,
                        "standard_name": "표준성분",
                        "status": "resolved",
                    },
                    {"raw_name": "미해결", "status": "unresolved"},
                ]
            },
        ),
    ]
    c = creative(jobs=jobs)
    graph = Graph()
    report = load(graph, [c])
    assert report["claims"] == report["mentions"] == report["unresolved"] == 1
    query, params = graph.calls[-1]
    assert params["rows"][0]["claims"] == ["hydration"]
    assert params["rows"][0]["mentions"] == [
        {"raw_name": raw, "standard_name": "표준성분"}
    ]
    assert "MERGE (a:IngredientAlias" in query and "ALIAS_OF" in query
    assert "SET r.raw_name = mention.raw_name" in query
    assert "CREATE" not in query.upper()
    assert all(value not in query for value in (raw, "표준성분", "hydration"))
    assert "claim_text" not in query and "claim_text" not in str(params)
    load(graph, [c])
    assert graph.calls[-1] == (query, params)
    load(graph, [creative()])
    assert graph.state[("youtube", "1")]["claims"] == []
    assert graph.state[("youtube", "1")]["mentions"] == []


def test_report_and_pairs_count_only_the_material_actually_applied():
    p = product()
    graph = Graph()
    report = load(graph, [creative(p.name_ko)], [p])
    assert report["promotes"] == report["product_creatives"] == 1
    assert len(report["sample_pairs"]) == 1
    pair = report["sample_pairs"][0]
    assert (pair["source"], pair["source_id"]) in graph.state
    empty = load(graph, [], [p])
    assert empty["promotes"] == empty["product_creatives"] == 0
    assert empty["sample_pairs"] == []


def test_empty_load_failure_and_semantic_replay_state():
    graph = Graph()
    assert load(graph, [])["promotes"] == 0 and graph.calls == []
    p = product()
    c = creative(p.name_ko)
    load(graph, [c], [p])
    state = read_link_state(graph, [c])
    load(graph, [c], [p])
    assert read_link_state(graph, [c]) == state
    graph.fail = True
    with pytest.raises(RuntimeError, match="synthetic"):
        load(graph, [creative("changed")], [p])
    assert read_link_state(graph, [c]) == state


@pytest.mark.parametrize("option,value", [("sample_pairs", -1), ("batch_size", 0)])
def test_invalid_load_options_rejected_before_writes(option, value):
    graph = Graph()
    with pytest.raises(ValueError):
        load(graph, [], **{option: value})
    assert graph.calls == []
