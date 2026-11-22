import type { Workspace } from "./types";

function displayBrand(displayName: string | null | undefined): string | undefined {
  return displayName?.replace(/ (?:평가 작업 공간|개발 작업 공간|작업 공간)$/, "").trim() || undefined;
}
export function koreanBrand(productDisplay: { display_name?: string | null }): string {
  return displayBrand(productDisplay.display_name) ?? "브랜드 정보 없음";
}
export function workspaceLabel(workspace: Workspace): string {
  return displayBrand(workspace.display_name) || workspace.brand || workspace.tenant_id;
}
