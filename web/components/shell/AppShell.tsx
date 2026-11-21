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
    <TopBar workspace={workspace} collapsed={collapsed} navId={navId} onToggle={() => setCollapsed(value => !value)} />
    <Sidebar id={navId} collapsed={collapsed} view={view} onViewChange={setView} />
    <main className="gs-content">{children(view, setView)}</main>
  </div>;
}
