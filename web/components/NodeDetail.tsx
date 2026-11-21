"use client";
import type { GraphNode } from "../lib/types";
import { safeLink } from "../lib/evidence";

export function NodeDetail({ node }: { node: GraphNode | null }) {
  return <aside className="node-detail" aria-label="노드 상세"><h4>노드 상세</h4>
    {node ? <><dl><dt>레이블</dt><dd>{node.label}</dd><dt>이름</dt><dd>{node.name ?? "이름 정보 없음"}</dd></dl>
      <dl>{Object.entries(node.props).map(([key, value]) => {
        const href = (key === "url" || key === "source_url") && typeof value === "string" ? safeLink(value) : undefined;
        return <div key={key}><dt>{key}</dt><dd>{href ? <a href={href} target="_blank" rel="noopener noreferrer">{String(value)}</a>
          : typeof value === "string" ? value : JSON.stringify(value)}</dd></div>;
      })}</dl></> : <p className="muted">노드를 선택하면 상세 정보를 표시합니다.</p>}
  </aside>;
}
