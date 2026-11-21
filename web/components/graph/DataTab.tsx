"use client";
import { useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { brandDisplayName, BrandNamesContext, type BrandNames } from "../../lib/brandNames";
import { ApiError, getGraphNeighbors, getGraphOverview, getSchema, type GraphExploreResponse } from "../../lib/api";
import { fragmentToElements } from "../../lib/graph";
import { ctaName, talentName, taxonomyNames } from "../../lib/taxonomy";
import type { GraphNode, SchemaResponse } from "../../lib/types";
import { GraphCanvas } from "../GraphCanvas";
import { NodeDetail } from "../NodeDetail";
import { Button } from "../ui";
import { GraphFilters, useGraphFilters } from "./GraphFilters";

type Failure = { status: number | null; code: string };
type DataState = { status: "loading" } | { status: "error"; error: Failure }
  | { status: "ready"; data: GraphExploreResponse; schema: SchemaResponse };
type Expansion = { status: "idle" } | { status: "loading"; id: string } | { status: "error"; id: string; error: Failure };
function failure(error: unknown): Failure {
  return error instanceof ApiError ? { status: error.status, code: error.code ?? "GRAPH_REQUEST_FAILED" }
    : { status: null, code: "GRAPH_REQUEST_FAILED" };
}
function RequestError({ error, retry }: { error: Failure; retry: () => void }) {
  return <div role="alert"><p>그래프를 불러오지 못했습니다. 상태: {error.status ?? "정보 없음"} · 코드: {error.code}</p>
    <Button variant="secondary" onClick={retry}>다시 시도</Button></div>;
}
function merge(current: GraphExploreResponse, incoming: GraphExploreResponse): GraphExploreResponse {
  const nodes = new Map([...current.nodes, ...incoming.nodes].map(node => [node.id, node]));
  const edges = new Map([...current.edges, ...incoming.edges].map(edge => [JSON.stringify([edge.source, edge.target, edge.type]), edge]));
  return { nodes: [...nodes.values()], edges: [...edges.values()], truncated: current.truncated || incoming.truncated };
}
// Preserve wire identities for expansion; translate only the presentation copy.
function displayNode(node: GraphNode, brandNames: BrandNames): GraphNode {
  const korean = (value: string) => /[가-힣]/.test(value) ? value : "정보 없음";
  const props = { ...node.props };
  let name = node.name;
  if (node.label === "Creative") name = "광고 소재";
  if (node.label === "Brand") name = brandDisplayName(name, brandNames);
  if (node.label === "Product") name = name ?? "정보 없음";
  for (const key of ["name", "brand", "name_ko"]) {
    if (key === "brand" || (node.label === "Brand" && key === "name")) {
      if (key in props) props[key] = brandDisplayName(typeof props[key] === "string" ? props[key] : null, brandNames);
    } else if (node.label === "Product") {
      if (key in props && props[key] === null) props[key] = "정보 없음";
    } else if (typeof props[key] === "string") props[key] = korean(props[key]);
  }
  if (node.label === "Talent" || node.label === "CtaType") {
    const translate = node.label === "Talent" ? talentName : ctaName;
    const translated = (value: string) => translate(value) === value && !/[가-힣]/.test(value) ? "기타" : value;
    if (name !== null) name = translated(name);
    if (typeof props.value === "string") props.value = translated(props.value);
  }
  return { ...node, name, props };
}
export function DataTab({ tenantId }: { tenantId: string }) {
  return <DataView key={tenantId} tenantId={tenantId} />;
}
function DataView({ tenantId }: { tenantId: string }) {
  const brandNames = useContext(BrandNamesContext);
  const [state, setState] = useState<DataState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string[]>([]);
  const [expansion, setExpansion] = useState<Expansion>({ status: "idle" });
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    let active = true;
    void Promise.all([getGraphOverview(tenantId), getSchema(tenantId)]).then(([data, schema]) => {
      if (active) setState({ status: "ready", data, schema });
    }).catch(error => { if (active) setState({ status: "error", error: failure(error) }); });
    return () => { active = false; };
  }, [tenantId, attempt]);
  const data = state.status === "ready" ? state.data : null;
  const schema = state.status === "ready" ? state.schema : null;
  const names = useMemo(() => {
    const original = taxonomyNames(schema);
    const translated = (value: string, name: string) => name === value && !/[가-힣]/.test(value) ? "기타" : name;
    return {
      axisName: (axis: keyof SchemaResponse["taxonomy"], value: string) => translated(value, original.axisName(axis, value)),
      claimName: (value: string) => translated(value, original.claimName(value)),
      valueName: (value: string) => translated(value, original.valueName(value)),
    };
  }, [schema]);
  const elements = useMemo(() => data ? fragmentToElements({ ...data, nodes: data.nodes.map(node => displayNode(node, brandNames)), missing: [] }, names) : [], [data, names, brandNames]);
  const filters = useGraphFilters(elements);
  const selected = filters.elements.find(element => element.group === "nodes" && element.data.id === selectedId);
  const selectedNode = selected?.group === "nodes" ? selected.data : null;
  const select = useCallback((id: string) => setSelectedId(id), []);
  async function expand(id: string) {
    setExpansion({ status: "loading", id });
    try {
      const incoming = await getGraphNeighbors(tenantId, id);
      if (!mounted.current) return;
      setState(current => current.status === "ready" ? { ...current, data: merge(current.data, incoming) } : current);
      setExpanded(current => [...current, id]);
      setExpansion({ status: "idle" });
    } catch (error) {
      if (mounted.current) setExpansion({ status: "error", id, error: failure(error) });
    }
  }
  return <>
    <p className="gs-graph-note">공용 카탈로그(브랜드·제품·효능)를 먼저 보여 주고, 노드를 선택해 연결된 이웃을 펼칩니다.</p>
    <section className="result-section graph-panel" aria-label="공용 카탈로그">
      {state.status === "loading" ? <p role="status">그래프를 불러오는 중입니다.</p>
        : state.status === "error" ? <RequestError error={state.error} retry={() => { setState({ status: "loading" }); setAttempt(value => value + 1); }} />
          : <>{data?.truncated && <p className="gs-graph-note">일부만 표시합니다. 표시 상한을 넘는 노드는 보이지 않습니다.</p>}
            {state.data.nodes.length ? <><GraphFilters {...filters} colorBy="kind" />
              <div className="graph-layout gs-graph-layout"><GraphCanvas elements={filters.elements} onNodeClick={select} />
                <div><NodeDetail node={selectedNode} names={names} />
                  {selectedNode && <p className="gs-graph-note"><Button variant="secondary" disabled={expanded.includes(selectedNode.id) || expansion.status === "loading"} onClick={() => { void expand(selectedNode.id); }}>이웃 펼치기</Button></p>}
                </div>
              </div>
            </> : <p>표시할 노드가 없습니다</p>}
            {expansion.status === "loading" && <p role="status">연결된 이웃을 불러오는 중입니다.</p>}
            {expansion.status === "error" && <RequestError error={expansion.error} retry={() => { void expand(expansion.id); }} />}
          </>}
    </section>
  </>;
}
