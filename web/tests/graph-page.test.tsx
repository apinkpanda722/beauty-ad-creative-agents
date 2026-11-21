import { useState } from "react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Page from "../app/page";
import { GraphPage } from "../components/graph/GraphPage";
import { GRAPH_TABS } from "../components/graph/tabs";
import { GraphPanel } from "../components/GraphPanel";
import { SchemaView } from "../components/SchemaView";
import { getGraphFragment, getSchema, getWorkspaces, postChatAsk } from "../lib/api";
import { fragmentToElements, schemaToElements } from "../lib/graph";
import { taxonomyNames } from "../lib/taxonomy";
import type { GraphFragment, SchemaResponse, SseFrame } from "../lib/types";

vi.mock("../lib/api", async original => ({ ...await original<typeof import("../lib/api")>(), getGraphFragment: vi.fn(), getSchema: vi.fn(), getWorkspaces: vi.fn(), postChatAsk: vi.fn() }));
const cy = vi.hoisted(() => ({ create: vi.fn(), on: vi.fn(), destroy: vi.fn(), zoom: vi.fn(() => 1), fit: vi.fn() }));
vi.mock("cytoscape", () => ({ default: cy.create }));
const schema: SchemaResponse = {
  labels: [{ label: "Product", name_ko: "제품", layer: 1 }, { label: "Creative", name_ko: "광고 소재", layer: 2 }, { label: "Hook", name_ko: "훅 유형", layer: 2 }, { label: "Feedback", name_ko: "피드백", layer: 3 }],
  relationships: [{ from: "Creative", to: "Product", type: "PROMOTES", layer: 2 }, { from: "Creative", to: "Hook", type: "USES_HOOK", layer: 2 }, { from: "Feedback", to: "Hook", type: "ABOUT", layer: 3 }],
  taxonomy: { hook_type: [{ value: "synthetic_hook", name: "합성 훅", definition: "합성" }], angle: [], format: [] }, claims: [],
};
const fragment: GraphFragment = {
  nodes: schema.labels.map(label => ({ id: label.label, label: label.label, name: label.name_ko, props: label.label === "Hook" ? { value: "synthetic_hook" } : {} })),
  edges: schema.relationships.map(edge => ({ source: edge.from, target: edge.to, type: edge.type })), missing: [],
};
beforeEach(() => {
  vi.clearAllMocks(); cy.create.mockReturnValue(cy);
  vi.mocked(getSchema).mockResolvedValue(schema); vi.mocked(getGraphFragment).mockResolvedValue(fragment);
  vi.mocked(getWorkspaces).mockResolvedValue({ workspaces: [{ tenant_id: "synthetic", display_name: "합성 공간", brand: null, product_name: null }], image_enabled: false });
  vi.mocked(postChatAsk).mockImplementation(async () => ({ threadId: "synthetic-thread", events: (async function* (): AsyncGenerator<SseFrame> {
    yield { event: "ui_command", data: { kind: "show_graph_fragment", data: { evidence_ids: ["youtube:a", "youtube:b"] } } };
    yield { event: "token", data: { text: "합성 결과" } };
  })() }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
function Harness({ pathIds = null, onPlan = vi.fn() }: { pathIds?: string[] | null; onPlan?: () => void }) {
  const [tab, setTab] = useState("schema");
  return <GraphPage tenantId="synthetic" pathIds={pathIds} tab={tab} onTabChange={setTab} onPlan={onPlan} />;
}
function latestElements() { return cy.create.mock.calls.at(-1)![0].elements as ReturnType<typeof schemaToElements>; }

it("uses the single tab registry in order, starts with schema and mounts only the active view", async () => {
  render(<Harness pathIds={["youtube:a"]} />);
  expect(within(screen.getByRole("tablist", { name: "지식 그래프 보기" })).getAllByRole("tab").map(tab => tab.textContent)).toEqual(GRAPH_TABS.map(tab => tab.label));
  expect(GRAPH_TABS.map(tab => tab.id)).toEqual(["schema", "path"]);
  expect(screen.getByRole("tab", { selected: true }).textContent).toBe("스키마");
  expect(screen.getByText("광고 지식이 어떻게 연결되어 있는지 노드(점)와 관계(선)로 살펴봅니다.")).toBeTruthy();
  expect(screen.getByText("그래프에 어떤 종류의 노드와 관계가 있는지 보여 줍니다. 층은 1층 제품 지식, 2층 광고에서 관찰한 값, 3층 승인·반려 피드백입니다.").className).toBe("gs-graph-note");
  await waitFor(() => expect(cy.create).toHaveBeenCalledTimes(1));
  expect(getSchema).toHaveBeenCalledExactlyOnceWith("synthetic"); expect(getGraphFragment).not.toHaveBeenCalled();
  const pathPanel = document.getElementById(screen.getByRole("tab", { name: "근거 경로" }).getAttribute("aria-controls")!)!;
  expect(pathPanel.hidden).toBe(true); expect(pathPanel.textContent).toBe("");
  fireEvent.click(screen.getByRole("tab", { name: "근거 경로" }));
  await waitFor(() => expect(cy.create).toHaveBeenCalledTimes(2));
  expect(getGraphFragment).toHaveBeenCalledExactlyOnceWith("synthetic", ["youtube:a"]);
  expect(screen.queryByRole("region", { name: "전체 스키마" })).toBeNull();
  expect(screen.getByText("기획안이 근거로 쓴 광고 소재가 어떤 값들과 연결되는지 보여 줍니다.").className).toBe("gs-graph-note");
  expect(cy.destroy).toHaveBeenCalledTimes(1);
});
it("keeps the path empty without IDs and sends its action to planning", async () => {
  const onPlan = vi.fn(); render(<Harness onPlan={onPlan} />);
  await waitFor(() => expect(cy.create).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByRole("tab", { name: "근거 경로" }));
  expect(screen.getByText("광고 기획에서 요청을 실행하면 근거 경로가 표시됩니다")).toBeTruthy();
  expect(getGraphFragment).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "광고 기획으로" })); expect(onPlan).toHaveBeenCalledTimes(1);
});
it("requires a workspace before mounting tabs or requesting graph data", () => {
  render(<GraphPage tenantId={null} pathIds={null} tab="schema" onTabChange={vi.fn()} onPlan={vi.fn()} />);
  expect(screen.getByText("상단 바에서 작업 공간을 선택하세요.")).toBeTruthy();
  expect(screen.queryByRole("tablist")).toBeNull(); expect(getSchema).not.toHaveBeenCalled(); expect(getGraphFragment).not.toHaveBeenCalled();
});
it.each(["schema", "path"])("independently filters layers and kinds in %s without changing original elements", async mode => {
  const snapshot = JSON.stringify({ schema, fragment });
  render(mode === "schema" ? <SchemaView tenantId="synthetic" /> : <GraphPanel tenantId="synthetic" ids={["youtube:a"]} />);
  await waitFor(() => expect(cy.create).toHaveBeenCalledTimes(1));
  const expected = mode === "schema" ? schemaToElements(schema) : fragmentToElements(fragment, taxonomyNames(schema));
  expect(latestElements()).toEqual(expected);
  const layers = screen.getByRole("group", { name: "층 필터" }); const kinds = screen.getByRole("group", { name: "노드 종류 필터" });
  expect(layers).not.toBe(kinds); expect(layers.parentElement).toBe(kinds.parentElement);
  expect(within(kinds).getAllByRole("button").map(button => button.textContent)).toEqual(["제품", "광고 소재", "훅 유형", "피드백"]);
  for (const button of [...within(layers).getAllByRole("button"), ...within(kinds).getAllByRole("button")]) expect(button.getAttribute("aria-pressed")).toBe("true");
  expect(screen.getByText("3층 피드백은 이 작업 공간의 데이터입니다.")).toBeTruthy();
  fireEvent.click(within(layers).getByRole("button", { name: "2층 · 광고 관찰" }));
  await waitFor(() => expect(latestElements().map(element => element.data.id)).toEqual(["Product", "Feedback"]));
  expect(within(kinds).getByRole("button", { name: "광고 소재" }).getAttribute("aria-pressed")).toBe("true");
  fireEvent.click(within(kinds).getByRole("button", { name: "제품" }));
  await waitFor(() => expect(latestElements().map(element => element.data.id)).toEqual(["Feedback"]));
  fireEvent.click(within(layers).getByRole("button", { name: "2층 · 광고 관찰" }));
  await waitFor(() => expect(latestElements().map(element => element.data.id)).toEqual(expected.filter(element => element.group === "nodes" ? element.data.label !== "Product" : element.data.target !== "Product").map(element => element.data.id)));
  fireEvent.click(within(kinds).getByRole("button", { name: "제품" }));
  await waitFor(() => expect(latestElements()).toEqual(expected));
  expect(JSON.stringify({ schema, fragment })).toBe(snapshot);
  expect(screen.getByRole("region", { name: mode === "schema" ? "전체 스키마" : "근거 그래프" }).textContent).not.toMatch(/Creative|USES_HOOK/);
});
async function completedPage() {
  render(<Page />); await screen.findByLabelText("요청");
  fireEvent.click(screen.getByRole("button", { name: "작업 공간" })); fireEvent.click(screen.getByRole("option", { name: /합성 공간/ }));
  fireEvent.click(screen.getByRole("button", { name: "+ 새 기획" }));
  fireEvent.change(screen.getByLabelText("요청"), { target: { value: "합성 요청" } }); fireEvent.click(screen.getByRole("button", { name: "기획하기" }));
  await screen.findByText("합성 결과");
}
it("opens a command path via context and returns to the same plan tabs and result DOM", async () => {
  await completedPage();
  const tabs = screen.getByRole("tablist", { name: "기획 탭" }); const selected = within(tabs).getByRole("tab", { selected: true }); const answer = screen.getByText("합성 결과");
  fireEvent.click(screen.getByRole("button", { name: "근거 그래프 보기" }));
  expect(screen.getByRole("tab", { name: "근거 경로" }).getAttribute("aria-selected")).toBe("true");
  expect(screen.getByRole("button", { name: "지식 그래프" }).getAttribute("aria-current")).toBe("page");
  await waitFor(() => expect(getGraphFragment).toHaveBeenCalledExactlyOnceWith("synthetic", ["youtube:a", "youtube:b"]));
  const back = screen.getByRole("button", { name: "광고 기획으로 돌아가기" }); expect(back.classList.contains("gs-button-secondary")).toBe(true); fireEvent.click(back);
  expect(screen.getByRole("tablist", { name: "기획 탭" })).toBe(tabs); expect(within(tabs).getByRole("tab", { selected: true })).toBe(selected);
  expect(within(tabs).getAllByRole("tab")).toHaveLength(2); expect(screen.getByText("합성 결과")).toBe(answer);
  expect(screen.queryByRole("region", { name: "근거 그래프" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "지식 그래프" }));
  expect(screen.queryByRole("button", { name: "광고 기획으로 돌아가기" })).toBeNull();
  expect(screen.getByRole("tab", { selected: true }).textContent).toBe("근거 경로");
});
it("clears the graph origin after sidebar navigation and preserves the last graph tab", async () => {
  await completedPage(); fireEvent.click(screen.getByRole("button", { name: "근거 그래프 보기" }));
  expect(screen.getByRole("button", { name: "광고 기획으로 돌아가기" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "근거 소재" })); fireEvent.click(screen.getByRole("button", { name: "지식 그래프" }));
  expect(screen.queryByRole("button", { name: "광고 기획으로 돌아가기" })).toBeNull();
  fireEvent.click(screen.getByRole("tab", { name: "스키마" })); fireEvent.click(screen.getByRole("button", { name: "광고 기획" })); fireEvent.click(screen.getByRole("button", { name: "지식 그래프" }));
  expect(screen.getByRole("tab", { selected: true }).textContent).toBe("스키마");
});
it("uses the latest command IDs when entering the path from the sidebar", async () => {
  await completedPage(); fireEvent.click(screen.getByRole("button", { name: "지식 그래프" }));
  expect(screen.queryByRole("button", { name: "광고 기획으로 돌아가기" })).toBeNull(); expect(getGraphFragment).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("tab", { name: "근거 경로" }));
  await waitFor(() => expect(getGraphFragment).toHaveBeenCalledExactlyOnceWith("synthetic", ["youtube:a", "youtube:b"]));
  await act(async () => { await Promise.resolve(); });
});
it("uses independent responsive graph geometry and reduced motion", () => {
  const css = readFileSync(join(process.cwd(), "app/graph.css"), "utf8");
  expect(css).not.toMatch(/--gs-sidebar-width|--gs-sidebar-rail-width/);
  expect(css).toMatch(/grid-template-columns:\s*minmax\(0, 1fr\) var\(--gs-graph-detail-width\)/);
  expect(css).toContain("--gs-graph-height"); expect(css).toMatch(/height:\s*var\(--gs-graph-height\)/);
  expect(css).toMatch(/prefers-reduced-motion:\s*reduce/);
  expect(css).toMatch(/\.gs-graph-filter-group\s*\{[^}]*display:\s*flex/);
});
