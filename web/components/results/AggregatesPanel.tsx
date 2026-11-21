import type { UiCommand } from "../../lib/types";
import { taxonomyNames, type TaxonomyNames } from "../../lib/taxonomy";
import { localizeText } from "../../lib/localize";
import { toolTitle } from "../../lib/insight";
import { Badge, Card } from "../ui";
export function AggregatesPanel({ data, names = taxonomyNames() }: { data: Extract<UiCommand, { kind: "show_aggregates" }>["data"]; names?: TaxonomyNames }) {
  if (!data.verified_counts.length && !data.model_written.length && !data.removed.length) return null;
  return <Card className="gs-aggregates gs-result-section">
    {data.verified_counts.length > 0 && <section aria-label="검증된 집계(도구가 센 값)" className="verified-block"><h3>검증된 집계(도구가 센 값)</h3><Badge variant="success" label="검증됨" /><ul>{data.verified_counts.map((item, i) => <li key={i}><span className="gs-source-chip" data-tool={item.tool}>{toolTitle(item.tool)}</span>: <span>{item.count_label}</span></li>)}</ul></section>}
    {data.model_written.length > 0 && <section aria-label="모델 작성값" className="model-block muted"><h4>{data.label}</h4><Badge variant="warn" label="미검증" /><dl>{data.model_written.map((item, i) => <div key={i}><dt>{localizeText(item.name, names)}</dt><dd>{localizeText(typeof item.value === "object" ? JSON.stringify(item.value) : String(item.value), names)}</dd></div>)}</dl></section>}
    {data.removed.length > 0 && <section aria-label="제외된 값" className="removed-block muted"><h4>제외된 값</h4><Badge variant="neutral" label="제외됨" /><p>도구 출력에 없는 수치라 제외했습니다.</p><ul>{data.removed.map((name, i) => <li key={i}>{name}</li>)}</ul></section>}
  </Card>;
}
