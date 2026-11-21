"use client";

import { useEffect, useId, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import { getSchema } from "../../lib/api";
import { useSession } from "../../lib/session";
import { taxonomyNames } from "../../lib/taxonomy";
import type { TaxonomyNames } from "../../lib/taxonomy";
import type { Turn } from "../../lib/reducer";
import { nextActiveTabId } from "../../lib/reducer";
import type { SchemaResponse } from "../../lib/types";
import { Button } from "../ui";

// Taxonomy values without a Korean display name must not expose internal codes.
function korean(value?: string | null) { return value && /[가-힣]/.test(value) ? value : null; }
function titleFor(turns: Turn[], id: number, names: TaxonomyNames) {
  const finished = turns.filter(turn => turn.status === "done");
  const result = finished.flatMap(turn => turn.commands).findLast(command => command.kind === "show_plan");
  if (result) {
    const claim = result.data.plan.claimed_efficacy?.[0];
    const product = korean(result.data.plan.category) ?? korean(result.data.product_display?.product_name);
    if (claim || product) return [claim ? korean(names.claimName(claim)) ?? "기타" : null, product].filter(Boolean).join(" · ");
  }
  const request = finished.at(-1)?.message;
  return request ? `${korean(request.slice(0, 14)) ?? "정보 없음"}…` : `기획 ${id}`;
}

export function PlanTabs() {
  const { state, newTab, selectTab, closeTab } = useSession();
  const prefix = useId();
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  const [schema, setSchema] = useState<{ tenantId: string; data: SchemaResponse } | null>(null);
  const tabs = state.tabs ?? [{ id: 1, threadId: state.threadId }];
  const active = state.activeTabId ?? 1;
  const needsSchema = tabs.some(tab => state.turns.filter(turn => (turn.tabId ?? 1) === tab.id && turn.status === "done")
    .flatMap(turn => turn.commands).findLast(command => command.kind === "show_plan")?.data.plan.claimed_efficacy?.length);
  useEffect(() => {
    const tenantId = state.tenantId;
    if (!tenantId || !needsSchema) return;
    let current = true;
    void getSchema(tenantId).then(data => { if (current) setSchema({ tenantId, data }); }).catch(() => { /* Unmapped claims use the Korean fallback. */ });
    return () => { current = false; };
  }, [state.tenantId, needsSchema]);
  const names = taxonomyNames(schema?.tenantId === state.tenantId ? schema.data : null);
  function move(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    let next: number;
    switch (event.key) {
      case "ArrowRight": case "ArrowDown": next = (index + 1) % tabs.length; break;
      case "ArrowLeft": case "ArrowUp": next = (index - 1 + tabs.length) % tabs.length; break;
      case "Home": next = 0; break;
      case "End": next = tabs.length - 1; break;
      default: return;
    }
    event.preventDefault();
    buttons.current[next]?.focus();
    selectTab(tabs[next].id);
  }
  function close(id: number) {
    // Move focus before removing the close button from the document.
    const nextId = nextActiveTabId(tabs, id, active);
    if (nextId !== null) buttons.current[tabs.findIndex(tab => tab.id === nextId)]?.focus();
    closeTab(id);
  }
  return <div className="gs-plan-tabs gs-ui">
    <div className="gs-tab-list" role="tablist" aria-label="기획 탭" aria-orientation="horizontal">
      {tabs.map((tab, index) => {
        const turns = state.turns.filter(turn => (turn.tabId ?? 1) === tab.id);
        const running = turns.some(turn => turn.id === state.activeTurnId);
        return <div className="gs-plan-tab-item" role="presentation" key={tab.id}>
          <button className="gs-tab" id={`${prefix}-tab-${tab.id}`} type="button" role="tab"
            ref={element => { buttons.current[index] = element; }} aria-selected={tab.id === active}
            tabIndex={tab.id === active ? 0 : -1} aria-busy={running}
            onClick={() => selectTab(tab.id)} onKeyDown={event => move(event, index)}>
            {running && <span className="gs-tab-spinner" aria-hidden="true" />}{titleFor(turns, tab.id, names)}
          </button>
          <button className="gs-tab-close" type="button" aria-label={`기획 ${tab.id} 닫기`} disabled={running}
            onClick={() => close(tab.id)}><svg aria-hidden="true" width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor"><path d="M3 3l6 6M9 3l-6 6" /></svg></button>
        </div>;
      })}
    </div>
    <Button variant="ghost" size="sm" disabled={state.activeTurnId !== null} onClick={newTab}>+ 새 기획</Button>
  </div>;
}
