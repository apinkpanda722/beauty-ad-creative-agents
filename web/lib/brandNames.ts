"use client";

import { createContext } from "react";
import type { Workspace } from "./types";
import { koreanBrand } from "./workspace";

export type BrandNames = ReadonlyMap<string, string>;
const normalize = (brand: string) => brand.trim().toLowerCase().replace(/[\s-]+/g, "_");

export function brandNameMap(workspaces: readonly Workspace[]): BrandNames {
  const names = new Map<string, string>();
  for (const workspace of workspaces) {
    const key = normalize(workspace.brand ?? "");
    const name = koreanBrand({ display_name: workspace.display_name });
    if (key && name !== "브랜드 정보 없음") names.set(key, name);
  }
  return names;
}

export function brandDisplayName(brand: string | null | undefined, names?: BrandNames, missing = "정보 없음"): string {
  if (!brand?.trim()) return missing;
  return names?.get(normalize(brand)) ?? brand.replace(/_/g, " ");
}

export const BrandNamesContext = createContext<BrandNames>(new Map());
