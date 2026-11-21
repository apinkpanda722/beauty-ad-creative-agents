"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, getGraphFragment, getSchema } from "../lib/api";
import { fragmentToElements } from "../lib/graph";
import { taxonomyNames } from "../lib/taxonomy";
import type { GraphFragment, GraphNode, SchemaResponse } from "../lib/types";
import { GraphCanvas } from "./GraphCanvas";
import { NodeDetail } from "./NodeDetail";
import { GraphFilters, useGraphFilters } from "./graph/GraphFilters";

type FragmentState = { status: "loading" } | { status: "error"; code: string } | { status: "ready"; fragment: GraphFragment; schema: SchemaResponse };
export function GraphPanel({ tenantId, ids }: { tenantId: string; ids: string[] }) {
  return <FragmentView key={JSON.stringify([tenantId, ids])} tenantId={tenantId} ids={ids} />;
}
function FragmentView({ tenantId, ids }: { tenantId: string; ids: string[] }) {
  const [state, setState] = useState<FragmentState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const idKey = JSON.stringify(ids);
  useEffect(() => {
    let active = true;
    void Promise.all([getGraphFragment(tenantId, JSON.parse(idKey)), getSchema(tenantId)]).then(([fragment, schema]) => {
      if (active) setState({ status: "ready", fragment, schema });
    }).catch(error => { if (active) setState({ status: "error", code: error instanceof ApiError ? error.code ?? `HTTP_${error.status}` : "GRAPH_REQUEST_FAILED" }); });
    return () => { active = false; };
  }, [tenantId, idKey, attempt]);
  const fragment = state.status === "ready" ? state.fragment : null;
  const schema = state.status === "ready" ? state.schema : null;
  const elements = useMemo(() => fragment ? fragmentToElements(fragment, taxonomyNames(schema)) : [], [fragment, schema]);
  const filters = useGraphFilters(elements);
  const select = useCallback((id: string) => setSelected(fragment?.nodes.find(node => node.id === id) ?? null), [fragment]);
  return <section className="result-section graph-panel" aria-label="근거 그래프"><h3>근거 그래프</h3>
    {state.status === "loading" ? <p role="status">그래프를 불러오는 중입니다.</p>
      : state.status === "error" ? <div role="alert"><p>{state.code}</p><button type="button" onClick={() => { setState({ status: "loading" }); setSelected(null); setAttempt(value => value + 1); }}>다시 시도</button></div>
        : <>{state.fragment.missing.length > 0 && <p className="muted">그래프에 아직 없는 소재 {state.fragment.missing.length}건</p>}
          {state.fragment.nodes.length ? <><p className="gs-graph-note">3층 피드백은 이 작업 공간의 데이터입니다.</p><GraphFilters {...filters} colorBy="kind" /><div className="graph-layout gs-graph-layout"><GraphCanvas elements={filters.elements} onNodeClick={select} /><NodeDetail node={filters.elements.some(element => element.group === "nodes" && element.data.id === selected?.id) ? selected : null} names={taxonomyNames(schema)} /></div></>
            : <p>표시할 노드가 없습니다</p>}</>}
  </section>;
}
