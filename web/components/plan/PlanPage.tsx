"use client";

import { useSession } from "../../lib/session";
import type { Workspace } from "../../lib/types";
import { CommandTenantContext, WorkspaceBrandContext } from "../results/ResultsView";
import { FeedbackSession } from "../results/FeedbackBar";
import { PageHeader } from "../ui";
import { Composer } from "./Composer";
import { TurnCard } from "./TurnCard";
import { PlanTabs } from "./PlanTabs";
import "../../app/plan.css";

export function PlanPage({ workspaces, imageEnabled }: {
  workspaces: Workspace[]; imageEnabled: boolean;
}) {
  const { state, start, send, cancel, retry } = useSession();
  const busy = state.activeTurnId !== null;
  const turns = state.turns.filter(turn => (turn.tabId ?? 1) === (state.activeTabId ?? 1));
  return <CommandTenantContext.Provider value={state.tenantId}><WorkspaceBrandContext.Provider value={workspaces.find(workspace => workspace.tenant_id === state.tenantId)?.brand ?? null}><FeedbackSession key={state.tenantId}>
    <div className="gs-plan-page">
      <PageHeader title="광고 기획" description="제품과 원하는 광고 방향을 알려주세요. 근거를 찾아 기획안을 만듭니다." />
      <PlanTabs />
      <Composer key={`${state.tenantId}-${state.activeTabId ?? 1}`} enabled={Boolean(state.tenantId)} busy={busy} imageEnabled={imageEnabled} onSend={send} />
      <section className="gs-conversation" aria-label="대화">
        {turns.map((turn, index) => {
          const next = turns[index + 1];
          const previous = turns[index - 1];
          // The reducer stores the chosen values on the continuation turn.
          // Present them on the resolved question without changing session state.
          let choiceLabel = previous?.clarification ? null : turn.choiceLabel;
          if (turn.clarification && next?.claimChoice && next.choiceLabel && next.message === turn.message) {
            const selected = next.claimChoice.claims.map(claim => turn.clarification?.available.find(item => item.claim === claim)?.label ?? claim);
            choiceLabel = [next.choiceLabel, ...selected].join(" · ");
          }
          const hideProgress = Boolean(turn.clarification && next?.claimChoice && next.message === turn.message);
          const hideMessage = Boolean(turn.claimChoice && previous?.clarification && previous.message === turn.message);
          return <TurnCard key={turn.id} turn={turn} busy={busy} choiceLabel={choiceLabel} hideProgress={hideProgress} hideMessage={hideMessage}
            onChoice={(choice, label) => start({ type: "choice_submitted", turnId: turn.id, choice, label })}
            onCancel={() => cancel(turn.id)} onRetry={() => retry(turn.id)} />;
        })}
      </section>
    </div>
  </FeedbackSession></WorkspaceBrandContext.Provider></CommandTenantContext.Provider>;
}
