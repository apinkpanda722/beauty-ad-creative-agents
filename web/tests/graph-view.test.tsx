import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { GraphPanel } from "../components/GraphPanel";
import { SchemaView } from "../components/SchemaView";
import { GraphCanvas } from "../components/GraphCanvas";
import { fragmentToElements, LAYER_COLORS, type GraphElement } from "../lib/graph";
import { taxonomyNames } from "../lib/taxonomy";
import { NodeDetail } from "../components/NodeDetail";
import { ResultsView } from "../components/results/ResultsView";
import Page from "../app/page";
import type { GraphFragment, SchemaResponse, UiCommand } from "../lib/types";

const cy = vi.hoisted(() => ({ create: vi.fn(), destroy: vi.fn(), on: vi.fn() }));
vi.mock("cytoscape", () => ({ default: cy.create }));
beforeEach(() => { cy.create.mockReset().mockReturnValue({ destroy: cy.destroy, on: cy.on }); cy.destroy.mockReset(); cy.on.mockReset(); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const schema: SchemaResponse = { labels: [{ label: "Creative", layer: 2, name_ko: "합성 소재" }], relationships: [], taxonomy: { hook_type: [], angle: [], format: [] }, claims: [] };
const fragment: GraphFragment = { nodes: [{ id: "creative:youtube:a", label: "Creative", name: "합성 노드", props: { url: "https://example.test/a", latest_view_count: 42 } }], edges: [], missing: ["youtube:b"] };
function stubFetch(value: GraphFragment | SchemaResponse = fragment) {
  const fetch = vi.fn().mockImplementation((url: string) => Promise.resolve(new Response(JSON.stringify(url === "/api/graph/schema" ? schema : value))));
  vi.stubGlobal("fetch", fetch); return fetch;
}

it("loads fragment, creates cose canvas, shows missing and node details, and destroys on unmount", async () => {
  let resolve!: (r: Response) => void;
  const fetch = stubFetch(); fetch.mockImplementation((url: string) => url === "/api/graph/schema" ? Promise.resolve(new Response(JSON.stringify(schema))) : new Promise<Response>(r => { resolve = r; }));
  const { unmount } = render(<GraphPanel tenantId="synthetic" ids={["youtube:a", "youtube:b"]} />);
  expect(screen.getByRole("status").textContent).toContain("불러오는 중"); expect(cy.create).not.toHaveBeenCalled();
  await act(async () => resolve(new Response(JSON.stringify(fragment))));
  await waitFor(() => expect(cy.create).toHaveBeenCalledTimes(1));
  expect(screen.getByText("그래프에 아직 없는 소재 1건")).toBeTruthy();
  expect(screen.queryByLabelText("그래프 범례")).toBeNull();
  expect(screen.getByRole("group", { name: "층 필터" })).toBeTruthy();
  expect(screen.getByRole("group", { name: "노드 종류 필터" })).toBeTruthy();
  const options = cy.create.mock.calls[0][0]; expect(options.container).toBe(screen.getByLabelText("그래프 캔버스"));
  expect(options.layout.name).toBe("cose"); expect(options.elements).toHaveLength(1);
  expect(cy.on.mock.calls[0].slice(0, 2)).toEqual(["tap", "node"]);
  act(() => cy.on.mock.calls[0][2]({ target: { id: () => fragment.nodes[0].id } }));
  expect(screen.getByRole("complementary", { name: "노드 상세" }).textContent).toContain("42");
  unmount(); expect(cy.destroy).toHaveBeenCalledTimes(1);
});

it.each(["fragment", "schema"] as const)("shows empty %s without creating a canvas", async mode => {
  vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => Promise.resolve(new Response(JSON.stringify(
    url === "/api/graph/schema" ? { ...schema, labels: mode === "schema" ? [] : schema.labels } : { nodes: [], edges: [], missing: ["youtube:a"] },
  )))));
  render(mode === "fragment" ? <GraphPanel tenantId="synthetic" ids={["youtube:a"]} /> : <SchemaView tenantId="synthetic" />);
  expect(await screen.findByText("표시할 노드가 없습니다")).toBeTruthy(); expect(cy.create).not.toHaveBeenCalled();
  if (mode === "fragment") expect(screen.getByText("그래프에 아직 없는 소재 1건")).toBeTruthy();
});
it.each(["fragment", "schema"] as const)("retries %s errors with status and code, then destroys a successful canvas", async mode => {
  const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response('{"detail":"GRAPH_UNAVAILABLE"}', { status: 503 }))); vi.stubGlobal("fetch", fetch);
  const { unmount } = render(mode === "fragment" ? <GraphPanel tenantId="synthetic" ids={["youtube:a"]} /> : <SchemaView tenantId="synthetic" />);
  expect(screen.getByRole("status").textContent).toContain("불러오는 중");
  expect((await screen.findByRole("alert")).textContent).toContain("GRAPH_UNAVAILABLE");
  fetch.mockImplementation((url: string) => Promise.resolve(new Response(JSON.stringify(url === "/api/graph/schema" ? schema : fragment))));
  const previous = fetch.mock.calls.length; fireEvent.click(screen.getByRole("button", { name: "다시 시도" }));
  await waitFor(() => expect(cy.create).toHaveBeenCalledTimes(1)); expect(fetch.mock.calls.length).toBeGreaterThan(previous);
  if (mode === "schema") expect(cy.create.mock.calls[0][0].layout.name).toBe("breadthfirst");
  unmount(); expect(cy.destroy).toHaveBeenCalledTimes(1);
});
it("ignores a fragment response arriving after unmount", async () => {
  let resolve!: (r: Response) => void;
  const fetch = stubFetch(); fetch.mockImplementation((url: string) => url === "/api/graph/schema" ? Promise.resolve(new Response(JSON.stringify(schema))) : new Promise<Response>(r => { resolve = r; }));
  const { unmount } = render(<GraphPanel tenantId="synthetic" ids={["youtube:a"]} />); unmount();
  await act(async () => resolve(new Response(JSON.stringify(fragment)))); expect(cy.create).not.toHaveBeenCalled();
});
it.each(["fragment", "schema"] as const)("ignores old %s responses and clears selection when the tenant changes", async mode => {
  let resolve!: (r: Response) => void;
  const fetch = vi.fn().mockImplementation((url: string, options: { headers: { "X-Tenant-Id": string } }) => {
    if (options.headers["X-Tenant-Id"] === "old" && (mode === "schema" || url !== "/api/graph/schema")) return new Promise<Response>(r => { resolve = r; });
    return Promise.resolve(new Response(JSON.stringify(url === "/api/graph/schema" ? schema : fragment)));
  }); vi.stubGlobal("fetch", fetch);
  const view = (tenantId: string) => mode === "fragment" ? <GraphPanel tenantId={tenantId} ids={["youtube:a"]} /> : <SchemaView tenantId={tenantId} />;
  const { rerender } = render(view("old")); rerender(view("new"));
  await waitFor(() => expect(cy.create).toHaveBeenCalledTimes(1));
  await act(async () => resolve(new Response(JSON.stringify(mode === "schema" ? { ...schema, labels: [] } : { nodes: [], edges: [], missing: [] }))));
  expect(screen.queryByText("표시할 노드가 없습니다")).toBeNull(); expect(cy.create).toHaveBeenCalledTimes(1);
  act(() => cy.on.mock.calls[0][2]({ target: { id: () => mode === "schema" ? "Creative" : fragment.nodes[0].id } }));
  expect(screen.getByRole("complementary", { name: "노드 상세" }).textContent).toContain(mode === "schema" ? "합성 소재" : "합성 노드");
  rerender(view("third")); expect(screen.queryByRole("complementary", { name: "노드 상세" })).toBeNull();
  await waitFor(() => expect(cy.create).toHaveBeenCalledTimes(2));
  expect(screen.getByText("노드를 선택하면 상세 정보를 표시합니다.")).toBeTruthy(); expect(cy.destroy).toHaveBeenCalledTimes(1);
});
it("does not initialize a canvas if unmounted before the dynamic import resolves", async () => {
  const { unmount } = render(<GraphCanvas elements={[]} onNodeClick={vi.fn()} />); unmount();
  await act(async () => { await Promise.resolve(); }); expect(cy.create).not.toHaveBeenCalled(); expect(cy.destroy).not.toHaveBeenCalled();
});
it("destroys and replaces canvas when elements change", async () => {
  const callback = vi.fn(); const { rerender, unmount } = render(<GraphCanvas elements={[]} onNodeClick={callback} />);
  await waitFor(() => expect(cy.create).toHaveBeenCalledTimes(1));
  rerender(<GraphCanvas elements={[{ group: "nodes", data: { ...fragment.nodes[0], displayName: "합성", layer: 2, color: "#000000" } }]} onNodeClick={callback} />);
  await waitFor(() => expect(cy.create).toHaveBeenCalledTimes(2)); expect(cy.destroy).toHaveBeenCalledTimes(1);
  unmount(); expect(cy.destroy).toHaveBeenCalledTimes(2);
});
it.each(["https://example.test/a", "http://example.test/a", "javascript:alert(1)", "data:text/html,synthetic"])("renders only server props and safe URL links: %s", url => {
  render(<NodeDetail node={{ ...fragment.nodes[0], props: { url, synthetic_flag: false, synthetic_nested: { count: 2 } } }} />);
  const detail = screen.getByRole("complementary", { name: "노드 상세" });
  for (const text of ["광고 소재", "합성 노드", "synthetic_flag", "false", "synthetic_nested"]) expect(detail.textContent).toContain(text);
  expect(detail.textContent).not.toContain("latest_view_count"); expect(detail.textContent).not.toContain("creative:youtube:a");
  const link = within(detail).queryByRole("link");
  if (url.startsWith("http")) { expect(link?.getAttribute("href")).toBe(url); expect(link?.getAttribute("rel")).toBe("noopener noreferrer"); }
  else expect(link).toBeNull();
});
it("renders graph command buttons only with a callback and passes the exact command IDs", () => {
  const commands: Extract<UiCommand, { kind: "show_graph_fragment" }>[] = [{ kind: "show_graph_fragment", data: { evidence_ids: ["youtube:a"] } }, { kind: "show_graph_fragment", data: { evidence_ids: ["youtube:b", "youtube:c"] } }];
  const open = vi.fn(); const { rerender } = render(<ResultsView commands={commands} />);
  expect(screen.queryByRole("button", { name: "근거 그래프 보기" })).toBeNull();
  rerender(<ResultsView commands={commands} onOpenGraph={open} />);
  const buttons = screen.getAllByRole("button", { name: "근거 그래프 보기" }); expect(buttons).toHaveLength(2);
  fireEvent.click(buttons[1]); expect(open).toHaveBeenCalledExactlyOnceWith(commands[1].data.evidence_ids);
  rerender(<ResultsView commands={[]} onOpenGraph={open} />); expect(screen.queryByRole("button", { name: "근거 그래프 보기" })).toBeNull();
});
it("switches page tabs, preserves conversation and opens the command graph with the selected tenant", async () => {
  const command: UiCommand = { kind: "show_graph_fragment", data: { evidence_ids: ["youtube:a"] } };
  const fetch = vi.fn().mockImplementation((url: string) => {
    if (url === "/api/workspaces") return Promise.resolve(new Response(JSON.stringify({ workspaces: [{ tenant_id: "synthetic", display_name: "합성 공간", brand: null, product_name: null }], image_enabled: false })));
    if (url === "/api/ask") return Promise.resolve(new Response(`event: ui_command\ndata: ${JSON.stringify(command)}\n\nevent: token\ndata: {"text":"합성 응답"}\n\n`));
    return Promise.resolve(new Response(JSON.stringify(url === "/api/graph/schema" ? schema : fragment)));
  }); vi.stubGlobal("fetch", fetch); render(<Page />);
  await screen.findByLabelText("작업 공간");
  fireEvent.click(screen.getByRole("button", { name: "지식 그래프" }));
  expect(screen.getByText("상단 바에서 작업 공간을 선택하세요.")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "광고 기획" }));
  fireEvent.click(screen.getByRole("button", { name: "작업 공간" }));
  fireEvent.click(await screen.findByRole("option", { name: /합성 공간/ }));
  fireEvent.change(screen.getByLabelText("요청"), { target: { value: "합성 요청" } }); fireEvent.click(screen.getByRole("button", { name: "기획하기" }));
  await screen.findByText("합성 응답"); fireEvent.click(screen.getByRole("button", { name: "근거 그래프 보기" }));
  await waitFor(() => expect(cy.create).toHaveBeenCalledTimes(1));
  expect(fetch).toHaveBeenCalledWith("/api/graph/fragment?ids=youtube%3Aa", { headers: { "X-Tenant-Id": "synthetic" } });
  fireEvent.click(screen.getByRole("tab", { name: "스키마" }));
  expect(screen.getByRole("button", { name: "지식 그래프" }).getAttribute("aria-current")).toBe("page");
  await waitFor(() => expect(cy.create).toHaveBeenCalledTimes(2));
  fireEvent.click(screen.getByRole("button", { name: "광고 기획" })); expect(screen.getByText("합성 응답")).toBeTruthy();
});

