import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { ProgressTracker } from "../components/plan/ProgressTracker";
import { TurnCard } from "../components/plan/TurnCard";
import { initialState, reducer } from "../lib/reducer";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { PlanPage } from "../components/plan/PlanPage";
import { ClarifyCard } from "../components/plan/ClarifyCard";
import { getWorkspaces } from "../lib/api";
import type { Clarification, SseFrame, WorkspacesResponse } from "../lib/types";
import Page from "../app/page";
import { WorkspaceChip } from "../components/shell/WorkspaceChip";
import { SessionProvider, useSession } from "../lib/session";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers(); });
const workspaces: WorkspacesResponse = {
  workspaces: [
    { tenant_id: "test-isntree", display_name: "합성 공간 A", brand: "합성 브랜드 A", product_name: "합성 제품 A" },
    { tenant_id: "synthetic-second", display_name: "합성 공간 B", brand: "합성 브랜드 B", product_name: "합성 제품 B" },
  ], image_enabled: false,
};
const clarification: Clarification = {
  reason: "requested_not_confirmed", requested_claim: "soothing", requested_label: "합성 요청 효능", text: "합성 서버 질문 그대로",
  available: [{ claim: "hydration", label: "합성 효능 A" }, { claim: "barrier", label: "합성 효능 B" }],
  options: [{ id: "select_confirmed", label: "합성 하나 선택" }, { id: "select_many", label: "합성 여럿 선택" }, { id: "none", label: "합성 생략" }, { id: "keep_requested", label: "합성 유지" }, { id: "cancel", label: "합성 중단" }],
};
function response(frames: SseFrame[], thread = "synthetic:thread") {
  const bytes = new TextEncoder().encode(frames.map(f => `event: ${f.event}\ndata: ${JSON.stringify(f.data)}\n\n`).join(""));
  return new Response(new ReadableStream({ start(c) { c.enqueue(bytes); c.close(); } }), { headers: { "X-Thread-Id": thread } });
}
function PlanHarness({ imageEnabled }: { imageEnabled: boolean }) {
  const { state, selectWorkspace } = useSession();
  return <><WorkspaceChip workspaces={workspaces.workspaces} value={state.tenantId} onChange={selectWorkspace} /><PlanPage workspaces={workspaces.workspaces} imageEnabled={imageEnabled} /></>;
}
function setup(frames: SseFrame[], imageEnabled = false) {
  const fetch = vi.fn().mockImplementation(() => Promise.resolve(response(frames)));
  vi.stubGlobal("fetch", fetch);
  render(<PlanHarness imageEnabled={imageEnabled} />, { wrapper: SessionProvider });
  return fetch;
}
function selectWorkspace(value = "test-isntree") {
  fireEvent.click(screen.getByRole("button", { name: "작업 공간" }));
  fireEvent.click(screen.getByRole("option", { name: value === "test-isntree" ? /합성 공간 A/ : /합성 공간 B/ }));
}
function send() {
  fireEvent.change(screen.getByLabelText("요청"), { target: { value: "합성 사용자 요청" } });
  fireEvent.click(screen.getByRole("button", { name: "기획하기" }));
}
async function ready() { await waitFor(() => expect((screen.getByLabelText("요청") as HTMLTextAreaElement).disabled).toBe(false)); }
function body(fetch: ReturnType<typeof vi.fn>, index: number) { return JSON.parse(fetch.mock.calls[index][1].body); }

