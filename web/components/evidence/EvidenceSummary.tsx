"use client";

import { useId } from "react";
import type { UiCommand } from "../../lib/types";
import { taxonomyNames, type TaxonomyNames } from "../../lib/taxonomy";
import { groupByPlatform, platformLabel } from "../../lib/evidence";
import { PlatformIcon } from "./PlatformIcon";
import { EvidenceCardView } from "./EvidenceCardView";

export function EvidenceSummary({ data, names = taxonomyNames(), anchors = {}, workspaceBrand }: {
  data: Extract<UiCommand, { kind: "show_evidence_cards" }>["data"]; names?: TaxonomyNames; anchors?: Record<string, string>; workspaceBrand?: string | null;
}) {
  const prefix = useId();
  if (!data.cards.length && !data.missing) return null;
  return <section aria-label="근거 소재" className="gs-result-section gs-evidence-summary"><h3>근거 요약</h3>
    {groupByPlatform(data.cards).map((group, groupIndex) => <section className="gs-platform-group" key={JSON.stringify(group.source)} aria-labelledby={`${prefix}-platform-${groupIndex}`}>
      <h4 className="gs-platform-heading" id={`${prefix}-platform-${groupIndex}`}><PlatformIcon source={group.source} />{platformLabel(group.source)} · {group.cards.length}건</h4>
      <div className="gs-evidence-grid">{group.cards.map((card, i) => <EvidenceCardView key={`${card.evidence_id}-${i}`} card={card} names={names} workspaceBrand={workspaceBrand} anchor={card.evidence_id && anchors[card.evidence_id] || `${prefix}-${groupIndex}-${i}`} />)}</div>
    </section>)}
    {data.missing > 0 && <p className="muted">근거 소재 {data.missing}건을 불러오지 못했습니다.</p>}
  </section>;
}
