"use client";
import type { GraphNode } from "../lib/types";
import { platformLabel, safeLink } from "../lib/evidence";
import { NODE_LABEL_NAMES, PROPERTY_NAMES } from "../lib/graph";
import { ctaName, talentName, taxonomyNames, type TaxonomyNames } from "../lib/taxonomy";

function valueName(label: string, value: string, names: TaxonomyNames): string {
  switch (label) {
    case "Hook": return names.axisName("hook_type", value);
    case "Angle": return names.axisName("angle", value);
    case "Format": return names.axisName("format", value);
    case "Efficacy": return names.claimName(value);
    case "Talent": return talentName(value);
    case "CtaType": return ctaName(value);
    default: return value;
  }
}
export function NodeDetail({ node, names = taxonomyNames() }: { node: GraphNode | null; names?: TaxonomyNames }) {
  return <aside className="node-detail" aria-label="노드 상세"><h4>노드 상세</h4>
    {node ? <><dl><dt>레이블</dt><dd>{NODE_LABEL_NAMES[node.label] ?? node.label}</dd><dt>이름</dt><dd>{node.name === null ? "이름 정보 없음" : valueName(node.label, node.name, names)}</dd></dl>
      <dl>{Object.entries(node.props).map(([key, value]) => {
        const href = (key === "url" || key === "source_url") && typeof value === "string" ? safeLink(value) : undefined;
        const displayValue = typeof value === "string" ? key === "source" ? platformLabel(value) : key === "value" ? valueName(node.label, value, names) : value : JSON.stringify(value);
        return <div key={key}><dt>{PROPERTY_NAMES[key] ?? key}</dt><dd>{href ? <a href={href} target="_blank" rel="noopener noreferrer">{String(value)}</a>
          : displayValue}</dd></div>;
      })}</dl></> : <p className="muted">노드를 선택하면 상세 정보를 표시합니다.</p>}
  </aside>;
}
