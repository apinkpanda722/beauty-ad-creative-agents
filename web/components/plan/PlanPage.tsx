"use client";

import { useSession } from "../../lib/session";
import type { Workspace } from "../../lib/types";
import { CommandTenantContext } from "../CommandSlot";
import { FeedbackSession } from "../FeedbackBar";
import { WorkspacePicker } from "../WorkspacePicker";
import { PageHeader } from "../ui";
import { Composer } from "./Composer";
import { TurnCard } from "./TurnCard";
import "../../app/plan.css";

export function PlanPage({ workspaces, imageEnabled, onWorkspaceChange }: {
  workspaces: Workspace[]; imageEnabled: boolean; onWorkspaceChange?: (tenantId: string | null) => void;
}) {
  const { state, start, send, cancel, retry, selectWorkspace } = useSession();
  const busy = state.activeTurnId !== null;
  return <CommandTenantContext.Provider value={state.tenantId}><FeedbackSession key={state.tenantId}>
    <div className="gs-plan-page">
      <PageHeader title="광고 기획" description="제품과 원하는 광고 방향을 알려주세요. 근거를 찾아 기획안을 만듭니다." />
      <WorkspacePicker workspaces={workspaces} value={state.tenantId} onChange={tenantId => {
        if (state.tenantId === tenantId) return;
        selectWorkspace(tenantId);
        onWorkspaceChange?.(tenantId);
      }} />
      <Composer key={state.tenantId} enabled={Boolean(state.tenantId)} busy={busy} imageEnabled={imageEnabled} onSend={send} />
      <section className="gs-conversation" aria-label="대화">
        {state.turns.map((turn, index) => {
          const next = state.turns[index + 1];
          const previous = state.turns[index - 1];
          // The reducer stores the chosen values on the continuation turn.
          // Present them on the resolved question without changing session state.
          let choiceLabel = previous?.clarification ? null : turn.choiceLabel;
          if (turn.clarification && next?.claimChoice && next.choiceLabel && next.message === turn.message) {
            const selected = next.claimChoice.claims.map(claim => turn.clarification?.available.find(item => item.claim === claim)?.label ?? claim);
            choiceLabel = [next.choiceLabel, ...selected].join(" · ");
          }
          return <TurnCard key={turn.id} turn={turn} busy={busy} choiceLabel={choiceLabel}
            onChoice={(choice, label) => start({ type: "choice_submitted", turnId: turn.id, choice, label })}
            onCancel={() => cancel(turn.id)} onRetry={() => retry(turn.id)} />;
        })}
      </section>
    </div>
  </FeedbackSession></CommandTenantContext.Provider>;
}
