import { describe, expect, it } from "vitest";
import { buildChoice, validateChoice } from "../lib/claim";
import type { Clarification, ClaimChoice } from "../lib/types";
const clarification: Clarification = {
  reason: "requested_not_confirmed", requested_claim: "soothing", requested_label: "합성 요청 효능", text: "합성 질문",
  available: [{ claim: "hydration", label: "합성 효능 A" }, { claim: "barrier", label: "합성 효능 B" }],
  options: ["keep_requested", "select_confirmed", "select_one", "select_many", "none", "cancel"].map(id => ({ id: id as Clarification["options"][number]["id"], label: `합성 ${id}` })),
};
describe("claim choices", () => {
  it.each(["select_confirmed", "select_one", "select_many"] as const)("builds exact selected body for %s with and without a requested claim", (option) => {
    expect(buildChoice(option, clarification, ["hydration"])).toEqual({ mode: "selected", claims: ["hydration"], requested_claim: "soothing" });
    expect(buildChoice(option, { ...clarification, reason: "no_claim_requested", requested_claim: null }, ["hydration"])).toEqual({ mode: "selected", claims: ["hydration"], requested_claim: null });
    expect(validateChoice(buildChoice(option, clarification, []), clarification)).toBe(false);
  });
  it("builds keep, none and cancel exactly", () => {
    expect(buildChoice("keep_requested", clarification, [])).toEqual({ mode: "keep_requested", claims: [], requested_claim: "soothing" });
    expect(buildChoice("none", clarification, [])).toEqual({ mode: "none", claims: [], requested_claim: "soothing" });
    expect(buildChoice("none", { ...clarification, requested_claim: null }, [])).toEqual({ mode: "none", claims: [], requested_claim: null });
    expect(buildChoice("cancel", clarification, [])).toBeNull();
  });
  it.each([
    { mode: "selected", claims: ["other"], requested_claim: null },
    { mode: "selected", claims: ["hydration", "hydration"], requested_claim: null },
    { mode: "selected", claims: ["soothing"], requested_claim: null },
    { mode: "selected", claims: ["unknown"], requested_claim: null },
    { mode: "keep_requested", claims: [], requested_claim: null },
    { mode: "none", claims: ["hydration"], requested_claim: null },
    { mode: "none", claims: [], requested_claim: "unknown" },
  ] as ClaimChoice[])("rejects invalid server body %j", choice => expect(validateChoice(choice, clarification)).toBe(false));
});
