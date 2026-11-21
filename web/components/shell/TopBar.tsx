import type { ReactNode } from "react";
import { BRAND } from "../../lib/brand";

export function TopBar({ workspace }: { workspace?: ReactNode }) {
  return <header className="gs-topbar">
    <div className="gs-logo"><strong>{BRAND.name}</strong><span>{BRAND.nameKo}</span></div>
    <div className="gs-workspace-slot" aria-label="현재 작업 공간">{workspace ?? "작업 공간을 선택하세요"}</div>
  </header>;
}
