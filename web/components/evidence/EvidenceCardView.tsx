/* eslint-disable @next/next/no-img-element -- Direct thumbnails are neither stored nor proxied. */
"use client";

import { useContext, useState } from "react";
import { brandDisplayName, BrandNamesContext } from "../../lib/brandNames";
import { PlatformGlyph } from "./PlatformIcon";
import { PlatformTile } from "./PlatformTile";
import { isOwnBrand, platformLabel, safeLink } from "../../lib/evidence";
import { publishedDate } from "../../lib/format";
import type { EvidenceCard } from "../../lib/types";
import { ctaName, talentName, taxonomyNames, type TaxonomyNames } from "../../lib/taxonomy";
import { Badge, Card } from "../ui";
import { displayValue } from "../../lib/localize";
import "../../app/evidence.css";

export function EvidenceChip({ id, card }: { id: string; card?: EvidenceCard }) {
  const brandNames = useContext(BrandNamesContext);
  const [failed, setFailed] = useState(false);
  const youtubeId = id.match(/^youtube:([A-Za-z0-9_-]{1,64})$/)?.[1];
  const source = card?.source ?? id.split(":", 1)[0];
  return <span className="gs-evidence-chip">
    {youtubeId && !failed ? <img src={`https://i.ytimg.com/vi/${youtubeId}/hqdefault.jpg`} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setFailed(true)} />
      : <span className="gs-platform-tile" data-platform={source} aria-hidden="true">{source === "instagram" || source === "tiktok" ? <PlatformGlyph source={source} /> : <span className="gs-platform-monogram">{source?.slice(0, 1).toUpperCase() || "?"}</span>}</span>}
    <span>{brandDisplayName(card?.brand, brandNames, "브랜드 정보 없음")}</span>
  </span>;
}

export function EvidenceCardView({ card, anchor, names = taxonomyNames(), workspaceBrand }: {
  card: EvidenceCard; anchor: string; names?: TaxonomyNames; workspaceBrand?: string | null;
}) {
  const brandNames = useContext(BrandNamesContext);
  const brand = brandDisplayName(card.brand, brandNames, "브랜드 정보 없음");
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const id = card.source === "youtube" ? card.evidence_id?.match(/^youtube:([A-Za-z0-9_-]{1,64})$/)?.[1] : null;
  const thumbnail = id ? `https://i.ytimg.com/vi/${id}/hqdefault.jpg` : null;
  const href = safeLink(card.url);
  const tags = [
    { category: "hook", prefix: "훅", value: card.hook_type ? names.axisName("hook_type", card.hook_type) : null },
    { category: "angle", prefix: "소구", value: card.angle ? names.axisName("angle", card.angle) : null },
    { category: "format", prefix: "형식", value: card.format ? names.axisName("format", card.format) : null },
    { category: "talent", prefix: "출연자", value: card.talent ? talentName(card.talent) : null },
    { category: "cta", prefix: "CTA", value: card.cta_type ? ctaName(card.cta_type) : null },
    ...(card.claims ?? []).map(claim => ({ category: "claim", prefix: "효능", value: names.claimName(claim) })),
  ].filter(tag => tag.value !== null);
  const label = platformLabel(card.source);
  const title = card.title?.trim() ? card.title : `${brand} · ${label} 광고`;
  return <article className="gs-evidence-card" id={anchor} tabIndex={-1} data-linked={href ? "true" : undefined}>
    <Card>
      {thumbnail && failedUrl !== thumbnail
        ? <img className="gs-evidence-thumbnail" src={thumbnail} alt={`${title} 썸네일`} referrerPolicy="no-referrer" loading="lazy" onError={() => setFailedUrl(thumbnail)} />
        : <PlatformTile source={card.source} label={label} />}
      <div className="gs-evidence-body">
        <div className="gs-evidence-meta"><small>{brand} · {label}</small>{isOwnBrand(card.brand, workspaceBrand) && <Badge label="자사" variant="accent" />}</div>
        <h4>{href ? <a href={href} rel="noopener noreferrer" target="_blank">{title}</a> : title}</h4>
        <p className="muted">{publishedDate(card.published_at)}</p>
        <div className="gs-evidence-metrics"><span>{card.view_count === null ? "조회수 정보 없음" : `조회수 ${card.view_count.toLocaleString("ko-KR")}`}</span><span>{card.like_count === null ? "좋아요 정보 없음" : `좋아요 ${card.like_count.toLocaleString("ko-KR")}`}</span></div>
        {tags.length ? <div aria-label="이 소재의 분석 결과" className="gs-result-badges">{tags.map((tag, index) => <span className="gs-tag" data-category={tag.category} key={index}><span className="gs-sr-only">{tag.prefix}: </span>{displayValue(tag.value!, names)}</span>)}</div> : <small className="muted">분석 대상 아님</small>}
      </div>
    </Card>
  </article>;
}
