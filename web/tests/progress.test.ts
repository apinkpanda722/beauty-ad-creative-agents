import { expect, it } from "vitest";
import { deriveProgress } from "../lib/stages";
import type { StepEvent } from "../lib/types";
const step = (agent: string, phase = "end", status = "ok"): StepEvent => ({ agent, phase, status });
const events = [step("supervisor"), step("research"), step("planning", "start", "running"), step("evaluation"), step("rework"), step("planning", "start", "running"), step("evaluation"), step("image"), step("supervisor", "done", "plan")];
it("combines planning and evaluation and only includes images with events", () => {
  expect(deriveProgress([], "running").map(p => [p.id, p.label])).toEqual([["supervisor", "요청 해석"], ["research", "리서치"], ["plan_eval", "기획·평가"]]);
  expect(deriveProgress(events, "done").map(p => [p.id, p.status, p.reworks])).toEqual([["supervisor", "done", 0], ["research", "done", 0], ["plan_eval", "done", 1], ["image", "done", 0]]);
});
it("retains failures, planning start semantics and terminal interruptions", () => {
  expect(deriveProgress(events.slice(0, 3), "running")[2].status).toBe("running");
  expect(deriveProgress(events.slice(0, 4), "running")[2].status).toBe("done");
  expect(deriveProgress(events.slice(0, 3), "error")[2].status).toBe("failed");
  expect(deriveProgress(events.slice(0, 3), "done")[2].status).toBe("pending");
  for (const agent of ["planning", "evaluation", "rework"]) expect(deriveProgress([step(agent, "end", "failed"), ...events], "done")[2].status).toBe("failed");
  expect(deriveProgress([...events, step("rework")], "done")[2].reworks).toBe(2);
});
it("uses first supervisor, research, final evaluation/rework and image arrival times", () => {
  const times = { startedAt: 100, stepAt: [1700, 9600, 9700, 20000, 21000, 22000, 31700, 35800, 35900] };
  expect(deriveProgress(events, "done", times).map(p => p.durationMs)).toEqual([1600, 7900, 22100, 4100]);
  expect(deriveProgress(events, "done").map(p => p.durationMs)).toEqual([null, null, null, null]);
  expect(deriveProgress(events, "done", { stepAt: times.stepAt }).map(p => p.durationMs)).toEqual([null, 7900, 22100, 4100]);
  expect(deriveProgress(events, "done", { startedAt: 100, stepAt: [1700] }).map(p => p.durationMs)).toEqual([1600, null, null, null]);
});
