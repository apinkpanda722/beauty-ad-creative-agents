"use client";

import { useEffect, useState } from "react";
import type { TurnStatus } from "../../lib/reducer";
import { deriveProgress, type ProgressTimes } from "../../lib/stages";
import type { StepEvent } from "../../lib/types";
import "../../app/plan.css";

const labels = { pending: "대기", running: "진행 중", done: "완료", failed: "실패" };
const monotonicClock = () => performance.now();

export function ProgressTracker({ stepEvents, turnStatus, times, costUsd, costLabel = "텍스트 모델 비용(이미지 제외)", clock = monotonicClock }: {
  stepEvents: StepEvent[]; turnStatus: TurnStatus; times?: ProgressTimes; costUsd?: number; costLabel?: string; clock?: () => number;
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
  const stages = deriveProgress(stepEvents, turnStatus, times);
  const running = stages.find(stage => stage.status === "running");
  const elapsedText = <span className={running ? "gs-progress-elapsed" : "gs-sr-only"} aria-label="경과 시간" aria-live="off">{elapsed}초 경과</span>;
  return <section className="gs-progress" aria-label="진행 단계" aria-live="polite">
    <ol className="gs-stages">
      {stages.map((stage, index) => <li key={stage.id} data-status={stage.status}>
        {index > 0 && <span className="gs-stage-connector" aria-hidden="true" data-filled={stages[index - 1].status === "done"}><span /></span>}
        <span className="gs-stage-chip">
        <span className={`gs-stage-icon${stage.status === "running" ? " gs-stage-ring" : ""}`} role="img" aria-label={labels[stage.status]}>
          {stage.status === "running" && <span className="gs-stage-running-text gs-sr-only">진행 중</span>}
        </span>
        <span className={`gs-stage-copy${stage.status === "running" ? " gs-stage-shimmer" : ""}`}>{stage.label}</span>
        {stage.status === "running" && elapsedText}
        {stage.id !== "image" && stage.durationMs !== null && <span className="gs-stage-duration">{(stage.durationMs / 1000).toFixed(1)}s</span>}
        {stage.id === "plan_eval" && stage.reworks > 0 && <span className="gs-rework-badge">재작업 {stage.reworks}회</span>}
        </span>
      </li>)}
    </ol>
    {costUsd !== undefined && <span className="gs-progress-cost" aria-label={costLabel}>${costUsd.toFixed(3)}</span>}
    {!running && elapsedText}
  </section>;
}
