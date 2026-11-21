"use client";
import { createContext, useContext, useEffect, useId, useState } from "react";
import type { SchemaResponse, UiCommand } from "../../lib/types";
import { getSchema } from "../../lib/api";
import { taxonomyNames } from "../../lib/taxonomy";
import { dedupeCards } from "../../lib/evidence";
import { EvidenceSummary } from "../evidence/EvidenceSummary";
import { PlanResult } from "./PlanResult";
import { DistributionChart } from "./DistributionChart";
import { AggregatesPanel } from "./AggregatesPanel";
import { Button } from "../ui";
import "../../app/results.css";

export const CommandTenantContext = createContext<string | null>(null);
export const WorkspaceBrandContext = createContext<string | null>(null);
export function ResultsView({ commands, onOpenGraph }: { commands: UiCommand[]; onOpenGraph?: (ids: string[]) => void }) {
  const tenantId = useContext(CommandTenantContext);
  const workspaceBrand = useContext(WorkspaceBrandContext);
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
  const cards = dedupeCards(evidence.flatMap(command => command.data.cards));
  const anchors: Record<string, string> = Object.fromEntries(cards.flatMap((card, i) => card.evidence_id ? [[card.evidence_id, `${prefix}-evidence-${i}`]] : []));
  // Anchors are turn-local so repeated evidence in another turn cannot hijack links.
  return <>

    {commands.filter(command => command.kind === "show_plan").map((command, i) => <PlanResult key={`plan-${i}-${command.data.plan_id ?? "unsaved"}`} data={command.data} names={names} tenantId={tenantId} evidenceAnchors={anchors} />)}
    <EvidenceSummary data={{ cards, missing: evidence.reduce((total, command) => total + command.data.missing, 0) }} names={names} anchors={anchors} workspaceBrand={workspaceBrand} />
    {onOpenGraph && commands.filter(command => command.kind === "show_graph_fragment").map((command, i) => <Button variant="secondary" key={`graph-${i}`} onClick={() => onOpenGraph(command.data.evidence_ids)}>근거 그래프 보기</Button>)}
    {commands.filter(command => command.kind === "show_distribution").map((command, i) => <DistributionChart key={`distribution-${i}`} data={command.data} names={names} />)}
    {commands.filter(command => command.kind === "show_aggregates").map((command, i) => <AggregatesPanel key={`aggregates-${i}`} data={command.data} />)}
  </>;
}
