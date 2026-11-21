import { expect, it } from "vitest";
import { summarizeTurn } from "../lib/history";
import { initialState, reducer, type Turn } from "../lib/reducer";
import type { UiCommand } from "../lib/types";
const base = reducer({ ...initialState, tenantId: "synthetic" }, { type: "request_started", message: "합성 요청", at: 100 }).turns[0];
it("distinguishes all five result kinds and unfinished work without inventing a plan", () => {
  const plan = { kind: "show_plan", data: {} } as UiCommand;
  const cases: [Partial<Turn>, string][] = [
    [{ status: "done", commands: [plan] }, "기획안"], [{ status: "needs_choice" }, "확인 질문"],
    [{ status: "unavailable" }, "근거 없음"], [{ status: "error", commands: [plan] }, "오류"],
    [{ status: "stopped" }, "중단"], [{ status: "running" }, "진행 중"],
    [{ status: "done", stepEvents: [{ agent: "supervisor", phase: "done", status: "no_evidence" }] }, "근거 없음"],
    [{ status: "done", commands: [] }, "근거 없음"],
  ];
  for (const [patch, kind] of cases) expect(summarizeTurn({ ...base, ...patch }).kind).toBe(kind);
});
it("uses only recorded last arrival minus start, never the current clock, and optional first cost", () => {
  expect(summarizeTurn({ ...base, stepAt: [300, 900, 700] }).durationMs).toBe(600);
  for (const turn of [{ ...base, startedAt: undefined, stepAt: [700] }, { ...base, stepAt: [] }, { ...base, stepAt: undefined }]) expect(summarizeTurn(turn).durationMs).toBeNull();
  expect(summarizeTurn(base).cost).toBeNull();
  const cost: UiCommand = { kind: "show_cost", data: { label: "합성 서버 비용", text_spent_usd: .012345, max_text_cost_usd: 1 } };
  expect(summarizeTurn({ ...base, commands: [cost, { ...cost, data: { ...cost.data, text_spent_usd: 2 } }] }).cost).toEqual(cost.data);
});
it("preserves planning/evaluation counts and reworks using existing stage derivation", () => {
  const agents = ["supervisor", "research", "planning", "evaluation", "rework", "planning", "evaluation", "image"];
  const turn = { ...base, status: "done" as const, stepEvents: agents.map(agent => ({ agent, phase: agent === "planning" ? "start" : "end", status: "ok" })), stepAt: [1100, 2100, 3100, 4100, 5100, 6100, 7100, 8100] };
  const result = summarizeTurn(turn);
  expect([result.planningCount, result.evaluationCount, result.reworks]).toEqual([2, 2, 1]);
  expect(result.progress.map(stage => [stage.id, stage.durationMs, stage.reworks])).toEqual([["supervisor", 1000, 0], ["research", 1000, 0], ["plan_eval", 5000, 1], ["image", 1000, 0]]);
});
