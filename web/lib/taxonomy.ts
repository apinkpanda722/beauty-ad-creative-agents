import type { SchemaResponse } from "./types";

// Closed names from analysis/prompts.py _TALENT_CRITERIA and _CTA_CRITERIA.
export const TALENT_NAMES = {
  none: "출연자 없음",
  ordinary_person: "일반 출연자",
  creator: "크리에이터",
  celebrity: "유명인",
  expert: "전문가",
  staff: "직원",
} as const;
export const CTA_NAMES = {
  none: "행동 유도 없음",
  shop_now: "구매 유도",
  learn_more: "자세히 알아보기",
  store_mention: "판매처 언급",
  event: "할인·증정·기간",
  follow_engage: "팔로우·참여 유도",
} as const;
export function talentName(value: string): string {
  return Object.hasOwn(TALENT_NAMES, value) ? TALENT_NAMES[value as keyof typeof TALENT_NAMES] : value;
}
export function ctaName(value: string): string {
  return Object.hasOwn(CTA_NAMES, value) ? CTA_NAMES[value as keyof typeof CTA_NAMES] : value;
}
export function taxonomyNames(schema?: SchemaResponse | null) {
  const angleDisplayName = (value: string) => value === "desire" ? "이상형 제시형" : undefined;
  return {
    axisName(axis: keyof SchemaResponse["taxonomy"], value: string): string {
      return (axis === "angle" ? angleDisplayName(value) : undefined) ?? schema?.taxonomy?.[axis]?.find(item => item.value === value)?.name ?? value;
    },
    claimName(value: string): string {
      return schema?.claims?.find(item => item.value === value)?.name ?? value;
    },
    valueName(value: string): string {
      const displayName = angleDisplayName(value);
      if (displayName) return displayName;
      for (const axis of ["hook_type", "angle", "format"] as const) {
        const name = schema?.taxonomy?.[axis]?.find(item => item.value === value)?.name;
        if (name != null) return name;
      }
      return schema?.claims?.find(item => item.value === value)?.name ?? value;
    },
  };
}
export type TaxonomyNames = ReturnType<typeof taxonomyNames>;
