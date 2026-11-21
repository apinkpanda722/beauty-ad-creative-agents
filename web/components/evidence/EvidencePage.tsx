"use client";

import { useId, useState } from "react";
import { collectSessionCards, groupByPlatform, isOwnBrand, platformLabel } from "../../lib/evidence";
import type { UiCommand } from "../../lib/types";
import { Button, EmptyState, PageHeader } from "../ui";
import { PlatformIcon } from "./PlatformIcon";
import { EvidenceCardView } from "./EvidenceCardView";

export function EvidencePage({ turns, workspaceBrand, onPlan }: {
  turns: readonly { commands: readonly UiCommand[] }[]; workspaceBrand: string | null; onPlan: () => void;
}) {
  const prefix = useId();
  const [platform, setPlatform] = useState<"all" | { source: string | null }>("all");
  const [ownOnly, setOwnOnly] = useState(false);
  const cards = collectSessionCards(turns);
  const platforms = groupByPlatform(cards);
  const visible = cards.filter(card => (platform === "all" || card.source === platform.source) && (!ownOnly || isOwnBrand(card.brand, workspaceBrand)));
  return <div className="gs-evidence-page">
    <PageHeader title="근거 소재" description="이번 세션에서 찾은 소재를 플랫폼별로 살펴보세요." />
    {cards.length > 0 && <div className="gs-evidence-filters">
      <div className="gs-evidence-filter-row" role="group" aria-label="플랫폼">
        <span className="gs-evidence-filter-label">플랫폼</span>
        <Button variant="secondary" size="sm" aria-pressed={platform === "all"} onClick={() => setPlatform("all")}>전체</Button>
        {platforms.map(group => <Button key={JSON.stringify(group.source)} variant="secondary" size="sm" aria-pressed={platform !== "all" && platform.source === group.source} onClick={() => setPlatform({ source: group.source })}>{platformLabel(group.source)}</Button>)}
      </div>
      <div className="gs-evidence-filter-row" role="group" aria-label="브랜드">
        <span className="gs-evidence-filter-label">브랜드</span>
        <Button variant="secondary" size="sm" aria-pressed={!ownOnly} onClick={() => setOwnOnly(false)}>전체 브랜드</Button>
        <Button variant="secondary" size="sm" aria-pressed={ownOnly} onClick={() => setOwnOnly(true)}>자사만</Button>
      </div>
    </div>}
    {visible.length ? groupByPlatform(visible).map((group, groupIndex) => <section key={JSON.stringify(group.source)} className="gs-platform-group" aria-labelledby={`${prefix}-platform-${groupIndex}`}>
      <h2 className="gs-platform-heading" id={`${prefix}-platform-${groupIndex}`}><PlatformIcon source={group.source} />{platformLabel(group.source)} · {group.cards.length}건</h2>
      <div className="gs-evidence-grid">{group.cards.map((card, index) => <EvidenceCardView key={`${card.evidence_id}-${index}`} card={card} workspaceBrand={workspaceBrand} anchor={`${prefix}-card-${groupIndex}-${index}`} />)}</div>
    </section>) : <EmptyState title={cards.length ? "조건에 맞는 근거 소재가 없습니다" : "아직 근거 소재가 없습니다"} description="광고 기획에서 요청을 보내면 찾은 근거 소재가 여기에 모입니다." action={{ label: "광고 기획으로", onClick: onPlan }} />}
  </div>;
}
