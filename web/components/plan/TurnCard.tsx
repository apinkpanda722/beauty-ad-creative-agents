"use client";
import { useContext, useState } from "react";
import type { Turn } from "../../lib/reducer";
import type { ClaimChoice } from "../../lib/types";
import { PLAN_INTRO_TEXT } from "../../lib/text";
import { ClarifyCard } from "./ClarifyCard";
import { CommandSlot, CommandTenantContext } from "../CommandSlot";
import { GraphPanel } from "../GraphPanel";
import { Notice } from "../Notice";
import { ProgressTracker } from "./ProgressTracker";
import { ClarifySummary } from "./ClarifySummary";
export function TurnCard({ turn, busy, onChoice, onCancel, onRetry, choiceLabel = turn.choiceLabel }: {
  turn: Turn; busy: boolean; choiceLabel?: string | null; onChoice: (choice: ClaimChoice, label: string) => void;
  onCancel: () => void; onRetry: () => void;
}) {
  const tenantId = useContext(CommandTenantContext);
  const [graphIds, setGraphIds] = useState<string[] | null>(null);
  const displayText = turn.commands.some(command => command.kind === "show_plan")
    ? turn.displayText.split("\n").filter(line => line !== PLAN_INTRO_TEXT).join("\n")
    : turn.displayText;
  return <article className="gs-turn" aria-label={`요청 ${turn.id}`}>
    <p className="gs-user-message">{turn.message}</p>
    <ProgressTracker stepEvents={turn.stepEvents} turnStatus={turn.status} />
    {displayText && <p className="gs-answer answer">{displayText}</p>}
    <CommandSlot commands={turn.commands} onOpenGraph={tenantId ? setGraphIds : undefined} />
    {tenantId && graphIds && <GraphPanel tenantId={tenantId} ids={graphIds} />}
    {turn.clarification && turn.status === "needs_choice" && !turn.choiceLabel
      ? <ClarifyCard clarification={turn.clarification} disabled={busy} onSubmit={onChoice} onCancel={onCancel} />
      : (turn.clarification || choiceLabel) && <ClarifySummary label={choiceLabel ?? "선택 완료"} />}
    {turn.unavailable && <Notice text={turn.unavailable.text} />}
    {turn.error && <Notice error={turn.error} onRetry={onRetry} disabled={busy} />}
    {turn.status === "stopped" && <Notice stopped />}
  </article>;
}
