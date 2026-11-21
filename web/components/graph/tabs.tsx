import type { ReactNode } from "react";
import { GraphPanel } from "../GraphPanel";
import { SchemaView } from "../SchemaView";
import { DataTab } from "./DataTab";

export type GraphTabContext = { tenantId: string; pathIds: string[] | null };
export const GRAPH_TABS: { id: string; label: string; render: (context: GraphTabContext) => ReactNode }[] = [
  { id: "schema", label: "스키마", render: ({ tenantId }) => <>
    <p className="gs-graph-note">그래프에 어떤 종류의 노드와 관계가 있는지 보여 줍니다. 층은 1층 제품 지식, 2층 광고에서 관찰한 값, 3층 승인·반려 피드백입니다.</p>
    <SchemaView tenantId={tenantId} />
  </> },
  { id: "data", label: "데이터", render: ({ tenantId }) => <DataTab tenantId={tenantId} /> },
  { id: "path", label: "근거 경로", render: ({ tenantId, pathIds }) => <>
    <p className="gs-graph-note">기획안이 근거로 쓴 광고 소재가 어떤 값들과 연결되는지 보여 줍니다.</p>
    {pathIds !== null && <GraphPanel tenantId={tenantId} ids={pathIds} />}
  </> },
];
