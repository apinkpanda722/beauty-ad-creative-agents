import { expect, it } from "vitest";
import { insightTitle, columnName, insightValue, TOOL_TITLES } from "../lib/insight";
import { taxonomyNames } from "../lib/taxonomy";
it.each([
  ["top_vs_bottom_axis", ["question"], "상위 vs 하위 광고 비교"],
  ["compare_axis_by_category", ["question", "person_first", "other"], "오프닝 방식 분포"],
  ["show_distribution", ["how_to", "desire"], "메시지 유형 분포"],
  ["show_distribution", ["demo", "studio_film"], "제작 형식 분포"],
  ["unknown_tool", [], "시장 인사이트"],
  ["show_distribution", [], "시장 인사이트"],
])("selects one insight title for %s", (tool, values, expected) => {
  expect(insightTitle(tool, values)).toBe(expected);
});
it("maps every aggregate and comparison tool from the registry", () => {
  expect(Object.keys(TOOL_TITLES).sort()).toEqual([
    "ad_angles_formats_by_skin_type", "compare_axis_by_category", "compare_competitor_claims", "compare_hooks_by_category",
    "compare_price_band_competitors", "count_claim_supported_ads", "ingredient_ad_trend", "top_claims_of_ingredient_ads",
    "top_vs_bottom_axis", "unclaimed_efficacy_gaps",
  ]);
  for (const [tool, title] of Object.entries(TOOL_TITLES)) expect(insightTitle(tool, [])).toBe(title);
});
it.each([["value", "분류"], ["n_top", "상위 25%"], ["n_bottom", "하위 25%"], ["creatives", "소재 수"], ["unknown", "항목"]])("localizes column %s", (key, expected) => {
  expect(columnName(key)).toBe(expected);
});
it("labels other without inventing unknown names", () => {
  expect(insightValue("other", taxonomyNames())).toBe("기타");
  expect(insightValue("unknown", taxonomyNames())).toBe("unknown");
});
