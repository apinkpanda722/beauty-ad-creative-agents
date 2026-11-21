import type { UiCommand } from "../../lib/types";
import { taxonomyNames, type TaxonomyNames } from "../../lib/taxonomy";
import { columnName, insightTitle, insightValue } from "../../lib/insight";
function isBar(row: Record<string, unknown>): row is Record<string, unknown> & { value: string; creatives: number } {
  return typeof row.value === "string" && typeof row.creatives === "number" && Number.isInteger(row.creatives) && row.creatives >= 0;
}
export function DistributionChart({ data, names = taxonomyNames() }: { data: Extract<UiCommand, { kind: "show_distribution" }>["data"]; names?: TaxonomyNames }) {
  const bars = data.rows.filter(isBar);
  const rows = data.rows.filter(row => !isBar(row));
  const columns = [...new Set(rows.flatMap(row => Object.entries(row).filter(([, value]) => value == null || ["string", "number", "boolean"].includes(typeof value)).map(([key]) => key)))];
  const maximum = Math.max(1, ...bars.map(row => row.creatives));
  return <section className="gs-result-section gs-distribution" aria-label="분포" data-tool={data.tool}><h3>{insightTitle(data.tool, bars.map(row => row.value))}</h3>
    {bars.map((row, i) => <div className="gs-distribution-row" key={i}><span>{insightValue(row.value, names)}{row.value === "other" && names.valueName(row.value) === "other" && <span className="gs-sr-only">other</span>}</span><meter aria-label={names.valueName(row.value)} aria-valuenow={row.creatives} min={0} max={maximum} value={row.creatives} /><span>{row.creatives}건</span></div>)}
    {rows.length > 0 && columns.length > 0 && <div className="gs-result-table-scroll"><table><thead><tr>{columns.map(key => <th scope="col" key={key}>{columnName(key)}</th>)}</tr></thead><tbody>{rows.map((row, i) => <tr key={i}>{columns.map(key => <td key={key}>{row[key] == null ? "—" : typeof row[key] === "object" ? "—" : typeof row[key] === "string" ? insightValue(row[key], names) : String(row[key])}</td>)}</tr>)}</tbody></table></div>}
  </section>;
}
