"use client";

import { useSession } from "../../lib/session";
import { historyDuration, historyTime, summarizeTurn } from "../../lib/history";
import type { Workspace } from "../../lib/types";
import { workspaceLabel } from "../../lib/workspace";
import { DataTable, EmptyState, PageHeader } from "../ui";
import { HistoryDetail } from "./HistoryDetail";
import "../../app/history.css";

export function HistoryPage({ workspaces, selectedTurnId, onSelectTurn, onPlan }: {
  workspaces: Workspace[]; selectedTurnId: number | null; onSelectTurn: (id: number | null) => void; onPlan: () => void;
}) {
  const { state } = useSession();
  const selected = state.turns.find(turn => turn.id === selectedTurnId);
  const workspace = workspaces.find(workspace => workspace.tenant_id === state.tenantId);
  if (selected) return <HistoryDetail key={selected.id} turn={selected} workspace={workspace ? workspaceLabel(workspace) : "정보 없음"} onBack={() => onSelectTurn(null)} />;
  const rows = state.turns.map(turn => ({ turn, summary: summarizeTurn(turn) }))
    .sort((a, b) => (b.summary.startedAt ?? -Infinity) - (a.summary.startedAt ?? -Infinity) || b.turn.id - a.turn.id);
  return <section className="gs-history-page">
    <PageHeader title="실행 기록·검증" description={`이번 접속 중 ${rows.length}건 · 새로고침하면 지워집니다`} />
    {rows.length ? <DataTable caption="실행 요청 목록" rows={rows} rowKey={row => String(row.turn.id)} onChange={id => onSelectTurn(Number(id))}
      columns={[
        { key: "time", header: "시각", render: ({ summary }) => { const time = historyTime(summary.startedAt); return time ? <time dateTime={time}>{new Date(time).toLocaleString("ko-KR")}</time> : "정보 없음"; } },
        { key: "message", header: "요청 문장", render: ({ turn }) => turn.message },
        { key: "kind", header: "결과 종류", render: ({ summary }) => summary.kind },
        { key: "duration", header: "소요 시간", render: ({ summary }) => historyDuration(summary.durationMs) },
        { key: "cost", header: "텍스트 비용", render: ({ summary }) => summary.cost ? `$${summary.cost.text_spent_usd.toFixed(4)}` : "정보 없음" },
      ]} emptyState={{ title: "아직 실행한 요청이 없습니다", description: "광고 기획에서 요청을 실행해 보세요.", action: { label: "광고 기획으로", onClick: onPlan } }} />
      : <EmptyState title="아직 실행한 요청이 없습니다" description="광고 기획에서 요청을 실행해 보세요." action={{ label: "광고 기획으로", onClick: onPlan }} />}
  </section>;
}
