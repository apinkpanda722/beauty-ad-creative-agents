"use client";

import { useId, useState } from "react";
import { collectSessionCards, groupByPlatform, isOwnBrand, platformLabel } from "../../lib/evidence";
import type { UiCommand } from "../../lib/types";
import { Button, EmptyState, PageHeader } from "../ui";
import { EvidenceCardView } from "./EvidenceCardView";

export function EvidencePage({ turns, workspaceBrand, onPlan }: {
  turns: readonly { commands: readonly UiCommand[] }[]; workspaceBrand: string | null; onPlan: () => void;
}) {
  const prefix = useId();
  const [filter, setFilter] = useState<{ type: "all" | "own" } | { type: "platform"; source: string | null }>({ type: "all" });
  const cards = collectSessionCards(turns);
  const platforms = groupByPlatform(cards);
  const visible = cards.filter(card => filter.type === "own" ? isOwnBrand(card.brand, workspaceBrand) : filter.type === "platform" ? card.source === filter.source : true);
  return <div className="gs-evidence-page">
    <PageHeader title="근거 소재" description="이번 세션에서 찾은 소재를 플랫폼별로 살펴보세요." />
    {cards.length > 0 && <div className="gs-evidence-filters" role="group" aria-label="근거 소재 필터">
      <Button variant="secondary" size="sm" aria-pressed={filter.type === "all"} onClick={() => setFilter({ type: "all" })}>전체</Button>
      {platforms.map(group => <Button key={JSON.stringify(group.source)} variant="secondary" size="sm" aria-pressed={filter.type === "platform" && filter.source === group.source} onClick={() => setFilter({ type: "platform", source: group.source })}>{platformLabel(group.source)}</Button>)}
      <Button variant="secondary" size="sm" aria-pressed={filter.type === "own"} onClick={() => setFilter({ type: "own" })}>자사만</Button>
    </div>}
    {visible.length ? groupByPlatform(visible).map((group, groupIndex) => <section key={JSON.stringify(group.source)} className="gs-platform-group" aria-labelledby={`${prefix}-platform-${groupIndex}`}>
      <h2 id={`${prefix}-platform-${groupIndex}`}>{platformLabel(group.source)} · {group.cards.length}건</h2>
      <div className="gs-evidence-grid">{group.cards.map((card, index) => <EvidenceCardView key={`${card.evidence_id}-${index}`} card={card} workspaceBrand={workspaceBrand} anchor={`${prefix}-card-${groupIndex}-${index}`} />)}</div>
    </section>) : <EmptyState title={cards.length ? "조건에 맞는 근거 소재가 없습니다" : "아직 근거 소재가 없습니다"} description="광고 기획에서 요청을 보내면 찾은 근거 소재가 여기에 모입니다." action={{ label: "광고 기획으로", onClick: onPlan }} />}
  </div>;
}
