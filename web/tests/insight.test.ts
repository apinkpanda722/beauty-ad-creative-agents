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

it("detects only a nonempty unmixed distribution axis", async () => {
  const { insightAxis, AXIS_TABS } = await import("../lib/insight");
  expect(insightAxis(["question", "problem", "other"])).toBe("hook");
  expect(insightAxis(["how_to", "desire"])).toBe("angle");
  expect(insightAxis(["demo", "studio_film"])).toBe("format");
  for (const values of [["other"], ["question", "how_to"], [], ["unknown"]]) expect(insightAxis(values)).toBeNull();
  expect(AXIS_TABS).toEqual([{ value: "hook", label: "훅" }, { value: "angle", label: "소구" }, { value: "format", label: "형식" }, { value: "other", label: "그 외" }]);
});
it("parses only complete explicit model fractions without guessing", async () => {
  const { parseModelBreakdown } = await import("../lib/insight");
  expect(parseModelBreakdown("question 3/7; problem 2/7")).toEqual([{ label: "question", count: 3, total: 7 }, { label: "problem", count: 2, total: 7 }]);
  expect(parseModelBreakdown("한글 분류 1/2")).toEqual([{ label: "한글 분류", count: 1, total: 2 }]);
  expect(parseModelBreakdown("question 0/2")).toEqual([{ label: "question", count: 0, total: 2 }]);
  for (const value of ["3/7", "question 3/0", "question 8/7", "question 3/7;", "question 3/7, problem 2/7", "question  3/7", "question -1/7", "question 1.5/7", "", 7, {}, undefined]) expect(parseModelBreakdown(value)).toBeNull();
});
it("matches model axis names exactly", async () => {
  const { modelAxis } = await import("../lib/insight");
  for (const name of ["오프닝 유형", "훅"]) expect(modelAxis(name)).toBe("hook");
  for (const name of ["스토리 소재", "소구", "메시지 유형"]) expect(modelAxis(name)).toBe("angle");
  expect(modelAxis("형식")).toBe("format");
  for (const name of ["오프닝", "훅 유형", " 훅", "훅 ", "오프닝  유형"]) expect(modelAxis(name)).toBeNull();
});

it("recognizes raw and localized other categories including schema names", async () => {
  const { isOtherCategory } = await import("../lib/insight");
  const names = taxonomyNames({ labels: [], relationships: [], claims: [], taxonomy: {
    hook_type: [{ value: "custom", name: "기타 훅", definition: "합성" }, { value: "question", name: "질문형", definition: "합성" }], angle: [], format: [],
  } });
  for (const label of ["other", "기타", "기타 훅", "기타 각도", "기타 포맷", "custom"]) expect(isOtherCategory(label, names)).toBe(true);
  for (const label of ["question", "질문형", "별도 유형"]) expect(isOtherCategory(label, names)).toBe(false);
});
it("sorts copied insight rows by counts stably with other categories last", async () => {
  const { sortInsightRows } = await import("../lib/insight");
  const rows = [{ value: "other", creatives: 99 }, { value: "question", creatives: 3 }, { value: "problem", creatives: 3 }, { value: "result_first", creatives: 5 }, { value: "기타 훅", creatives: 100 }];
  const snapshot = JSON.stringify(rows);
  expect(sortInsightRows("compare_axis_by_category", rows, taxonomyNames()).map(row => row.value)).toEqual(["result_first", "question", "problem", "기타 훅", "other"]);
  expect(JSON.stringify(rows)).toBe(snapshot);
});
it("uses top then bottom counts for comparison and count fallback with invalid numbers as zero", async () => {
  const { sortInsightRows } = await import("../lib/insight");
  const rows = [{ value: "other", n_top: 99, n_bottom: 99 }, { value: "a", n_top: 1, n_bottom: 5 }, { value: "b", n_top: 3, n_bottom: 1 }, { value: "c", n_top: 3, n_bottom: 4 }, { value: "d", n_top: 3, n_bottom: 4 }];
  const snapshot = JSON.stringify(rows);
  expect(sortInsightRows("top_vs_bottom_axis", rows, taxonomyNames()).map(row => row.value)).toEqual(["c", "d", "b", "a", "other"]);
  expect(JSON.stringify(rows)).toBe(snapshot);
  const counts = [{ value: "a", count: "9" }, { value: "b", count: 4 }, { value: "c", creatives: 3, count: 99 }, { value: "d", creatives: "8", count: 99 }, { value: "e" }, { value: "f", creatives: NaN }, { value: "g", count: Infinity }];
  expect(sortInsightRows("unknown", counts, taxonomyNames()).map(row => row.value)).toEqual(["b", "c", "a", "d", "e", "f", "g"]);
});
it("sorts model rows stably by count with localized other categories last without mutation", async () => {
  const { sortModelRows } = await import("../lib/insight");
  const rows = [{ label: "기타 각도", count: 9, total: 10 }, { label: "question", count: 2, total: 10 }, { label: "problem", count: 2, total: 10 }, { label: "result_first", count: 4, total: 10 }];
  const snapshot = JSON.stringify(rows);
  expect(sortModelRows(rows, taxonomyNames()).map(row => row.label)).toEqual(["result_first", "question", "problem", "기타 각도"]);
  expect(JSON.stringify(rows)).toBe(snapshot);
});
it("returns a total only for nonempty rows sharing one finite nonnegative integer", async () => {
  const { insightTotal } = await import("../lib/insight");
  expect(insightTotal([{ total: 1234 }, { total: 1234 }])).toBe(1234);
  expect(insightTotal([{ total: 0 }])).toBe(0);
  for (const rows of [[], [{ total: 2 }, { total: 3 }], [{ total: 2 }, {}], [{ total: 2.5 }], [{ total: -1 }], [{ total: NaN }], [{ total: Infinity }], [{ total: "2" }], [{ total: null }]]) expect(insightTotal(rows)).toBeNull();
});
it("limits the extra comparison note to the top and bottom tool", async () => {
  const { insightLimitNote } = await import("../lib/insight");
  expect(insightLimitNote("top_vs_bottom_axis")).toBe("상위 25% 광고 수가 많은 분류부터 5개까지 표시합니다.");
  for (const tool of ["compare_axis_by_category", "show_distribution", "unknown"]) expect(insightLimitNote(tool)).toBeNull();
});
