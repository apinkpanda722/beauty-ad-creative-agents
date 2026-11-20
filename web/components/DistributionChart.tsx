import type { UiCommand } from "../lib/types";
function isBar(row: Record<string, unknown>): row is Record<string, unknown> & { value: string; creatives: number } {
  return typeof row.value === "string" && typeof row.creatives === "number" && Number.isInteger(row.creatives) && row.creatives >= 0;
}
export function DistributionChart({ data }: { data: Extract<UiCommand, { kind: "show_distribution" }>["data"] }) {
  const bars = data.rows.filter(isBar);
  const rows = data.rows.filter(row => !isBar(row));
  const columns = [...new Set(rows.flatMap(row => Object.entries(row).filter(([, value]) => value == null || ["string", "number", "boolean"].includes(typeof value)).map(([key]) => key)))];
  const maximum = Math.max(1, ...bars.map(row => row.creatives));
  return <section className="result-section" aria-label="분포"><h3>분포 · {data.tool}</h3>
    {bars.map((row, i) => <div className="distribution-row" key={i}><span>{row.value}</span><meter aria-label={row.value} aria-valuenow={row.creatives} min={0} max={maximum} value={row.creatives} /><span>{row.creatives}건</span></div>)}
    {rows.length > 0 && columns.length > 0 && <div className="table-scroll"><table><caption>{data.tool} 도구 결과</caption><thead><tr>{columns.map(key => <th scope="col" key={key}>{key}</th>)}</tr></thead><tbody>{rows.map((row, i) => <tr key={i}>{columns.map(key => <td key={key}>{row[key] == null ? "—" : typeof row[key] === "object" ? "—" : String(row[key])}</td>)}</tr>)}</tbody></table></div>}
  </section>;
}
