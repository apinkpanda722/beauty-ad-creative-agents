"use client";

import { useEffect, useState } from "react";
import { Chat } from "../components/Chat";
import { getWorkspaces } from "../lib/api";
import type { WorkspacesResponse } from "../lib/types";

export default function Page() {
  const [data, setData] = useState<WorkspacesResponse | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let active = true;
    getWorkspaces().then(value => { if (active) setData(value); }).catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, []);
  return <main>
    <header><h1>Beauty Ad Creative Agents</h1><p className="muted">뷰티 광고 기획 작업 공간</p></header>
    {failed ? <p role="alert">API 서버에 연결하지 못했습니다. 서버가 실행 중인지 확인하세요.</p>
      : data ? <Chat workspaces={data.workspaces} imageEnabled={data.image_enabled} />
        : <p role="status">작업 공간 목록을 불러오는 중입니다.</p>}
  </main>;
}
