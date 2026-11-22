import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { InsightPanel } from "../components/results/InsightPanel";
import { insightDescription } from "../lib/insight";
import { taxonomyNames } from "../lib/taxonomy";
import type { SchemaResponse } from "../lib/types";
const names = taxonomyNames({ labels: [], relationships: [], claims: [], taxonomy: {
  hook_type: [{ value: "question", name: "질문형", definition: "합성" }],
  angle: [{ value: "how_to", name: "사용법", definition: "합성" }],
  format: [{ value: "demo", name: "시연형", definition: "합성" }],
} } satisfies SchemaResponse);
const distributions = ["demo", "how_to", "question"].map(value => ({ tool: "compare_axis_by_category", rows: [{ value, creatives: 2 }] }));
afterEach(cleanup);
it("merges three axes in one card with fixed tab order and the first tab selected", () => {
  const snapshot = JSON.stringify(distributions);
  const { container } = render(<InsightPanel distributions={distributions} names={names} />);
  expect(screen.getAllByRole("heading").map(node => node.textContent)).toEqual(["시장 광고 분포"]);
  const tabs = within(screen.getByRole("tablist", { name: "시장 광고 분포 축" })).getAllByRole("tab");
  expect(tabs.map(node => node.textContent)).toEqual(["훅", "소구", "형식"]);
  expect(tabs.map(node => node.getAttribute("aria-selected"))).toEqual(["true", "false", "false"]);
  expect(screen.getByRole("region", { name: "분포" }).getAttribute("data-tool")).toBe("compare_axis_by_category");
  expect(screen.getByRole("meter", { name: "질문형" }).getAttribute("aria-valuenow")).toBe("2");
  expect(screen.queryByRole("button", { name: "표로 보기" })).toBeNull();
  expect(screen.queryByText("검증됨")).toBeNull(); expect(screen.queryByLabelText("모델 작성값 차트")).toBeNull();
  expect(container.querySelector(".gs-card")).toBeNull();
  expect(JSON.stringify(distributions)).toBe(snapshot);
});
it("omits absent axes, keeps repeated distributions in the same axis and uses other for unknown values", () => {
  const { rerender } = render(<InsightPanel distributions={[distributions[1], distributions[1]]} names={names} />);
  expect(screen.getAllByRole("tab").map(node => node.textContent)).toEqual(["소구"]);
  expect(screen.getAllByRole("region", { name: "분포" })).toHaveLength(2);
  rerender(<InsightPanel distributions={[{ tool: "unknown_tool", rows: [{ value: "other", creatives: 1 }] }]} names={names} />);
  expect(screen.getAllByRole("tab").map(node => node.textContent)).toEqual(["그 외"]);
  expect(screen.getByRole("region", { name: "분포" }).getAttribute("data-tool")).toBe("unknown_tool");
});
it("separates comparison in its own card with one explanation and unchanged columns", () => {
  render(<InsightPanel distributions={[...distributions, { tool: "top_vs_bottom_axis", rows: [{ value: "question", n_top: 3, n_bottom: 1 }] }]} names={names} />);
  expect(screen.getAllByRole("heading").map(node => node.textContent)).toEqual(["시장 광고 분포", "조회수 상위·하위 25% 광고 비교"]);
  expect(screen.getAllByText(insightDescription("top_vs_bottom_axis")!)).toHaveLength(1);
  const card = screen.getByRole("region", { name: "조회수 상위·하위 25% 광고 비교" });
  expect(within(card).getAllByRole("columnheader").map(node => node.textContent)).toEqual(["분류", "상위 25% 광고 수", "하위 25% 광고 수"]);
  expect(within(card).getAllByRole("cell").map(node => node.textContent)).toEqual(["질문형", "3", "1"]);
});
it("renders nothing without distributions", () => {
  const { container } = render(<InsightPanel distributions={[]} names={names} />);
  expect(container.innerHTML).toBe("");
});
it("shows independently collapsed verification tables for only the active axis", () => {
  const input = [...distributions, { tool: "top_vs_bottom_axis", rows: [{ value: "question", n_top: 3, n_bottom: 1 }] }];
  const snapshot = JSON.stringify(input);
  render(<InsightPanel distributions={input} names={names} variant="verification" />);
  const cards = [screen.getByRole("region", { name: "시장 광고 분포" }), screen.getByRole("region", { name: "조회수 상위·하위 25% 광고 비교" })];
  const toggles = cards.map(card => within(card).getByRole("button", { name: "표로 보기" }));
  const contents = toggles.map(toggle => document.getElementById(toggle.getAttribute("aria-controls")!)!);
  expect(toggles.map(toggle => toggle.getAttribute("aria-expanded"))).toEqual(["false", "false"]);
  expect(contents.map(content => content.hidden)).toEqual([true, true]);
  fireEvent.click(toggles[0]);
  expect(toggles[0].textContent).toBe("표 접기"); expect(contents.map(content => content.hidden)).toEqual([false, true]);
  const source = () => within(cards[0]).getByRole("table", { name: "시장 인사이트 원천 데이터" });
  expect(within(source()).getAllByRole("columnheader").map(node => node.textContent)).toEqual(["분류", "소재 수"]);
  expect(within(source()).getAllByRole("cell").map(node => node.textContent)).toEqual(["질문형", "2"]);
  fireEvent.click(within(cards[0]).getByRole("tab", { name: "소구" }));
  expect(within(source()).getAllByRole("cell").map(node => node.textContent)).toEqual(["사용법", "2"]);
  fireEvent.click(toggles[1]); expect(contents[1].hidden).toBe(false);
  fireEvent.click(toggles[0]); expect(contents[0].hidden).toBe(true);
  expect(JSON.stringify(input)).toBe(snapshot);
});
it("labels known and unknown tools only in card headings and keeps raw tool attributes", () => {
  render(<InsightPanel distributions={[{ tool: "top_vs_bottom_axis", rows: [{ value: "question", n_top: 1, n_bottom: 0 }] }, { tool: "unknown_tool", rows: [{ value: "other", creatives: 2 }] }]} names={names} />);
  expect(screen.getAllByRole("heading").map(node => node.textContent)).toEqual(["시장 광고 분포", "조회수 상위·하위 25% 광고 비교"]);
  expect(within(screen.getByRole("region", { name: "시장 광고 분포" })).getByRole("tab").textContent).toBe("그 외");
  expect(screen.getAllByRole("region", { name: "분포" }).map(node => node.getAttribute("data-tool"))).toEqual(["unknown_tool", "top_vs_bottom_axis"]);
  expect(document.body.textContent).not.toMatch(/unknown_tool|top_vs_bottom_axis/);
});

