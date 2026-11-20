"use client";
import { createContext, useContext, useEffect, useId, useState } from "react";
import type { SchemaResponse, UiCommand } from "../lib/types";
import { getSchema } from "../lib/api";
import { taxonomyNames } from "../lib/taxonomy";
import { EvidenceCards } from "./EvidenceCards";
import { PlanCard } from "./PlanCard";
import { DistributionChart } from "./DistributionChart";
import { AggregatesPanel } from "./AggregatesPanel";
import { CostLine } from "./CostLine";

export const CommandTenantContext = createContext<string | null>(null);
export function CommandSlot({ commands, onOpenGraph }: { commands: UiCommand[]; onOpenGraph?: (ids: string[]) => void }) {
  const tenantId = useContext(CommandTenantContext);
  const [schema, setSchema] = useState<{ tenantId: string; data: SchemaResponse } | null>(null);
  const prefix = useId();
  const needsSchema = commands.some(command => command.kind === "show_evidence_cards" || command.kind === "show_plan" || command.kind === "show_distribution");
  useEffect(() => {
    if (!tenantId || !needsSchema) return;
    let active = true;
    void getSchema(tenantId).then(data => { if (active) setSchema({ tenantId, data }); }).catch(() => { /* Raw values remain visible without schema. */ });
    return () => { active = false; };
  }, [tenantId, needsSchema]);
  const names = taxonomyNames(schema?.tenantId === tenantId ? schema?.data : null);
  const evidence = commands.filter(command => command.kind === "show_evidence_cards");
  const anchors: Record<string, string> = {};
  evidence.forEach((command, group) => command.data.cards.forEach((card, i) => {
    if (card.evidence_id) anchors[card.evidence_id] ??= `${prefix}-evidence-${group}-${i}`;
  }));
  // Anchors are turn-local so repeated evidence in another turn cannot hijack links.
  return <>
    {evidence.map((command, i) => <EvidenceCards key={`evidence-${i}`} data={command.data} names={names} anchors={anchors} />)}
    {commands.filter(command => command.kind === "show_plan").map((command, i) => <PlanCard key={`plan-${i}-${command.data.plan_id ?? "unsaved"}`} data={command.data} names={names} tenantId={tenantId} evidenceAnchors={anchors} />)}
    {onOpenGraph && commands.filter(command => command.kind === "show_graph_fragment").map((command, i) => <button key={`graph-${i}`} type="button" onClick={() => onOpenGraph(command.data.evidence_ids)}>근거 그래프 보기</button>)}
    {commands.filter(command => command.kind === "show_distribution").map((command, i) => <DistributionChart key={`distribution-${i}`} data={command.data} names={names} />)}
    {commands.filter(command => command.kind === "show_aggregates").map((command, i) => <AggregatesPanel key={`aggregates-${i}`} data={command.data} />)}
    {commands.filter(command => command.kind === "show_cost").map((command, i) => <CostLine key={`cost-${i}`} data={command.data} />)}
  </>;
}
