import { useState } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { PlanPage } from "../components/plan/PlanPage";
import { EvidencePage } from "../components/evidence/EvidencePage";
import { SessionProvider, useSession } from "../lib/session";
import type { State } from "../lib/reducer";
import { getSchema, postChatAsk } from "../lib/api";
import type { Clarification, EvidenceCard, PlanView, SseFrame } from "../lib/types";

vi.mock("../lib/api", async original => ({
  ...await original<typeof import("../lib/api")>(), getSchema: vi.fn(), postChatAsk: vi.fn(),
}));
const spaces = [{ tenant_id: "a", display_name: "합성 공간 가", brand: null, product_name: null }, { tenant_id: "b", display_name: "합성 공간 나", brand: null, product_name: null }];
const plan: PlanView = {
  plan: { title: "합성 기획안", claimed_efficacy: ["sun_protection"], category: "선케어" },
  plan_id: null, passed: true, unknown_count: 0, unknown_codes: {}, efficacy_status: {}, efficacy_summary: { supported: 0, unknown: 0 },
  count_label: "합성 건수", result_counts: [], evidence_counts: {}, status: "passed", attempts: [], pattern_alignment: {}, pattern_alignment_label: "합성 비교", disclaimer: "합성 안내", image: null, design_disclaimer: null, product_display: { brand: null, display_name: null, product_name: null },
};
const question: Clarification = {
  reason: "no_claim_requested", requested_claim: null, requested_label: null, text: "합성 확인 질문",
  available: [{ claim: "hydration", label: "합성 보습" }], options: [{ id: "select_one", label: "합성 효능 고르기" }],
};
function reply(frames: SseFrame[], threadId: string) {
  return { threadId, events: (async function* () { for (const frame of frames) yield frame; })() };
}
function done(text: string): SseFrame { return { event: "token", data: { text } }; }
function Harness() {
  const { state, selectWorkspace } = useSession();
  const [evidence, setEvidence] = useState(false);
  return <>
    {spaces.map(space => <button key={space.tenant_id} onClick={() => selectWorkspace(space.tenant_id)}>{space.display_name}</button>)}
    <button onClick={() => setEvidence(value => !value)}>합성 화면 전환</button>
    {evidence ? <EvidencePage turns={state.turns} workspaceBrand={null} onPlan={() => setEvidence(false)} /> : <PlanPage workspaces={spaces} imageEnabled={false} />}
    <output aria-label="합성 상태">{JSON.stringify(state)}</output>
  </>;
}
function setup() {
  render(<SessionProvider><Harness /></SessionProvider>);
  fireEvent.click(screen.getByRole("button", { name: "합성 공간 가" }));
}
function state(): State { return JSON.parse(screen.getByLabelText("합성 상태").textContent!); }
function send(message = "합성 요청") {
  fireEvent.change(screen.getByLabelText("요청"), { target: { value: message } });
  fireEvent.click(screen.getByRole("button", { name: "기획하기" }));
}
async function idle() { await waitFor(() => expect(state().activeTurnId).toBeNull()); }
function newTab() { fireEvent.click(screen.getByRole("button", { name: "+ 새 기획" })); }
function tabs() { return within(screen.getByRole("tablist", { name: "기획 탭" })).getAllByRole("tab"); }
beforeEach(() => {
  vi.mocked(getSchema).mockResolvedValue({ labels: [], relationships: [], taxonomy: { hook_type: [], angle: [], format: [] }, claims: [{ value: "sun_protection", name: "자외선 차단" }] });
  vi.mocked(postChatAsk).mockImplementation(async () => reply([done("합성 완료 결과")], "first"));
});
afterEach(() => { cleanup(); vi.resetAllMocks(); });