it("loads workspace metadata with no headers and renders API failure", async () => {
  const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify(workspaces))));
  vi.stubGlobal("fetch", fetch);
  expect(await getWorkspaces()).toEqual(workspaces);
  expect(fetch).toHaveBeenCalledExactlyOnceWith("/api/workspaces");
  render(<Page />);
  fireEvent.click(screen.getByRole("button", { name: "작업 공간" }));
  expect(await screen.findByRole("option", { name: /합성 공간 A.*합성 제품 A/ })).toBeTruthy();
  cleanup();
  fetch.mockRejectedValue(new TypeError("synthetic"));
  render(<Page />);
  expect(await screen.findByText("API 서버에 연결하지 못했습니다. 서버가 실행 중인지 확인하세요.")).toBeTruthy();
});
it("enables input only after workspace selection and has no preset request buttons", () => {
  const fetch = setup([]);
  expect((screen.getByLabelText("요청") as HTMLTextAreaElement).disabled).toBe(true);
  selectWorkspace();
  expect((screen.getByLabelText("요청") as HTMLTextAreaElement).disabled).toBe(false);
  expect(screen.queryByLabelText("예시 요청")).toBeNull();
  expect(existsSync(join(process.cwd(), "lib/examples.ts"))).toBe(false);
  expect((screen.getByLabelText("요청") as HTMLTextAreaElement).value).toBe("");
  expect(screen.getAllByRole("button").map(button => button.textContent)).toEqual(["합성 공간 A · 합성 제품 A", "기획하기"]);
  expect(fetch).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "작업 공간" }));
  expect(screen.getByText("작업 공간은 서버를 시작할 때 정한 그룹 하나만 보입니다. 바꾸려면 서버를 다시 시작하세요.")).toBeTruthy();
});
it("renders server labels verbatim, limits chips to available values and requires at least one selection", () => {
  const submit = vi.fn();
  render(<ClarifyCard clarification={clarification} onSubmit={submit} onCancel={vi.fn()} />);
  expect(screen.getByText(clarification.text)).toBeTruthy();
  for (const option of clarification.options) expect(screen.getByRole("button", { name: option.label })).toBeTruthy();
  expect(screen.queryByRole("checkbox")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "합성 여럿 선택" }));
  expect(screen.getAllByRole("checkbox").map(c => c.getAttribute("aria-label"))).toEqual(clarification.available.map(a => a.label));
  expect((screen.getByRole("button", { name: "선택 제출" }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByLabelText("합성 효능 A"));
  expect((screen.getByRole("button", { name: "선택 제출" }) as HTMLButtonElement).disabled).toBe(false);
  fireEvent.click(screen.getByLabelText("합성 효능 B"));
  fireEvent.click(screen.getByRole("button", { name: "선택 제출" }));
  expect(submit).toHaveBeenCalledExactlyOnceWith({ mode: "selected", claims: ["hydration", "barrier"], requested_claim: "soothing" }, "합성 여럿 선택");
});
it("closes the actual conversation choice without a new request or duplicate token", async () => {
  const fetch = setup([{ event: "needs_clarification", data: clarification }, { event: "token", data: { text: clarification.text } }]);
  selectWorkspace(); send(); await ready();
  expect(screen.getAllByText(clarification.text)).toHaveLength(1);
  fetch.mockClear();
  fireEvent.click(screen.getByRole("button", { name: "합성 중단" }));
  expect(fetch).not.toHaveBeenCalled();
  expect(screen.queryByRole("button", { name: "합성 중단" })).toBeNull();
  expect(screen.getByText("중단했습니다. 새 요청을 입력하세요.")).toBeTruthy();
});
it.each(["select_confirmed", "select_one", "select_many", "none", "keep_requested"] as const)("posts exact choice body for %s with the same message and thread", async optionId => {
  const option = { id: optionId, label: "합성 분기 선택" };
  const question = { ...clarification, options: [option] };
  const fetch = setup([{ event: "needs_clarification", data: question }, { event: "token", data: { text: question.text } }]);
  selectWorkspace(); send(); await ready();
  fetch.mockResolvedValue(response([{ event: "token", data: { text: "합성 완료" } }]));
  fireEvent.click(screen.getByRole("button", { name: option.label }));
  if (optionId.startsWith("select")) {
    fireEvent.click(screen.getByLabelText("합성 효능 A"));
    fireEvent.click(screen.getByRole("button", { name: "선택 제출" }));
  }
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  expect(fetch.mock.calls[1][0]).toBe("/api/ask");
  expect(body(fetch, 1)).toEqual({ message: "합성 사용자 요청", thread_id: "synthetic:thread", claim_choice: { mode: optionId.startsWith("select") ? "selected" : optionId, claims: optionId.startsWith("select") ? ["hydration"] : [], requested_claim: "soothing" } });
  expect(screen.getByText(optionId.startsWith("select") ? "효능 선택 · 합성 분기 선택 · 합성 효능 A" : "효능 선택 · 합성 분기 선택")).toBeTruthy();
  expect(within(screen.getByRole("article", { name: "요청 1" })).queryByRole("button")).toBeNull();
  await ready();
});
it("shows an unavailable notice without choices and allows new input", async () => {
  setup([{ event: "efficacy_unavailable", data: { reason: "failed", text: "합성 서버 효능 안내" } }, { event: "token", data: { text: "합성 서버 효능 안내" } }]);
  selectWorkspace(); send(); await ready();
  expect(screen.getAllByText("합성 서버 효능 안내")).toHaveLength(1);
  expect(screen.queryByRole("button", { name: "선택 제출" })).toBeNull();
  expect(screen.queryByRole("button", { name: "다시 시도" })).toBeNull();
});
it("shows error codes, server details and retries the same body including choice", async () => {
  const fetch = setup([{ event: "needs_clarification", data: clarification }]);
  selectWorkspace(); send(); await ready();
  fetch.mockResolvedValue(response([{ event: "error", data: { code: "AGENT_INTERNAL_ERROR", detail: "합성 서버 오류", error_code: "SYNTHETIC_LIMIT" } }]));
  fireEvent.click(screen.getByRole("button", { name: "합성 생략" }));
  await ready();
  expect(screen.getByText(/AGENT_INTERNAL_ERROR/)).toBeTruthy();
  expect(screen.getByText("합성 서버 오류")).toBeTruthy();
  expect(screen.getByText("SYNTHETIC_LIMIT")).toBeTruthy();
  fetch.mockResolvedValue(response([{ event: "token", data: { text: "합성 재시도 완료" } }]));
  fireEvent.click(screen.getByRole("button", { name: "다시 시도" }));
  await ready();
  expect(body(fetch, 2)).toEqual(body(fetch, 1));
});
it("reports an early stream end and HTTP validation errors", async () => {
  const fetch = setup([]); selectWorkspace(); send(); await ready();
  expect(screen.getByText(/STREAM_ENDED_EARLY/)).toBeTruthy();
  expect(screen.getByText(/응답이 중간에 끊겼습니다/)).toBeTruthy();
  fetch.mockResolvedValue(new Response('{"detail":[{"type":"missing"}]}', { status: 422 }));
  fireEvent.click(screen.getByRole("button", { name: "다시 시도" })); await ready();
  expect(screen.getByText(/HTTP_422/)).toBeTruthy();
});
it("handles IME, Shift+Enter, a 2000 character cap and disabled running input", async () => {
  const fetch = setup([{ event: "token", data: { text: "합성 완료" } }]); selectWorkspace();
  const input = screen.getByLabelText("요청") as HTMLTextAreaElement;
  fireEvent.change(input, { target: { value: "가".repeat(2001) } });
  expect(input.maxLength).toBe(2000); expect(input.value).toHaveLength(2000);
  fireEvent.keyDown(input, { key: "Enter", shiftKey: true }); expect(fetch).not.toHaveBeenCalled();
  fireEvent.compositionStart(input);
  fireEvent.keyDown(input, { key: "Enter", isComposing: true }); expect(fetch).not.toHaveBeenCalled();
  fireEvent.compositionEnd(input);
  fireEvent.keyDown(input, { key: "Enter" });
  expect(fetch).toHaveBeenCalledTimes(1); expect(input.disabled).toBe(true);
  expect((screen.getByRole("button", { name: "기획하기" }) as HTMLButtonElement).disabled).toBe(true);
  await ready();
});
it.each([true, false])("image_enabled=%s controls checkbox and optional request field", async enabled => {
  const fetch = setup([{ event: "token", data: { text: "합성 완료" } }], enabled); selectWorkspace();
  const checkbox = screen.queryByLabelText("시안 이미지 포함") as HTMLInputElement | null;
  if (enabled) expect(checkbox?.checked).toBe(true); else expect(checkbox).toBeNull();
  send(); await ready();
  expect(body(fetch, 0)).toEqual({ message: "합성 사용자 요청", ...(enabled ? { with_image: true } : {}) });
});
it("aborts on workspace change, clears conversation and ignores late responses", async () => {
  let resolve!: (response: Response) => void;
  const fetch = setup([]);
  fetch.mockImplementationOnce(() => new Promise<Response>(r => { resolve = r; }));
  selectWorkspace(); send();
  const signal = fetch.mock.calls[0][1].signal as AbortSignal;
  selectWorkspace("synthetic-second");
  expect(signal.aborted).toBe(true);
  expect(screen.queryByText("합성 사용자 요청")).toBeNull();
  await act(async () => { resolve(response([{ event: "token", data: { text: "합성 늦은 응답" } }])); });
  expect(screen.queryByText("합성 늦은 응답")).toBeNull();
  send(); await ready();
  expect(body(fetch, 1).thread_id).toBeUndefined();
});
it("enforces single choice chips and can submit without a requested claim", async () => {
  const question: Clarification = { ...clarification, reason: "no_claim_requested", requested_claim: null,
    options: [{ id: "select_one", label: "합성 단일 선택" }] };
  const fetch = setup([{ event: "needs_clarification", data: question }]);
  selectWorkspace(); send(); await ready();
  fetch.mockResolvedValue(response([{ event: "token", data: { text: "합성 완료" } }]));
  fireEvent.click(screen.getByRole("button", { name: "합성 단일 선택" }));
  expect((screen.getByRole("button", { name: "선택 제출" }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByLabelText("합성 효능 A")); fireEvent.click(screen.getByLabelText("합성 효능 B"));
  expect((screen.getByLabelText("합성 효능 A") as HTMLInputElement).checked).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "선택 제출" })); await ready();
  expect(body(fetch, 1).claim_choice).toEqual({ mode: "selected", claims: ["barrier"], requested_claim: null });
});
it("reuses the first response thread, supports image opt-out and leaves Shift+Enter unprevented", async () => {
  const fetch = setup([{ event: "token", data: { text: "합성 완료" } }], true);
  selectWorkspace(); fireEvent.click(screen.getByLabelText("시안 이미지 포함")); send(); await ready();
  const input = screen.getByLabelText("요청") as HTMLTextAreaElement;
  fireEvent.change(input, { target: { value: "합성 다음 줄" } });
  const event = new KeyboardEvent("keydown", { key: "Enter", shiftKey: true, bubbles: true, cancelable: true });
  fireEvent(input, event); expect(event.defaultPrevented).toBe(false);
  fireEvent.change(input, { target: { value: "합성 다음 줄\n합성 추가 줄" } });
  expect(input.value).toContain("\n");
  fetch.mockResolvedValue(response([{ event: "token", data: { text: "합성 두 번째 완료" } }], "synthetic:other"));
  fireEvent.click(screen.getByRole("button", { name: "기획하기" })); await ready();
  send(); await ready();
  expect(body(fetch, 0).with_image).toBe(false);
  expect(body(fetch, 1).thread_id).toBe("synthetic:thread"); expect(body(fetch, 2).thread_id).toBe("synthetic:thread");
});
it("keeps no-evidence and limit notices as normal server text without fabricated cards", async () => {
  setup([{ event: "token", data: { text: "합성 원문", display_text: "합성 서버 종료 안내" } }]);
  selectWorkspace(); send(); await ready();
  expect(screen.getByText("합성 서버 종료 안내")).toBeTruthy();
  expect(screen.queryByText("합성 원문")).toBeNull();
  expect(screen.queryByRole("button", { name: "다시 시도" })).toBeNull();
  expect(screen.queryByLabelText("효능 선택")).toBeNull();
});

