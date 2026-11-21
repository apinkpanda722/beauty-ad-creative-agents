"use client";

import { useEffect, useState } from "react";
import { HistoryPage } from "../components/history/HistoryPage";
import { OpenHistoryDetailContext, CommandTenantContext } from "../components/results/ResultsView";
import { PlanPage } from "../components/plan/PlanPage";
import { GraphPage } from "../components/graph/GraphPage";
import { OpenGraphPathContext } from "../components/graph/context";
import { AppShell } from "../components/shell/AppShell";
import type { View } from "../components/shell/AppShell";
import { EvidencePage } from "../components/evidence/EvidencePage";
import { SavedPage } from "../components/saved/SavedPage";
import { WorkspaceChip } from "../components/shell/WorkspaceChip";
import { getWorkspaces } from "../lib/api";
import { latestGraphIds } from "../lib/graph";
import { SessionProvider, useSession } from "../lib/session";
import type { WorkspacesResponse } from "../lib/types";

export default function Page() {
  return <SessionProvider><WorkspaceShell /></SessionProvider>;
}

function WorkspaceShell() {
  const [data, setData] = useState<WorkspacesResponse | null>(null);
  const [failed, setFailed] = useState(false);
  const { state, selectWorkspace } = useSession();
  useEffect(() => {
    let active = true;
    getWorkspaces().then(value => { if (active) setData(value); }).catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, []);
  return <AppShell workspace={<WorkspaceChip workspaces={data?.workspaces ?? []} value={state.tenantId} onChange={selectWorkspace} />}>
    {(view, setView) => <WorkspaceContent view={view} setView={setView} data={data} failed={failed} />}
  </AppShell>;
}

function WorkspaceContent({ view, setView, data, failed }: {
  view: View; setView: (view: View) => void; data: WorkspacesResponse | null; failed: boolean;
}) {
  const { state } = useSession();
  const [selectedTurnId, setSelectedTurnId] = useState<number | null>(null);
  const [historyOrigin, setHistoryOrigin] = useState<"plan" | null>(null);
  const [graphTab, setGraphTab] = useState("schema");
  const [graphPathIds, setGraphPathIds] = useState<string[] | null>(null);
  const [graphOrigin, setGraphOrigin] = useState<"plan" | null>(null);
  const [previousView, setPreviousView] = useState(view);
  if (view !== previousView) {
    setPreviousView(view);
    if (view !== "history") setHistoryOrigin(null);
    if (view !== "graph") setGraphOrigin(null);
  }
  return <CommandTenantContext.Provider value={state.tenantId}><OpenGraphPathContext.Provider value={ids => {
      setGraphPathIds(ids); setGraphTab("path"); setGraphOrigin("plan"); setView("graph");
    }}><OpenHistoryDetailContext.Provider value={commands => {
      const turn = state.turns.find(turn => turn.commands === commands);
      if (turn) { setSelectedTurnId(turn.id); setHistoryOrigin("plan"); setView("history"); }
    }}>
      {view === "evidence" && <EvidencePage key={state.tenantId} turns={state.turns} workspaceBrand={data?.workspaces.find(workspace => workspace.tenant_id === state.tenantId)?.brand ?? null} onPlan={() => setView("plan")} />}
      {view === "history" && <HistoryPage workspaces={data?.workspaces ?? []} selectedTurnId={selectedTurnId}
        onSelectTurn={id => { setSelectedTurnId(id); setHistoryOrigin(null); }} onPlan={() => setView("plan")}
        origin={historyOrigin} onReturn={() => { setHistoryOrigin(null); setView("plan"); }} />}
      {view === "saved" && <SavedPage tenantId={state.tenantId} onPlan={() => setView("plan")} />}
      {failed ? <p role="alert">API 서버에 연결하지 못했습니다. 서버가 실행 중인지 확인하세요.</p>
        : data ? <>
          <div hidden={view !== "plan"}><PlanPage workspaces={data.workspaces} imageEnabled={data.image_enabled} /></div>
          {view === "graph" && <GraphPage tenantId={state.tenantId} tab={graphTab} onTabChange={setGraphTab}
            pathIds={graphPathIds ?? latestGraphIds(state.turns)} onPlan={() => setView("plan")}
            origin={graphOrigin} onReturn={() => { setGraphOrigin(null); setView("plan"); }} />}
        </> : (view === "plan" || view === "graph") && <p role="status">작업 공간 목록을 불러오는 중입니다.</p>}
    </OpenHistoryDetailContext.Provider></OpenGraphPathContext.Provider></CommandTenantContext.Provider>;
}
