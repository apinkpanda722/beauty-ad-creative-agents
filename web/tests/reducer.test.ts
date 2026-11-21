import { describe, expect, it } from "vitest";
import { initialState, reducer } from "../lib/reducer";
import type { SseFrame, UiCommand } from "../lib/types";

const command: UiCommand = { kind: "show_graph_fragment", data: { evidence_ids: ["synthetic-id"] } };
function started() {
  return reducer(reducer(initialState, { type: "workspace_selected", tenantId: "synthetic" }), {
    type: "request_started", message: "합성 요청", withImage: true,
  });
}
function receive(state: ReturnType<typeof started>, frame: SseFrame) {
  return reducer(state, { type: "stream_event", turnId: 1, frame });
}

describe("conversation reducer", () => {
  it("stores ordered stages, tools, commands and prefers display_text", () => {
    let state = started();
    const steps = [
      { agent: "supervisor", phase: "end", status: "ok" },
      { agent: "research", phase: "end", status: "ok" },
      { agent: "planning", phase: "start", status: "running" },
      { agent: "evaluation", phase: "end", status: "done" },
      { agent: "rework", phase: "end", status: "done" },
      { agent: "image", phase: "end", status: "ok" },
      { agent: "supervisor", phase: "done", status: "plan" },
    ];
    for (const data of steps) state = receive(state, { event: "step", data });
    state = receive(state, { event: "tool_start", data: { name: "synthetic-tool", kind: "lookup" } });
    state = receive(state, { event: "ui_command", data: command });
    state = receive(state, { event: "token", data: { text: "합성 원문", display_text: "합성 표시" } });
    state = reducer(state, { type: "stream_ended", turnId: 1 });
    expect(state.turns[0]).toMatchObject({ status: "done", stepEvents: steps, commands: [command], displayText: "합성 표시", tools: [{ name: "synthetic-tool", kind: "lookup" }] });
    expect(receive(started(), { event: "token", data: { text: "합성 대체" } }).turns[0].displayText).toBe("합성 대체");
    expect(receive(started(), { event: "token", data: { text: "합성 원문", display_text: "" } }).turns[0].displayText).toBe("");
  });
  it.each(["needs_clarification", "efficacy_unavailable"] as const)("suppresses duplicate token after %s", (event) => {
    const frame: SseFrame = event === "needs_clarification"
      ? { event, data: { reason: "no_efficacy_confirmed", requested_claim: null, requested_label: null, available: [], options: [], text: "합성 안내" } }
      : { event, data: { reason: "failed", text: "합성 안내" } };
    let state = receive(started(), frame);
    state = receive(state, { event: "token", data: { text: "합성 안내" } });
    state = reducer(state, { type: "stream_ended", turnId: 1 });
    expect(state.turns[0].displayText).toBe("");
    expect(state.turns[0].status).toBe(event === "needs_clarification" ? "needs_choice" : "unavailable");
  });
  it("rejects a stream ending without a terminal signal", () => {
    const state = reducer(receive(started(), { event: "step", data: { agent: "supervisor", phase: "done", status: "plan" } }), { type: "stream_ended", turnId: 1 });
    expect(state.turns[0]).toMatchObject({ status: "error", error: { code: "STREAM_ENDED_EARLY" } });
  });
  it("preserves received commands on SSE and transport errors", () => {
    const state = receive(started(), { event: "ui_command", data: command });
    expect(receive(state, { event: "error", data: { code: "AGENT_INTERNAL_ERROR", detail: "합성 상세" } }).turns[0]).toMatchObject({ status: "error", commands: [command] });
    expect(reducer(state, { type: "request_failed", turnId: 1, error: { code: "HTTP_422" } }).turns[0]).toMatchObject({ status: "error", commands: [command] });
  });
  it("clears the conversation and thread on workspace changes and ignores late events", () => {
    let state = reducer(started(), { type: "thread_received", turnId: 1, threadId: "synthetic:thread" });
    state = reducer(state, { type: "workspace_selected", tenantId: "second" });
    expect(state.turns).toEqual([]);
    expect(state.threadId).toBeNull();
    state = reducer(state, { type: "request_started", message: "두 번째 합성 요청" });
    expect(receive(state, { event: "token", data: { text: "늦은 합성 응답" } })).toEqual(state);
  });
  it("creates new turns for choices and retries retaining message, thread and image setting", () => {
    const choice = { mode: "none", claims: [], requested_claim: null } as const;
    let state = reducer(started(), { type: "thread_received", turnId: 1, threadId: "synthetic:thread" });
    state = receive(state, { event: "needs_clarification", data: { reason: "no_efficacy_confirmed", requested_claim: null, requested_label: null, available: [], options: [{ id: "none", label: "합성 선택" }], text: "합성 안내" } });
    state = reducer(state, { type: "stream_ended", turnId: 1 });
    state = reducer(state, { type: "choice_submitted", turnId: 1, choice: { ...choice, claims: [] }, label: "합성 선택" });
    expect(state.turns[1]).toMatchObject({ id: 2, message: "합성 요청", threadId: "synthetic:thread", claimChoice: choice, choiceLabel: "합성 선택", withImage: true });
    state = reducer(state, { type: "request_failed", turnId: 2, error: { code: "AGENT_INTERNAL_ERROR" } });
    state = reducer(state, { type: "stream_ended", turnId: 2 });
    state = reducer(state, { type: "retry_requested", turnId: 2 });
    expect(state.turns[2]).toMatchObject({ id: 3, message: state.turns[1].message, threadId: state.turns[1].threadId, claimChoice: choice, withImage: true });
  });
});

