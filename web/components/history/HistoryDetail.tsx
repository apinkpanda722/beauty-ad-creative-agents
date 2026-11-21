"use client";

import { useContext, useEffect, useId, useRef, useState } from "react";
import type { Turn } from "../../lib/reducer";
import type { EvaluationAttempt, SchemaResponse } from "../../lib/types";
import { getSchema } from "../../lib/api";
import { historyDuration, historyTime, summarizeTurn } from "../../lib/history";
import { taxonomyNames, type TaxonomyNames } from "../../lib/taxonomy";
import { scoreNames } from "../../lib/localize";
import { insightColumnName, insightDescription, insightTitle, insightValue } from "../../lib/insight";
import { unknownNames } from "../../lib/unknown";
import { Badge, Button, Card, DataTable, PageHeader, Tabs } from "../ui";
import { AggregatesPanel } from "../results/AggregatesPanel";
import { CostDetail } from "../results/CostDetail";
import { CommandTenantContext } from "../results/ResultsView";
import "../../app/history.css";

type DisplayAttempt = Omit<EvaluationAttempt, "scores"> & { scores?: Record<string, unknown> | null };
const checkLabel = (value: boolean | null | undefined) => value == null ? "미실행" : value ? "통과" : "실패";
function attemptLine(attempt: DisplayAttempt): string {
  const parts = [`시도 ${attempt.attempt}`, `검사 ${checkLabel(attempt.checks_passed)}`, `최종 ${checkLabel(attempt.final_passed)}`];
  for (const key of ["differentiation", "fit"] as const) {
    if (typeof attempt.scores?.[key] === "number") parts.push(`${scoreNames[key]} ${attempt.scores[key]}/5`);
  }
  if (attempt.low_items?.length) parts.push(`재검토: ${attempt.low_items.map(key => Object.hasOwn(scoreNames, key) ? scoreNames[key] : "기타").join(", ")}`);
  return parts.join(" · ");
}
const statusNames: Record<string, string> = { done: "완료", needs_review: "검토 필요", failed: "실패" };