it("merges the legend colors into the layer and kind filters", async () => {
  const input: SchemaResponse = { ...schema, labels: [
    { label: "Creative", layer: 2, name_ko: "광고 소재" }, { label: "Product", layer: 1, name_ko: "제품" }, { label: "Feedback", layer: 3, name_ko: "피드백" },
  ] };
  const path: GraphFragment = { nodes: input.labels.map(label => ({ id: label.label, label: label.label, name: label.name_ko, props: {} })), edges: [], missing: [] };
  vi.stubGlobal("fetch", vi.fn((url: string) => Promise.resolve(new Response(JSON.stringify(url === "/api/graph/schema" ? input : path)))));
  const view = render(<SchemaView tenantId="synthetic" />);
  await waitFor(() => expect(cy.create).toHaveBeenCalledTimes(1));
  const layerButtons = within(screen.getByRole("group", { name: "층 필터" })).getAllByRole("button");
  expect(layerButtons.map(button => button.textContent)).toEqual(["1층 · 제품 지식", "2층 · 광고 관찰", "3층 · 피드백"]);
  for (const [index, layer] of ([1, 2, 3] as const).entries()) {
    const dot = layerButtons[index].querySelector<HTMLElement>('span[aria-hidden="true"].gs-graph-dot');
    expect(dot).toBeTruthy(); expect(dot!.style.backgroundColor).toBe(rgb(LAYER_COLORS[layer]));
  }
  expect(screen.queryByLabelText("그래프 범례")).toBeNull();
  for (const title of ["층", "노드 종류"]) expect(screen.queryByRole("heading", { name: title, level: 4 })).toBeNull();
  view.unmount();
  render(<GraphPanel tenantId="synthetic" ids={["youtube:a"]} />);
  await waitFor(() => expect(cy.create).toHaveBeenCalledTimes(2));
  for (const button of within(screen.getByRole("group", { name: "층 필터" })).getAllByRole("button")) expect(button.querySelector(".gs-graph-dot")).toBeNull();
  const chips = within(screen.getByRole("group", { name: "노드 종류 필터" })).getAllByRole("button");
  expect(chips.map(button => button.textContent)).toEqual(["광고 소재", "제품", "피드백"]);
  const nodes = fragmentToElements(path, taxonomyNames(input)).filter(element => element.group === "nodes");
  for (const [index, label] of ["Creative", "Product", "Feedback"].entries()) {
    const dot = chips[index].querySelector<HTMLElement>('span[aria-hidden="true"].gs-graph-dot');
    expect(dot).toBeTruthy(); expect(dot!.style.backgroundColor).toBe(rgb(nodes.find(node => node.data.label === label)!.data.color));
  }
  expect(screen.queryByLabelText("그래프 범례")).toBeNull();
  for (const title of ["층", "노드 종류"]) expect(screen.queryByRole("heading", { name: title, level: 4 })).toBeNull();
});
it("uses readable label sizes, outlines and edge pills and spreads cose nodes with built-in layout options", async () => {
  render(<GraphCanvas elements={[]} onNodeClick={vi.fn()} />);
  await waitFor(() => expect(cy.create).toHaveBeenCalledTimes(1));
  const options = cy.create.mock.calls[0][0];
  const node = options.style.find((item: { selector: string }) => item.selector === "node").style;
  const edge = options.style.find((item: { selector: string }) => item.selector === "edge").style;
  expect(node["font-size"]).toBe(12);
  expect(node["text-margin-y"]).toBeGreaterThanOrEqual(0); expect(node["text-margin-y"]).toBeLessThan(7);
  expect(edge["font-size"]).toBe(11);
  expect(node["text-outline-width"]).toBeGreaterThan(0); expect(node["text-outline-opacity"]).toBe(1);
  expect(edge["text-background-opacity"]).toBe(1); expect(edge["text-background-shape"]).toBe("roundrectangle");
  expect(parseFloat(edge["text-background-padding"])).toBeGreaterThanOrEqual(2); expect(parseFloat(edge["text-background-padding"])).toBeLessThanOrEqual(3);
  expect(edge["arrow-scale"]).toBeGreaterThanOrEqual(1); expect(edge["target-arrow-shape"]).toBe("triangle");
  expect(edge["curve-style"]).toBe("unbundled-bezier"); expect(edge.width).toBeGreaterThan(1.5);
  expect(options.layout.fit).toBe(true); expect(options.layout.padding).toBeGreaterThanOrEqual(40);
  expect(options.layout.name).toBe("cose");
  expect(options.layout.nodeRepulsion).toBeGreaterThan(2048);
  expect(options.layout.idealEdgeLength).toBeGreaterThan(32);
  expect(options.layout.nodeOverlap).toBeGreaterThan(4);
});

