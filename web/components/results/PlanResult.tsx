"use client";
import { useId, useState } from "react";
import type { EvaluationAttempt, PatternData, PlanView } from "../../lib/types";
import { taxonomyNames } from "../../lib/taxonomy";
import type { TaxonomyNames } from "../../lib/taxonomy";
import { PatternAlignment, PatternSummary } from "./PatternAlignment";
import { DesignImage } from "./DesignImage";
import { FeedbackBar } from "./FeedbackBar";
import { Badge, Button, Card } from "../ui";
import "../../app/results.css";
const unknownNames: Record<string, string> = {
  CERT_REQUIRED_UNVERIFIED: "인증 연결 없음",
  EFFICACY_UNKNOWN: "효능 근거 연결 없음",
  EFFICACY_UNSUPPORTED: "효능 근거가 뒷받침하지 않음",
};
const statusNames: Record<string, string> = { done: "완료", needs_review: "검토 필요", failed: "실패" };
const scoreNames: Record<string, string> = { differentiation: "차별성", fit: "요청 적합성" };
function checkLabel(value: boolean | null | undefined) { return value == null ? "미실행" : value ? "통과" : "실패"; }
export function PlanResult({ data, tenantId, names = taxonomyNames(), evidenceAnchors = {} }: {
  data: PlanView; tenantId: string | null; names?: TaxonomyNames; evidenceAnchors?: Record<string, string>;
}) {
  const [expanded, setExpanded] = useState(false);
  const expandedId = useId();
  const plan = data.plan;
  const attempts = data.attempts as EvaluationAttempt[];
  return <Card role="article" className="plan-card gs-plan-result" aria-label={plan.title ?? "기획안"}>
    <div className="gs-plan-media">
      {data.image && tenantId ? <DesignImage tenantId={tenantId} image={data.image} disclaimer={null} /> : <div className="gs-design-placeholder"><svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true"><path d="M3 3h18v18H3V3Zm0 13 5-5 5 5 3-3 5 5M16 7h.01" /></svg><span>시안 이미지</span></div>}
    </div>
    <div className="gs-plan-summary">
      <div className="gs-result-badges">{plan.claimed_efficacy?.map((claim, i) => <Badge key={i} variant={data.efficacy_status[claim] === "supported" ? "success" : "warn"} label={`${names.claimName(claim)} · ${data.efficacy_status[claim] === "supported" ? "확인됨" : data.efficacy_status[claim] === "unsupported" ? "근거가 뒷받침하지 않음" : "근거 연결 없음"}`} />)}
        <Badge className={data.unknown_count > 0 ? "attention" : "clear"} variant={data.unknown_count > 0 ? "warn" : "success"} label={`근거 연결 없음 ${data.unknown_count}건`} />
      </div>
    <header><small>기획안 · {Object.values(data.product_display).filter(Boolean).join(" · ")}</small><h3>{plan.title ?? "기획안"}</h3><p className="hook-text">{plan.hook_text}</p>
      <div className="gs-result-badges">{(["hook_type", "angle", "format"] as const).map(axis => plan[axis] && <Badge key={axis} variant="accent" label={names.axisName(axis, plan[axis])} />)}</div>
    </header>
      <PatternSummary data={data.pattern_alignment as PatternData} />
      <div className="gs-plan-actions">
        {tenantId && <FeedbackBar key={data.plan_id} tenantId={tenantId} planId={data.plan_id} />}
        <Button variant="ghost" size="sm" className="gs-plan-toggle" aria-expanded={expanded} aria-controls={expandedId} onClick={() => setExpanded(value => !value)}>전체 보기 →</Button>
      </div>
    </div>
    <div className="gs-plan-expanded" id={expandedId} hidden={!expanded}>
    {plan.scenes?.length ? <section aria-label="장면 구성"><h4>장면 구성</h4><ol>{plan.scenes.map((scene, i) => <li key={i}>{scene}</li>)}</ol></section> : null}
    {plan.copy_lines?.length ? <section aria-label="카피"><h4>카피</h4>{plan.copy_lines.map((copy, i) => <p key={i}>{copy}</p>)}</section> : null}
    {(plan.claimed_efficacy?.length ?? 0) > 0 && <section aria-label="주장 효능"><h4>주장 효능</h4><div className="gs-result-badges">{plan.claimed_efficacy?.map((claim, i) => {
      const status = data.efficacy_status[claim];
      return <Badge key={i} variant={status === "supported" ? "success" : "warn"} label={`${names.claimName(claim)} · ${status === "supported" ? "확인됨" : status === "unsupported" ? "근거가 뒷받침하지 않음" : "근거 연결 없음"}`} />;
    })}</div></section>}
    <section className="gs-plan-checks" aria-label="검사 결과">
      {Object.keys(data.unknown_codes).length > 0 && <ul>{Object.keys(data.unknown_codes).map(code => <li key={code}>{Object.hasOwn(unknownNames, code) ? unknownNames[code] : code}</li>)}</ul>}
      <p className="code-result">코드 검사: {data.passed ? "통과" : "실패"}</p>
      <p className="evaluation-status">평가 상태: {Object.hasOwn(statusNames, data.status) ? statusNames[data.status] : data.status}</p>
    </section>
    <PatternAlignment data={data.pattern_alignment as PatternData} label={data.pattern_alignment_label} names={names} />
    {(plan.evidence_ids?.length ?? 0) > 0 && <section aria-label="기획안 근거"><h4>근거 소재 목록</h4><ul>{plan.evidence_ids?.map((id, i) => <li key={i}>{evidenceAnchors[id] ? <a href={`#${evidenceAnchors[id]}`}>{id}</a> : id}</li>)}</ul></section>}
    <details><summary>평가 시도 보기 · 되돌림 {Math.max(0, attempts.length - 1)}회</summary><ol>{attempts.map((attempt, i) => <li key={i}>
      <strong>시도 {attempt.attempt}</strong><p>시도 코드 검사: {checkLabel(attempt.checks_passed)} · 최종 판정: {checkLabel(attempt.final_passed)}</p>
      {attempt.scores && <ul>{Object.entries(attempt.scores).map(([key, score]) => <li key={key}>{Object.hasOwn(scoreNames, key) ? `${scoreNames[key]} (${key})` : key}: {score}</li>)}</ul>}
      {(attempt.low_items?.length ?? 0) > 0 && <p className="muted">재검토 항목: {attempt.low_items?.map(key => Object.hasOwn(scoreNames, key) ? scoreNames[key] : key).join(", ")}</p>}
      {attempt.cost_usd != null && <small>시도 텍스트 비용 ${attempt.cost_usd.toFixed(4)}</small>}
    </li>)}</ol></details>
    <p className="muted">{data.disclaimer}</p>
    {data.design_disclaimer && <p className="muted">{data.design_disclaimer}</p>}
    </div>
  </Card>;
}
