import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { GraphPanel } from "../components/GraphPanel";
import { SchemaView } from "../components/SchemaView";
import { GraphCanvas, GraphLegend } from "../components/GraphCanvas";
import { NodeDetail } from "../components/NodeDetail";
import { CommandSlot } from "../components/CommandSlot";
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
  expect(screen.getByLabelText("그래프 범례")).toBeTruthy();
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
  for (const text of ["Creative", "합성 노드", "synthetic_flag", "false", "synthetic_nested"]) expect(detail.textContent).toContain(text);
  expect(detail.textContent).not.toContain("latest_view_count"); expect(detail.textContent).not.toContain("creative:youtube:a");
  const link = within(detail).queryByRole("link");
  if (url.startsWith("http")) { expect(link?.getAttribute("href")).toBe(url); expect(link?.getAttribute("rel")).toBe("noopener noreferrer"); }
  else expect(link).toBeNull();
});
it("renders graph command buttons only with a callback and passes the exact command IDs", () => {
  const commands: Extract<UiCommand, { kind: "show_graph_fragment" }>[] = [{ kind: "show_graph_fragment", data: { evidence_ids: ["youtube:a"] } }, { kind: "show_graph_fragment", data: { evidence_ids: ["youtube:b", "youtube:c"] } }];
  const open = vi.fn(); const { rerender } = render(<CommandSlot commands={commands} />);
  expect(screen.queryByRole("button", { name: "근거 그래프 보기" })).toBeNull();
  rerender(<CommandSlot commands={commands} onOpenGraph={open} />);
  const buttons = screen.getAllByRole("button", { name: "근거 그래프 보기" }); expect(buttons).toHaveLength(2);
  fireEvent.click(buttons[1]); expect(open).toHaveBeenCalledExactlyOnceWith(commands[1].data.evidence_ids);
  rerender(<CommandSlot commands={[]} onOpenGraph={open} />); expect(screen.queryByRole("button", { name: "근거 그래프 보기" })).toBeNull();
});
it("switches page tabs, preserves conversation and opens the command graph with the selected tenant", async () => {
  const command: UiCommand = { kind: "show_graph_fragment", data: { evidence_ids: ["youtube:a"] } };
  const fetch = vi.fn().mockImplementation((url: string) => {
    if (url === "/api/workspaces") return Promise.resolve(new Response(JSON.stringify({ workspaces: [{ tenant_id: "synthetic", display_name: "합성 공간", brand: null, product_name: null }], image_enabled: false })));
    if (url === "/api/ask") return Promise.resolve(new Response(`event: ui_command\ndata: ${JSON.stringify(command)}\n\nevent: token\ndata: {"text":"합성 응답"}\n\n`));
    return Promise.resolve(new Response(JSON.stringify(url === "/api/graph/schema" ? schema : fragment)));
  }); vi.stubGlobal("fetch", fetch); render(<Page />);
  await screen.findByLabelText("작업 공간");
  fireEvent.click(screen.getByRole("tab", { name: "전체 스키마" }));
  expect(screen.getByText("대화 탭에서 작업 공간을 선택하세요.")).toBeTruthy();
  fireEvent.click(screen.getByRole("tab", { name: "대화" }));
  fireEvent.change(screen.getByLabelText("작업 공간"), { target: { value: "synthetic" } });
  fireEvent.change(screen.getByLabelText("요청"), { target: { value: "합성 요청" } }); fireEvent.click(screen.getByRole("button", { name: "전송" }));
  await screen.findByText("합성 응답"); fireEvent.click(screen.getByRole("button", { name: "근거 그래프 보기" }));
  await waitFor(() => expect(cy.create).toHaveBeenCalledTimes(1));
  expect(fetch).toHaveBeenCalledWith("/api/graph/fragment?ids=youtube%3Aa", { headers: { "X-Tenant-Id": "synthetic" } });
  fireEvent.click(screen.getByRole("tab", { name: "전체 스키마" }));
  expect(screen.getByRole("tab", { name: "전체 스키마" }).getAttribute("aria-selected")).toBe("true");
  await waitFor(() => expect(cy.create).toHaveBeenCalledTimes(2));
  fireEvent.click(screen.getByRole("tab", { name: "대화" })); expect(screen.getByText("합성 응답")).toBeTruthy();
});

it("renders separate layer and node kind legend groups", () => {
  render(<GraphLegend />);
  const legend = screen.getByLabelText("그래프 범례");
  expect(within(legend).getAllByRole("heading").map(node => node.textContent)).toEqual(["층", "노드 종류"]);
  expect(within(legend).getAllByRole("list").map(list => Array.from(list.children).map(node => node.textContent))).toEqual([
    ["1층 · 제품 지식", "2층 · 광고 관찰", "3층 · 피드백"], ["제품", "광고 소재"],
  ]);
});
it("uses smaller labels and spreads cose nodes with built-in layout options", async () => {
  render(<GraphCanvas elements={[]} onNodeClick={vi.fn()} />);
  await waitFor(() => expect(cy.create).toHaveBeenCalledTimes(1));
  const options = cy.create.mock.calls[0][0];
  const node = options.style.find((item: { selector: string }) => item.selector === "node").style;
  const edge = options.style.find((item: { selector: string }) => item.selector === "edge").style;
  expect(node["font-size"]).toBeGreaterThanOrEqual(9); expect(node["font-size"]).toBeLessThanOrEqual(10);
  expect(node["text-margin-y"]).toBeGreaterThanOrEqual(0); expect(node["text-margin-y"]).toBeLessThan(7);
  expect(edge["font-size"]).toBe(7);
  expect(options.layout.name).toBe("cose");
  expect(options.layout.nodeRepulsion).toBeGreaterThan(2048);
  expect(options.layout.idealEdgeLength).toBeGreaterThan(32);
  expect(options.layout.nodeOverlap).toBeGreaterThan(4);
});