it.each(["result", "verification"] as const)("shows only a consistent active-axis total in the %s competitor title line", variant => {
  const input = [
    { tool: "compare_axis_by_category", rows: [{ value: "question", creatives: 3, total: 1234 }, { value: "problem", creatives: 2, total: 1234 }] },
    { tool: "compare_axis_by_category", rows: [{ value: "question", creatives: 1, total: 1234 }] },
    { tool: "compare_axis_by_category", rows: [{ value: "how_to", creatives: 1, total: 27 }] },
  ];
  const snapshot = JSON.stringify(input);
  const { container, rerender } = render(<InsightPanel distributions={input} names={names} variant={variant} />);
  const total = () => container.querySelector(".gs-insight-head > .gs-insight-total");
  expect(total()?.tagName).toBe("SPAN"); expect(total()?.textContent).toBe("총 1,234건");
  expect(total()?.previousElementSibling).toBe(screen.getByRole("heading", { name: "시장 광고 분포" }));
  expect(screen.getAllByRole("heading").map(node => node.textContent)).toEqual(["시장 광고 분포"]);
  fireEvent.click(screen.getByRole("tab", { name: "소구" })); expect(total()?.textContent).toBe("총 27건");
  fireEvent.click(screen.getByRole("tab", { name: "훅" })); expect(total()?.textContent).toBe("총 1,234건");
  expect(JSON.stringify(input)).toBe(snapshot);
  for (const rows of [[{ value: "question", creatives: 1, total: 3 }, { value: "problem", creatives: 1, total: 4 }], [{ value: "question", creatives: 1, total: 3 }, { value: "problem", creatives: 1 }]]) {
    rerender(<InsightPanel distributions={[{ tool: "compare_axis_by_category", rows }]} names={names} variant={variant} />);
    expect(total()).toBeNull();
  }
  // A missing total in a second distribution of the same axis also suppresses it.
  rerender(<InsightPanel distributions={[input[0], { tool: "compare_axis_by_category", rows: [{ value: "question", creatives: 1 }] }]} names={names} variant={variant} />);
  expect(total()).toBeNull();
});
it.each(["result", "verification"] as const)("never shows a comparison total in %s", variant => {
  const { container } = render(<InsightPanel distributions={[{ tool: "top_vs_bottom_axis", rows: [{ value: "question", n_top: 3, n_bottom: 1, total: 20 }] }]} names={names} variant={variant} />);
  expect(container.querySelector(".gs-insight-total")).toBeNull();
  expect(container.textContent).not.toContain("총 20건");
});
const sortingNames = taxonomyNames({ labels: [], relationships: [], claims: [], taxonomy: {
  hook_type: [{ value: "question", name: "질문형", definition: "합성" }, { value: "problem", name: "고민 제시형", definition: "합성" }, { value: "other", name: "기타 훅", definition: "합성" }],
  angle: [], format: [],
} } satisfies SchemaResponse);
it("sorts bars and source values identically and keeps input and model chart objects unchanged", () => {
  const input = [{ tool: "compare_axis_by_category", rows: [{ value: "other", creatives: 1 }, { value: "question", creatives: 3 }, { value: "problem", creatives: 3 }] }];
  const modelCharts = [{ axis: "hook" as const, label: "훅", rows: [{ label: "기타 훅", count: 9, total: 10 }, { label: "problem", count: 1, total: 10 }, { label: "question", count: 3, total: 10 }] }];
  const snapshot = JSON.stringify({ input, modelCharts });
  render(<InsightPanel distributions={input} names={sortingNames} variant="verification" modelCharts={modelCharts} />);
  const chart = screen.getByRole("region", { name: "분포" });
  expect(within(chart).getAllByRole("meter").map(node => node.getAttribute("aria-label"))).toEqual(["질문형", "고민 제시형", "기타 훅"]);
  fireEvent.click(screen.getByRole("button", { name: "표로 보기" }));
  const table = screen.getByRole("table", { name: "시장 인사이트 원천 데이터" });
  expect(within(table).getAllByRole("row").slice(1).map(row => within(row).getAllByRole("cell")[0].textContent)).toEqual(["질문형", "고민 제시형", "기타"]);
  expect(within(table).getAllByRole("row").slice(1).map(row => within(row).getAllByRole("cell")[1].textContent)).toEqual(["3", "3", "1"]);
  const model = screen.getByRole("region", { name: "모델 작성값 차트" });
  expect(within(model).getAllByRole("meter").map(node => node.getAttribute("aria-label"))).toEqual(["질문형", "고민 제시형", "기타 훅"]);
  expect(within(model).getAllByRole("meter").map(node => node.getAttribute("aria-valuenow"))).toEqual(["3", "1", "9"]);
  expect(JSON.stringify({ input, modelCharts })).toBe(snapshot);
});
it.each(["result", "verification"] as const)("orders and emphasizes comparison columns and rows in %s without changing text or input", variant => {
  const input = [{ tool: "top_vs_bottom_axis", rows: [
    { n_bottom: 5, value: "a", n_top: 1 }, { n_bottom: 9, value: "other", n_top: 9 },
    { n_bottom: 1, value: "b", n_top: 3 }, { n_bottom: 4, value: "c", n_top: 3 },
  ] }];
  const comparisonNames = taxonomyNames({ labels: [], relationships: [], claims: [], taxonomy: {
    hook_type: [ ["a", "가 분류"], ["b", "나 분류"], ["c", "다 분류"] ].map(([value, name]) => ({ value, name, definition: "합성" })), angle: [], format: [],
  } });
  const snapshot = JSON.stringify(input);
  render(<InsightPanel distributions={input} names={comparisonNames} variant={variant} />);
  const title = screen.getByRole("heading", { name: "조회수 상위·하위 25% 광고 비교" });
  const description = screen.getByText(insightDescription("top_vs_bottom_axis")!);
  expect(title.nextElementSibling).toBe(description);
  expect(description.nextElementSibling?.tagName).toBe("P");
  expect(description.nextElementSibling?.className).toBe("gs-insight-note");
  expect(description.nextElementSibling?.textContent).toBe("상위 25% 광고 수가 많은 분류부터 5개까지 표시합니다.");
  if (variant === "verification") fireEvent.click(screen.getByRole("button", { name: "표로 보기" }));
  for (const table of screen.getAllByRole("table")) {
    const headers = within(table).getAllByRole("columnheader");
    expect(headers.map(node => node.textContent)).toEqual(["분류", "상위 25% 광고 수", "하위 25% 광고 수"]);
    expect(headers[1].querySelector("span.gs-col-primary")?.textContent).toBe("상위 25% 광고 수");
    expect(headers[2].querySelector("span.gs-col-muted")?.textContent).toBe("하위 25% 광고 수");
    const cells = within(table).getAllByRole("row").slice(1).map(row => within(row).getAllByRole("cell"));
    expect(cells.map(row => row.map(cell => cell.textContent))).toEqual([["다 분류", "3", "4"], ["나 분류", "3", "1"], ["가 분류", "1", "5"], ["기타", "9", "9"]]);
    for (const row of cells) {
      expect(row[1].querySelector("span.gs-col-primary")?.textContent).toBe(row[1].textContent);
      expect(row[2].querySelector("span.gs-col-muted")?.textContent).toBe(row[2].textContent);
      expect(row[1].hasAttribute("class")).toBe(false); expect(row[2].hasAttribute("class")).toBe(false);
    }
  }
  expect(JSON.stringify(input)).toBe(snapshot);
});
it("displays a raw model other category in Korean after sorting", () => {
  const modelCharts = [{ axis: "hook" as const, label: "훅", rows: [{ label: "other", count: 9, total: 10 }, { label: "question", count: 3, total: 10 }] }];
  const snapshot = JSON.stringify(modelCharts);
  render(<InsightPanel distributions={[distributions[2]]} names={sortingNames} variant="verification" modelCharts={modelCharts} />);
  const chart = screen.getByRole("region", { name: "모델 작성값 차트" });
  expect(within(chart).getAllByRole("meter").map(node => node.getAttribute("aria-label"))).toEqual(["질문형", "기타"]);
  expect(chart.textContent).not.toContain("other");
  expect(JSON.stringify(modelCharts)).toBe(snapshot);
});