it("renders the terminal stage label exactly once and retains stage counts and reworks", () => {
  const events = [
    { agent: "supervisor", phase: "end", status: "ok" },
    { agent: "research", phase: "end", status: "ok" },
    { agent: "planning", phase: "start", status: "running" },
    { agent: "evaluation", phase: "end", status: "done" },
    { agent: "rework", phase: "end", status: "done" },
    { agent: "planning", phase: "start", status: "running" },
    { agent: "evaluation", phase: "end", status: "done" },
    { agent: "supervisor", phase: "done", status: "plan" },
  ];
  render(<ProgressTracker stepEvents={events} turnStatus="done" />);
  for (const label of ["요청 해석", "리서치", "기획·평가"]) expect(screen.getAllByText(label)).toHaveLength(1);
  expect(screen.queryByText(/완료 완료|요청 해석 완료/)).toBeNull();
  expect(screen.getByText("재작업 1회").closest("li")?.textContent).toContain("기획·평가");
  expect(screen.getAllByRole("img", { name: "완료" })).toHaveLength(3);
  expect(screen.getAllByRole("listitem").map(item => item.getAttribute("data-status"))).toEqual(["done", "done", "done"]);
});
it("announces running and failed stages with icons and text in a live region", () => {
  const { rerender } = render(<ProgressTracker stepEvents={[]} turnStatus="running" />);
  const region = screen.getByLabelText("진행 단계");
  expect(region.getAttribute("aria-live")).toBe("polite");
  expect(within(region).getByText("요청 해석").closest("li")?.getAttribute("data-status")).toBe("running");
  expect(within(region).getByRole("img", { name: "진행 중" })).toBeTruthy();
  expect(region.querySelector('[data-status="running"] .gs-stage-icon')).toBeTruthy();
  rerender(<ProgressTracker stepEvents={[{ agent: "research", phase: "end", status: "failed" }]} turnStatus="error" />);
  expect(screen.getByText("리서치").closest("li")?.getAttribute("data-status")).toBe("failed");
});
it("updates elapsed numbers with an injected clock only while running and cleans up timers", () => {
  vi.useFakeTimers();
  let now = 1000;
  const clock = vi.fn(() => now);
  const { rerender, unmount } = render(<ProgressTracker stepEvents={[]} turnStatus="running" clock={clock} />);
  expect(screen.getByLabelText("경과 시간").textContent).toBe("0초 경과");
  now = 4000;
  act(() => { vi.advanceTimersByTime(1000); });
  expect(screen.getByLabelText("경과 시간").textContent).toBe("3초 경과");
  rerender(<ProgressTracker stepEvents={[]} turnStatus="done" clock={clock} />);
  const calls = clock.mock.calls.length;
  now = 10000;
  act(() => { vi.advanceTimersByTime(5000); });
  expect(screen.getByLabelText("경과 시간").textContent).toBe("3초 경과");
  expect(clock).toHaveBeenCalledTimes(calls);
  expect(vi.getTimerCount()).toBe(0);
  rerender(<ProgressTracker stepEvents={[]} turnStatus="running" clock={clock} />);
  unmount();
  expect(vi.getTimerCount()).toBe(0);
});
it("uses CSS pulse and line transitions with reduced motion disabling both", () => {
  const css = readFileSync(join(process.cwd(), "app/plan.css"), "utf8");
  expect(css).toMatch(/@keyframes\s+gs-progress-pulse/);
  expect(css).toMatch(/transition\s*:[^;]*;/);
  const reduced = css.slice(css.indexOf("@media (prefers-reduced-motion: reduce)"));
  expect(reduced).toMatch(/animation\s*:\s*none/);
  expect(reduced).toMatch(/transition\s*:\s*none/);
});
it("collapses resolved clarification to one line, then renders a fresh request as an ordinary turn", async () => {
  const fetch = setup([{ event: "needs_clarification", data: clarification }]);
  selectWorkspace(); send(); await ready();
  const question = screen.getByRole("article", { name: "요청 1" });
  expect(within(question).getByRole("button", { name: "합성 하나 선택" })).toBeTruthy();
  fetch.mockResolvedValue(response([{ event: "token", data: { text: "합성 선택 결과" } }]));
  fireEvent.click(screen.getByRole("button", { name: "합성 하나 선택" }));
  fireEvent.click(screen.getByLabelText("합성 효능 A"));
  fireEvent.click(screen.getByRole("button", { name: "선택 제출" }));
  await ready();
  expect(within(question).getByText("효능 선택 · 합성 하나 선택 · 합성 효능 A")).toBeTruthy();
  expect(within(question).queryByRole("button")).toBeNull();
  expect(within(question).queryByRole("checkbox")).toBeNull();
  expect(within(question).queryByRole("radio")).toBeNull();
  expect(within(question).queryByText(clarification.text)).toBeNull();
  send(); await ready();
  const fresh = screen.getByRole("article", { name: "요청 3" });
  expect(within(fresh).getByText("합성 사용자 요청")).toBeTruthy();
  expect(within(fresh).queryByLabelText("효능 선택")).toBeNull();
  expect(within(fresh).queryByText(/효능 선택 ·/)).toBeNull();
});
it("hides choice buttons for every resolved status and for a turn with a recorded choice label", () => {
  const turn = reducer({ ...initialState, tenantId: "synthetic" }, { type: "request_started", message: "합성 요청" }).turns[0];
  const { rerender } = render(<TurnCard turn={{ ...turn, status: "needs_choice", clarification }} busy={false} onChoice={vi.fn()} onCancel={vi.fn()} onRetry={vi.fn()} />);
  expect(screen.getByRole("button", { name: "합성 하나 선택" })).toBeTruthy();
  for (const status of ["done", "running", "error", "unavailable", "stopped"] as const) {
    rerender(<TurnCard turn={{ ...turn, status, clarification }} busy={false} onChoice={vi.fn()} onCancel={vi.fn()} onRetry={vi.fn()} />);
    const summary = screen.getByLabelText("효능 선택 요약");
    expect(summary.tagName).toBe("P");
    expect(summary.textContent).toBe("효능 선택 · 선택 완료");
    expect(screen.queryByRole("button")).toBeNull();
  }
  rerender(<TurnCard turn={{ ...turn, status: "needs_choice", choiceLabel: "합성 선택", clarification }} busy={false} onChoice={vi.fn()} onCancel={vi.fn()} onRetry={vi.fn()} />);
  expect(screen.getByText("효능 선택 · 합성 선택")).toBeTruthy();
  expect(screen.queryByRole("button")).toBeNull();
});

