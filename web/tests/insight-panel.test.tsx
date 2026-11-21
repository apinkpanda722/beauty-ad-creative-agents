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
  expect(screen.getAllByRole("heading").map(node => node.textContent)).toEqual(["경쟁사 광고 분포"]);
  const tabs = within(screen.getByRole("tablist", { name: "경쟁사 광고 분포 축" })).getAllByRole("tab");
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
  expect(screen.getAllByRole("heading").map(node => node.textContent)).toEqual(["경쟁사 광고 분포", "조회수 상위·하위 25% 광고 비교"]);
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
  const cards = [screen.getByRole("region", { name: "경쟁사 광고 분포" }), screen.getByRole("region", { name: "조회수 상위·하위 25% 광고 비교" })];
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
  expect(screen.getAllByRole("heading").map(node => node.textContent)).toEqual(["경쟁사 광고 분포", "조회수 상위·하위 25% 광고 비교"]);
  expect(within(screen.getByRole("region", { name: "경쟁사 광고 분포" })).getByRole("tab").textContent).toBe("그 외");
  expect(screen.getAllByRole("region", { name: "분포" }).map(node => node.getAttribute("data-tool"))).toEqual(["unknown_tool", "top_vs_bottom_axis"]);
  expect(document.body.textContent).not.toMatch(/unknown_tool|top_vs_bottom_axis/);
});
