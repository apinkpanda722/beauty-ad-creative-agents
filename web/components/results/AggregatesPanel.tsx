import type { UiCommand } from "../../lib/types";
import type { TaxonomyNames } from "../../lib/taxonomy";
import { Badge, Card } from "../ui";
// model_written is received but intentionally not drawn: its item names vary per run and cannot be organized reliably.
export function AggregatesPanel({ data }: { data: Extract<UiCommand, { kind: "show_aggregates" }>["data"]; names?: TaxonomyNames }) {
  if (!data.removed.length) return null;
  return <Card className="gs-aggregates gs-result-section">
    <section aria-label="제외된 값" className="removed-block muted"><h4>제외된 값</h4><Badge variant="neutral" label="제외됨" /><p>도구 출력에 없는 수치라 제외했습니다.</p><ul>{data.removed.map((name, i) => <li key={i}>{name}</li>)}</ul></section>
  </Card>;
}