it("places one named tablist and the new button above the composer, resets new input and isolates results", async () => {
  setup();
  expect(screen.getAllByRole("tablist", { name: "기획 탭" })).toHaveLength(1);
  expect(tabs().map(tab => tab.textContent)).toEqual(["기획 1"]);
  for (const element of [screen.getByRole("tablist", { name: "기획 탭" }), screen.getByRole("button", { name: "+ 새 기획" })]) {
    expect(element.compareDocumentPosition(screen.getByLabelText("요청")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  }
  send(); await idle();
  fireEvent.change(screen.getByLabelText("요청"), { target: { value: "합성 작성 중" } });
  newTab();
  expect(tabs()).toHaveLength(2);
  expect(tabs()[1].getAttribute("aria-selected")).toBe("true");
  expect((screen.getByLabelText("요청") as HTMLTextAreaElement).value).toBe("");
  expect(screen.queryByText("합성 완료 결과")).toBeNull();
  fireEvent.click(tabs()[0]);
  expect(screen.getByText("합성 완료 결과")).toBeTruthy();
  expect(state().turns.map(turn => turn.tabId)).toEqual([1]);
});
it("moves tab selection and focus by arrows, Home and End", () => {
  setup(); newTab(); newTab();
  const list = tabs();
  for (const [from, key, to] of [[2, "ArrowRight", 0], [0, "ArrowLeft", 2], [2, "Home", 0], [0, "End", 2]] as const) {
    fireEvent.keyDown(list[from], { key });
    expect(document.activeElement).toBe(list[to]);
    expect(list[to].getAttribute("aria-selected")).toBe("true");
    expect(list.filter(tab => tab.tabIndex === 0)).toEqual([list[to]]);
  }
});
it("blocks creation, sending and closing the running tab but lets the user inspect previous results", async () => {
  setup(); send(); await idle(); newTab();
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  vi.mocked(postChatAsk).mockResolvedValueOnce({ threadId: "second", events: (async function* () { await gate; yield done("합성 두 번째 결과"); })() });
  send("합성 진행 요청");
  await waitFor(() => expect(tabs()[1].getAttribute("aria-busy")).toBe("true"));
  expect(tabs()[1].querySelector(".gs-tab-spinner")).toBeTruthy();
  expect((screen.getByRole("button", { name: "+ 새 기획" }) as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByRole("button", { name: "기획 2 닫기" }) as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByRole("button", { name: "기획하기" }) as HTMLButtonElement).disabled).toBe(true);
  const signal = vi.mocked(postChatAsk).mock.calls[1][0].signal!;
  fireEvent.click(tabs()[0]);
  expect(screen.getByText("합성 완료 결과")).toBeTruthy();
  expect(screen.queryByText("합성 진행 요청")).toBeNull();
  expect((screen.getByLabelText("요청") as HTMLTextAreaElement).disabled).toBe(true);
  expect(signal.aborted).toBe(false);
  expect(state().threadId).toBe("first");
  await act(async () => { release(); await gate; }); await idle();
  expect(state().tabs?.map(tab => tab.threadId)).toEqual(["first", "second"]);
  expect(state().threadId).toBe("first");
  fireEvent.click(tabs()[1]);
  expect(screen.getByText("합성 두 번째 결과")).toBeTruthy();
  expect(tabs()[1].getAttribute("aria-busy")).toBe("false");
  expect((screen.getByRole("button", { name: "기획 2 닫기" }) as HTMLButtonElement).disabled).toBe(false);
});
it("names completed tabs from translated efficacy and product, otherwise truncates the request at 14 characters", async () => {
  vi.mocked(postChatAsk).mockResolvedValueOnce(reply([{ event: "ui_command", data: { kind: "show_plan", data: plan } }, done("합성 완료")], "first"));
  setup(); send(); await idle();
  await waitFor(() => expect(tabs()[0].textContent).toBe("자외선 차단 · 선케어"));
  newTab();
  expect(tabs()[1].textContent).toBe("기획 2");
  const message = "합성 요청 문장이 열네 글자를 넘어서 이어집니다";
  send(message); await idle();
  expect(tabs()[1].textContent).toBe(`${message.slice(0, 14)}…`);
  newTab();
  vi.mocked(postChatAsk).mockResolvedValueOnce(reply([{ event: "ui_command", data: { kind: "show_plan", data: { ...plan, plan: { claimed_efficacy: ["unknown_code"], category: "internal_code" }, product_display: { brand: null, display_name: null, product_name: "합성 제품" } } } }, done("합성 완료")], "third"));
  send(); await idle();
  expect(tabs()[2].textContent).toBe("기타 · 합성 제품");
  expect(tabs()[2].textContent).not.toMatch(/unknown_code|internal_code/);
});
it("closes tabs and their turns, retains the selected tab when closing another, and replaces the last tab", async () => {
  setup(); send(); await idle(); newTab(); send("다음 요청"); await idle();
  fireEvent.click(tabs()[0]);
  fireEvent.click(screen.getByRole("button", { name: "기획 2 닫기" }));
  expect(tabs()).toHaveLength(1);
  expect(tabs()[0].getAttribute("aria-selected")).toBe("true");
  expect(state().turns.map(turn => turn.message)).toEqual(["합성 요청"]);
  fireEvent.click(screen.getByRole("button", { name: "기획 1 닫기" }));
  expect(tabs()).toHaveLength(1);
  expect(state().turns).toEqual([]);
  expect(state().threadId).toBeNull();
  expect(screen.queryByText("합성 완료 결과")).toBeNull();
});
it("omits threadId on each new tab's first request and reuses only that tab's first response", async () => {
  setup(); send(); await idle(); newTab();
  vi.mocked(postChatAsk).mockResolvedValueOnce(reply([done("두 번째 완료")], "second"));
  send(); await idle();
  vi.mocked(postChatAsk).mockResolvedValueOnce(reply([done("이어지는 완료")], "ignored"));
  send(); await idle();
  fireEvent.click(tabs()[0]); send(); await idle();
  const calls = vi.mocked(postChatAsk).mock.calls.map(([request]) => request);
  expect(calls.map(request => request.threadId)).toEqual([undefined, undefined, "second", "first"]);
  expect(Object.hasOwn(calls[0], "threadId")).toBe(false);
  expect(Object.hasOwn(calls[1], "threadId")).toBe(false);
  expect(calls.map(request => request.tenantId)).toEqual(["a", "a", "a", "a"]);
});
it("keeps clarification neighbors within their tab even when another tab's turn lies between them", async () => {
  vi.mocked(postChatAsk).mockResolvedValueOnce(reply([{ event: "needs_clarification", data: question }], "first"));
  setup(); send(); await idle(); newTab(); send("다른 탭 요청"); await idle();
  fireEvent.click(tabs()[0]);
  expect(screen.getByText(question.text)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "합성 효능 고르기" }));
  fireEvent.click(screen.getByLabelText("합성 보습"));
  fireEvent.click(screen.getByRole("button", { name: "선택 제출" })); await idle();
  expect(screen.getAllByLabelText("효능 선택 요약")).toHaveLength(1);
  const resolved = screen.getByRole("article", { name: "요청 1" });
  expect(within(resolved).getByText("효능 선택 · 합성 효능 고르기 · 합성 보습")).toBeTruthy();
  expect(within(resolved).queryByRole("button")).toBeNull();
  expect(within(resolved).queryByRole("radio")).toBeNull();
  expect(within(resolved).queryByRole("checkbox")).toBeNull();
  expect(screen.queryByText(question.text)).toBeNull();
  expect(state().turns.map(turn => turn.tabId)).toEqual([1, 2, 1]);
  expect(vi.mocked(postChatAsk).mock.calls[2][0]).toMatchObject({ threadId: "first", message: "합성 요청", claimChoice: { mode: "selected", claims: ["hydration"], requested_claim: null } });
  fireEvent.click(tabs()[1]);
  expect(screen.queryByLabelText("효능 선택 요약")).toBeNull();
});
it("collects evidence from all tabs in the flat turn list, removes closed evidence, and resets on workspace change", async () => {
  const cards: EvidenceCard[] = ["첫 번째 근거", "두 번째 근거"].map((title, index) => ({ evidence_id: `youtube:${index}`, source: "youtube", title, url: null, brand: null, published_at: null, view_count: null, like_count: null, hook_type: null, angle: null, format: null, talent: null, cta_type: null, claims: null }));
  for (const [index, card] of cards.entries()) vi.mocked(postChatAsk).mockResolvedValueOnce(reply([{ event: "ui_command", data: { kind: "show_evidence_cards", data: { cards: [card], missing: 0 } } }, done(`합성 결과 ${index}`)], `thread:${index}`));
  setup(); send(); await idle(); newTab(); send(); await idle();
  expect(state().turns).toHaveLength(2);
  fireEvent.click(screen.getByRole("button", { name: "합성 화면 전환" }));
  for (const card of cards) expect(screen.getByText(card.title!)).toBeTruthy();
  expect(screen.queryByRole("tablist", { name: "기획 탭" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "합성 화면 전환" }));
  fireEvent.click(screen.getByRole("button", { name: "기획 1 닫기" }));
  fireEvent.click(screen.getByRole("button", { name: "합성 화면 전환" }));
  expect(screen.queryByText(cards[0].title!)).toBeNull();
  expect(screen.getByText(cards[1].title!)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "합성 화면 전환" }));
  newTab();
  fireEvent.click(screen.getByRole("button", { name: "합성 공간 나" }));
  expect(tabs().map(tab => tab.textContent)).toEqual(["기획 1"]);
  expect(state().tabs).toEqual([{ id: 1, threadId: null }]);
  expect(state().activeTabId).toBe(1);
  expect(state().turns).toEqual([]);
});