export function HistoryDetail({ turn, workspace, onBack, onReturn, names: suppliedNames }: {
  turn: Turn; workspace: string; onBack: () => void; names?: TaxonomyNames;
  onReturn?: () => void;
}) {
  const [tab, setTab] = useState("stages");
  const [expanded, setExpanded] = useState(false);
  const [visible, setVisible] = useState(false);
  const [open, setOpen] = useState(false);
  const sourceId = useId();
  const gridRef = useRef<HTMLDivElement>(null);
  const frame = useRef<number | undefined>(undefined);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => { if (frame.current !== undefined) cancelAnimationFrame(frame.current); clearTimeout(timer.current); }, []);
  function toggleSources() {
    if (frame.current !== undefined) cancelAnimationFrame(frame.current);
    clearTimeout(timer.current);
    if (!expanded) {
      setVisible(true); setExpanded(true);
      frame.current = requestAnimationFrame(() => { setOpen(true); frame.current = undefined; });
    } else {
      setExpanded(false); setOpen(false);
      const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
      const style = gridRef.current ? getComputedStyle(gridRef.current) : null;
      const milliseconds = (value: string) => value.split(",").map(part => parseFloat(part) * (part.trim().endsWith("ms") ? 1 : 1000) || 0);
      const duration = Math.max(0, ...milliseconds(style?.transitionDuration ?? ""));
      const delay = Math.max(0, ...milliseconds(style?.transitionDelay ?? ""));
      if (reduced || duration === 0) setVisible(false);
      else timer.current = setTimeout(() => setVisible(false), Math.max(300, duration + delay + 50));
    }
  }
  const tenantId = useContext(CommandTenantContext);
  const [schema, setSchema] = useState<{ tenantId: string; data: SchemaResponse } | null>(null);
  useEffect(() => {
    if (!tenantId || suppliedNames) return;
    let active = true;
    void getSchema(tenantId).then(data => { if (active) setSchema({ tenantId, data }); }).catch(() => { /* Closed-name fallback below. */ });
    return () => { active = false; };
  }, [tenantId, suppliedNames]);
  const names = suppliedNames ?? taxonomyNames(schema?.tenantId === tenantId ? schema?.data : null);
  const summary = summarizeTurn(turn);
  const time = historyTime(summary.startedAt);
  const plans = turn.commands.filter(command => command.kind === "show_plan");
  const distributions = turn.commands.filter(command => command.kind === "show_distribution");
  const sourceValue = (value: unknown) => value == null || typeof value === "object" ? "—" : typeof value === "string" ? insightValue(value, names) : String(value);
  const allAttempts = plans.flatMap(command => command.data.attempts as DisplayAttempt[]);
  const empty = <p>정보 없음</p>;
  return <section className="gs-history-page">
    <PageHeader title="실행 기록·검증" actions={<><Button variant="secondary" onClick={onBack}>목록으로</Button>{onReturn && <Button variant="secondary" onClick={onReturn}>광고 기획으로 돌아가기</Button>}</>} />
    <Card className="gs-history-summary" aria-label="실행 요약">
      <h2>{turn.message}</h2><dl>
        <div><dt>작업 공간</dt><dd>{workspace}</dd></div>
        <div><dt>시각</dt><dd>{time ? <time dateTime={time}>{new Date(time).toLocaleString("ko-KR")}</time> : "정보 없음"}</dd></div>
        <div><dt>총 시간</dt><dd>{historyDuration(summary.durationMs)}</dd></div>
        <div><dt>총 비용</dt><dd>{summary.cost ? `$${summary.cost.text_spent_usd.toFixed(4)}` : "정보 없음"}</dd></div>
      </dl>
    </Card>
    <Tabs label="실행 상세" value={tab} onChange={setTab} items={[
      { value: "stages", label: "단계", panel: <>
        <p>기획 {summary.planningCount}회 · 평가 {summary.evaluationCount}회</p>
        <ol className="gs-history-timeline">{summary.progress.map(stage => <li key={stage.id} data-status={stage.status}>
          <svg role="img" aria-label={{ done: "완료", pending: "대기", running: "진행 중", failed: "실패" }[stage.status]} width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d={stage.status === "done" ? "m5 12 4 4L19 6" : stage.status === "failed" ? "m6 6 12 12M6 18 18 6" : "M12 4v8l4 4"} /></svg>
          <span>{stage.label}</span>{stage.id !== "image" && <time>{historyDuration(stage.durationMs)}</time>}
          {stage.id === "plan_eval" && <>
            <Badge variant={stage.reworks > 0 ? "warn" : "neutral"} label={`재작업 ${stage.reworks}회`} />
            {plans.map(({ data }, index) => data.attempts.length > 0 && <div className="gs-history-plan-attempts" key={index}>
              {plans.length > 1 && <p className="gs-history-plan-label">기획안 {index + 1}</p>}
              <ul className="gs-history-attempts">{(data.attempts as DisplayAttempt[]).map((attempt, i) => <li key={i}>{attemptLine(attempt)}</li>)}</ul>
            </div>)}
          </>}
        </li>)}</ol>
      </> },
      { value: "verification", label: "검증", panel: <>
        {plans.map(({ data }, i) => <section key={i} className="gs-plan-checks gs-detail-card" aria-label="검사 결과">
          <h2>검사 결과{plans.length > 1 ? ` · 기획안 ${i + 1}` : ""}</h2>
          <Badge className={data.unknown_count > 0 ? "attention" : "clear"} variant={data.unknown_count > 0 ? "warn" : "success"} label={`근거 연결 없음 ${data.unknown_count}건`} />
          {Object.keys(data.unknown_codes).length > 0 && <ul>{Object.keys(data.unknown_codes).map(code => <li key={code}>{Object.hasOwn(unknownNames, code) ? unknownNames[code] : code}</li>)}</ul>}
          <p className="code-result">코드 검사: {data.passed ? "통과" : "실패"}</p>
          <p className="evaluation-status">평가 상태: {Object.hasOwn(statusNames, data.status) ? statusNames[data.status] : "정보 없음"}</p>
          <small className="gs-pattern-label muted">{data.pattern_alignment_label}</small>
        </section>)}
        {turn.commands.filter(command => command.kind === "show_aggregates").map((command, i) => <AggregatesPanel key={i} data={command.data} names={names} />)}
        {distributions.length > 0 && <section className="gs-history-source" aria-label="시장 인사이트 원천">
          <Button variant="secondary" className="gs-history-source-toggle" aria-expanded={expanded} aria-controls={sourceId} onClick={toggleSources}>
            {`원천 데이터 ${expanded ? "접기" : "보기"} (${distributions.length})`}<svg className="gs-history-source-arrow" aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="m9 5 7 7-7 7" /></svg>
          </Button>
          <div ref={gridRef} className={`gs-history-source-accordion${open ? " gs-open" : ""}`} onTransitionEnd={event => {
            if (event.target === event.currentTarget && (!event.propertyName || event.propertyName === "grid-template-rows") && !expanded) { clearTimeout(timer.current); setVisible(false); }
          }}><div className="gs-history-source-content" id={sourceId} hidden={!visible}>
            {distributions.map(({ data }, index) => {
              const columns = [...new Set(data.rows.flatMap(row => Object.keys(row)))].filter(key => data.rows.some(row => sourceValue(row[key]) !== "—"));
              const values = data.rows.filter(row => typeof row.value === "string" && typeof row.creatives === "number" && Number.isInteger(row.creatives) && row.creatives >= 0).map(row => String(row.value));
              const description = insightDescription(data.tool);
              return <div className="gs-history-source-table" key={index}>
                <h3>{insightTitle(data.tool, values)}</h3>
                {description && <p className="gs-insight-note">{description}</p>}
                <DataTable caption="시장 인사이트 원천 데이터" rows={data.rows.map((row, i) => ({ row, id: String(i) }))} rowKey={item => item.id}
                  columns={columns.map(key => ({ key, header: insightColumnName(data.tool, key), render: ({ row }: { row: Record<string, unknown> }) => sourceValue(row[key]) }))}
                  emptyState={{ title: "원천 데이터가 없습니다", description: "수신한 표 데이터가 없습니다.", action: { label: "목록으로", onClick: onBack } }} />
              </div>;
            })}
          </div></div>
        </section>}
        {!plans.length && !turn.commands.some(command => command.kind === "show_aggregates" || command.kind === "show_distribution") && empty}
      </> },
      { value: "cost", label: "비용", panel: <>
        {summary.cost ? <CostDetail data={summary.cost} /> : <p>텍스트 비용 정보 없음</p>}
        {allAttempts.length ? <ul>{plans.flatMap(({ data }, planIndex) => (data.attempts as DisplayAttempt[]).map((attempt, index) => <li key={`${planIndex}-${index}`}>{plans.length > 1 ? `기획안 ${planIndex + 1} · ` : ""}시도 {attempt.attempt} · 시도 텍스트 비용 {attempt.cost_usd == null ? "정보 없음" : `$${attempt.cost_usd.toFixed(4)}`}</li>))}</ul> : empty}
      </> },
    ]} />
  </section>;
}
