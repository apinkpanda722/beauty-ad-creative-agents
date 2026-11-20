/* eslint-disable @next/next/no-img-element -- Direct thumbnails are neither stored nor proxied. */
"use client";
import { useId, useState } from "react";
import { publishedDate } from "../lib/format";
import type { EvidenceCard, UiCommand } from "../lib/types";
import { ctaName, talentName, taxonomyNames } from "../lib/taxonomy";
import type { TaxonomyNames } from "../lib/taxonomy";

export function safeLink(value: string | null): string | undefined {
  if (!value) return;
  try { const url = new URL(value); if (url.protocol === "https:" || url.protocol === "http:") return url.href; } catch { /* Missing or invalid URLs have no link. */ }
}
function Card({ card, anchor, names }: { card: EvidenceCard; anchor: string; names: TaxonomyNames }) {
  const [failed, setFailed] = useState(false);
  const id = card.source === "youtube" ? card.evidence_id?.match(/^youtube:([A-Za-z0-9_-]{1,64})$/)?.[1] : null;
  const href = safeLink(card.url);
  const badges = [
    card.hook_type ? names.axisName("hook_type", card.hook_type) : null,
    card.angle ? names.axisName("angle", card.angle) : null,
    card.format ? names.axisName("format", card.format) : null,
    card.talent ? talentName(card.talent) : null,
    card.cta_type ? ctaName(card.cta_type) : null,
    ...(card.claims ?? []).map(names.claimName),
  ].filter((value): value is string => value !== null);
  const title = card.title ?? card.evidence_id ?? "제목 정보 없음";
  return <article className="evidence-card" id={anchor}>
    {id && !failed ? <img className="evidence-thumbnail" src={`https://i.ytimg.com/vi/${id}/hqdefault.jpg`} alt={`${title} 썸네일`} referrerPolicy="no-referrer" loading="lazy" onError={() => setFailed(true)} />
      : <div className="source-icon" aria-label={`${card.source ?? "알 수 없는"} 출처`}>{card.source ?? "출처 정보 없음"}</div>}
    <div className="evidence-body"><small>{card.brand ?? "브랜드 정보 없음"} · {card.source ?? "출처 정보 없음"}</small>
      <h4>{href ? <a href={href} rel="noopener noreferrer" target="_blank">{title}</a> : title}</h4>
      <p className="muted">{publishedDate(card.published_at)}</p>
      <div className="metric-row"><span>{card.view_count === null ? "조회수 정보 없음" : `조회수 ${card.view_count.toLocaleString("ko-KR")}`}</span><span>{card.like_count === null ? "좋아요 정보 없음" : `좋아요 ${card.like_count.toLocaleString("ko-KR")}`}</span></div>
      {badges.length ? <div aria-label="이 소재의 분석 결과" className="analysis-badges">{badges.map((label, i) => <span className="analysis-badge" key={i}>{label}</span>)}</div> : <small className="muted">분석 대상 아님</small>}
    </div>
  </article>;
}
export function EvidenceCards({ data, names = taxonomyNames(), anchors = {} }: {
  data: Extract<UiCommand, { kind: "show_evidence_cards" }>["data"]; names?: TaxonomyNames; anchors?: Record<string, string>;
}) {
  const prefix = useId();
  if (!data.cards.length && !data.missing) return null;
  return <section aria-label="근거 소재" className="result-section"><h3>근거 소재</h3><div className="evidence-grid">
    {data.cards.map((card, i) => <Card key={`${card.evidence_id}-${i}`} card={card} names={names} anchor={card.evidence_id && anchors[card.evidence_id] || `${prefix}-${i}`} />)}
  </div>{data.missing > 0 && <p className="muted">근거 소재 {data.missing}건을 불러오지 못했습니다.</p>}</section>;
}
