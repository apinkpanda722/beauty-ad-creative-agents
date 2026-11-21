"use client";

import { useEffect, useId, useRef, useState } from "react";
import type { Workspace } from "../../lib/types";
import { workspaceLabel } from "../../lib/workspace";

export function WorkspaceChip({ workspaces, value, onChange }: {
  workspaces: Workspace[]; value: string | null; onChange: (tenantId: string | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const options = useRef<(HTMLLIElement | null)[]>([]);
  const id = useId();
  const selected = workspaces.find(workspace => workspace.tenant_id === value);
  useEffect(() => {
    if (!open) return;
    options.current[active]?.focus();
  }, [open, active]);
  useEffect(() => {
    if (!open) return;
    function outside(event: MouseEvent) { if (!root.current?.contains(event.target as Node)) setOpen(false); }
    document.addEventListener("mousedown", outside);
    document.addEventListener("click", outside);
    return () => { document.removeEventListener("mousedown", outside); document.removeEventListener("click", outside); };
  }, [open]);
  function close() { setOpen(false); button.current?.focus(); }
  function show() { setActive(Math.max(0, workspaces.findIndex(workspace => workspace.tenant_id === value))); setOpen(true); }
  function choose(workspace: Workspace) {
    if (value !== workspace.tenant_id) onChange(workspace.tenant_id);
    close();
  }
  return <div className="gs-workspace" ref={root} onBlur={event => {
    if (event.relatedTarget && !event.currentTarget.contains(event.relatedTarget as Node)) setOpen(false);
  }}>
    <button className="gs-workspace-chip" type="button" ref={button} aria-label="작업 공간" aria-haspopup="listbox" aria-expanded={open} aria-controls={open ? id : undefined}
      onClick={() => open ? close() : show()} onKeyDown={event => {
        if (["Enter", " ", "ArrowDown"].includes(event.key)) { event.preventDefault(); show(); }
        if (event.key === "Escape") { event.preventDefault(); close(); }
      }}>
      <span className="gs-workspace-dot" data-selected={Boolean(selected)} aria-hidden="true" />
      <span>{selected ? workspaceLabel(selected) : "작업 공간을 선택하세요"}</span>
      <svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" aria-hidden="true"><path d="m5 8 5 5 5-5" /></svg>
    </button>
    {open && <div className="gs-workspace-menu">
      <ul role="listbox" id={id} aria-label="작업 공간 목록" onKeyDown={event => {
        if (event.key === "Escape") { event.preventDefault(); close(); }
        else if (["ArrowDown", "ArrowUp"].includes(event.key)) {
          event.preventDefault();
          if (workspaces.length) setActive(index => (index + (event.key === "ArrowDown" ? 1 : -1) + workspaces.length) % workspaces.length);
        } else if (event.key === "Enter" || event.key === " ") {
          event.preventDefault(); if (workspaces[active]) choose(workspaces[active]);
        }
      }}>
        {workspaces.map((workspace, index) => <li key={workspace.tenant_id} role="option" aria-selected={workspace.tenant_id === value} tabIndex={index === active ? 0 : -1}
          ref={element => { options.current[index] = element; }} onClick={() => choose(workspace)} onFocus={() => setActive(index)}>{workspaceLabel(workspace)}</li>)}
      </ul>
      <small>작업 공간은 서버를 시작할 때 정한 그룹 하나만 보입니다. 바꾸려면 서버를 다시 시작하세요.</small>
    </div>}
  </div>;
}
