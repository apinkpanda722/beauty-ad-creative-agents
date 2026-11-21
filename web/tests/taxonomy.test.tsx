import { cleanup, fireEvent, render, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { taxonomyNames } from "../lib/taxonomy";
import type { PlanView, SchemaResponse } from "../lib/types";
import { initialState, reducer } from "../lib/reducer";
import { DistributionChart } from "../components/results/DistributionChart";
import { PatternAlignment } from "../components/results/PatternAlignment";
import { HistoryDetail } from "../components/history/HistoryDetail";

afterEach(cleanup);
const angles = ["problem_solution", "social_proof", "comparison", "ingredient_science", "how_to"];
function schema(desireName: string): SchemaResponse {
  return { labels: [], relationships: [], claims: [], taxonomy: {
    hook_type: [], format: [], angle: [
      { value: "desire", name: desireName, definition: "합성" },
      ...angles.map((value, index) => ({ value, name: `합성 소구 ${index + 1}`, definition: "합성" })),
    ],
  } };
}
it.each([undefined, schema("욕구"), schema(""), schema("합성 서버 이름")])("overrides only the desire display name with or without schema: %j", source => {
  const snapshot = JSON.stringify(source);
  const names = taxonomyNames(source);
  expect(names.axisName("angle", "desire")).toBe("이상형 제시형");
  expect(names.valueName("desire")).toBe("이상형 제시형");
  for (const [index, value] of angles.entries()) {
    const expected = source ? `합성 소구 ${index + 1}` : value;
    expect(names.axisName("angle", value)).toBe(expected);
    expect(names.valueName(value)).toBe(expected);
  }
  expect(JSON.stringify(source)).toBe(snapshot);
});
it("uses the same desire name in chart rows, source rows and pattern facts without mutating data", () => {
  const source = schema("욕구"); const names = taxonomyNames(source);
  const rows = [{ value: "desire", creatives: 3 }];
  const pattern = { axes: { angle: { plan: "desire", dominant: ["desire"], same: true, share: .25 } } };
  const data: PlanView = { plan: { title: "합성 기획안" }, plan_id: null, passed: true, status: "done", unknown_count: 0, unknown_codes: {}, efficacy_status: {}, efficacy_summary: { supported: 0, unknown: 0 }, count_label: "합성", result_counts: [], evidence_counts: {}, pattern_alignment: pattern, pattern_alignment_label: "코드 계산, 판정 아님", disclaimer: "합성", image: null, design_disclaimer: null, product_display: { brand: null, display_name: null, product_name: null }, attempts: [] };
  const distribution = { tool: "compare_axis_by_category", rows };
  const snapshot = JSON.stringify({ rows, pattern, source });
  const chart = render(<DistributionChart data={distribution} names={names} />);
  expect(within(chart.container).getByText("이상형 제시형")).toBeTruthy();
  expect(within(chart.container).getByRole("meter", { name: "이상형 제시형" })).toBeTruthy();
  const facts = render(<PatternAlignment data={pattern} names={names} />);
  expect(within(facts.container).getAllByText("이상형 제시형")).toHaveLength(2);
  const base = reducer({ ...initialState, tenantId: "synthetic" }, { type: "request_started", message: "합성" }).turns[0];
  const history = render(<HistoryDetail turn={{ ...base, status: "done", commands: [{ kind: "show_plan", data }, { kind: "show_distribution", data: distribution }] }} names={names} workspace="합성" onBack={vi.fn()} />);
  fireEvent.click(within(history.container).getByRole("tab", { name: "검증" }));
  fireEvent.click(within(history.container).getByRole("button", { name: "원천 데이터 보기 (1)" }));
  const table = within(history.container).getByRole("table", { name: "시장 인사이트 원천 데이터" });
  expect(within(table).getByText("이상형 제시형")).toBeTruthy();
  for (const view of [chart, facts, history]) expect(view.container.textContent).not.toContain("욕구");
  expect(JSON.stringify({ rows, pattern, source })).toBe(snapshot);
});
