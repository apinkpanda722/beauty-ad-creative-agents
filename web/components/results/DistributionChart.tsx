import type { UiCommand } from "../../lib/types";
import { taxonomyNames, type TaxonomyNames } from "../../lib/taxonomy";
import { insightColumnName, insightDescription, insightLimitNote, insightTitle, insightTotal, insightValue } from "../../lib/insight";
function isBar(row: Record<string, unknown>): row is Record<string, unknown> & { value: string; creatives: number } {
  return typeof row.value === "string" && typeof row.creatives === "number" && Number.isInteger(row.creatives) && row.creatives >= 0;
}
export function DistributionChart({ data, names = taxonomyNames(), embedded = false }: { data: Extract<UiCommand, { kind: "show_distribution" }>["data"]; names?: TaxonomyNames; embedded?: boolean }) {
  const bars = data.rows.filter(isBar);
  const rows = data.rows.filter(row => !isBar(row));
  const columns = [...new Set(rows.flatMap(row => Object.entries(row).filter(([, value]) => value == null || ["string", "number", "boolean"].includes(typeof value)).map(([key]) => key)))];
  const orderedColumns = data.tool === "top_vs_bottom_axis" ? ["value", "n_top", "n_bottom", ...columns.filter(key => !["value", "n_top", "n_bottom"].includes(key))].filter(key => columns.includes(key)) : columns;
  const emphasize = (key: string, text: string) => data.tool === "top_vs_bottom_axis" && ["n_top", "n_bottom"].includes(key) ? <span className={key === "n_top" ? "gs-col-primary" : "gs-col-muted"}>{text}</span> : text;
  const maximum = Math.max(1, ...bars.map(row => row.creatives));
  const total = insightTotal(data.rows);
  const meterMax = total !== null && total >= maximum ? total : maximum;
  const description = insightDescription(data.tool);
  const limitNote = insightLimitNote(data.tool);
  return <section className="gs-result-section gs-distribution" aria-label="분포" data-tool={data.tool}>{!embedded && <h3>{insightTitle(data.tool, bars.map(row => row.value))}</h3>}
    {!embedded && description && <p className="gs-insight-note">{description}</p>}
    {!embedded && limitNote && <p className="gs-insight-note">{limitNote}</p>}
    {bars.map((row, i) => <div className="gs-distribution-row" key={i}><span>{insightValue(row.value, names)}{row.value === "other" && names.valueName(row.value) === "other" && <span className="gs-sr-only">other</span>}</span><meter aria-label={names.valueName(row.value)} aria-valuenow={row.creatives} min={0} max={meterMax} value={row.creatives} /><span>{row.creatives}건</span></div>)}
    {rows.length > 0 && orderedColumns.length > 0 && <div className="gs-result-table-scroll"><table><thead><tr>{orderedColumns.map(key => <th scope="col" key={key}>{emphasize(key, insightColumnName(data.tool, key))}</th>)}</tr></thead><tbody>{rows.map((row, i) => <tr key={i}>{orderedColumns.map(key => <td key={key}>{emphasize(key, row[key] == null ? "—" : typeof row[key] === "object" ? "—" : typeof row[key] === "string" ? insightValue(row[key], names) : String(row[key]))}</td>)}</tr>)}</tbody></table></div>}
  </section>;
}
