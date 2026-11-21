import { useState } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { BrandNamesContext } from "../lib/brandNames";
import { DataTab } from "../components/graph/DataTab";
import { GraphPage } from "../components/graph/GraphPage";
import { GRAPH_TABS } from "../components/graph/tabs";
import { ApiError, getGraphNeighbors, getGraphOverview, getSchema, type GraphExploreResponse } from "../lib/api";
import { LABEL_COLORS, type GraphElement } from "../lib/graph";
import type { SchemaResponse } from "../lib/types";

vi.mock("../lib/api", async original => ({ ...await original<typeof import("../lib/api")>(), getGraphOverview: vi.fn(), getGraphNeighbors: vi.fn(), getSchema: vi.fn() }));
const canvas = vi.hoisted(() => ({ elements: [] as GraphElement[], select: (() => {}) as (id: string) => void }));
vi.mock("../components/GraphCanvas", async original => ({ ...await original<typeof import("../components/GraphCanvas")>(), GraphCanvas: ({ elements, onNodeClick }: { elements: GraphElement[]; onNodeClick: (id: string) => void }) => {
  canvas.elements = elements; canvas.select = onNodeClick;
  return <div aria-label="합성 캔버스">{elements.map(element => <span key={element.data.id}>{element.group === "nodes" ? element.data.displayName : element.data.typeName}</span>)}</div>;
} }));
const brand = { id: "Brand:synthetic", label: "Brand", name: "합성 브랜드", props: { name: "합성 브랜드" } };
const product = { id: "Product:synthetic:https://example.invalid/p", label: "Product", name: "합성 제품", props: { brand: "합성 브랜드", name_ko: "합성 제품" } };
const efficacy = { id: "Efficacy:synthetic", label: "Efficacy", name: "synthetic", props: { value: "synthetic" } };
const edge = { source: brand.id, target: product.id, type: "OWNS" };
const overview: GraphExploreResponse = { nodes: [brand, product], edges: [edge], truncated: false };
const schema: SchemaResponse = { labels: [], relationships: [], taxonomy: { hook_type: [], angle: [], format: [] }, claims: [{ value: "synthetic", name: "합성 효능" }] };
beforeEach(() => {
  vi.clearAllMocks(); canvas.elements = [];
  vi.mocked(getGraphOverview).mockResolvedValue(overview); vi.mocked(getSchema).mockResolvedValue(schema);
  vi.mocked(getGraphNeighbors).mockResolvedValue({ nodes: [product, efficacy], edges: [], truncated: false });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
async function ready() { await screen.findByLabelText("합성 캔버스"); }
function select(id: string) { act(() => canvas.select(id)); }
function Harness() {
  const [tab, setTab] = useState("schema");
  return <GraphPage tenantId="synthetic" pathIds={null} tab={tab} onTabChange={setTab} onPlan={vi.fn()} />;
}
it("registers the data tab in order, explains its meaning and mounts it only on selection", async () => {
  render(<Harness />);
  expect(GRAPH_TABS.map(tab => tab.id)).toEqual(["schema", "data", "path"]);
  expect(within(screen.getByRole("tablist", { name: "지식 그래프 보기" })).getAllByRole("tab").map(tab => tab.textContent)).toEqual(["스키마", "데이터", "근거 경로"]);
  expect(getGraphOverview).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("tab", { name: "데이터" })); await ready();
  const panel = screen.getByRole("tabpanel");
  expect(within(panel).getByText("공용 카탈로그(브랜드·제품·효능)를 먼저 보여 주고, 노드를 선택해 연결된 이웃을 펼칩니다.").className).toBe("gs-graph-note");
  expect(getGraphOverview).toHaveBeenCalledExactlyOnceWith("synthetic");
});
it("selects, expands the exact ID and merges nodes and edges without duplicates", async () => {
  vi.mocked(getGraphNeighbors).mockResolvedValue({ nodes: [brand, product, efficacy, efficacy], edges: [edge, edge], truncated: false });
  const snapshot = JSON.stringify(overview);
  render(<DataTab tenantId="synthetic" />); await ready();
  expect(canvas.elements).toHaveLength(3); expect(screen.queryByRole("button", { name: "이웃 펼치기" })).toBeNull();
  select(product.id);
  expect(within(screen.getByRole("complementary", { name: "노드 상세" })).getAllByText("합성 제품")).toHaveLength(2);
  const button = screen.getByRole("button", { name: "이웃 펼치기" });
  expect(button.compareDocumentPosition(screen.getByRole("complementary", { name: "노드 상세" })) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy();
  fireEvent.click(button);
  await waitFor(() => expect(canvas.elements).toHaveLength(4));
  expect(getGraphNeighbors).toHaveBeenCalledExactlyOnceWith("synthetic", product.id);
  expect((screen.getByRole("button", { name: "이웃 펼치기" }) as HTMLButtonElement).disabled).toBe(true);
  select(brand.id); expect((screen.getByRole("button", { name: "이웃 펼치기" }) as HTMLButtonElement).disabled).toBe(false);
  select(product.id); expect((screen.getByRole("button", { name: "이웃 펼치기" }) as HTMLButtonElement).disabled).toBe(true);
  expect(JSON.stringify(overview)).toBe(snapshot);
  expect(screen.getByLabelText("합성 캔버스").textContent).toContain("합성 효능");
});
it("reuses separate layer and kind filters and Korean detail names", async () => {
  vi.mocked(getGraphOverview).mockResolvedValue({ ...overview, nodes: [...overview.nodes, efficacy] });
  render(<DataTab tenantId="synthetic" />); await ready(); select(efficacy.id);
  const layers = screen.getByRole("group", { name: "층 필터" }); const kinds = screen.getByRole("group", { name: "노드 종류 필터" });
  expect(layers.parentElement).toBe(kinds.parentElement);
  expect(within(kinds).getAllByRole("button").map(button => button.textContent)).toEqual(["브랜드", "제품", "효능"]);
  expect(screen.getByRole("complementary").textContent).toContain("합성 효능");
  expect(document.body.textContent).not.toMatch(/Product|Brand|Efficacy|OWNS|source_url|name_ko/);
  fireEvent.click(within(kinds).getByRole("button", { name: "제품" })); expect(canvas.elements).toHaveLength(2);
  fireEvent.click(within(layers).getByRole("button", { name: "1층 · 제품 지식" })); expect(canvas.elements).toHaveLength(0);
  expect(screen.queryByRole("button", { name: "이웃 펼치기" })).toBeNull();
});
it.each(["overview", "neighbors"])("shows the truncation note for %s and keeps it after further expansion", async mode => {
  if (mode === "overview") vi.mocked(getGraphOverview).mockResolvedValue({ ...overview, truncated: true });
  else vi.mocked(getGraphNeighbors).mockResolvedValueOnce({ nodes: [product], edges: [], truncated: true });
  render(<DataTab tenantId="synthetic" />); await ready();
  if (mode === "neighbors") { select(product.id); fireEvent.click(screen.getByRole("button", { name: "이웃 펼치기" })); }
  await screen.findByText("일부만 표시합니다. 표시 상한을 넘는 노드는 보이지 않습니다.");
  select(brand.id); fireEvent.click(screen.getByRole("button", { name: "이웃 펼치기" }));
  await waitFor(() => expect(getGraphNeighbors).toHaveBeenCalledTimes(mode === "overview" ? 1 : 2));
  expect(screen.getByText("일부만 표시합니다. 표시 상한을 넘는 노드는 보이지 않습니다.")).toBeTruthy();
});
it("shows loading, empty response and retries overview with status and code", async () => {
  vi.mocked(getGraphOverview).mockRejectedValueOnce(new ApiError(503, "GRAPH_UNAVAILABLE")).mockResolvedValueOnce({ nodes: [], edges: [], truncated: false });
  render(<DataTab tenantId="synthetic" />); expect(screen.getByRole("status")).toBeTruthy();
  const alert = await screen.findByRole("alert"); expect(alert.textContent).toContain("503"); expect(alert.textContent).toContain("GRAPH_UNAVAILABLE");
  fireEvent.click(within(alert).getByRole("button", { name: "다시 시도" }));
  await screen.findByText("표시할 노드가 없습니다"); expect(getGraphOverview).toHaveBeenCalledTimes(2);
});
it("retries a failed neighbor request without losing existing nodes or marking it expanded", async () => {
  vi.mocked(getGraphNeighbors).mockRejectedValueOnce(new ApiError(500, "GRAPH_QUERY_FAILED"));
  render(<DataTab tenantId="synthetic" />); await ready(); select(product.id);
  fireEvent.click(screen.getByRole("button", { name: "이웃 펼치기" }));
  const alert = await screen.findByRole("alert"); expect(alert.textContent).toContain("500"); expect(alert.textContent).toContain("GRAPH_QUERY_FAILED");
  expect(canvas.elements).toHaveLength(3);
  fireEvent.click(within(alert).getByRole("button", { name: "다시 시도" }));
  await waitFor(() => expect(canvas.elements).toHaveLength(4));
  expect(getGraphNeighbors).toHaveBeenNthCalledWith(2, "synthetic", product.id);
  expect(getGraphOverview).toHaveBeenCalledTimes(1);
});
it("resets data and ignores old pending expansion when the workspace changes", async () => {
  let finish!: (value: GraphExploreResponse) => void;
  vi.mocked(getGraphNeighbors).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  const view = render(<DataTab tenantId="synthetic" />); await ready(); select(product.id);
  fireEvent.click(screen.getByRole("button", { name: "이웃 펼치기" })); expect(screen.getByRole("status")).toBeTruthy();
  vi.mocked(getGraphOverview).mockResolvedValue({ nodes: [brand], edges: [], truncated: false });
  view.rerender(<DataTab tenantId="other" />); await ready();
  await act(async () => finish({ nodes: [product, efficacy], edges: [edge], truncated: true }));
  expect(canvas.elements).toHaveLength(1); expect(getGraphOverview).toHaveBeenLastCalledWith("other");
  expect(screen.queryByRole("button", { name: "이웃 펼치기" })).toBeNull();
});
it("uses Korean fallbacks for unmapped classification values", async () => {
  const unknown = { id: "Hook:unknown", label: "Hook", name: "unknown", props: { value: "unknown" } };
  vi.mocked(getGraphOverview).mockResolvedValue({ nodes: [unknown], edges: [], truncated: false });
  render(<DataTab tenantId="synthetic" />); await ready(); select(unknown.id);
  expect(document.body.textContent).not.toMatch(/unknown|Hook|value/); expect(document.body.textContent).toContain("기타");
});
it("API clients forward tenant headers, encode the full ID and retain HTTP errors", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  const fetcher = vi.fn().mockImplementation(async () => new Response(JSON.stringify(overview), { status: 200 })); vi.stubGlobal("fetch", fetcher);
  expect(await actual.getGraphOverview("synthetic")).toEqual(overview);
  const id = "Product:합성:https://example.invalid/p?a=1&b=2#x";
  expect(await actual.getGraphNeighbors("synthetic", id)).toEqual(overview);
  expect(fetcher.mock.calls).toEqual([["/api/graph/overview", { headers: { "X-Tenant-Id": "synthetic" } }], [`/api/graph/neighbors?id=${encodeURIComponent(id)}`, { headers: { "X-Tenant-Id": "synthetic" } }]]);
  for (const request of [() => actual.getGraphOverview("synthetic"), () => actual.getGraphNeighbors("synthetic", id)]) {
    fetcher.mockResolvedValueOnce(new Response(JSON.stringify({ detail: "GRAPH_QUERY_FAILED" }), { status: 500 }));
    await expect(request()).rejects.toMatchObject({ name: "ApiError", status: 500, code: "GRAPH_QUERY_FAILED" });
    fetcher.mockResolvedValueOnce(new Response("", { status: 503 }));
    await expect(request()).rejects.toMatchObject({ name: "ApiError", status: 503, code: null });
  }
});

it("maps brand display names, preserves product names and wire objects, and falls back only for missing names", async () => {
  const nodes = [
    { id: "Brand:beauty_of_joseon", label: "Brand", name: "beauty_of_joseon", props: { name: "beauty_of_joseon", brand: "beauty_of_joseon" } },
    { id: "Brand:synthetic_x", label: "Brand", name: "synthetic_x", props: { name: "synthetic_x" } },
    { id: "Product:synthetic", label: "Product", name: "Synthetic Product", props: { name: "Synthetic Product", name_ko: "Synthetic Original", brand: "beauty_of_joseon" } },
    { id: "Brand:missing", label: "Brand", name: null, props: { name: null, brand: null } },
    { id: "Product:missing", label: "Product", name: null, props: { name: null, name_ko: null } },
  ];
  const data = { nodes, edges: [], truncated: false }; const snapshot = JSON.stringify(data);
  vi.mocked(getGraphOverview).mockResolvedValue(data);
  render(<BrandNamesContext.Provider value={new Map([["beauty_of_joseon", "조선미녀"]])}><DataTab tenantId="synthetic" /></BrandNamesContext.Provider>); await ready();
  for (const [index, expected] of [[0, "조선미녀"], [1, "synthetic x"], [2, "Synthetic Product"], [3, "정보 없음"], [4, "정보 없음"]] as const) {
    select(nodes[index].id); const panel = screen.getByRole("complementary", { name: "노드 상세" }); expect(panel.textContent).toContain(expected);
    const element = canvas.elements.find(element => element.group === "nodes" && element.data.id === nodes[index].id)!;
    expect(element.group === "nodes" && element.data.displayName).toBe(expected);
    if (index === 2) { expect(panel.textContent).toContain("Synthetic Original"); expect(panel.textContent).toContain("조선미녀"); expect(panel.textContent).not.toContain("정보 없음"); }
  }
  expect(JSON.stringify(data)).toBe(snapshot);
});
it("shows kind color dots only on data chips and preserves them when a kind is hidden", async () => {
  vi.mocked(getGraphOverview).mockResolvedValue({ ...overview, nodes: [brand, product, efficacy] });
  render(<DataTab tenantId="synthetic" />); await ready();
  const layers = screen.getByRole("group", { name: "층 필터" }), kinds = screen.getByRole("group", { name: "노드 종류 필터" });
  expect(layers.querySelector(".gs-graph-dot")).toBeNull(); expect(layers.classList.contains("gs-graph-segmented")).toBe(true);
  expect(within(kinds).getAllByRole("button").map(button => button.textContent)).toEqual(["브랜드", "제품", "효능"]);
  for (const [name, label] of [["브랜드", "Brand"], ["제품", "Product"], ["효능", "Efficacy"]]) {
    const chip = within(kinds).getByRole("button", { name });
    const expected = `rgb(${[1, 3, 5].map(start => parseInt(LABEL_COLORS[label].slice(start, start + 2), 16)).join(", ")})`;
    expect(chip.classList.contains("gs-graph-chip")).toBe(true);
    expect(chip.querySelector<HTMLElement>('span[aria-hidden="true"].gs-graph-dot')!.style.backgroundColor).toBe(expected);
    fireEvent.click(chip); expect(chip.getAttribute("aria-pressed")).toBe("false");
    expect(chip.querySelector<HTMLElement>(".gs-graph-dot")!.style.backgroundColor).toBe(expected);
    fireEvent.click(chip);
  }
  expect(screen.queryByLabelText("그래프 범례")).toBeNull();
});
