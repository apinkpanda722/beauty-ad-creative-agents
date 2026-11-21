"use client";

import { useContext, useEffect, useState, type ReactNode } from "react";
import type { Turn } from "../../lib/reducer";
import type { EvaluationAttempt, SchemaResponse } from "../../lib/types";
import { getSchema } from "../../lib/api";
import { historyDuration, historyTime, summarizeTurn, totalCost } from "../../lib/history";
import { taxonomyNames, type TaxonomyNames } from "../../lib/taxonomy";
import { localizeText, scoreNames } from "../../lib/localize";
import { modelAxis, parseModelBreakdown } from "../../lib/insight";
import { unknownNames } from "../../lib/unknown";
import { Badge, Button, Card, DataTable, PageHeader, Tabs, Tooltip } from "../ui";
import { AggregatesPanel } from "../results/AggregatesPanel";
import { InsightPanel, type ModelChart } from "../results/InsightPanel";
import { ScoreLabel } from "../results/ScoreLabel";
import { CommandTenantContext } from "../results/ResultsView";
import "../../app/history.css";

type DisplayAttempt = Omit<EvaluationAttempt, "scores"> & { scores?: Record<string, unknown> | null };
const checkLabel = (value: boolean | null | undefined) => value == null ? "미실행" : value ? "통과" : "실패";
function AttemptLine({ attempt }: { attempt: DisplayAttempt }) {
  return <span className="gs-attempt-line">검사 {checkLabel(attempt.checks_passed)} · 최종 {checkLabel(attempt.final_passed)}
    {(["differentiation", "fit"] as const).map(key => typeof attempt.scores?.[key] === "number" && <span key={key}> · <ScoreLabel name={key} /> {attempt.scores[key]}/5</span>)}
    {Boolean(attempt.low_items?.length) && ` · 재검토: ${attempt.low_items!.map(key => Object.hasOwn(scoreNames, key) ? scoreNames[key] : "기타").join(", ")}`}
  </span>;
}
const statusNames: Record<string, string> = { done: "완료", needs_review: "검토 필요", failed: "실패" };
const stageStatusNames = { done: "완료", pending: "대기", running: "진행 중", failed: "실패" };
type StageRow = { id: string; stage: ReactNode; result: ReactNode; duration: string };
type CostRow = { id: string; label: ReactNode; amount: ReactNode };

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
  const distributions = turn.commands.filter(command => command.kind === "show_distribution").map(command => command.data);
  const hasCompetitor = distributions.some(data => data.tool !== "top_vs_bottom_axis");
  const modelCharts: ModelChart[] = [];
  const aggregates = turn.commands.filter(command => command.kind === "show_aggregates").map(({ data }) => ({ ...data, model_written: data.model_written.filter(item => {
    const label = localizeText(item.name, names).trim();
    const axis = modelAxis(label);
    const rows = parseModelBreakdown(item.value);
    if (!hasCompetitor || !axis || !rows) return true;
    modelCharts.push({ axis, label, rows });
    return false;
  }) }));
  const attempts = plans.flatMap(({ data }, planIndex) => (data.attempts as DisplayAttempt[]).map((attempt, index) => ({
    attempt, id: `${planIndex}-${index}`, label: `${plans.length > 1 ? `기획안 ${planIndex + 1} · ` : ""}시도 ${attempt.attempt}`,
  })));
  const stageRows: StageRow[] = summary.progress.flatMap(stage => [{
    id: stage.id,
    stage: <span className="gs-history-stage" data-status={stage.status}>
      <svg role="img" aria-label={stageStatusNames[stage.status]} width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d={stage.status === "done" ? "m5 12 4 4L19 6" : stage.status === "failed" ? "m6 6 12 12M6 18 18 6" : "M12 4v8l4 4"} /></svg>
      <span>{stage.label}</span>
    </span>,
    result: <span className="gs-history-stage-result">{stageStatusNames[stage.status]}{stage.id === "plan_eval" && <> <Badge variant={stage.reworks > 0 ? "warn" : "neutral"} label={`재작업 ${stage.reworks}회`} /></>}</span>,
    duration: stage.id === "image" ? "" : historyDuration(stage.durationMs),
  }, ...(stage.id === "plan_eval" ? attempts.map(({ attempt, id, label }) => ({ id: `attempt-${id}`, stage: <span className="gs-history-attempt-label">{label}</span>, result: <AttemptLine attempt={attempt} />, duration: "" })) : [])]);
  stageRows.push({ id: "total", stage: "총 시간", result: "", duration: historyDuration(summary.durationMs) });
  const cost = summary.cost;
  const allAttemptCosts = attempts.every(({ attempt }) => typeof attempt.cost_usd === "number");
  const costRows: CostRow[] = cost ? [
    ...attempts.map(({ attempt, id, label }) => ({ id, label, amount: attempt.cost_usd == null ? "정보 없음" : `$${attempt.cost_usd.toFixed(4)}` })),
    ...(allAttemptCosts ? [{ id: "remainder", label: "그 외 텍스트 모델 호출", amount: `$${(cost.text_spent_usd - attempts.reduce((sum, { attempt }) => sum + attempt.cost_usd!, 0)).toFixed(4)}` }] : []),
    { id: "text", label: cost.label, amount: `$${cost.text_spent_usd.toFixed(4)}` },
    { id: "image", label: "시안 이미지 생성", amount: cost.image_cost_usd == null ? "이미지 없음" : `$${cost.image_cost_usd.toFixed(4)}` },
    { id: "total", label: <strong>총 비용</strong>, amount: <strong>${totalCost(cost).toFixed(4)}</strong> },
  ] : [];
  const usage = cost && cost.max_text_cost_usd > 0 ? Math.round(cost.text_spent_usd / cost.max_text_cost_usd * 100) : null;
  const emptyState = { title: "정보 없음", description: "수신한 데이터가 없습니다.", action: { label: "목록으로", onClick: onBack } };
  const empty = <p>정보 없음</p>;
  return <section className="gs-history-page">
    <PageHeader title="실행 기록·검증" actions={<><Button variant="secondary" onClick={onBack}>목록으로</Button>{onReturn && <Button variant="secondary" onClick={onReturn}>광고 기획으로 돌아가기</Button>}</>} />
    <Card className="gs-history-summary" aria-label="실행 요약">
      <h2>{turn.message}</h2><dl>
        <div><dt>작업 공간</dt><dd>{workspace}</dd></div>
        <div><dt>시각</dt><dd>{time ? <time dateTime={time}>{new Date(time).toLocaleString("ko-KR")}</time> : "정보 없음"}</dd></div>
        <div><dt>총 시간</dt><dd>{historyDuration(summary.durationMs)}</dd></div>
        <div><dt>총 비용</dt><dd>{cost ? `$${totalCost(cost).toFixed(4)}` : "정보 없음"}</dd></div>
      </dl>
    </Card>
    <Tabs label="실행 상세" value={tab} onChange={setTab} items={[
      { value: "stages", label: "단계", panel: <>
        <p>기획 {summary.planningCount}회 · 평가 {summary.evaluationCount}회</p>
        <DataTable caption="단계별 처리 결과" rows={stageRows} rowKey={row => row.id} emptyState={emptyState} columns={[
          { key: "stage", header: "단계", render: row => row.stage },
          { key: "result", header: "결과", render: row => row.result },
          { key: "duration", header: "소요 시간", render: row => row.duration },
        ]} />
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
        {distributions.length > 0 && <section aria-label="검증된 집계(도구가 센 값)" className="gs-verified-aggregates">
          <h3>검증된 집계(도구가 센 값)</h3><Badge variant="success" label="검증됨" />
          <InsightPanel distributions={distributions} names={names} variant="verification" modelCharts={modelCharts} />
          <p className="gs-insight-note">분류가 많으면 상위 5개만 표시합니다</p>
        </section>}
        {aggregates.map((data, index) => <AggregatesPanel key={index} data={data} names={names} />)}
        {!plans.length && !turn.commands.some(command => command.kind === "show_aggregates" || command.kind === "show_distribution") && empty}
      </> },
      { value: "cost", label: "비용", panel: cost ? <div className="gs-history-cost">
        <DataTable caption="비용 내역" rows={costRows} rowKey={row => row.id} emptyState={emptyState} columns={[
          { key: "label", header: "항목", render: row => row.label },
          { key: "amount", header: "금액", render: row => row.amount },
        ]} />
        {allAttemptCosts && <p className="gs-insight-note">그 외 텍스트 모델 호출은 텍스트 모델 비용에서 시도별 비용 합계를 뺀 계산값입니다.</p>}
        {usage !== null && <><p>텍스트 비용 <Tooltip content="요청 하나가 쓸 수 있는 텍스트 비용 한도입니다.">상한</Tooltip> ${cost.max_text_cost_usd.toFixed(4)} 중 {usage}% 사용</p>
          <meter className="gs-cost-meter" min={0} max={100} value={Math.min(100, usage)} aria-valuenow={Math.min(100, usage)} aria-label="텍스트 비용 사용률" />
        </>}
      </div> : <p>비용 정보 없음</p> },
    ]} />
  </section>;
}
