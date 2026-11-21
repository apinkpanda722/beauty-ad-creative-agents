import { expect, it } from "vitest";
import { localizeText, scoreNames, scoreExplanations } from "../lib/localize";
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
  "https://example.test/how_to?q=fit#person_first", "이미 한글인 문장", "unknown_snake_case",
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

it("overrides desire while preserving unnamed angle values and protected axis tokens", () => {
  expect(localizeText("desire other question", names)).toBe("이상형 제시형 other question");
  expect(localizeText("desire")).toBe("이상형 제시형");
  expect(localizeText("how_to problem_solution social_proof comparison ingredient_science")).toBe("how_to problem_solution social_proof comparison ingredient_science");
  expect(localizeText("hook_type angle format", names)).toBe("훅 소구 형식");
  expect(localizeText("how_to_use youtube:angle angles", names)).toBe("how_to_use youtube:angle angles");
});

it("defines the shared score explanations exactly", () => {
  expect(scoreExplanations.differentiation).toBe("경쟁사가 가장 많이 쓰는 방식(훅·소구·형식)과 얼마나 다른지 AI가 1~5점으로 평가합니다. 5점은 뚜렷이 다르면서 근거로 뒷받침된 경우입니다.");
  expect(scoreExplanations.fit).toBe("요청한 조건(카테고리·목표·제품·말투)을 얼마나 충족하고, 카피가 소비자의 실제 상황에서 출발한 자연스러운 구어체인지 AI가 1~5점으로 평가합니다.");
});
