import { displayValue } from "./localize";
import type { TaxonomyNames } from "./taxonomy";

// Aggregate/compare entries in agents/tools.py; display titles do not change tool data.
export const TOOL_TITLES: Record<string, string> = {
  ad_angles_formats_by_skin_type: "피부 타입별 메시지와 제작 형식",
  compare_axis_by_category: "카테고리별 광고 비교",
  compare_competitor_claims: "경쟁 광고 효능 비교",
  compare_hooks_by_category: "카테고리별 오프닝 비교",
  compare_price_band_competitors: "비슷한 가격대 광고 비교",
  count_claim_supported_ads: "효능 근거가 연결된 광고",
  ingredient_ad_trend: "성분 광고의 게시 추이",
  top_claims_of_ingredient_ads: "성분 광고의 효능 분포",
  top_vs_bottom_axis: "상위 vs 하위 광고 비교",
  unclaimed_efficacy_gaps: "광고에 언급되지 않은 효능",
};
const axes = [
  { title: "오프닝 방식 분포", values: ["question", "problem", "result_first", "bold_claim", "product_first", "person_first", "other"] },
  { title: "메시지 유형 분포", values: ["problem_solution", "desire", "social_proof", "comparison", "ingredient_science", "how_to", "other"] },
  { title: "제작 형식 분포", values: ["ugc_style", "studio_film", "demo", "text_motion", "static_image", "other"] },
];
export function insightTitle(tool: string, values: string[]): string {
  if (tool === "top_vs_bottom_axis") return TOOL_TITLES[tool];
  if (tool !== "show_distribution" && !Object.hasOwn(TOOL_TITLES, tool)) return "시장 인사이트";
  const axis = values.some(value => value !== "other") && axes.find(axis => values.every(value => axis.values.includes(value)));
  return axis ? axis.title : Object.hasOwn(TOOL_TITLES, tool) ? TOOL_TITLES[tool] : "시장 인사이트";
}
const columns: Record<string, string> = {
  value: "분류", n_top: "상위 25%", n_bottom: "하위 25%", creatives: "소재 수",
  category: "카테고리", claim: "효능", hook_type: "오프닝 방식", angle: "메시지 유형", format: "제작 형식",
  count: "건수", total: "전체 건수", brand: "브랜드", published_at: "게시일", view_count: "조회수",
};
export function columnName(key: string): string { return Object.hasOwn(columns, key) ? columns[key] : "항목"; }
export function insightValue(value: string, names: TaxonomyNames): string { return displayValue(value, names); }
