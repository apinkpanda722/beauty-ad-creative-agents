import type { Turn } from "./reducer";
import { deriveProgress, deriveStages } from "./stages";

export function summarizeTurn(turn: Turn) {
  const stages = deriveStages(turn.stepEvents, turn.status);
  const kind = turn.status === "error" ? "오류" : turn.status === "stopped" ? "중단"
    : turn.status === "needs_choice" || turn.clarification ? "확인 질문"
    : turn.status === "unavailable" ? "근거 없음"
    : turn.commands.some(command => command.kind === "show_plan") ? "기획안"
    : turn.status === "running" ? "진행 중" : "근거 없음";
  const lastAt = turn.stepAt?.at(-1);
  return {
    kind,
    startedAt: turn.startedAt ?? null,
    durationMs: turn.startedAt === undefined || lastAt === undefined ? null : lastAt - turn.startedAt,
    cost: turn.commands.find(command => command.kind === "show_cost")?.data ?? null,
    planningCount: stages.find(stage => stage.id === "planning")?.count ?? 0,
    evaluationCount: stages.find(stage => stage.id === "evaluation")?.count ?? 0,
    reworks: stages.find(stage => stage.id === "evaluation")?.reworks ?? 0,
    progress: deriveProgress(turn.stepEvents, turn.status, { startedAt: turn.startedAt, stepAt: turn.stepAt }),
  };
}

export function historyDuration(milliseconds: number | null) {
  return milliseconds === null ? "정보 없음" : `${(milliseconds / 1000).toFixed(1)}초`;
}

export function historyTime(startedAt: number | null) {
  // Session timestamps use performance.now(), relative to this browser's time origin.
  return startedAt === null ? null : new Date(performance.timeOrigin + startedAt).toISOString();
}
