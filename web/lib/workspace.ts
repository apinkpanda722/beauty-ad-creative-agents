import type { Workspace } from "./types";

export function workspaceLabel(workspace: Workspace): string {
  const brand = workspace.display_name?.replace(/ (?:평가 작업 공간|개발 작업 공간|작업 공간)$/, "") || workspace.brand || workspace.tenant_id;
  return workspace.product_name ? `${brand} · ${workspace.product_name}` : brand;
}
