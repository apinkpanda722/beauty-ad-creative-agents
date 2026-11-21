"use client";

import { useEffect, useState } from "react";
import type { TurnStatus } from "../../lib/reducer";
import { deriveStages } from "../../lib/stages";
import type { StepEvent } from "../../lib/types";
import "../../app/plan.css";

const labels = { pending: "대기", running: "진행 중", done: "완료", failed: "실패" };
const monotonicClock = () => performance.now();

export function ProgressTracker({ stepEvents, turnStatus, clock = monotonicClock }: {
  stepEvents: StepEvent[]; turnStatus: TurnStatus; clock?: () => number;
}) {
  const [startedAt] = useState(clock);
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (turnStatus !== "running") return;
    // This timer updates the elapsed number only; all motion is CSS.
    const timer = setInterval(() => setElapsed(Math.max(0, Math.floor((clock() - startedAt) / 1000))), 1000);
    return () => clearInterval(timer);
  }, [turnStatus, clock, startedAt]);

  if (turnStatus === "unavailable" || turnStatus === "stopped") return null;
  if (turnStatus === "needs_choice") return <p className="gs-progress-choice" aria-label="진행 단계" aria-live="polite">요청 해석 완료 · 선택을 기다리는 중</p>;
  const stages = deriveStages(stepEvents, turnStatus);
  return <section className="gs-progress" aria-label="진행 단계" aria-live="polite">
    <ol className="gs-stages">
      {stages.map(stage => <li key={stage.id} data-status={stage.status}>
        <span className="gs-stage-icon" aria-hidden="true" />
        <span className="gs-stage-copy">{stage.id === "complete" && stage.display === "label_only_when_done" && stage.status === "done"
          ? stage.label : `${stage.label} ${labels[stage.status]}`}</span>
      </li>)}
    </ol>
    <div className="gs-progress-details">
      <span aria-label="경과 시간" aria-live="off">{elapsed}초 경과</span>
      {stages.filter(stage => stage.count > 1).map(stage => <span key={stage.id}>{stage.label} {stage.count}회</span>)}
      {stages.filter(stage => stage.reworks > 0).map(stage => <span key={stage.id}>되돌림 {stage.reworks}회</span>)}
    </div>
  </section>;
}
