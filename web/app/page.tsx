"use client";

import { useEffect, useState } from "react";
import { PlanPage } from "../components/plan/PlanPage";
import { SchemaView } from "../components/SchemaView";
import { AppShell } from "../components/shell/AppShell";
import { EvidencePage } from "../components/evidence/EvidencePage";
import { getWorkspaces } from "../lib/api";
import { SessionProvider, useSession } from "../lib/session";
import type { WorkspacesResponse } from "../lib/types";

export default function Page() {
  return <SessionProvider><WorkspaceShell /></SessionProvider>;
}

function WorkspaceShell() {
  const [data, setData] = useState<WorkspacesResponse | null>(null);
  const [failed, setFailed] = useState(false);
  const { state } = useSession();
  useEffect(() => {
    let active = true;
    getWorkspaces().then(value => { if (active) setData(value); }).catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, []);
  return <AppShell workspace={data?.workspaces.find(workspace => workspace.tenant_id === state.tenantId)?.display_name}>
    {(view, setView) => <>
      {(view === "plan" || view === "graph") && <>
        <header><h1>Beauty Ad Creative Agents</h1><p className="muted">뷰티 광고 기획 작업 공간</p></header>
        <div role="tablist" aria-label="화면 선택" className="view-tabs">
          <button type="button" role="tab" id="chat-tab" aria-selected={view === "plan"} aria-controls="chat-view" onClick={() => setView("plan")}>대화</button>
          <button type="button" role="tab" id="schema-tab" aria-selected={view === "graph"} aria-controls="schema-view" onClick={() => setView("graph")}>전체 스키마</button>
        </div>
      </>}
      {view === "evidence" && <EvidencePage key={state.tenantId} turns={state.turns} workspaceBrand={data?.workspaces.find(workspace => workspace.tenant_id === state.tenantId)?.brand ?? null} onPlan={() => setView("plan")} />}
      {view === "history" || view === "saved" ? <section className="gs-placeholder">
        <h1>{{ history: "실행 기록", saved: "저장한 기획" }[view]}</h1><p>준비 중</p>
      </section> : null}
      {failed ? <p role="alert">API 서버에 연결하지 못했습니다. 서버가 실행 중인지 확인하세요.</p>
        : data ? <>
          <div role="tabpanel" id="chat-view" aria-labelledby="chat-tab" hidden={view !== "plan"}><PlanPage workspaces={data.workspaces} imageEnabled={data.image_enabled} /></div>
          <div role="tabpanel" id="schema-view" aria-labelledby="schema-tab" hidden={view !== "graph"}>{view === "graph" && (state.tenantId ? <SchemaView tenantId={state.tenantId} /> : <p>대화 탭에서 작업 공간을 선택하세요.</p>)}</div>
        </> : (view === "plan" || view === "graph") && <p role="status">작업 공간 목록을 불러오는 중입니다.</p>}
    </>}
  </AppShell>;
}
