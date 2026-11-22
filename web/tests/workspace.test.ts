import { expect, it } from "vitest";
import { koreanBrand, workspaceLabel } from "../lib/workspace";
import type { Workspace } from "../lib/types";
const base: Workspace = { tenant_id: "synthetic", display_name: null, brand: null, product_name: null };
it.each([
  ["믹순 개발 작업 공간", "믹순"], ["코스알엑스 개발 작업 공간", "코스알엑스"],
  ["이즈앤트리 평가 작업 공간", "이즈앤트리"], ["조선미녀 평가 작업 공간", "조선미녀"],
  ["이름 작업 공간", "이름"], ["접미사 없는 이름", "접미사 없는 이름"],
])("removes only workspace suffixes: %s", (display_name, brand) => {
  expect(workspaceLabel({ ...base, display_name })).toBe(brand);
  expect(workspaceLabel({ ...base, display_name, product_name: "인삼선세럼 SPF 50+" })).toBe(brand);
});
it("shows only the brand in the label even when the workspace has a product name", () => {
  const workspace: Workspace = { ...base, display_name: "조선미녀 평가 작업 공간", brand: "beauty_of_joseon", product_name: "인삼선세럼 (SPF 50+ PA++++)" };
  const snapshot = JSON.stringify(workspace);
  expect(workspaceLabel(workspace)).toBe("조선미녀");
  expect(workspaceLabel(workspace)).not.toContain("인삼선세럼");
  expect(workspaceLabel(workspace)).not.toContain("·");
  expect(JSON.stringify(workspace)).toBe(snapshot);
});
it("falls back to the brand slug then tenant ID", () => {
  expect(workspaceLabel({ ...base, brand: "synthetic-brand" })).toBe("synthetic-brand");
  expect(workspaceLabel(base)).toBe("synthetic");
});
it.each([
  ["믹순 개발 작업 공간", "믹순"], ["코스알엑스 개발 작업 공간", "코스알엑스"],
  ["이즈앤트리 평가 작업 공간", "이즈앤트리"], ["조선미녀 평가 작업 공간", "조선미녀"],
  [null, "브랜드 정보 없음"], ["", "브랜드 정보 없음"],
])("extracts the display brand without a slug fallback: %s", (display_name, expected) => {
  expect(koreanBrand({ display_name })).toBe(expected);
});
