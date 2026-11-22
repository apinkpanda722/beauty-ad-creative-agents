import { readFileSync } from "node:fs";
import { join } from "node:path";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { HistoryDetail } from "../components/history/HistoryDetail";
import { AggregatesPanel } from "../components/results/AggregatesPanel";
import { DistributionChart } from "../components/results/DistributionChart";
import { InsightPanel } from "../components/results/InsightPanel";
import { initialState, reducer } from "../lib/reducer";
import { taxonomyNames } from "../lib/taxonomy";
import type { SchemaResponse, UiCommand } from "../lib/types";

afterEach(cleanup);
type Aggregates = Extract<UiCommand, { kind: "show_aggregates" }>["data"];
const base: Aggregates = { label: "모델 작성값, 검증되지 않음", verified_counts: [], model_written: [], removed: [] };
const css = readFileSync(join(process.cwd(), "app/results.css"), "utf8");
const schema: SchemaResponse = { labels: [], relationships: [], claims: [{ value: "sun_protection", name: "자외선 차단" }], taxonomy: {
  hook_type: [{ value: "person_first", name: "인물 먼저 제시형", definition: "합성" }, { value: "question", name: "질문형", definition: "합성" }, { value: "other", name: "기타 훅", definition: "합성" }],
  angle: [{ value: "how_to", name: "사용법", definition: "합성" }],
  format: [{ value: "ugc_style", name: "일반인 후기형", definition: "합성" }],
} };
const names = taxonomyNames(schema);
const ruleBody = (selector: string) => css.match(new RegExp(`${selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*\\{([^}]*)\\}`))?.[1] ?? null;

// Model-written values are received but no longer drawn in the verification tab.
const modelWritten: Aggregates["model_written"] = [
  { name: "훅 집계: 제품 먼저 제시형", value: "35 / 85" }, { name: "자외선 차단 라벨", value: "79 / 92" },
  { name: " 오프닝 유형 ", value: "question 3/7; problem 2/7" }, { name: "합성 모델 항목", value: 42 as unknown as string },
];
it("renders nothing when only model-written values exist", () => {
  const data: Aggregates = { ...base, model_written: modelWritten };
  const snapshot = JSON.stringify(data);
  const { container } = render(<AggregatesPanel data={data} names={names} />);
  expect(container.innerHTML).toBe("");
  expect(JSON.stringify(data)).toBe(snapshot);
});
it("renders only the removed values when model-written values come with removed names", () => {
  const data: Aggregates = { ...base, model_written: modelWritten, removed: ["synthetic_removed", "다른 제외 항목"] };
  const snapshot = JSON.stringify(data);
  const { container } = render(<AggregatesPanel data={data} names={names} />);
  const removed = screen.getByRole("region", { name: "제외된 값" });
  expect([...removed.querySelectorAll("li")].map(node => node.textContent)).toEqual(["synthetic_removed", "다른 제외 항목"]);
  expect(within(removed).getByText("제외됨").className).toContain("gs-badge-neutral");
  expect(screen.queryByRole("region", { name: "모델 작성값" })).toBeNull();
  expect(screen.queryByText("미검증")).toBeNull(); expect(screen.queryByText(base.label)).toBeNull();
  expect(screen.queryAllByRole("meter")).toHaveLength(0); expect(container.querySelector("dl")).toBeNull();
  for (const text of ["합성 모델 항목", "훅 집계", "제품 먼저 제시형", "35 / 85", "79 / 92", "오프닝 유형", "42"]) expect(container.textContent).not.toContain(text);
  expect(container.querySelectorAll(".gs-aggregates")).toHaveLength(1);
  expect(JSON.stringify(data)).toBe(snapshot);
});
it("renders nothing when there are neither model values nor removed values", () => {
  const { container } = render(<AggregatesPanel data={base} names={names} />);
  expect(container.innerHTML).toBe("");
});
it("keeps the verified aggregates and removed values in the verification tab but not model-written values", () => {
  const turn = reducer({ ...initialState, tenantId: "synthetic" }, { type: "request_started", message: "합성 검증 요청" }).turns[0];
  const commands: UiCommand[] = [
    { kind: "show_distribution", data: { tool: "compare_axis_by_category", rows: [{ value: "question", creatives: 4 }] } },
    { kind: "show_aggregates", data: { ...base, model_written: modelWritten, removed: ["synthetic_removed"] } },
  ];
  const snapshot = JSON.stringify(commands);
  render(<HistoryDetail turn={{ ...turn, status: "done", commands }} workspace="합성" onBack={vi.fn()} names={names} />);
  fireEvent.click(screen.getByRole("tab", { name: "검증" }));
  const panel = screen.getByRole("tabpanel", { name: "검증" });
  expect(within(panel).getByRole("region", { name: "검증된 집계(도구가 센 값)" })).toBeTruthy();
  expect(within(panel).getByRole("region", { name: "제외된 값" }).textContent).toContain("synthetic_removed");
  expect(within(panel).queryByRole("region", { name: "모델 작성값" })).toBeNull();
  expect(within(panel).queryByRole("region", { name: "모델 작성값 차트" })).toBeNull();
  expect(within(panel).queryByText("미검증")).toBeNull();
  expect(within(panel).getAllByRole("meter").map(node => [node.getAttribute("aria-label"), node.getAttribute("value")])).toEqual([["질문형", "4"]]);
  for (const text of ["합성 모델 항목", "훅 집계", "제품 먼저 제시형", "35 / 85", "79 / 92", "오프닝 유형", "3/7"]) expect(panel.textContent).not.toContain(text);
  expect(JSON.stringify(commands)).toBe(snapshot);
});

