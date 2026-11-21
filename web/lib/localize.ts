import { ctaName, talentName, taxonomyNames, type TaxonomyNames } from "./taxonomy";

export const scoreNames: Record<string, string> = { differentiation: "차별성", fit: "요청 적합성" };
export const scoreExplanations = {
  differentiation: "경쟁사가 가장 많이 쓰는 방식(훅·소구·형식)과 얼마나 다른지 AI가 1~5점으로 평가합니다. 5점은 뚜렷이 다르면서 근거로 뒷받침된 경우입니다.",
  fit: "요청한 조건(카테고리·목표·제품·말투)을 얼마나 충족하고, 카피가 소비자의 실제 상황에서 출발한 자연스러운 구어체인지 AI가 1~5점으로 평가합니다.",
} as const;
export const axisNames = { hook_type: "훅", angle: "소구", format: "형식" } as const;

export function displayValue(value: string, names: TaxonomyNames = taxonomyNames()): string {
  if (value === "other") return "기타";
  return names.valueName(value) || value;
}

// Match a whole identifier at once (longest first), and protect URLs and namespaced IDs.
// Names come from the schema and the existing closed maps; source data stays untouched.
export function localizeText(text: string | null | undefined, names: TaxonomyNames = taxonomyNames()): string {
  return (text ?? "").replace(
    /[A-Za-z][A-Za-z0-9+.-]*:\/\/[^\s<>"']+|[A-Za-z0-9_]+:[A-Za-z0-9_:/?&#=.%+-]+|[A-Za-z0-9_]+/g,
    token => {
      if (token.includes(":") || token === "other") return token;
      const label = Object.hasOwn(axisNames, token) ? axisNames[token as keyof typeof axisNames]
        : Object.hasOwn(scoreNames, token) ? scoreNames[token]
        : names.valueName(token) !== token ? names.valueName(token)
        : talentName(token) !== token ? talentName(token) : ctaName(token);
      return label?.trim() ? label : token;
    },
  );
}