it("sets zoom bounds, clamps button changes, follows zoom events and fits the graph", async () => {
  const { ZOOM_LIMITS } = await import("../lib/graph");
  let level = 1;
  const zoom = vi.fn((value?: number) => { if (value !== undefined) level = value; return level; });
  const fit = vi.fn();
  cy.create.mockReturnValue({ on: cy.on, destroy: cy.destroy, zoom, fit });
  render(<GraphCanvas elements={[]} onNodeClick={vi.fn()} />);
  await waitFor(() => expect(cy.create).toHaveBeenCalledTimes(1));
  const options = cy.create.mock.calls[0][0];
  expect(options.minZoom).toBe(ZOOM_LIMITS.min); expect(options.maxZoom).toBe(ZOOM_LIMITS.max); expect(options.wheelSensitivity).toBe(0.2);
  expect(cy.on.mock.calls[0].slice(0, 2)).toEqual(["tap", "node"]);
  const changed = cy.on.mock.calls.find(call => call[0] === "zoom")![1];
  const plus = screen.getByRole("button", { name: "확대" }) as HTMLButtonElement;
  const minus = screen.getByRole("button", { name: "축소" }) as HTMLButtonElement;
  for (const name of ["확대", "축소", "화면에 맞춤"]) expect(screen.getByRole("button", { name }).querySelector('svg[aria-hidden="true"]')).toBeTruthy();
  act(() => { level = 2.49; changed(); }); fireEvent.click(plus);
  expect(level).toBe(ZOOM_LIMITS.max); expect(plus.disabled).toBe(true); expect(minus.disabled).toBe(false);
  act(() => { level = 0.31; changed(); }); fireEvent.click(minus);
  expect(level).toBe(ZOOM_LIMITS.min); expect(minus.disabled).toBe(true); expect(plus.disabled).toBe(false);
  act(() => { level = 1; changed(); }); expect(minus.disabled).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "화면에 맞춤" })); expect(fit).toHaveBeenCalledTimes(1);
  expect(screen.getByLabelText("그래프 캔버스").style.height).toBe("");
  expect(options.style.find((item: { selector: string }) => item.selector === "edge").style.label).toBe("data(typeName)");
});
it("localizes detail keys, platforms and taxonomy values without changing the source", async () => {
  const { taxonomyNames } = await import("../lib/taxonomy");
  const names = taxonomyNames({ ...schema, taxonomy: { ...schema.taxonomy, hook_type: [{ value: "synthetic_hook", name: "합성 훅 이름", definition: "합성" }] } });
  const node = { ...fragment.nodes[0], props: { source: "youtube", url: "https://example.test/a", latest_view_count: 42, synthetic_unknown: false } };
  const snapshot = JSON.stringify(node);
  const { rerender } = render(<NodeDetail node={node} names={names} />);
  const detail = screen.getByRole("complementary", { name: "노드 상세" });
  for (const text of ["광고 소재", "원본 링크", "조회수", "출처", "YouTube", "synthetic_unknown", "false"]) expect(detail.textContent).toContain(text);
  expect(detail.textContent).not.toMatch(/Creative|latest_view_count/);
  expect(JSON.stringify(node)).toBe(snapshot);
  for (const [label, value, text] of [["Hook", "synthetic_hook", "합성 훅 이름"], ["Angle", "desire", "이상형 제시형"]]) {
    const input = { id: "synthetic", label, name: value, props: { value } }; const before = JSON.stringify(input);
    rerender(<NodeDetail node={input} names={names} />);
    expect(within(detail).getByText("값")).toBeTruthy(); expect(within(detail).getAllByText(text).length).toBeGreaterThan(0);
    expect(detail.textContent).not.toContain(value); expect(JSON.stringify(input)).toBe(before);
  }
});

