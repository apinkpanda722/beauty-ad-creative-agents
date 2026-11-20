"use client";

import { useEffect, useState } from "react";
import { Chat } from "../components/Chat";
import { SchemaView } from "../components/SchemaView";
import { getWorkspaces } from "../lib/api";
import type { WorkspacesResponse } from "../lib/types";

export default function Page() {
  const [data, setData] = useState<WorkspacesResponse | null>(null);
  const [failed, setFailed] = useState(false);
  const [tab, setTab] = useState<"chat" | "schema">("chat");
  const [tenantId, setTenantId] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    getWorkspaces().then(value => { if (active) setData(value); }).catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, []);
  return <main>
    <header><h1>Beauty Ad Creative Agents</h1><p className="muted">뷰티 광고 기획 작업 공간</p></header>
    <div role="tablist" aria-label="화면 선택" className="view-tabs">
      <button type="button" role="tab" id="chat-tab" aria-selected={tab === "chat"} aria-controls="chat-view" onClick={() => setTab("chat")}>대화</button>
      <button type="button" role="tab" id="schema-tab" aria-selected={tab === "schema"} aria-controls="schema-view" onClick={() => setTab("schema")}>전체 스키마</button>
    </div>
    {failed ? <p role="alert">API 서버에 연결하지 못했습니다. 서버가 실행 중인지 확인하세요.</p>
      : data ? <>
        <div role="tabpanel" id="chat-view" aria-labelledby="chat-tab" hidden={tab !== "chat"}><Chat workspaces={data.workspaces} imageEnabled={data.image_enabled} onWorkspaceChange={setTenantId} /></div>
        <div role="tabpanel" id="schema-view" aria-labelledby="schema-tab" hidden={tab !== "schema"}>{tab === "schema" && (tenantId ? <SchemaView tenantId={tenantId} /> : <p>대화 탭에서 작업 공간을 선택하세요.</p>)}</div>
      </>
        : <p role="status">작업 공간 목록을 불러오는 중입니다.</p>}
  </main>;
}
