import type { ClaimChoice, Clarification } from "./types";
type OptionId = Clarification["options"][number]["id"];
const claims = new Set(["hydration", "soothing", "brightening", "firming_elasticity", "pore_sebum", "acne_trouble", "barrier", "anti_aging", "sun_protection", "texture_finish", "other"]);

export function buildChoice(optionId: OptionId, clarification: Clarification, selectedClaims: string[]): ClaimChoice | null {
  if (optionId === "cancel") return null;
  return {
    mode: optionId === "keep_requested" || optionId === "none" ? optionId : "selected",
    claims: optionId.startsWith("select") ? [...selectedClaims] : [],
    requested_claim: clarification.requested_claim,
  };
}
export function validateChoice(choice: ClaimChoice | null, clarification?: Clarification): boolean {
  if (!choice || !["selected", "keep_requested", "none"].includes(choice.mode)) return false;
  if (choice.requested_claim !== null && !claims.has(choice.requested_claim)) return false;
  if (choice.claims.some(c => c === "other" || !claims.has(c)) || new Set(choice.claims).size !== choice.claims.length) return false;
  if (choice.mode === "keep_requested" && choice.requested_claim === null) return false;
  if (choice.mode !== "selected") return choice.claims.length === 0;
  return choice.claims.length > 0 && (!clarification || choice.claims.every(c => clarification.available.some(a => a.claim === c)));
}
