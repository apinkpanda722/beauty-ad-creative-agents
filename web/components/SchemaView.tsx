"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, getSchema } from "../lib/api";
import { schemaToElements } from "../lib/graph";
import type { GraphNode, SchemaResponse } from "../lib/types";
import { GraphCanvas, GraphLegend } from "./GraphCanvas";
import { NodeDetail } from "./NodeDetail";

type SchemaState = { status: "loading" } | { status: "error"; code: string } | { status: "ready"; schema: SchemaResponse };
export function SchemaView({ tenantId }: { tenantId: string }) {
  return <SchemaContent key={tenantId} tenantId={tenantId} />;
}
function SchemaContent({ tenantId }: { tenantId: string }) {
  const [state, setState] = useState<SchemaState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [selected, setSelected] = useState<GraphNode | null>(null);
  useEffect(() => {
    let active = true;
    void getSchema(tenantId).then(schema => { if (active) setState({ status: "ready", schema }); })
      .catch(error => { if (active) setState({ status: "error", code: error instanceof ApiError ? error.code ?? `HTTP_${error.status}` : "GRAPH_REQUEST_FAILED" }); });
    return () => { active = false; };
  }, [tenantId, attempt]);
  const schema = state.status === "ready" ? state.schema : null;
  const elements = useMemo(() => schema ? schemaToElements(schema) : [], [schema]);
  const select = useCallback((id: string) => {
    const element = elements.find(element => element.group === "nodes" && element.data.id === id);
    setSelected(element?.group === "nodes" ? { id: element.data.id, label: element.data.label, name: element.data.name, props: element.data.props } : null);
  }, [elements]);
  return <section className="result-section" aria-label="전체 스키마"><h2>전체 스키마</h2>
    {state.status === "loading" ? <p role="status">스키마를 불러오는 중입니다.</p>
      : state.status === "error" ? <div role="alert"><p>{state.code}</p><button type="button" onClick={() => { setState({ status: "loading" }); setSelected(null); setAttempt(value => value + 1); }}>다시 시도</button></div>
        : state.schema.labels.length ? <><GraphLegend /><div className="graph-layout"><GraphCanvas elements={elements} layout="breadthfirst" onNodeClick={select} /><NodeDetail node={selected} /></div></>
          : <p>표시할 노드가 없습니다</p>}
  </section>;
}