it("starts with one input row, grows with content, and only describes nonempty input", () => {
  setup([]); selectWorkspace();
  const input = screen.getByLabelText("요청") as HTMLTextAreaElement;
  expect(input.rows).toBe(1);
  expect(input.getAttribute("aria-describedby")).toBeNull();
  expect(screen.queryByText(/2000 · Enter/)).toBeNull();
  Object.defineProperty(input, "scrollHeight", { configurable: true, value: 120 });
  fireEvent.change(input, { target: { value: "합성 입력" } });
  expect(input.style.height).toBe("120px");
  expect(screen.getByText("5/2000 · Enter 전송, Shift+Enter 줄바꿈").id).toBe(input.getAttribute("aria-describedby"));
  expect(document.querySelector("select, .workspace-picker")).toBeNull();
  fireEvent.keyDown(input, { key: "Enter", keyCode: 229 });
  expect(input.value).toBe("합성 입력");
});
it("renders arrival durations and the same turn's optional text cost in the progress row", () => {
  const base = reducer({ ...initialState, tenantId: "synthetic" }, { type: "request_started", message: "합성 요청" }).turns[0];
  const turn = { ...base, startedAt: 100, stepAt: [1700], stepEvents: [{ agent: "supervisor", phase: "end", status: "ok" }] };
  const props = { busy: false, onChoice: vi.fn(), onCancel: vi.fn(), onRetry: vi.fn() };
  const { rerender } = render(<TurnCard turn={turn} {...props} />);
  expect(screen.getByText("1.6s")).toBeTruthy();
  expect(screen.queryByLabelText("텍스트 모델 비용(이미지 제외)")).toBeNull();
  rerender(<TurnCard turn={{ ...turn, commands: [{ kind: "show_cost", data: { label: "텍스트 모델 비용(이미지 제외)", text_spent_usd: .062, max_text_cost_usd: 1 } }] }} {...props} />);
  const cost = screen.getByLabelText("텍스트 모델 비용(이미지 제외)");
  expect(cost.textContent).toBe("$0.062");
  expect(cost.closest("section")).toBe(screen.getByLabelText("진행 단계"));
  expect(screen.getAllByText("$0.062")).toHaveLength(1);
});

