import type { UiCommand } from "../lib/types";
export function CostLine({ data }: { data?: Extract<UiCommand, { kind: "show_cost" }>["data"] }) {
  return data ? <p className="cost-line muted">이 요청의 {data.label} ${data.text_spent_usd.toFixed(4)} (이미지 제외)</p> : null;
}
