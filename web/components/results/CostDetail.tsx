import type { UiCommand } from "../../lib/types";
import { CostLine } from "./CostLine";

export function CostDetail({ data }: { data?: Extract<UiCommand, { kind: "show_cost" }>["data"] }) {
  return data ? <>
    <CostLine data={data} />
    <p className="gs-cost-line muted">텍스트 비용 상한 ${data.max_text_cost_usd.toFixed(4)}</p>
  </> : null;
}
