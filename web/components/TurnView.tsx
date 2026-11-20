"use client";
import { useContext, useState } from "react";
import type { Turn } from "../lib/reducer";
import type { ClaimChoice } from "../lib/types";
import { PLAN_INTRO_TEXT } from "../lib/text";
import { ClarifyCard } from "./ClarifyCard";
import { CommandSlot, CommandTenantContext } from "./CommandSlot";
import { GraphPanel } from "./GraphPanel";
import { Notice } from "./Notice";
import { StepBar } from "./StepBar";
export function TurnView({ turn, busy, onChoice, onCancel, onRetry }: {
  turn: Turn; busy: boolean; onChoice: (choice: ClaimChoice, label: string) => void;
  onCancel: () => void; onRetry: () => void;
}) {
  const tenantId = useContext(CommandTenantContext);
  const [graphIds, setGraphIds] = useState<string[] | null>(null);
  const displayText = turn.commands.some(command => command.kind === "show_plan")
    ? turn.displayText.split("\n").filter(line => line !== PLAN_INTRO_TEXT).join("\n")
    : turn.displayText;
  return <article className="turn" aria-label={`요청 ${turn.id}`}>
    <p className="user-message">{turn.message}</p>
    {turn.choiceLabel && <p className="muted">선택: {turn.choiceLabel}</p>}
    <StepBar stepEvents={turn.stepEvents} turnStatus={turn.status} />
    {displayText && <p className="answer">{displayText}</p>}
    <CommandSlot commands={turn.commands} onOpenGraph={tenantId ? setGraphIds : undefined} />
    {tenantId && graphIds && <GraphPanel tenantId={tenantId} ids={graphIds} />}
    {turn.clarification && <ClarifyCard clarification={turn.clarification} disabled={busy || turn.status !== "needs_choice"}
      onSubmit={onChoice} onCancel={onCancel} />}
    {turn.unavailable && <Notice text={turn.unavailable.text} />}
    {turn.error && <Notice error={turn.error} onRetry={onRetry} disabled={busy} />}
    {turn.status === "stopped" && <Notice stopped />}
  </article>;
}
