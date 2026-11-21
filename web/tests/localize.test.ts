import { expect, it } from "vitest";
import { localizeText, scoreNames } from "../lib/localize";
import { taxonomyNames } from "../lib/taxonomy";

const names = taxonomyNames({ labels: [], relationships: [], taxonomy: {
  hook_type: [{ value: "person_first", name: "인물 먼저 제시형", definition: "" }, { value: "product_first", name: "합성 제품 먼저", definition: "" }],
  angle: [{ value: "how_to", name: "합성 사용법", definition: "" }, { value: "desire", name: "", definition: "" }],
  format: [{ value: "studio_film", name: "합성 스튜디오", definition: "" }],
}, claims: [{ value: "hydration", name: "합성 보습" }, { value: "product", name: "합성 제품" }] });
it("localizes known complete codes using server names and shared score/closed names", () => {
  expect(localizeText("person_first how_to studio_film differentiation fit hydration ordinary_person shop_now", names))
    .toBe(`인물 먼저 제시형 합성 사용법 합성 스튜디오 ${scoreNames.differentiation} ${scoreNames.fit} 합성 보습 일반 출연자 구매 유도`);
});
it.each([
  "profit benefit fitness outfit", "how_to_use person_first_x", "youtube:how_to instagram:person_first",
  "https://example.test/how_to?q=fit#person_first", "이미 한글인 문장", "unknown_snake_case", "desire other question",
  "evidence_id=youtube:how_to", "urn:synthetic:fit",
])("preserves protected and unnamed text: %s", text => {
  expect(localizeText(text, names)).toBe(text);
});
it("replaces longest whole identifiers repeatedly without modifying the source", () => {
  const text = "product_first product person_first, person_first (fit).";
  expect(localizeText(text, names)).toBe("합성 제품 먼저 합성 제품 인물 먼저 제시형, 인물 먼저 제시형 (요청 적합성).");
  expect(text).toBe("product_first product person_first, person_first (fit).");
});
it("accepts empty and null text", () => {
  expect(localizeText("", names)).toBe("");
  expect(localizeText(null, names)).toBe("");
});
