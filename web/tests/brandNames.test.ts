import { expect, it } from "vitest";
import { brandDisplayName, brandNameMap } from "../lib/brandNames";
import type { Workspace } from "../lib/types";
const workspace = (brand: string | null, display_name: string | null): Workspace => ({ brand, display_name, tenant_id: "synthetic", product_name: null });
it("maps normalized workspace slugs without changing workspaces or inventing missing names", () => {
  const source = [workspace(" Beauty-Of Joseon ", "조선미녀 평가 작업 공간"), workspace("SYNTHETIC-BRAND", "합성 개발 작업 공간"), workspace("absent", null), workspace("   ", "합성 작업 공간")];
  const snapshot = JSON.stringify(source); const names = brandNameMap(source);
  expect([...names]).toEqual([["beauty_of_joseon", "조선미녀"], ["synthetic_brand", "합성"]]);
  expect(brandDisplayName("beauty_of_joseon", names)).toBe("조선미녀");
  expect(brandDisplayName("Beauty-Of Joseon", names)).toBe("조선미녀");
  expect(JSON.stringify(source)).toBe(snapshot); expect([...names]).toEqual([["beauty_of_joseon", "조선미녀"], ["synthetic_brand", "합성"]]);
});
it.each([["synthetic_brand_x", "synthetic brand x"], ["합성 브랜드", "합성 브랜드"], ["Synthetic-Brand", "Synthetic-Brand"]])("preserves unmapped spelling except underscores: %s", (value, expected) => {
  const names = new Map([["other", "합성"]]); const snapshot = [...names];
  expect(brandDisplayName(value, names)).toBe(expected); expect([...names]).toEqual(snapshot);
});
it.each([null, "", "   "])("uses the specified missing label for %s", value => {
  expect(brandDisplayName(value)).toBe("정보 없음"); expect(brandDisplayName(value, undefined, "브랜드 정보 없음")).toBe("브랜드 정보 없음");
});
