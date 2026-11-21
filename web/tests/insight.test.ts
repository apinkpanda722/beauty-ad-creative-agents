import { expect, it } from "vitest";
import { insightTitle, columnName, insightValue, TOOL_TITLES, toolTitle, insightDescription, insightColumnName } from "../lib/insight";
import { taxonomyNames } from "../lib/taxonomy";
it.each([
  ["top_vs_bottom_axis", ["question"], "조회수 상위·하위 25% 광고 비교"],
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

it("provides Korean tool titles and a scoped comparison description", () => {
  expect(toolTitle("top_vs_bottom_axis")).toBe("조회수 상위·하위 25% 광고 비교");
  expect(toolTitle("compare_axis_by_category")).toBe("카테고리별 광고 비교");
  expect(toolTitle("unknown_tool")).toBe("집계 항목");
  expect(insightDescription("top_vs_bottom_axis")).toBe("같은 플랫폼·브랜드 안에서 조회수 상위 25%와 하위 25% 광고가 각 방식을 쓴 광고 수입니다.");
  for (const tool of ["compare_axis_by_category", "unknown_tool"]) expect(insightDescription(tool)).toBeNull();
});
it("specializes comparison columns while leaving generic column names intact", () => {
  expect(insightColumnName("top_vs_bottom_axis", "n_top")).toBe("상위 25% 광고 수");
  expect(insightColumnName("top_vs_bottom_axis", "n_bottom")).toBe("하위 25% 광고 수");
  expect(insightColumnName("top_vs_bottom_axis", "value")).toBe("분류");
  for (const key of ["n_top", "n_bottom", "value", "creatives", "unknown"]) expect(insightColumnName("compare_axis_by_category", key)).toBe(columnName(key));
  expect(insightColumnName("top_vs_bottom_axis", "creatives")).toBe(columnName("creatives"));
  expect(columnName("n_top")).toBe("상위 25%");
});
