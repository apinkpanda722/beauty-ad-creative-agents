"use client";

import { useId, useState } from "react";
import type { UiCommand } from "../../lib/types";
import { taxonomyNames, type TaxonomyNames } from "../../lib/taxonomy";
import { localizeText } from "../../lib/localize";
import { AXIS_TABS, insightAxis, insightColumnName, insightDescription, insightValue } from "../../lib/insight";
import { useGridAccordion } from "../../lib/useGridAccordion";
import { Badge, Button, DataTable, Tabs } from "../ui";
import { DistributionChart } from "./DistributionChart";
import "../../app/results.css";

type Distribution = Extract<UiCommand, { kind: "show_distribution" }>["data"];
export type ModelChart = {
  axis: "hook" | "angle" | "format";
  label: string;
  rows: { label: string; count: number; total: number }[];
};
type Props = {
  distributions: Distribution[];
  names?: TaxonomyNames;
  variant?: "result" | "verification";
  modelCharts?: ModelChart[];
};
function InsightCard({ title, distributions, names, variant, modelCharts, comparison = false }: Required<Props> & { title: string; comparison?: boolean }) {
  const titleId = useId();
  const tableId = useId();
  const [axis, setAxis] = useState("");
  const { expanded, visible, open, gridRef, toggle, onTransitionEnd } = useGridAccordion();
  const grouped = distributions.map(data => ({ data, axis: insightAxis(data.rows.flatMap(row => typeof row.value === "string" ? [row.value] : [])) ?? "other" }));
  const charts = variant === "verification" && !comparison ? modelCharts : [];
  const tabs = AXIS_TABS.filter(tab => grouped.some(item => item.axis === tab.value) || charts.some(chart => chart.axis === tab.value));
  const active = tabs.find(tab => tab.value === axis) ?? tabs[0];
  const sourceValue = (value: unknown) => value == null || typeof value === "object" ? "—" : typeof value === "string" ? insightValue(value, names) : String(value);
  return <section className="gs-result-section gs-distribution gs-insight-card" aria-labelledby={titleId}>
    <h3 id={titleId}>{title}</h3>
    {comparison && <p className="gs-insight-note">{insightDescription("top_vs_bottom_axis")}</p>}
    <Tabs label={`${title} 축`} value={active.value} onChange={setAxis} items={tabs.map(tab => ({ ...tab, panel: <div className={`gs-insight-charts${charts.some(chart => chart.axis === tab.value) ? " gs-insight-with-model" : ""}`}>
      <div>{grouped.filter(item => item.axis === tab.value).map(({ data }, index) => <DistributionChart key={index} embedded data={data} names={names} />)}</div>
      {charts.some(chart => chart.axis === tab.value) && <div className="gs-model-charts">{charts.filter(chart => chart.axis === tab.value).map((chart, index) => <section aria-label="모델 작성값 차트" className="gs-model-chart" key={index}>
        <h4>{chart.label}</h4><Badge variant="warn" label="미검증" />
        {chart.rows.map((row, index) => <div className="gs-distribution-row" key={index}>
          <span>{localizeText(row.label, names)}</span><meter aria-label={localizeText(row.label, names)} min={0} max={row.total} value={row.count} aria-valuenow={row.count} /><span>{row.count}/{row.total}</span>
        </div>)}
      </section>)}</div>}
    </div> }))} />
    {variant === "verification" && <>
      <Button variant="secondary" className="gs-insight-table-toggle" aria-expanded={expanded} aria-controls={tableId} onClick={toggle}>
        {expanded ? "표 접기" : "표로 보기"}<svg className="gs-insight-arrow" aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="m9 5 7 7-7 7" /></svg>
      </Button>
      <div ref={gridRef} className={`gs-insight-accordion${open ? " gs-open" : ""}`} onTransitionEnd={onTransitionEnd}><div className="gs-insight-source-content" id={tableId} hidden={!visible}>
        {grouped.filter(item => item.axis === active.value).map(({ data }, index) => {
          const columns = [...new Set(data.rows.flatMap(row => Object.keys(row)))].filter(key => data.rows.some(row => sourceValue(row[key]) !== "—"));
          return <DataTable key={index} caption="시장 인사이트 원천 데이터" rows={data.rows.map((row, i) => ({ row, id: String(i) }))} rowKey={item => item.id}
            columns={columns.map(key => ({ key, header: insightColumnName(data.tool, key), render: ({ row }: { row: Record<string, unknown> }) => sourceValue(row[key]) }))}
            emptyState={{ title: "원천 데이터가 없습니다", description: "수신한 표 데이터가 없습니다.", action: { label: "표 접기", onClick: toggle } }} />;
        })}
      </div></div>
    </>}
  </section>;
}
export function InsightPanel({ distributions, names = taxonomyNames(), variant = "result", modelCharts = [] }: Props) {
  const competitor = distributions.filter(data => data.tool !== "top_vs_bottom_axis");
  const comparison = distributions.filter(data => data.tool === "top_vs_bottom_axis");
  if (!competitor.length && !comparison.length) return null;
  return <>
    {competitor.length > 0 && <InsightCard title="경쟁사 광고 분포" distributions={competitor} names={names} variant={variant} modelCharts={modelCharts} />}
    {comparison.length > 0 && <InsightCard title="조회수 상위·하위 25% 광고 비교" comparison distributions={comparison} names={names} variant={variant} modelCharts={[]} />}
  </>;
}