it("timestamps requests and SSE arrivals with the injected session clock, including retries and choices", async () => {
  let now = 100;
  const step: SseFrame = { event: "step", data: { agent: "supervisor", phase: "end", status: "ok" } };
  const fetch = vi.fn().mockImplementationOnce(async () => {
    now = 1700; return response([step, { event: "error", data: { code: "AGENT_INTERNAL_ERROR" } }]);
  }).mockImplementationOnce(async () => {
    now = 4900; return response([step, { event: "needs_clarification", data: clarification }]);
  }).mockImplementationOnce(async () => {
    now = 8100; return response([step, { event: "token", data: { text: "합성 시간 완료" } }]);
  });
  vi.stubGlobal("fetch", fetch);
  function Snapshot() {
    const { state } = useSession();
    return <output aria-label="합성 세션">{JSON.stringify(state.turns.map(turn => ({ startedAt: turn.startedAt, stepAt: turn.stepAt })))}</output>;
  }
  render(<SessionProvider clock={() => now}><PlanHarness imageEnabled={false} /><Snapshot /></SessionProvider>);
  const snapshot = () => JSON.parse(screen.getByLabelText("합성 세션").textContent!);
  selectWorkspace(); send(); await ready();
  expect(snapshot()).toEqual([{ startedAt: 100, stepAt: [1700] }]);
  now = 3300; fireEvent.click(screen.getByRole("button", { name: "다시 시도" })); await ready();
  expect(snapshot()).toEqual([{ startedAt: 100, stepAt: [1700] }, { startedAt: 3300, stepAt: [4900] }]);
  now = 6500; fireEvent.click(screen.getByRole("button", { name: "합성 생략" })); await ready();
  expect(snapshot()).toEqual([{ startedAt: 100, stepAt: [1700] }, { startedAt: 3300, stepAt: [4900] }, { startedAt: 6500, stepAt: [8100] }]);
  expect(fetch).toHaveBeenCalledTimes(3);
});
