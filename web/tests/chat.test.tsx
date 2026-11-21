import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { Chat } from "../components/Chat";
import { ClarifyCard } from "../components/ClarifyCard";
import { getWorkspaces } from "../lib/api";
import type { Clarification, SseFrame, WorkspacesResponse } from "../lib/types";
import Page from "../app/page";
import { SessionProvider } from "../lib/session";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
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
function setup(frames: SseFrame[], imageEnabled = false) {
  const fetch = vi.fn().mockImplementation(() => Promise.resolve(response(frames)));
  vi.stubGlobal("fetch", fetch);
  render(<Chat workspaces={workspaces.workspaces} imageEnabled={imageEnabled} />, { wrapper: SessionProvider });
  return fetch;
}
function selectWorkspace(value = "test-isntree") {
  fireEvent.change(screen.getByLabelText("작업 공간"), { target: { value } });
}
function send() {
  fireEvent.change(screen.getByLabelText("요청"), { target: { value: "합성 사용자 요청" } });
  fireEvent.click(screen.getByRole("button", { name: "전송" }));
}
async function ready() { await waitFor(() => expect((screen.getByLabelText("요청") as HTMLTextAreaElement).disabled).toBe(false)); }
function body(fetch: ReturnType<typeof vi.fn>, index: number) { return JSON.parse(fetch.mock.calls[index][1].body); }

it("loads workspace metadata with no headers and renders API failure", async () => {
  const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify(workspaces))));
  vi.stubGlobal("fetch", fetch);
  expect(await getWorkspaces()).toEqual(workspaces);
  expect(fetch).toHaveBeenCalledExactlyOnceWith("/api/workspaces");
  render(<Page />);
  expect(await screen.findByRole("option", { name: /합성 공간 A.*합성 브랜드 A.*합성 제품 A/ })).toBeTruthy();
  cleanup();
  fetch.mockRejectedValue(new TypeError("synthetic"));
  render(<Page />);
  expect(await screen.findByText("API 서버에 연결하지 못했습니다. 서버가 실행 중인지 확인하세요.")).toBeTruthy();
});
it("enables input only after workspace selection; example chips fill without sending", () => {
  const fetch = setup([]);
  expect((screen.getByLabelText("요청") as HTMLTextAreaElement).disabled).toBe(true);
  selectWorkspace();
  expect((screen.getByLabelText("요청") as HTMLTextAreaElement).disabled).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "정상" }));
  expect((screen.getByLabelText("요청") as HTMLTextAreaElement).value.length).toBeGreaterThan(0);
  expect(fetch).not.toHaveBeenCalled();
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
  expect(screen.getByText("선택: 합성 분기 선택")).toBeTruthy();
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
  expect((screen.getByRole("button", { name: "전송" }) as HTMLButtonElement).disabled).toBe(true);
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
  fireEvent.click(screen.getByRole("button", { name: "전송" })); await ready();
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
