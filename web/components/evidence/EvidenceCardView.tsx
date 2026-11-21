/* eslint-disable @next/next/no-img-element -- Direct thumbnails are neither stored nor proxied. */
"use client";

import { useState } from "react";
import { isOwnBrand, platformLabel, safeLink } from "../../lib/evidence";
import { publishedDate } from "../../lib/format";
import type { EvidenceCard } from "../../lib/types";
import { ctaName, talentName, taxonomyNames, type TaxonomyNames } from "../../lib/taxonomy";
import { Badge, Card } from "../ui";
import "../../app/evidence.css";

export function EvidenceCardView({ card, anchor, names = taxonomyNames(), workspaceBrand }: {
  card: EvidenceCard; anchor: string; names?: TaxonomyNames; workspaceBrand?: string | null;
}) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const id = card.source === "youtube" ? card.evidence_id?.match(/^youtube:([A-Za-z0-9_-]{1,64})$/)?.[1] : null;
  const thumbnail = id ? `https://i.ytimg.com/vi/${id}/hqdefault.jpg` : null;
  const href = safeLink(card.url);
  const hook = card.hook_type ? names.axisName("hook_type", card.hook_type) : null;
  const badges = [
    card.angle ? names.axisName("angle", card.angle) : null,
    card.format ? names.axisName("format", card.format) : null,
    card.talent ? talentName(card.talent) : null,
    card.cta_type ? ctaName(card.cta_type) : null,
    ...(card.claims ?? []).map(names.claimName),
  ].filter((value): value is string => value !== null);
  const title = card.title ?? card.evidence_id ?? "제목 정보 없음";
  const label = platformLabel(card.source);
  return <article className="gs-evidence-card" id={anchor} tabIndex={-1}>
    <Card>
      {thumbnail && failedUrl !== thumbnail
        ? <img className="gs-evidence-thumbnail" src={thumbnail} alt={`${title} 썸네일`} referrerPolicy="no-referrer" loading="lazy" onError={() => setFailedUrl(thumbnail)} />
        : <div className="gs-platform-tile" aria-label={`${card.source ?? "알 수 없는"} 출처`}>
          <span className="gs-platform-monogram" aria-hidden="true">{card.source?.slice(0, 1).toUpperCase() || "?"}</span>
          <span>{label}</span>
        </div>}
      <div className="gs-evidence-body">
        <div className="gs-evidence-meta"><small>{card.brand ?? "브랜드 정보 없음"} · {label}</small>{isOwnBrand(card.brand, workspaceBrand) && <Badge label="자사" variant="accent" />}</div>
        {hook && <span className="gs-evidence-hook">{hook}</span>}
        <h4>{href ? <a href={href} rel="noopener noreferrer" target="_blank">{title}</a> : title}</h4>
        <details className="gs-evidence-extra"><summary>소재 정보</summary>
        <p className="muted">{publishedDate(card.published_at)}</p>
        <div className="gs-evidence-metrics"><span>{card.view_count === null ? "조회수 정보 없음" : `조회수 ${card.view_count.toLocaleString("ko-KR")}`}</span><span>{card.like_count === null ? "좋아요 정보 없음" : `좋아요 ${card.like_count.toLocaleString("ko-KR")}`}</span></div>
        {badges.length ? <div aria-label="이 소재의 분석 결과" className="gs-result-badges">{badges.map((label, i) => <Badge key={i} label={label} />)}</div> : !hook && <small className="muted">분석 대상 아님</small>}
        </details>
      </div>
    </Card>
  </article>;
}
