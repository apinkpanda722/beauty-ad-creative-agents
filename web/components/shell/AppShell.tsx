"use client";

import { useId, useState } from "react";
import type { ReactNode } from "react";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

export type View = "plan" | "evidence" | "graph" | "history" | "saved";

export function AppShell({ children, workspace }: {
  children: (view: View, onViewChange: (view: View) => void) => ReactNode;
  workspace?: ReactNode;
}) {
  const [view, setView] = useState<View>("plan");
  const [collapsed, setCollapsed] = useState(false);
  const navId = useId();
  return <div className="gs-shell" data-sidebar={collapsed ? "collapsed" : "expanded"}>
    <TopBar workspace={workspace} />
    <div className="gs-sidebar-column">
      <div className="gs-sidebar-head">
        <button type="button" className="gs-sidebar-toggle" aria-label={collapsed ? "사이드바 펼치기" : "사이드바 접기"}
          aria-expanded={!collapsed} aria-controls={navId} onClick={() => setCollapsed(value => !value)}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true" style={{ display: "block" }}>
            <path d={collapsed ? "M13 7l5 5-5 5M6 7l5 5-5 5" : "M11 7 6 12l5 5M18 7l-5 5 5 5"} />
          </svg>
        </button>
      </div>
      <Sidebar id={navId} collapsed={collapsed} view={view} onViewChange={setView} />
    </div>
    <main className="gs-content">{children(view, setView)}</main>
  </div>;
}
