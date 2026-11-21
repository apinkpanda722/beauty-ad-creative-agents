import { expect, it } from "vitest";
import { deriveStages } from "../lib/stages";
const step = (agent: string, phase: string, status: string) => ({ agent, phase, status });
it("starts request interpretation and advances stages lacking start events", () => {
  expect(deriveStages([], "running")[0]).toMatchObject({ id: "supervisor", status: "running" });
  expect(deriveStages([step("supervisor", "end", "ok")], "running")[1]).toMatchObject({ id: "research", status: "running" });
  expect(deriveStages([step("supervisor", "end", "ok"), step("research", "end", "ok")], "running")[2]).toMatchObject({ id: "planning", status: "running" });
  expect(deriveStages([], "running").some(s => s.id === "image")).toBe(false);
});
it("counts three plans, evaluations, six reworks and three images in server order", () => {
  const events = [step("supervisor", "end", "ok"), step("research", "end", "ok"), ...Array.from({ length: 3 }, () => [step("planning", "start", "running"), step("evaluation", "end", "done"), step("rework", "end", "done"), step("rework", "end", "done"), step("image", "end", "ok")]).flat(), step("supervisor", "done", "plan")];
  const stages = deriveStages(events, "done");
  expect(stages.map(s => s.status)).toEqual(["done", "done", "done", "done", "done", "done"]);
  expect(stages.find(s => s.id === "planning")?.count).toBe(3);
  expect(stages.find(s => s.id === "evaluation")).toMatchObject({ count: 3, reworks: 6 });
  expect(stages.find(s => s.id === "image")?.count).toBe(3);
});
it("retains failures and does not invent completed stages on terminal interruptions", () => {
  const stages = deriveStages([step("supervisor", "end", "ok"), step("research", "end", "failed")], "error");
  expect(stages[1].status).toBe("failed");
  expect(stages[2].status).toBe("pending");
  expect(deriveStages([step("image", "end", "failed"), step("supervisor", "done", "plan")], "done").find(s => s.id === "image")?.status).toBe("failed");
});
it("keeps planning in progress until its evaluation result and reopens it for later plans", () => {
  const events = [step("supervisor", "end", "ok"), step("research", "end", "ok"), step("planning", "start", "running")];
  expect(deriveStages(events, "running").find(s => s.id === "planning")).toMatchObject({ status: "running", count: 1 });
  expect(deriveStages(events, "error").find(s => s.id === "planning")?.status).toBe("failed");
  events.push(step("evaluation", "end", "done"));
  expect(deriveStages(events, "running").find(s => s.id === "planning")?.status).toBe("done");
  events.push(step("planning", "start", "running"));
  expect(deriveStages(events, "running").find(s => s.id === "planning")).toMatchObject({ status: "running", count: 2 });
});

it("adds only the terminal display rule without changing its stage data", () => {
  const terminal = deriveStages([step("supervisor", "done", "plan")], "done").at(-1);
  expect(terminal).toEqual({ id: "complete", label: "완료", status: "done", count: 1, reworks: 0, display: "label_only_when_done" });
  expect(deriveStages([], "running").slice(0, -1).map(stage => stage.display)).toEqual([
    "label_and_status", "label_and_status", "label_and_status", "label_and_status",
  ]);
});
