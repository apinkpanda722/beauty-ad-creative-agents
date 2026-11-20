import type { TurnStatus } from "../lib/reducer";
import type { StepEvent } from "../lib/types";
import { deriveStages } from "../lib/stages";
const labels = { pending: "대기", running: "진행 중", done: "완료", failed: "실패" };
export function StepBar({ stepEvents, turnStatus }: { stepEvents: StepEvent[]; turnStatus: TurnStatus }) {
  return <ol className="step-bar" aria-label="진행 단계" aria-live="polite">
    {deriveStages(stepEvents, turnStatus).map(stage => <li key={stage.id} data-status={stage.status}>
      <span>{stage.label}</span> <small>{labels[stage.status]}</small>
      {stage.count > 1 && <small> {stage.count}회</small>}
      {stage.reworks > 0 && <small className="badge">되돌림 {stage.reworks}회</small>}
    </li>)}
  </ol>;
}
