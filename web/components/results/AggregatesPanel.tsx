import type { UiCommand } from "../../lib/types";
import { Card } from "../ui";
import { TOOL_TITLES } from "../../lib/insight";
export function AggregatesPanel({ data }: { data: Extract<UiCommand, { kind: "show_aggregates" }>["data"] }) {
  if (!data.verified_counts.length && !data.model_written.length && !data.removed.length) return null;
  return <Card className="gs-aggregates gs-result-section">
    {data.verified_counts.length > 0 && <section aria-label="검증된 집계(도구가 센 값)" className="verified-block"><h3>검증된 집계(도구가 센 값)</h3><ul>{data.verified_counts.map((item, i) => <li key={i}>{Object.hasOwn(TOOL_TITLES, item.tool) ? TOOL_TITLES[item.tool] : item.tool}: <span>{item.count_label}</span></li>)}</ul></section>}
    {data.model_written.length > 0 && <section aria-label="모델 작성값" className="model-block muted"><h4>{data.label}</h4><dl>{data.model_written.map((item, i) => <div key={i}><dt>{item.name}</dt><dd>{typeof item.value === "object" ? JSON.stringify(item.value) : String(item.value)}</dd></div>)}</dl></section>}
    {data.removed.length > 0 && <section aria-label="제외된 값" className="removed-block muted"><h4>제외된 값</h4><p>도구 출력에 없는 수치라 제외했습니다.</p><ul>{data.removed.map((name, i) => <li key={i}>{name}</li>)}</ul></section>}
  </Card>;
}
