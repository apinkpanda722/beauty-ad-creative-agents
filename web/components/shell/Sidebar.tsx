import type { View } from "./AppShell";

const items: { view: View; label: string }[] = [
  { view: "plan", label: "광고 기획" },
  { view: "evidence", label: "근거 소재" },
  { view: "graph", label: "지식 그래프" },
  { view: "history", label: "실행 기록" },
  { view: "saved", label: "저장한 기획" },
];

export function Sidebar({ view, onViewChange }: { view: View; onViewChange: (view: View) => void }) {
  return <nav className="gs-sidebar" aria-label="주요 화면">
    {items.map(item => <button key={item.view} type="button"
      aria-current={view === item.view ? "page" : undefined}
      onClick={() => onViewChange(item.view)}>{item.label}</button>)}
  </nav>;
}