it("records optional arrival times aligned to step events and leaves untimed actions unchanged", () => {
  let state = reducer({ ...initialState, tenantId: "synthetic" }, { type: "request_started", message: "합성 요청", at: 100 });
  const frame: SseFrame = { event: "step", data: { agent: "supervisor", phase: "end", status: "ok" } };
  state = reducer(state, { type: "stream_event", turnId: 1, frame, at: 1700 });
  state = reducer(state, { type: "stream_event", turnId: 1, frame, at: 1800 });
  expect(state.turns[0].startedAt).toBe(100);
  expect(state.turns[0].stepAt).toEqual([1700, 1800]);
  expect(state.turns[0].stepAt).toHaveLength(state.turns[0].stepEvents.length);
  const untimed = receive(started(), frame).turns[0];
  expect(Object.hasOwn(untimed, "startedAt")).toBe(false);
  expect(Object.hasOwn(untimed, "stepAt")).toBe(false);
});

it("keeps timing arrays aligned when timed and untimed steps are mixed and never reuses retry timing", () => {
  const frame: SseFrame = { event: "step", data: { agent: "supervisor", phase: "end", status: "ok" } };
  let state = reducer({ ...initialState, tenantId: "synthetic" }, { type: "request_started", message: "합성 요청", at: 100 });
  state = reducer(state, { type: "stream_event", turnId: 1, frame, at: 1700 });
  state = reducer(state, { type: "request_failed", turnId: 1, error: { code: "SYNTHETIC" } });
  const finished = reducer(state, { type: "stream_ended", turnId: 1 });
  const retry = reducer(finished, { type: "retry_requested", turnId: 1 }).turns[1];
  expect(Object.hasOwn(retry, "startedAt")).toBe(false);
  expect(Object.hasOwn(retry, "stepAt")).toBe(false);
  state = reducer(state, { type: "stream_event", turnId: 1, frame });
  expect(Object.hasOwn(state.turns[0], "stepAt")).toBe(false);
  state = reducer(state, { type: "stream_event", turnId: 1, frame, at: 1800 });
  expect(Object.hasOwn(state.turns[0], "stepAt")).toBe(false);
});
