import { afterEach, expect, it, vi } from "vitest";
import { ApiError, getGraphFragment } from "../lib/api";
import { fragmentToElements, schemaToElements, LAYER_COLORS, LABEL_COLORS, GRAPH_LEGEND } from "../lib/graph";
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
