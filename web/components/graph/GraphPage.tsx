"use client";
import { Button, EmptyState, PageHeader, Tabs } from "../ui";
import { GRAPH_TABS } from "./tabs";
import "../../app/graph.css";

export function GraphPage({ tenantId, pathIds, tab, onTabChange, onPlan, origin = null, onReturn }: {
  tenantId: string | null; pathIds: string[] | null; tab: string; onTabChange: (tab: string) => void;
  onPlan: () => void; origin?: "plan" | null; onReturn?: () => void;
}) {
  return <div className="gs-graph-page">
    <PageHeader title="지식 그래프" description="광고 지식이 어떻게 연결되어 있는지 노드(점)와 관계(선)로 살펴봅니다."
      actions={origin === "plan" && <Button variant="secondary" onClick={onReturn}>광고 기획으로 돌아가기</Button>} />
    {tenantId === null ? <p>상단 바에서 작업 공간을 선택하세요.</p> : <Tabs label="지식 그래프 보기" value={tab} onChange={onTabChange}
      items={GRAPH_TABS.map(item => ({ value: item.id, label: item.label, panel: item.id === tab ? <>
        {item.render({ tenantId, pathIds })}
        {item.id === "path" && pathIds === null && <EmptyState title="근거 경로가 없습니다"
          description="광고 기획에서 요청을 실행하면 근거 경로가 표시됩니다" action={{ label: "광고 기획으로", onClick: onPlan }} />}
      </> : <></> }))} />}
  </div>;
}
