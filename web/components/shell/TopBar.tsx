import type { ReactNode } from "react";
import { Mark } from "./Mark";
import { BRAND } from "../../lib/brand";

export function TopBar({ workspace }: { workspace?: ReactNode }) {
  return <header className="gs-topbar">
    <div className="gs-logo"><Mark /><strong>{BRAND.name}</strong><span>{BRAND.nameKo}</span></div>
    <div className="gs-workspace-slot" aria-label="현재 작업 공간">{workspace}</div>
  </header>;
}
