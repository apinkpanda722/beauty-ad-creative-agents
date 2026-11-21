import { afterEach, expect, it, vi } from "vitest";
import { ApiError, getGraphFragment } from "../lib/api";
import { fragmentToElements, schemaToElements, LAYER_COLORS, LAYER_BORDER_COLORS, LABEL_COLORS, LABEL_BORDER_COLORS, GRAPH_LEGEND } from "../lib/graph";
import { taxonomyNames } from "../lib/taxonomy";
import type { GraphFragment, SchemaResponse } from "../lib/types";

afterEach(() => vi.unstubAllGlobals());
const schema: SchemaResponse = {
  labels: [{ label: "Product", layer: 1, name_ko: "합성 제품" }, { label: "Creative", layer: 2, name_ko: "합성 소재" }, { label: "Feedback", layer: 3, name_ko: "합성 피드백" }],
  relationships: [{ type: "PROMOTES", from: "Creative", to: "Product", layer: 2 }, { type: "ABOUT", from: "Feedback", to: "Creative", layer: 3 }],
  taxonomy: { hook_type: [{ value: "synthetic_hook", name: "합성 훅 이름", definition: "합성 정의" }], angle: [], format: [] },
  claims: [{ value: "synthetic_claim", name: "합성 효능 이름" }],
};
const fragment: GraphFragment = {
  nodes: [
    { id: "creative:youtube:a", label: "Creative", name: "youtube:a", props: {} },
    { id: "creative:youtube:isolated", label: "Creative", name: "youtube:isolated", props: {} },
    { id: "Hook:synthetic_hook", label: "Hook", name: "synthetic_hook", props: { value: "synthetic_hook" } },
    { id: "Efficacy:synthetic_claim", label: "Efficacy", name: "synthetic_claim", props: { value: "synthetic_claim" } },
    { id: "Angle:unknown", label: "Angle", name: "원 이름", props: { value: "unknown" } },
  ],
  edges: [{ source: "creative:youtube:a", target: "Hook:synthetic_hook", type: "USES_HOOK" }, { source: "creative:youtube:a", target: "Efficacy:synthetic_claim", type: "CLAIMS" }],
  missing: ["youtube:missing"],
};

it("converts every fragment node including isolated creatives, translates values and excludes missing", () => {
  const elements = fragmentToElements(fragment, taxonomyNames(schema));
  const nodes = elements.filter(e => e.group === "nodes");
  const edges = elements.filter(e => e.group === "edges");
  expect(nodes).toHaveLength(fragment.nodes.length); expect(edges).toHaveLength(fragment.edges.length);
  expect(nodes.map(n => n.data.id)).toEqual(fragment.nodes.map(n => n.id));
  const ids = new Set(nodes.map(n => n.data.id));
  for (const edge of edges) { expect(ids.has(edge.data.source)).toBe(true); expect(ids.has(edge.data.target)).toBe(true); }
  expect(new Set(elements.map(e => e.data.id)).size).toBe(elements.length);
  expect(nodes.find(n => n.data.id === "creative:youtube:isolated")).toBeTruthy();
  expect(nodes.map(n => n.data.displayName)).toEqual(["youtube:a", "youtube:isolated", "합성 훅 이름", "합성 효능 이름", "원 이름"]);
  expect(elements.some(e => e.data.id.includes("missing"))).toBe(false);
  expect(fragmentToElements(fragment, taxonomyNames()).filter(e => e.group === "nodes").find(e => e.data.id === "Hook:synthetic_hook")?.data.displayName).toBe("synthetic_hook");
  for (const node of nodes) expect(GRAPH_LEGEND.some(group => group.items.some(item => item.color === node.data.color))).toBe(true);
});

it("maps nonempty schema labels and relationships one for one, with distinct layer colors", () => {
  const elements = schemaToElements(schema);
  const nodes = elements.filter(e => e.group === "nodes"); const edges = elements.filter(e => e.group === "edges");
  expect(nodes.length).toBeGreaterThan(0); expect(edges.length).toBeGreaterThan(0);
  expect(nodes).toHaveLength(schema.labels.length); expect(edges).toHaveLength(schema.relationships.length);
  expect(new Set(Object.values(LAYER_COLORS)).size).toBe(3);
  for (const label of schema.labels) {
    const node = nodes.find(n => n.data.id === label.label)!;
    expect(node.data.layer).toBe(label.layer); expect(node.data.color).toBe(LABEL_COLORS[label.label] ?? LAYER_COLORS[label.layer as 1 | 2 | 3]);
    expect(node.data.displayName).toBe(label.name_ko);
  }
  for (const edge of edges) {
    expect(nodes.some(n => n.data.id === edge.data.source)).toBe(true);
    expect(nodes.some(n => n.data.id === edge.data.target)).toBe(true);
  }
  expect(new Set(edges.map(e => e.data.id)).size).toBe(edges.length);
});

