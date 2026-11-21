/* eslint-disable @next/next/no-img-element -- Authenticated image bytes use temporary blob URLs. */
"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { ApiError, getPlanImage, getSavedPlans, getSchema } from "../../lib/api";
import { platformLabel } from "../../lib/evidence";
import { taxonomyNames } from "../../lib/taxonomy";
import type { TaxonomyNames } from "../../lib/taxonomy";
import type { SavedPlan, SchemaResponse } from "../../lib/types";
import { Badge, Button, Card, EmptyState, PageHeader, SidePanel } from "../ui";
import "../../app/saved.css";

export function SavedPage({ tenantId, onPlan }: { tenantId: string | null; onPlan: () => void }) {
  return <section className="gs-saved-page">
    <PageHeader title="저장한 기획" description="승인한 기획안을 모아 봅니다. 광고 기획 결과에서 승인을 누르면 여기에 모입니다." />
    {tenantId === null ? <p>상단 바에서 작업 공간을 선택하세요.</p>
      : <SavedWorkspace key={tenantId} tenantId={tenantId} onPlan={onPlan} />}
  </section>;
}

function SavedWorkspace({ tenantId, onPlan }: { tenantId: string; onPlan: () => void }) {
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<{ attempt: number; plans?: SavedPlan[]; error?: string } | null>(null);
  const [schema, setSchema] = useState<SchemaResponse | null>(null);
  useEffect(() => {
    let active = true;
    void getSavedPlans(tenantId).then(plans => {
      if (active) setResult({ attempt, plans });
    }).catch(error => {
      if (active) setResult({ attempt, error: error instanceof ApiError
        ? `기획안을 불러오지 못했습니다. 상태 ${error.status} · 코드 ${error.code ?? "정보 없음"}`
        : "기획안을 불러오지 못했습니다. 연결 상태를 확인하세요." });
    });
    return () => { active = false; };
  }, [tenantId, attempt]);
  useEffect(() => {
    let active = true;
    void getSchema(tenantId).then(value => { if (active) setSchema(value); }).catch(() => {
      // The list remains available with Korean fallback badges.
    });
    return () => { active = false; };
  }, [tenantId]);
  const current = result?.attempt === attempt ? result : null;
  const names = taxonomyNames(schema);
  if (!current) return <p role="status">저장한 기획안을 불러오는 중입니다.</p>;
  if (current.error) return <div className="gs-saved-error"><p role="alert">{current.error}</p>
    <Button variant="secondary" onClick={() => setAttempt(value => value + 1)}>다시 시도</Button></div>;
  if (!current.plans?.length) return <EmptyState title="승인한 기획안이 없습니다"
    description="광고 기획 결과에서 승인을 누르면 여기에 모입니다." action={{ label: "광고 기획으로", onClick: onPlan }} />;
  return <>
    <p className="gs-saved-note">승인 일시는 광고 기획 결과에서 승인을 저장한 시각입니다.</p>
    <div className="gs-saved-grid">{current.plans.map(plan => <SavedPlanCard key={plan.plan_id} tenantId={tenantId} plan={plan} names={names} />)}</div>
  </>;
}

function koreanName(name: string, value: string): string {
  return name !== value && /[가-힣]/.test(name) ? name : "기타";
}

function evidenceSummary(ids: readonly string[]): string {
  const platforms = ["youtube", "instagram", "tiktok"];
  const sources = ids.map(id => id.includes(":") ? id.split(":", 1)[0] : null);
  const known = platforms.flatMap(source => {
    const count = sources.filter(value => value === source).length;
    return count ? [`${platformLabel(source)} ${count}건`] : [];
  });
  const unknown = sources.filter(source => source === null || !platforms.includes(source)).length;
  if (unknown) known.push(`${platformLabel(null)} ${unknown}건`);
  return known.join(" · ") || "출처 정보 없음";
}

function SavedPlanCard({ tenantId, plan, names }: { tenantId: string; plan: SavedPlan; names: TaxonomyNames }) {
  const [open, setOpen] = useState(false);
  const [image, setImage] = useState<{ key: string; url?: string; failed?: boolean } | null>(null);
  const imageKey = JSON.stringify([tenantId, plan.plan_id, plan.has_image]);
  useEffect(() => {
    if (!plan.has_image) return;
    let active = true;
    let url: string | undefined;
    void getPlanImage(tenantId, plan.plan_id).then(blob => {
      if (!active) return;
      url = URL.createObjectURL(blob);
      setImage({ key: imageKey, url });
    }).catch(() => { if (active) setImage({ key: imageKey, failed: true }); });
    return () => { active = false; if (url) URL.revokeObjectURL(url); };
  }, [tenantId, plan.plan_id, plan.has_image, imageKey]);
  const currentImage = image?.key === imageKey ? image : null;
  const title = plan.title || "기획안";
  const claims = plan.claimed_efficacy ?? [];
  const ids = plan.evidence_ids ?? [];
  function media() {
    return <span className="gs-saved-media">{!plan.has_image ? <span className="gs-saved-tile">시안 없음</span>
      : currentImage?.url ? <img src={currentImage.url} alt="기획안 시안 이미지" onError={() => setImage({ key: imageKey, failed: true })} />
      : <span className="gs-saved-tile">{currentImage?.failed ? "시안 이미지를 불러오지 못했습니다" : "시안 이미지를 불러오는 중입니다."}</span>}</span>;
  }
  function efficacyBadges() {
    return claims.length ? claims.map((claim, index) => <Badge key={index} label={koreanName(names.claimName(claim), claim)} />)
      : <Badge label="정보 없음" />;
  }
  return <Card className="gs-saved-card">
    <button type="button" className="gs-saved-card-button" aria-label={title} onClick={() => setOpen(true)}>
      {media()}
      <span className="gs-saved-card-copy"><span className="gs-saved-title">{title}</span>
        <span className="gs-saved-hook">{plan.hook_text || "정보 없음"}</span>
        <span className="gs-saved-badges"><Badge variant="accent" label={plan.hook_type ? koreanName(names.axisName("hook_type", plan.hook_type), plan.hook_type) : "정보 없음"} />{efficacyBadges()}</span>
        <span className="gs-saved-date">승인 일시 <time dateTime={plan.decided_at}>{new Date(plan.decided_at).toLocaleString("ko-KR")}</time></span>
        {plan.reason && <span className="gs-saved-reason">사유: {plan.reason}</span>}
      </span>
    </button>
    {open && createPortal(<SidePanel title={title} value={open} onChange={setOpen}>
      <div className="gs-saved-detail">
        <section aria-label="장면 구성"><h3>장면 구성</h3>{plan.scenes?.length
          ? <ol>{plan.scenes.map((scene, index) => <li key={index}>{scene}</li>)}</ol> : <p>정보 없음</p>}</section>
        <section aria-label="카피"><h3>카피</h3>{plan.copy_lines?.length
          ? plan.copy_lines.map((copy, index) => <blockquote key={index}>{copy}</blockquote>) : <p>정보 없음</p>}</section>
        <section aria-label="주장 효능"><h3>주장 효능</h3><div className="gs-saved-badges">{efficacyBadges()}</div></section>
        <section aria-label="기획안 근거"><h3>근거 소재 {ids.length}건</h3><p>{evidenceSummary(ids)}</p></section>
        {media()}
      </div>
    </SidePanel>, document.body)}
  </Card>;
}
