import { ctaName, talentName, taxonomyNames, type TaxonomyNames } from "./taxonomy";

export const scoreNames: Record<string, string> = { differentiation: "차별성", fit: "요청 적합성" };

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
      const label = Object.hasOwn(scoreNames, token) ? scoreNames[token]
        : names.valueName(token) !== token ? names.valueName(token)
        : talentName(token) !== token ? talentName(token) : ctaName(token);
      return label?.trim() ? label : token;
    },
  );
}