function rgb(hex: string) {
  return `rgb(${[1, 3, 5].map(start => parseInt(hex.slice(start, start + 2), 16)).join(", ")})`;
}
function canvasStyles() {
  return cy.create.mock.calls.at(-1)![0].style as { selector: string; style: Record<string, unknown> }[];
}
it("fits the initial breadthfirst layout with label padding and extra spacing", async () => {
  render(<GraphCanvas elements={[]} layout="breadthfirst" onNodeClick={vi.fn()} />);
  await waitFor(() => expect(cy.create).toHaveBeenCalledTimes(1));
  const options = cy.create.mock.calls[0][0];
  expect(options.layout.name).toBe("breadthfirst"); expect(options.layout.fit).toBe(true);
  expect(options.layout.padding).toBeGreaterThanOrEqual(40); expect(options.layout.spacingFactor).toBeGreaterThan(1);
});
it("registers hover after tap and zoom and dims only outside the closed neighborhood", async () => {
  const keep = { id: "합성 이웃" };
  const addClass = vi.fn(), removeClass = vi.fn(), not = vi.fn(() => ({ addClass }));
  const elements = vi.fn(() => ({ not, removeClass }));
  cy.create.mockReturnValue({ on: cy.on, destroy: cy.destroy, elements });
  render(<GraphCanvas elements={[]} onNodeClick={vi.fn()} />);
  await waitFor(() => expect(cy.create).toHaveBeenCalledTimes(1));
  expect(cy.on.mock.calls.map(call => call[0])).toEqual(["tap", "zoom", "mouseover", "mouseout"]);
  expect(cy.on.mock.calls[0].slice(0, 2)).toEqual(["tap", "node"]);
  const over = cy.on.mock.calls.find(call => call[0] === "mouseover")!;
  const out = cy.on.mock.calls.find(call => call[0] === "mouseout")!;
  expect(over[1]).toBe("node"); expect(out[1]).toBe("node");
  expect(elements).not.toHaveBeenCalled();
  const closedNeighborhood = vi.fn(() => keep);
  act(() => over[2]({ target: { closedNeighborhood } }));
  expect(closedNeighborhood).toHaveBeenCalledTimes(1); expect(not).toHaveBeenCalledExactlyOnceWith(keep);
  expect(addClass).toHaveBeenCalledExactlyOnceWith("gs-dim"); expect(removeClass).not.toHaveBeenCalled();
  act(() => out[2]());
  expect(elements).toHaveBeenCalledTimes(2); expect(removeClass).toHaveBeenCalledExactlyOnceWith("gs-dim");
  expect(canvasStyles().find(item => item.selector === ".gs-dim")!.style.opacity).toBe(0.3);
});
it("skips absent ResizeObserver and does not manually fit or resize during initialization", async () => {
  vi.stubGlobal("ResizeObserver", undefined);
  const fit = vi.fn(), resize = vi.fn();
  cy.create.mockReturnValue({ on: cy.on, destroy: cy.destroy, zoom: () => 1, fit, resize });
  render(<GraphCanvas elements={[]} onNodeClick={vi.fn()} />);
  await waitFor(() => expect(cy.create).toHaveBeenCalledTimes(1));
  expect(fit).not.toHaveBeenCalled(); expect(resize).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "화면에 맞춤" }));
  expect(fit).toHaveBeenCalledTimes(1); expect(resize).not.toHaveBeenCalled();
});
it.each([true, false])("observes container size without fitting and disconnects, resize available: %s", async available => {
  let notify!: () => void;
  const observe = vi.fn(), disconnect = vi.fn(), resize = vi.fn(), fit = vi.fn();
  vi.stubGlobal("ResizeObserver", class {
    constructor(callback: () => void) { notify = callback; }
    observe = observe; disconnect = disconnect;
  });
  cy.create.mockReturnValue({ on: cy.on, destroy: cy.destroy, fit, ...(available ? { resize } : {}) });
  const { unmount } = render(<GraphCanvas elements={[]} onNodeClick={vi.fn()} />);
  await waitFor(() => expect(observe).toHaveBeenCalledExactlyOnceWith(screen.getByLabelText("그래프 캔버스")));
  expect(resize).not.toHaveBeenCalled(); expect(fit).not.toHaveBeenCalled();
  act(() => notify()); expect(resize).toHaveBeenCalledTimes(available ? 1 : 0); expect(fit).not.toHaveBeenCalled();
  unmount(); expect(disconnect).toHaveBeenCalledTimes(1);
});
it("scales degree nodes with the actual minimum and maximum without changing default nodes", async () => {
  const elements: GraphElement[] = [3, 0, 1].map((degree, index) => ({ group: "nodes", data: { ...fragment.nodes[0], id: String(index), displayName: "합성", color: LAYER_COLORS[2], layer: 2, degree } }));
  render(<GraphCanvas elements={elements} onNodeClick={vi.fn()} />);
  await waitFor(() => expect(cy.create).toHaveBeenCalledTimes(1));
  const style = canvasStyles().find(item => item.selector === "node[degree]")!.style;
  expect(style.width).toBe("mapData(degree, 0, 3, 24, 56)"); expect(style.height).toBe(style.width);
  const base = canvasStyles().find(item => item.selector === "node")!.style;
  expect(base.width).toBe(28); expect(base.height).toBe(28);
  expect(base["border-color"]).toBe("data(borderColor)"); expect(base["border-width"]).toBe(1.5);
});
it.each([{ degrees: [] }, { degrees: [2, 2] }, { degrees: [undefined, undefined] }])("omits degree mapping for uniform or missing degrees: %j", async ({ degrees }) => {
  const elements: GraphElement[] = degrees.map((degree, index) => ({ group: "nodes", data: { ...fragment.nodes[0], id: String(index), displayName: "합성", color: LAYER_COLORS[2], layer: 2, ...(degree === undefined ? {} : { degree }) } }));
  render(<GraphCanvas elements={elements} onNodeClick={vi.fn()} />);
  await waitFor(() => expect(cy.create).toHaveBeenCalledTimes(1));
  expect(canvasStyles().find(item => item.selector === "node[degree]")).toBeUndefined();
});
it("counts displayed nodes only and updates to zero with an empty canvas", async () => {
  const elements = fragmentToElements({ ...fragment, nodes: [...fragment.nodes, { ...fragment.nodes[0], id: "second" }], edges: [{ source: fragment.nodes[0].id, target: "second", type: "PROMOTES" }] }, taxonomyNames());
  const onNodeClick = vi.fn();
  const { rerender } = render(<GraphCanvas elements={elements} onNodeClick={onNodeClick} />);
  await waitFor(() => expect(cy.create).toHaveBeenCalledTimes(1));
  expect(screen.getByText("2개 표시").className).toBe("gs-graph-count");
  expect(screen.queryByText(/개 중/)).toBeNull();
  rerender(<GraphCanvas elements={[]} onNodeClick={onNodeClick} />);
  await waitFor(() => expect(cy.create).toHaveBeenCalledTimes(2));
  expect(screen.getByText("0개 표시")).toBeTruthy();
});