it("fetches with exact tenant header, encoding each ID before comma joining", async () => {
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(fragment))); vi.stubGlobal("fetch", fetch);
  expect(await getGraphFragment("synthetic", ["youtube:a/b?c", "instagram:한 글"])).toEqual(fragment);
  expect(fetch).toHaveBeenCalledExactlyOnceWith("/api/graph/fragment?ids=youtube%3Aa%2Fb%3Fc,instagram%3A%ED%95%9C%20%EA%B8%80", { headers: { "X-Tenant-Id": "synthetic" } });
});
it.each([0, 31, 45])("rejects %i IDs without fetching", async count => {
  const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
  await expect(getGraphFragment("synthetic", Array.from({ length: count }, (_, i) => `youtube:${i}`))).rejects.toMatchObject({ code: "GRAPH_IDS_INVALID" });
  expect(fetch).not.toHaveBeenCalled();
});
it.each([[422, '{"detail":"GRAPH_IDS_INVALID"}', "GRAPH_IDS_INVALID"], [503, '{"detail":"GRAPH_UNAVAILABLE"}', "GRAPH_UNAVAILABLE"], [500, '{"detail":"GRAPH_QUERY_FAILED"}', "GRAPH_QUERY_FAILED"], [201, '{}', null], [500, 'not JSON', null], [422, '{"detail":[]}', null]] as const)("preserves non-200 status %i and string error codes", async (status, body, code) => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body, { status })));
  const result = getGraphFragment("synthetic", ["youtube:a"]);
  await expect(result).rejects.toBeInstanceOf(ApiError); await expect(result).rejects.toMatchObject({ status, code });
});

it("groups the legend into layers and node kinds without losing any colors", () => {
  expect(GRAPH_LEGEND.map(group => group.title)).toEqual(["층", "노드 종류"]);
  expect(GRAPH_LEGEND[0].items.map(item => item.color)).toEqual(Object.values(LAYER_COLORS));
  expect(new Set(GRAPH_LEGEND[1].items.map(item => item.color))).toEqual(new Set(Object.values(LABEL_COLORS)));
});

it("exports fixed zoom limits and a Korean creative label", async () => {
  const { ZOOM_LIMITS, NODE_LABEL_NAMES } = await import("../lib/graph");
  expect(ZOOM_LIMITS).toEqual({ min: 0.3, max: 2.5 });
  expect(ZOOM_LIMITS.min).toBeLessThan(ZOOM_LIMITS.max);
  expect(NODE_LABEL_NAMES.Creative).toBe("광고 소재");
});
it("finds the last graph command across all turns without mutating input", async () => {
  const { latestGraphIds } = await import("../lib/graph");
  const graph = (ids: string[]): import("../lib/types").UiCommand => ({ kind: "show_graph_fragment", data: { evidence_ids: ids } });
  const input = [{ commands: [graph(["youtube:a"]), graph(["youtube:b"])] }, { commands: [graph(["youtube:c", "youtube:d"])] }, { commands: [] }];
  const snapshot = JSON.stringify(input);
  expect(latestGraphIds(input)).toEqual(["youtube:c", "youtube:d"]);
  expect(latestGraphIds(input.slice(0, 1))).toEqual(["youtube:b"]);
  expect(latestGraphIds([])).toBeNull(); expect(latestGraphIds([{ commands: [] }])).toBeNull();
  expect(latestGraphIds([{ commands: [graph([])] }])).toEqual([]);
  expect(JSON.stringify(input)).toBe(snapshot);
});
it("adds translated relationship names while retaining raw types and unknown names", () => {
  const input = { ...fragment, edges: [...fragment.edges, { source: "creative:youtube:a", target: "Hook:synthetic_hook", type: "SYNTHETIC_UNKNOWN" }] };
  const snapshot = JSON.stringify(input);
  const edges = fragmentToElements(input, taxonomyNames(schema)).filter(element => element.group === "edges");
  expect(edges.map(edge => [edge.data.type, edge.data.typeName])).toEqual([["USES_HOOK", "훅 사용"], ["CLAIMS", "주장"], ["SYNTHETIC_UNKNOWN", "SYNTHETIC_UNKNOWN"]]);
  expect(schemaToElements(schema).filter(element => element.group === "edges").map(edge => edge.data.typeName)).toEqual(["홍보", "피드백 대상"]);
  expect(JSON.stringify(input)).toBe(snapshot);
});

