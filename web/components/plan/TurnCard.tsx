"use client";
import { useContext } from "react";
import type { Turn } from "../../lib/reducer";
import type { ClaimChoice } from "../../lib/types";
import { PLAN_INTRO_TEXT } from "../../lib/text";
import { ClarifyCard } from "./ClarifyCard";
import { ResultsView, CommandTenantContext } from "../results/ResultsView";
import { OpenGraphPathContext } from "../graph/context";
import { Notice } from "../Notice";
import { ProgressTracker } from "./ProgressTracker";
import { ClarifySummary } from "./ClarifySummary";
export function TurnCard({ turn, busy, onChoice, onCancel, onRetry, choiceLabel = turn.choiceLabel }: {
  turn: Turn; busy: boolean; choiceLabel?: string | null; onChoice: (choice: ClaimChoice, label: string) => void;
  onCancel: () => void; onRetry: () => void;
}) {
  const tenantId = useContext(CommandTenantContext);
  const openGraphPath = useContext(OpenGraphPathContext);
  const displayText = turn.commands.some(command => command.kind === "show_plan")
    ? turn.displayText.split("\n").filter(line => line !== PLAN_INTRO_TEXT).join("\n")
    : turn.displayText;
  const cost = turn.commands.findLast(command => command.kind === "show_cost");
  return <article className="gs-turn" aria-label={`요청 ${turn.id}`}>
    <p className="gs-user-message">{turn.message}</p>
    <ProgressTracker stepEvents={turn.stepEvents} turnStatus={turn.status} times={{ startedAt: turn.startedAt, stepAt: turn.stepAt }} costUsd={cost?.data.text_spent_usd} costLabel={cost?.data.label} />
    {displayText && <p className="gs-answer answer">{displayText}</p>}
    <ResultsView commands={turn.commands} onOpenGraph={tenantId ? openGraphPath ?? undefined : undefined} />
    {turn.clarification && turn.status === "needs_choice" && !turn.choiceLabel
      ? <ClarifyCard clarification={turn.clarification} disabled={busy} onSubmit={onChoice} onCancel={onCancel} />
      : (turn.clarification || choiceLabel) && <ClarifySummary label={choiceLabel ?? "선택 완료"} />}
    {turn.unavailable && <Notice text={turn.unavailable.text} />}
    {turn.error && <Notice error={turn.error} onRetry={onRetry} disabled={busy} />}
    {turn.status === "stopped" && <Notice stopped />}
  </article>;
}
