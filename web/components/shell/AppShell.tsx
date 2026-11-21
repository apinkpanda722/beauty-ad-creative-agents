"use client";

import { useState } from "react";
import type { ReactNode } from "react";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

export type View = "plan" | "evidence" | "graph" | "history" | "saved";

export function AppShell({ children, workspace }: {
  children: (view: View, onViewChange: (view: View) => void) => ReactNode;
  workspace?: ReactNode;
}) {
  const [view, setView] = useState<View>("plan");
  return <div className="gs-shell">
    <TopBar workspace={workspace} />
    <Sidebar view={view} onViewChange={setView} />
    <main className="gs-content">{children(view, setView)}</main>
  </div>;
}
