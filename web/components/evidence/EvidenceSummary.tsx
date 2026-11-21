"use client";

import { useId } from "react";
import type { UiCommand } from "../../lib/types";
import { taxonomyNames, type TaxonomyNames } from "../../lib/taxonomy";
import { EvidenceCardView } from "./EvidenceCardView";

export function EvidenceSummary({ data, names = taxonomyNames(), anchors = {}, workspaceBrand }: {
  data: Extract<UiCommand, { kind: "show_evidence_cards" }>["data"]; names?: TaxonomyNames; anchors?: Record<string, string>; workspaceBrand?: string | null;
}) {
  const prefix = useId();
  if (!data.cards.length && !data.missing) return null;
  return <section aria-label="근거 소재" className="gs-result-section gs-evidence-summary"><h3>근거 요약</h3>
    <div className="gs-evidence-grid">{data.cards.map((card, i) => <EvidenceCardView key={`${card.evidence_id}-${i}`} card={card} names={names} workspaceBrand={workspaceBrand} anchor={card.evidence_id && anchors[card.evidence_id] || `${prefix}-${i}`} />)}</div>
    {data.missing > 0 && <p className="muted">근거 소재 {data.missing}건을 불러오지 못했습니다.</p>}
  </section>;
}
