import { NavIcon } from "./icons";
import type { View } from "./AppShell";

const groups: { label: string; items: { view: View; label: string }[] }[] = [
  { label: "작업", items: [
    { view: "plan", label: "광고 기획" },
    { view: "evidence", label: "근거 소재" },
    { view: "saved", label: "저장한 기획" },
  ] },
  { label: "관리", items: [
    { view: "graph", label: "지식 그래프" },
    { view: "history", label: "실행 기록·검증" },
  ] },
];

export function Sidebar({ view, onViewChange }: { view: View; onViewChange: (view: View) => void }) {
  return <nav className="gs-sidebar" aria-label="주요 화면">
    {groups.map(group => <div className="gs-nav-group" role="group" aria-label={group.label} key={group.label}>
      <span className="gs-nav-group-label">{group.label}</span>
      {group.items.map(item => <button key={item.view} type="button"
      className={view === item.view ? "gs-nav-pill" : undefined}
      aria-current={view === item.view ? "page" : undefined}
      onClick={() => onViewChange(item.view)}><NavIcon view={item.view} />{item.label}</button>)}
    </div>)}
  </nav>;
}
