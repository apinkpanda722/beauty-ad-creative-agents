"use client";
import { useEffect, useId, useRef, useState } from "react";
import type { EvaluationAttempt, EvidenceCard, PatternData, PlanView, UiCommand } from "../../lib/types";
import { taxonomyNames } from "../../lib/taxonomy";
import type { TaxonomyNames } from "../../lib/taxonomy";
import { PatternAlignment, PatternSummary } from "./PatternAlignment";
import { DesignImage } from "./DesignImage";
import { FeedbackBar } from "./FeedbackBar";
import { CostDetail } from "./CostDetail";
import { Badge, Button, Card } from "../ui";
import { koreanBrand } from "../../lib/workspace";
import { displayValue, localizeText, scoreNames } from "../../lib/localize";
import { unknownExplanation, unknownNames, unknownReasons } from "../../lib/unknown";
import { EvidenceChip } from "../evidence/EvidenceCardView";
import "../../app/results.css";
const statusNames: Record<string, string> = { done: "완료", needs_review: "검토 필요", failed: "실패" };
type DisplayAttempt = Omit<EvaluationAttempt, "scores"> & { scores?: Record<string, unknown> | null };
function checkLabel(value: boolean | null | undefined) { return value == null ? "미실행" : value ? "통과" : "실패"; }
export function PlanResult({ data, tenantId, names = taxonomyNames(), evidenceAnchors = {}, evidenceCards = [], cost }: {
  data: PlanView; tenantId: string | null; names?: TaxonomyNames; evidenceAnchors?: Record<string, string>;
  evidenceCards?: readonly EvidenceCard[];
  cost?: Extract<UiCommand, { kind: "show_cost" }>["data"];
}) {
  const [expanded, setExpanded] = useState(false);
  const [visible, setVisible] = useState(false);
  const [open, setOpen] = useState(false);
  const [media, setMedia] = useState<{ key: string; ratio: number | null } | null>(null);
  const imageKey = JSON.stringify([tenantId, data.image?.request_key, data.image?.index, data.image?.sha256]);
  const expandedRef = useRef<HTMLDivElement>(null);
  const gridRef = useRef<HTMLDivElement>(null);
  const frame = useRef<number | undefined>(undefined);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const expandedId = useId();
  const tooltipId = useId();
  const plan = data.plan;
  const attempts = data.attempts as DisplayAttempt[];
  const latest = attempts.at(-1);
  const scores = (["differentiation", "fit"] as const).flatMap(key => typeof latest?.scores?.[key] === "number" ? [`${scoreNames[key]} ${latest.scores[key]}/5`] : []);
  const quality = `품질 검사 ${checkLabel(latest ? latest.checks_passed : data.passed)}${scores.length ? ` · 평가 ${scores.join(", ")}` : ""}`;
  const reasons = unknownReasons(data.unknown_codes, data.unknown_count);
  useEffect(() => {
    // CostDetail keeps its established output and direct-child placement.
    expandedRef.current?.querySelectorAll(".gs-cost-line").forEach(node => node.classList.add("gs-footnote"));
  }, [cost]);
  useEffect(() => () => { if (frame.current !== undefined) cancelAnimationFrame(frame.current); clearTimeout(timer.current); }, []);
  function toggle() {
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
  return <Card role="article" className="plan-card gs-plan-result" aria-label={plan.title ?? "기획안"}>
    <div className="gs-plan-media" style={{ aspectRatio: media?.key === imageKey && media.ratio ? media.ratio : "1 / 1" }}>
      {data.image && tenantId ? <DesignImage key={imageKey} tenantId={tenantId} image={data.image} disclaimer={null} onAspectRatio={ratio => setMedia({ key: imageKey, ratio })} /> : <div className="gs-design-placeholder"><svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true"><path d="M3 3h18v18H3V3Zm0 13 5-5 5 5 3-3 5 5M16 7h.01" /></svg><span>시안 이미지</span></div>}
    </div>
    <div className="gs-plan-summary">
      <div className="gs-result-badges">{plan.claimed_efficacy?.map((claim, i) => <Badge key={i} variant={data.efficacy_status[claim] === "supported" ? "success" : "warn"} label={`${names.claimName(claim)} · ${data.efficacy_status[claim] === "supported" ? "확인됨" : data.efficacy_status[claim] === "unsupported" ? "근거가 뒷받침하지 않음" : "근거 연결 없음"}`} />)}
        <span className="gs-review-badge" tabIndex={0} title={unknownExplanation} aria-describedby={tooltipId}>확인 필요 {data.unknown_count}건{reasons ? ` · ${reasons}` : ""}</span>
        <span className="gs-review-tooltip" role="tooltip" id={tooltipId}>{unknownExplanation}</span>
      </div>
    <header><small>기획안 · {koreanBrand(data.product_display)}{data.product_display.product_name ? ` · ${data.product_display.product_name}` : ""}</small><h3>{plan.title ?? "기획안"}</h3><p className="hook-text">{plan.hook_text}</p>
      <div className="gs-result-badges">{(["hook_type", "angle", "format"] as const).map(axis => plan[axis] && <Badge key={axis} variant="accent" label={displayValue(names.axisName(axis, plan[axis]), names)} />)}</div>
    </header>
      <PatternSummary data={data.pattern_alignment as PatternData} />
      <p className="gs-quality-summary">{quality}</p>
      <div className="gs-plan-actions">
        {tenantId && <FeedbackBar key={data.plan_id} tenantId={tenantId} planId={data.plan_id} />}
        <Button variant="ghost" size="sm" className="gs-plan-toggle" aria-expanded={expanded} aria-controls={expandedId} onClick={toggle}>전체 보기 <span className="gs-toggle-arrow">→</span></Button>
      </div>
    </div>
    <div ref={gridRef} className={`gs-plan-accordion${open ? " gs-open" : ""}`} onTransitionEnd={event => {
      if (event.target === event.currentTarget && (!event.propertyName || event.propertyName === "grid-template-rows") && !expanded) { clearTimeout(timer.current); setVisible(false); }
    }}><div ref={expandedRef} className={`gs-plan-expanded${open ? " gs-open" : ""}`} id={expandedId} hidden={!visible}>
    {plan.scenes?.length ? <section className="gs-detail-card gs-scene-steps" aria-label="장면 구성"><h4>장면 구성</h4><ol>{plan.scenes.map((scene, i) => <li key={i}>{scene}</li>)}</ol></section> : null}
    {plan.copy_lines?.length ? <section className="gs-detail-card gs-copy-card" aria-label="카피"><h4>카피</h4>{plan.copy_lines.map((copy, i) => <blockquote key={i}>{copy}</blockquote>)}</section> : null}
    {(plan.claimed_efficacy?.length ?? 0) > 0 && <section className="gs-detail-card" aria-label="주장 효능"><h4>주장 효능</h4><div className="gs-result-badges">{plan.claimed_efficacy?.map((claim, i) => {
      const status = data.efficacy_status[claim];
      return <Badge key={i} variant={status === "supported" ? "success" : "warn"} label={`${names.claimName(claim)} · ${status === "supported" ? "확인됨" : status === "unsupported" ? "근거가 뒷받침하지 않음" : "근거 연결 없음"}`} />;
    })}</div></section>}
    <section className="gs-plan-checks gs-detail-card" aria-label="검사 결과">
      <Badge className={data.unknown_count > 0 ? "attention" : "clear"} variant={data.unknown_count > 0 ? "warn" : "success"} label={`근거 연결 없음 ${data.unknown_count}건`} />
      {Object.keys(data.unknown_codes).length > 0 && <ul>{Object.keys(data.unknown_codes).map(code => <li key={code}>{Object.hasOwn(unknownNames, code) ? unknownNames[code] : code}</li>)}</ul>}
      <p className="code-result">코드 검사: {data.passed ? "통과" : "실패"}</p>
      <p className="evaluation-status">평가 상태: {Object.hasOwn(statusNames, data.status) ? statusNames[data.status] : data.status}</p>
    </section>
    <PatternAlignment data={data.pattern_alignment as PatternData} label={data.pattern_alignment_label} names={names} />
    {(plan.evidence_ids?.length ?? 0) > 0 && <section className="gs-detail-card" aria-label="기획안 근거"><h4>근거 소재 목록</h4><ul className="gs-evidence-chips">{plan.evidence_ids?.map((id, i) => <li key={i}>{evidenceAnchors[id] ? <a href={`#${evidenceAnchors[id]}`} aria-label={id}><EvidenceChip key={id} id={id} card={evidenceCards.find(card => card.evidence_id === id)} /></a> : `근거 소재 ${i + 1}`}</li>)}</ul></section>}
    <details><summary>평가 시도 보기 · 되돌림 {Math.max(0, attempts.length - 1)}회</summary><ol>{attempts.map((attempt, i) => <li key={i}>
      <strong>시도 {attempt.attempt}</strong><p>시도 코드 검사: {checkLabel(attempt.checks_passed)} · 최종 판정: {checkLabel(attempt.final_passed)}</p>
      {attempt.scores && <ul>{Object.entries(attempt.scores).filter(([, score]) => typeof score === "number").map(([key, score]) => <li key={key}>{Object.hasOwn(scoreNames, key) ? `${scoreNames[key]} (${key})` : key}: {String(score)}</li>)}</ul>}
      {typeof attempt.scores?.rationale === "string" && <p>사유: {localizeText(attempt.scores.rationale, names)}</p>}
      {(attempt.low_items?.length ?? 0) > 0 && <p className="muted">재검토 항목: {attempt.low_items?.map(key => Object.hasOwn(scoreNames, key) ? scoreNames[key] : key).join(", ")}</p>}
      {attempt.cost_usd != null && <small>시도 텍스트 비용 ${attempt.cost_usd.toFixed(4)}</small>}
    </li>)}</ol></details>
    <p className="muted gs-footnote gs-footnote-first">{data.disclaimer}</p>
    {data.design_disclaimer && <p className="muted gs-footnote">{data.design_disclaimer}</p>}
    <CostDetail data={cost} />
    </div></div>
  </Card>;
}