// (B) card title
it("titles the competitor card 시장 광고 분포 and no longer shows the old title", () => {
  const { container } = render(<InsightPanel distributions={[{ tool: "compare_axis_by_category", rows: [{ value: "question", creatives: 2 }] }]} names={names} />);
  expect(screen.getByRole("heading", { name: "시장 광고 분포" })).toBeTruthy();
  expect(screen.getByRole("tablist", { name: "시장 광고 분포 축" })).toBeTruthy();
  expect(screen.getByRole("region", { name: "시장 광고 분포" })).toBeTruthy();
  expect(container.textContent).not.toContain("경쟁사 광고 분포");
  expect(screen.queryByRole("heading", { name: "경쟁사 광고 분포" })).toBeNull();
});

// (C) truncation note in the result screen
const hookRows = [
  { value: "person_first", creatives: 55, total: 114 }, { value: "other", creatives: 20, total: 114 }, { value: "question", creatives: 17, total: 114 },
  { value: "product_first", creatives: 16, total: 114 }, { value: "problem", creatives: 3, total: 114 },
];
const note = (root: HTMLElement) => [...root.querySelectorAll(".gs-insight-note")].filter(node => node.textContent?.startsWith("분류가 많아"));
it("explains the missing 3 of 114 in the active hook tab of the result variant exactly once", () => {
  const input = [{ tool: "compare_axis_by_category", rows: hookRows }];
  const snapshot = JSON.stringify(input);
  const { container } = render(<InsightPanel distributions={input} names={names} variant="result" />);
  expect(container.querySelector(".gs-insight-total")?.textContent).toBe("총 114건");
  const found = note(container);
  expect(found).toHaveLength(1);
  expect(found[0].textContent).toBe("분류가 많아 상위 5개만 표시합니다(나머지 3건은 표시하지 않음)");
  expect(found[0].tagName).toBe("P"); expect(found[0].className).toBe("gs-insight-note");
  const panel = screen.getByRole("tabpanel"); expect(panel.contains(found[0])).toBe(true);
  expect(found[0].previousElementSibling).toBe(within(panel).getByRole("region", { name: "분포" }));
  expect(JSON.stringify(input)).toBe(snapshot);
});
it.each([["angle", "how_to"], ["format", "ugc_style"]] as const)("shows the note on the %s tab too", (_axis, value) => {
  const { container } = render(<InsightPanel distributions={[{ tool: "compare_axis_by_category", rows: [{ value, creatives: 5, total: 9 }] }]} names={names} />);
  expect(note(container)).toHaveLength(1);
  expect(note(container)[0].textContent).toBe("분류가 많아 상위 1개만 표시합니다(나머지 4건은 표시하지 않음)");
});
it("shows no note when the displayed rows add up to the total", () => {
  const rows = [{ value: "question", creatives: 4, total: 6 }, { value: "problem", creatives: 2, total: 6 }];
  const { container } = render(<InsightPanel distributions={[{ tool: "compare_axis_by_category", rows }]} names={names} />);
  expect(container.querySelector(".gs-insight-total")?.textContent).toBe("총 6건");
  expect(note(container)).toHaveLength(0);
});
it("shows no note when the rows add up to more than the total or the total is missing or inconsistent", () => {
  const cases = [
    [{ value: "question", creatives: 9, total: 6 }],
    [{ value: "question", creatives: 1 }],
    [{ value: "question", creatives: 1, total: 6 }, { value: "problem", creatives: 1, total: 7 }],
  ];
  for (const rows of cases) {
    const { container, unmount } = render(<InsightPanel distributions={[{ tool: "compare_axis_by_category", rows }]} names={names} />);
    expect(note(container)).toHaveLength(0); unmount();
  }
});
it("shows no note on the 그 외 tab even though its multi-label rows do not add up", () => {
  const rows = [{ value: "sun_protection", creatives: 79, total: 92 }, { value: "hydration", creatives: 56, total: 92 }];
  const { container } = render(<InsightPanel distributions={[{ tool: "compare_axis_by_category", rows }]} names={names} />);
  expect(screen.getByRole("tab", { name: "그 외" }).getAttribute("aria-selected")).toBe("true");
  expect(container.querySelector(".gs-insight-total")?.textContent).toBe("총 92건");
  expect(note(container)).toHaveLength(0);
});
it("shows no note in the verification variant or on the comparison card", () => {
  const { container, rerender } = render(<InsightPanel distributions={[{ tool: "compare_axis_by_category", rows: hookRows }]} names={names} variant="verification" />);
  expect(note(container)).toHaveLength(0);
  rerender(<InsightPanel distributions={[{ tool: "top_vs_bottom_axis", rows: [{ value: "question", n_top: 3, n_bottom: 1, total: 20 }] }]} names={names} variant="result" />);
  expect(note(container)).toHaveLength(0);
});
it("counts bar rows and sums across every distribution of the active tab and formats numbers like the total", () => {
  const input = [
    { tool: "compare_axis_by_category", rows: [{ value: "question", creatives: 3, total: 1234 }, { value: "problem", creatives: 2, total: 1234 }] },
    { tool: "compare_axis_by_category", rows: [{ value: "bold_claim", creatives: 1, total: 1234 }] },
  ];
  const { container } = render(<InsightPanel distributions={input} names={names} />);
  expect(container.querySelector(".gs-insight-total")?.textContent).toBe("총 1,234건");
  expect(note(container).map(node => node.textContent)).toEqual(["분류가 많아 상위 3개만 표시합니다(나머지 1,228건은 표시하지 않음)"]);
});
it("updates the note with the active tab and hides it where the tab adds up", () => {
  const input = [
    { tool: "compare_axis_by_category", rows: [{ value: "question", creatives: 3, total: 10 }] },
    { tool: "compare_axis_by_category", rows: [{ value: "how_to", creatives: 4, total: 4 }] },
  ];
  const { container } = render(<InsightPanel distributions={input} names={names} />);
  expect(note(container).map(node => node.textContent)).toEqual(["분류가 많아 상위 1개만 표시합니다(나머지 7건은 표시하지 않음)"]);
  fireEvent.click(screen.getByRole("tab", { name: "소구" }));
  expect(within(screen.getByRole("tabpanel")).queryByText(/분류가 많아/)).toBeNull();
});

