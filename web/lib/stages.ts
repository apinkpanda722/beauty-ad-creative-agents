import type { TurnStatus } from "./reducer";
import type { StepEvent } from "./types";
export type Stage = { id: string; label: string; status: "pending" | "running" | "done" | "failed"; count: number; reworks: number; display: "label_and_status" | "label_only_when_done" };
export function deriveStages(stepEvents: StepEvent[], turnStatus: TurnStatus): Stage[] {
  const stages: Stage[] = [
    { id: "supervisor", label: "요청 해석", status: "pending", count: 0, reworks: 0, display: "label_and_status" },
    { id: "research", label: "리서치", status: "pending", count: 0, reworks: 0, display: "label_and_status" },
    { id: "planning", label: "기획", status: "pending", count: 0, reworks: 0, display: "label_and_status" },
    { id: "evaluation", label: "평가", status: "pending", count: 0, reworks: 0, display: "label_and_status" },
    ...(stepEvents.some(e => e.agent === "image") ? [{ id: "image", label: "시안", status: "pending" as const, count: 0, reworks: 0, display: "label_and_status" as const }] : []),
    { id: "complete", label: "완료", status: "pending", count: 0, reworks: 0, display: "label_only_when_done" },
  ];
  let active = "supervisor";
  function finish(id: string, failed: boolean) {
    const stage = stages.find(s => s.id === id)!;
    stage.count += 1;
    stage.status = failed || stage.status === "failed" ? "failed" : "done";
  }
  for (const e of stepEvents) {
    const failed = e.status === "failed";
    if (e.agent === "supervisor" && e.phase === "done") { finish("complete", failed); active = ""; }
    else if (e.agent === "supervisor") { finish("supervisor", failed); active = failed ? "" : "research"; }
    else if (e.agent === "research") { finish("research", failed); active = failed ? "" : "planning"; }
    else if (e.agent === "planning") {
      const planning = stages.find(s => s.id === "planning")!;
      planning.count += 1;
      planning.status = failed || planning.status === "failed" ? "failed" : "running";
      active = failed ? "" : "planning";
    } else if (e.agent === "evaluation") {
      const planning = stages.find(s => s.id === "planning")!;
      if (planning.count && planning.status !== "failed") planning.status = "done";
      finish("evaluation", failed); active = "";
    }
    else if (e.agent === "rework") {
      stages.find(s => s.id === "evaluation")!.reworks += 1;
      if (failed) stages.find(s => s.id === "evaluation")!.status = "failed";
    } else if (e.agent === "image") { finish("image", failed); active = ""; }
  }
  // Planning has only a start event; evaluation's result closes that work.
  // Do not infer a successful model output from planning's start alone.
  if (turnStatus === "running" && active) {
    const stage = stages.find(s => s.id === active);
    if (stage && stage.status !== "failed") stage.status = "running";
  }
  if (turnStatus !== "running") {
    for (const stage of stages) {
      if (stage.status === "running") stage.status = turnStatus === "error" ? "failed" : "pending";
    }
  }
  return stages;
}

export type Progress = {
  id: "supervisor" | "research" | "plan_eval" | "image";
  label: string;
  status: Stage["status"];
  reworks: number;
  durationMs: number | null;
};
export type ProgressTimes = { startedAt?: number; stepAt?: number[] };

export function deriveProgress(stepEvents: StepEvent[], turnStatus: TurnStatus, times?: ProgressTimes): Progress[] {
  const stages = deriveStages(stepEvents, turnStatus);
  const planning = stages.find(stage => stage.id === "planning")!;
  const evaluation = stages.find(stage => stage.id === "evaluation")!;
  const first = (agent: string) => stepEvents.findIndex(event => event.agent === agent && event.phase !== "start" && event.phase !== "done");
  const supervisorAt = times?.stepAt?.[first("supervisor")];
  const researchAt = times?.stepAt?.[first("research")];
  const finalEvaluation = stepEvents.findLastIndex(event => event.agent === "evaluation" || event.agent === "rework");
  const evaluationAt = times?.stepAt?.[finalEvaluation];
  const imageAt = times?.stepAt?.[stepEvents.findLastIndex(event => event.agent === "image")];
  const duration = (from?: number, to?: number) => from === undefined || to === undefined ? null : Math.max(0, to - from);
  const combined = planning.status === "failed" || evaluation.status === "failed" ? "failed"
    : planning.status === "running" ? "running" : evaluation.status === "done" ? "done" : planning.status;
  return [
    { id: "supervisor", label: "요청 해석", status: stages[0].status, reworks: 0, durationMs: duration(times?.startedAt, supervisorAt) },
    { id: "research", label: "리서치", status: stages[1].status, reworks: 0, durationMs: duration(supervisorAt, researchAt) },
    { id: "plan_eval", label: "기획·평가", status: combined, reworks: stepEvents.filter(event => event.agent === "rework").length, durationMs: duration(researchAt, evaluationAt) },
    ...stages.filter(stage => stage.id === "image").map(stage => ({ id: "image" as const, label: "시안", status: stage.status, reworks: 0, durationMs: duration(evaluationAt, imageAt) })),
  ];
}
