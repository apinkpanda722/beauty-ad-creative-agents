import { expect, it } from "vitest";
import { unknownReasons } from "../lib/unknown";
it.each([
  ["CERT_REQUIRED_UNVERIFIED", "인증 자료 연결 없음"],
  ["EFFICACY_UNKNOWN", "효능 근거 연결 없음"],
  ["EFFICACY_UNSUPPORTED", "효능 근거가 뒷받침하지 않음"],
  ["SYNTHETIC_UNKNOWN", "SYNTHETIC_UNKNOWN"],
])("uses only known reason names: %s", (code, expected) => {
  expect(unknownReasons({ [code]: 1 }, 1)).toBe(expected);
});
it("sorts by descending count then code and abbreviates after two reasons", () => {
  expect(unknownReasons({ EFFICACY_UNKNOWN: 1, Z: 3, CERT_REQUIRED_UNVERIFIED: 3, EFFICACY_UNSUPPORTED: 2 }, 9))
    .toBe("인증 자료 연결 없음 · Z · 외 2종");
  expect(unknownReasons({ Z: 1, A: 1 }, 2)).toBe("A · Z");
});
it("has no reasons for zero unknown items", () => {
  expect(unknownReasons({ EFFICACY_UNKNOWN: 2 }, 0)).toBe("");
  expect(unknownReasons({}, 1)).toBe("");
});