it("separates the truncation note with a weak divider and a wider gap only inside chart panels", () => {
  expect(css).toMatch(/\.gs-insight-charts \.gs-insight-note\s*\{\s*margin-top:\s*var\(--gs-space-12\);\s*padding-top:\s*var\(--gs-space-6\);\s*border-top:\s*var\(--gs-border-width\) solid var\(--gs-border\);\s*\}/);
  expect(ruleBody(".gs-insight-note")).toBe(" color: var(--gs-text-muted); font-size: var(--gs-text-sm); margin-block: var(--gs-space-2); ");
});

// Bars are drawn against the total count, not against the largest bar.
type Distribution = Extract<UiCommand, { kind: "show_distribution" }>["data"];
const bar = (value: string, creatives: number, total?: number | null): Record<string, unknown> => total === undefined ? { value, creatives } : { value, creatives, total };
const meters = () => screen.getAllByRole("meter").map(node => [node.getAttribute("max"), node.getAttribute("value"), node.getAttribute("aria-valuenow")]);
it("scales every bar to the total count so the largest bar is not full", () => {
  const data: Distribution = { tool: "compare_axis_by_category", rows: [bar("question", 55, 114), bar("problem", 17, 114), bar("result_first", 16, 114), bar("bold_claim", 3, 114), bar("product_first", 20, 114)] };
  const snapshot = JSON.stringify(data);
  render(<DistributionChart data={data} names={names} />);
  expect(meters()).toEqual([["114", "55", "55"], ["114", "17", "17"], ["114", "16", "16"], ["114", "3", "3"], ["114", "20", "20"]]);
  for (const text of ["55건", "17건", "16건", "3건", "20건"]) expect(screen.getByText(text)).toBeTruthy();
  expect(screen.getByRole("meter", { name: "질문형" })).toBeTruthy();
  expect(JSON.stringify(data)).toBe(snapshot);
});
it("uses the total of the other tab (multi-label) as the bar scale", () => {
  render(<DistributionChart data={{ tool: "compare_axis_by_category", rows: [bar("other", 79, 92), bar("question", 5, 92)] }} names={names} />);
  expect(meters()).toEqual([["92", "79", "79"], ["92", "5", "5"]]);
  expect(screen.getByText("79건")).toBeTruthy();
});
it("falls back to the largest bar when no total exists, the total is invalid, or totals differ per row", () => {
  for (const rows of [
    [bar("question", 55), bar("problem", 17)],
    [bar("question", 55, null), bar("problem", 17, null)],
    [bar("question", 55, 40), bar("problem", 17, 40)],
    [bar("question", 55, 114), bar("problem", 17, 100)],
  ]) {
    const { unmount } = render(<DistributionChart data={{ tool: "compare_axis_by_category", rows }} names={names} />);
    expect(meters()).toEqual([["55", "55", "55"], ["55", "17", "17"]]);
    unmount();
  }
});
