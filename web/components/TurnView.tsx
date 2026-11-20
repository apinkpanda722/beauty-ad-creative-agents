import type { Turn } from "../lib/reducer";
import type { ClaimChoice } from "../lib/types";
import { ClarifyCard } from "./ClarifyCard";
import { CommandSlot } from "./CommandSlot";
import { Notice } from "./Notice";
import { StepBar } from "./StepBar";
export function TurnView({ turn, busy, onChoice, onCancel, onRetry }: {
  turn: Turn; busy: boolean; onChoice: (choice: ClaimChoice, label: string) => void;
  onCancel: () => void; onRetry: () => void;
}) {
  return <article className="turn" aria-label={`요청 ${turn.id}`}>
    <p className="user-message">{turn.message}</p>
    {turn.choiceLabel && <p className="muted">선택: {turn.choiceLabel}</p>}
    <StepBar stepEvents={turn.stepEvents} turnStatus={turn.status} />
    <CommandSlot commands={turn.commands} />
    {turn.displayText && <p className="answer">{turn.displayText}</p>}
    {turn.clarification && <ClarifyCard clarification={turn.clarification} disabled={busy || turn.status !== "needs_choice"}
      onSubmit={onChoice} onCancel={onCancel} />}
    {turn.unavailable && <Notice text={turn.unavailable.text} />}
    {turn.error && <Notice error={turn.error} onRetry={onRetry} disabled={busy} />}
    {turn.status === "stopped" && <Notice stopped />}
  </article>;
}