it("exports the exact approved layer and kind fill and border palettes", () => {
  expect(LAYER_COLORS).toEqual({ 1: "#1D9E75", 2: "#378ADD", 3: "#7F77DD" });
  expect(LAYER_BORDER_COLORS).toEqual({ 1: "#0F6E56", 2: "#185FA5", 3: "#534AB7" });
  expect(LABEL_COLORS).toEqual({ Brand: "#7F77DD", Product: "#1D9E75", Efficacy: "#EF9F27", Creative: "#378ADD", Other: "#888780" });
  expect(LABEL_BORDER_COLORS).toEqual({ Brand: "#534AB7", Product: "#0F6E56", Efficacy: "#854F0B", Creative: "#185FA5", Other: "#5F5E5A" });
});
it("colors every schema node by layer including a brand instead of by kind", () => {
  const input: SchemaResponse = { ...schema, labels: [...schema.labels, { label: "Brand", layer: 1, name_ko: "브랜드" }] };
  const nodes = schemaToElements(input).filter(element => element.group === "nodes");
  for (const label of input.labels) {
    const node = nodes.find(node => node.data.id === label.label)!;
    expect(node.data.color).toBe(LAYER_COLORS[label.layer as 1 | 2 | 3]);
    expect(node.data.borderColor).toBe(LAYER_BORDER_COLORS[label.layer as 1 | 2 | 3]);
    expect(node.data.degree).toBeUndefined();
  }
  expect(nodes.find(node => node.data.label === "Brand")!.data.color).not.toBe(LABEL_COLORS.Brand);
});
it("colors fragment kinds and counts incident endpoints including isolated and self-linked nodes", () => {
  const input: GraphFragment = {
    nodes: ["Brand", "Product", "Efficacy", "Creative", "Hook", "Angle"].map(label => ({ id: label, label, name: "합성", props: {} })),
    edges: [{ source: "Brand", target: "Product", type: "OWNS" }, { source: "Product", target: "Efficacy", type: "HAS_EFFICACY" }, { source: "Creative", target: "Product", type: "PROMOTES" }, { source: "Hook", target: "Hook", type: "ABOUT" }], missing: [],
  };
  const nodes = fragmentToElements(input, taxonomyNames()).filter(element => element.group === "nodes");
  for (const [label, kind, degree] of [["Brand", "Brand", 1], ["Product", "Product", 3], ["Efficacy", "Efficacy", 1], ["Creative", "Creative", 1], ["Hook", "Other", 2], ["Angle", "Other", 0]] as const) {
    const node = nodes.find(node => node.data.id === label)!;
    expect(node.data.color).toBe(LABEL_COLORS[kind]);
    expect(node.data.borderColor).toBe(LABEL_BORDER_COLORS[kind]);
    expect(node.data.degree).toBe(degree);
  }
});
it("keeps fragment and schema JSON unchanged when adding presentation fields", () => {
  const beforeFragment = JSON.stringify(fragment), beforeSchema = JSON.stringify(schema);
  fragmentToElements(fragment, taxonomyNames(schema)); schemaToElements(schema);
  expect(JSON.stringify(fragment)).toBe(beforeFragment); expect(JSON.stringify(schema)).toBe(beforeSchema);
});
it("lists the five kind colors with their Korean names in explicit order", () => {
  expect(GRAPH_LEGEND[1].items.map(item => item.name)).toEqual(["브랜드", "제품", "효능", "광고 소재", "그 밖"]);
  expect(GRAPH_LEGEND[1].items.map(item => item.color)).toEqual([LABEL_COLORS.Brand, LABEL_COLORS.Product, LABEL_COLORS.Efficacy, LABEL_COLORS.Creative, LABEL_COLORS.Other]);
});
