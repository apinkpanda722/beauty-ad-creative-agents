import type { TurnStatus } from "./reducer";
import type { StepEvent } from "./types";
export type Stage = { id: string; label: string; status: "pending" | "running" | "done" | "failed"; count: number; reworks: number };
export function deriveStages(stepEvents: StepEvent[], turnStatus: TurnStatus): Stage[] {
  const stages: Stage[] = [
    { id: "supervisor", label: "요청 해석", status: "pending", count: 0, reworks: 0 },
    { id: "research", label: "리서치", status: "pending", count: 0, reworks: 0 },
    { id: "planning", label: "기획", status: "pending", count: 0, reworks: 0 },
    { id: "evaluation", label: "평가", status: "pending", count: 0, reworks: 0 },
    ...(stepEvents.some(e => e.agent === "image") ? [{ id: "image", label: "시안", status: "pending" as const, count: 0, reworks: 0 }] : []),
    { id: "complete", label: "완료", status: "pending", count: 0, reworks: 0 },
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
