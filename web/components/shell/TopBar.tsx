import type { ReactNode } from "react";
import { Mark } from "./Mark";
import { BRAND } from "../../lib/brand";

export function TopBar({ workspace, collapsed, navId, onToggle }: {
  workspace?: ReactNode; collapsed: boolean; navId: string; onToggle: () => void;
}) {
  return <header className="gs-topbar">
    <div className="gs-logo"><button type="button" className="gs-sidebar-toggle" aria-label={collapsed ? "사이드바 펼치기" : "사이드바 접기"}
      aria-expanded={!collapsed} aria-controls={navId} onClick={onToggle}><Mark /></button><strong>{BRAND.name}</strong><span>{BRAND.nameKo}</span></div>
    <div className="gs-workspace-slot" aria-label="현재 작업 공간">{workspace}</div>
  </header>;
}
