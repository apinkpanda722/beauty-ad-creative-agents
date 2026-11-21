"use client";

import { useContext, useEffect, useState } from "react";
import type { Turn } from "../../lib/reducer";
import type { EvaluationAttempt, SchemaResponse } from "../../lib/types";
import { getSchema } from "../../lib/api";
import { historyDuration, historyTime, summarizeTurn } from "../../lib/history";
import { taxonomyNames, type TaxonomyNames } from "../../lib/taxonomy";
import { localizeText, scoreNames } from "../../lib/localize";
import { columnName, insightValue } from "../../lib/insight";
import { unknownNames } from "../../lib/unknown";
import { Badge, Button, Card, DataTable, PageHeader, Tabs } from "../ui";
import { AggregatesPanel } from "../results/AggregatesPanel";
import { CostDetail } from "../results/CostDetail";
import { CommandTenantContext } from "../results/ResultsView";
import "../../app/history.css";

type DisplayAttempt = Omit<EvaluationAttempt, "scores"> & { scores?: Record<string, unknown> | null };
const checkLabel = (value: boolean | null | undefined) => value == null ? "미실행" : value ? "통과" : "실패";
const statusNames: Record<string, string> = { done: "완료", needs_review: "검토 필요", failed: "실패" };

export function HistoryDetail({ turn, workspace, onBack, onReturn, names: suppliedNames }: {
  turn: Turn; workspace: string; onBack: () => void; names?: TaxonomyNames;
  onReturn?: () => void;
}) {
  const [tab, setTab] = useState("stages");
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
          {stage.id === "plan_eval" && <Badge variant={stage.reworks > 0 ? "warn" : "neutral"} label={`재작업 ${stage.reworks}회`} />}
        </li>)}</ol>
      </> },
      { value: "verification", label: "검증", panel: <>
        {plans.map(({ data }, i) => <section key={i} className="gs-plan-checks gs-detail-card" aria-label="검사 결과">
          <h2>검사 결과{plans.length > 1 ? ` · 기획안 ${i + 1}` : ""}</h2>
          <Badge className={data.unknown_count > 0 ? "attention" : "clear"} variant={data.unknown_count > 0 ? "warn" : "success"} label={`근거 연결 없음 ${data.unknown_count}건`} />
          {Object.keys(data.unknown_codes).length > 0 && <ul>{Object.keys(data.unknown_codes).map(code => <li key={code}>{Object.hasOwn(unknownNames, code) ? unknownNames[code] : code}</li>)}</ul>}
          <p className="code-result">코드 검사: {data.passed ? "통과" : "실패"}</p>
          <p className="evaluation-status">평가 상태: {Object.hasOwn(statusNames, data.status) ? statusNames[data.status] : "정보 없음"}</p>
        </section>)}
        {turn.commands.filter(command => command.kind === "show_aggregates").map((command, i) => <AggregatesPanel key={i} data={command.data} />)}
        {turn.commands.filter(command => command.kind === "show_distribution").map(({ data }, index) => {
          const columns = [...new Set(data.rows.flatMap(row => Object.keys(row)))];
          return <section key={index} className="gs-history-source" aria-label="시장 인사이트 원천">
            <span className="gs-source-chip">{data.tool}</span>
            <DataTable caption="시장 인사이트 원천 데이터" rows={data.rows.map((row, i) => ({ row, id: String(i) }))} rowKey={item => item.id}
              columns={columns.map(key => ({ key, header: columnName(key), render: ({ row }: { row: Record<string, unknown> }) => row[key] == null || typeof row[key] === "object" ? "—" : typeof row[key] === "string" ? insightValue(row[key], names) : String(row[key]) }))}
              emptyState={{ title: "원천 데이터가 없습니다", description: "수신한 표 데이터가 없습니다.", action: { label: "목록으로", onClick: onBack } }} />
          </section>;
        })}
        {!plans.length && !turn.commands.some(command => command.kind === "show_aggregates" || command.kind === "show_distribution") && empty}
      </> },
      { value: "evaluation", label: "평가", panel: <>
        {plans.map(({ data }, index) => {
          const attempts = data.attempts as DisplayAttempt[];
          const reworks = Math.max(0, attempts.length - 1);
          return <section className="gs-history-evaluation" key={index} aria-label={plans.length > 1 ? `기획안 ${index + 1} 평가` : "평가 시도"}>
            <h2>평가 시도 보기 · 되돌림 {reworks}회</h2>
            {reworks > 0 && <Badge variant="warn" label={`되돌림 ${reworks}회`} />}
            {attempts.length ? <ol>{attempts.map((attempt, i) => <li className={`gs-history-attempt${reworks ? " gs-history-reworked" : ""}`} key={i}>
              <strong>시도 {attempt.attempt}</strong><p>시도 코드 검사: {checkLabel(attempt.checks_passed)} · 최종 판정: {checkLabel(attempt.final_passed)}</p>
              {attempt.scores && <ul>{Object.entries(attempt.scores).filter(([, score]) => typeof score === "number").map(([key, score]) => <li key={key}>{Object.hasOwn(scoreNames, key) ? `${scoreNames[key]} (${key})` : "기타"}: {String(score)}</li>)}</ul>}
              {typeof attempt.scores?.rationale === "string" && <p>사유: {localizeText(attempt.scores.rationale, names)}</p>}
              {(attempt.low_items?.length ?? 0) > 0 && <p className="muted">재검토 항목: {attempt.low_items?.map(key => Object.hasOwn(scoreNames, key) ? scoreNames[key] : "기타").join(", ")}</p>}
              {attempt.cost_usd != null && <small>시도 텍스트 비용 ${attempt.cost_usd.toFixed(4)}</small>}
            </li>)}</ol> : empty}
          </section>;
        })}
        {!plans.length && empty}
      </> },
      { value: "cost", label: "비용", panel: <>
        {summary.cost ? <CostDetail data={summary.cost} /> : <p>텍스트 비용 정보 없음</p>}
        {allAttempts.length ? <ul>{plans.flatMap(({ data }, planIndex) => (data.attempts as DisplayAttempt[]).map((attempt, index) => <li key={`${planIndex}-${index}`}>{plans.length > 1 ? `기획안 ${planIndex + 1} · ` : ""}시도 {attempt.attempt} · 시도 텍스트 비용 {attempt.cost_usd == null ? "정보 없음" : `$${attempt.cost_usd.toFixed(4)}`}</li>))}</ul> : empty}
      </> },
    ]} />
  </section>;
}
