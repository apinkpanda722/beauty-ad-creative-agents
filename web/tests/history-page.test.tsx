import { useState } from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Page from "../app/page";
import { HistoryPage } from "../components/history/HistoryPage";
import { HistoryDetail } from "../components/history/HistoryDetail";
import { DistributionChart } from "../components/results/DistributionChart";
import { SessionProvider, useSession } from "../lib/session";
import { initialState, reducer } from "../lib/reducer";
import { getWorkspaces, getSchema, postChatAsk } from "../lib/api";
import { taxonomyNames } from "../lib/taxonomy";
import type { PlanView, SchemaResponse, SseFrame, UiCommand } from "../lib/types";
vi.mock("../lib/api", async original => ({ ...await original<typeof import("../lib/api")>(), getWorkspaces: vi.fn(), getSchema: vi.fn(), postChatAsk: vi.fn() }));
const spaces = [{ tenant_id: "synthetic", display_name: "합성 브랜드 작업 공간", brand: "synthetic", product_name: "합성 제품" }];
const schema: SchemaResponse = { labels: [], relationships: [], taxonomy: { hook_type: [{ value: "question", name: "질문형", definition: "합성" }], angle: [{ value: "how_to", name: "사용법", definition: "합성" }], format: [] }, claims: [] };
const plan: PlanView = { plan: { title: "합성 기획안" }, plan_id: null, passed: false, status: "needs_review", unknown_count: 2, unknown_codes: { CERT_REQUIRED_UNVERIFIED: 1, EFFICACY_UNKNOWN: 1 }, efficacy_status: {}, efficacy_summary: { supported: 0, unknown: 2 }, count_label: "합성 건수", result_counts: [], evidence_counts: {}, pattern_alignment: {}, pattern_alignment_label: "합성 비교", disclaimer: "합성 면책", image: null, design_disclaimer: null, product_display: { brand: null, display_name: null, product_name: null }, attempts: [
  { attempt: 1, checks_passed: false, final_passed: false, scores: { differentiation: 2, fit: 3, rationale: "how_to 대비 differentiation, fit. profit" }, low_items: ["differentiation"], cost_usd: .012345 },
  { attempt: 2, checks_passed: true, final_passed: true, scores: { differentiation: 4, fit: 5 }, low_items: [] },
] };
const distribution = { tool: "top_vs_bottom_axis", rows: [{ value: "question", n_top: 7, n_bottom: 2 }, { value: "how_to", n_top: 3, n_bottom: 1 }] };
const aggregate: UiCommand = { kind: "show_aggregates", data: { label: "모델 작성값 · 검증되지 않음", verified_counts: [{ tool: distribution.tool, count_label: "합성 전체 10건 중 2건 표시", row_count: 10, shown_count: 2 }], model_written: [{ name: "합성 모델 항목", value: 42 }], removed: ["합성 제외 항목"] } };
const cost: UiCommand = { kind: "show_cost", data: { label: "합성 서버 비용(이미지 제외)", text_spent_usd: .062345, max_text_cost_usd: 1 } };
const commands: UiCommand[] = [{ kind: "show_plan", data: plan }, aggregate, { kind: "show_distribution", data: distribution }, cost];
const base = reducer({ ...initialState, tenantId: "synthetic" }, { type: "request_started", message: "합성 상세 요청", at: 100 }).turns[0];
const turn = { ...base, status: "done" as const, commands, stepEvents: ["supervisor", "research", "planning", "evaluation", "rework", "planning", "evaluation", "image"].map(agent => ({ agent, phase: agent === "planning" ? "start" : "end", status: "ok" })), stepAt: [1100, 2100, 3100, 4100, 5100, 6100, 7100, 8100] };
function detail() { return render(<HistoryDetail turn={turn} workspace="합성 브랜드 · 합성 제품" onBack={vi.fn()} names={taxonomyNames(schema)} />); }
function tab(label: string) { fireEvent.click(screen.getByRole("tab", { name: label })); return screen.getByRole("tabpanel", { name: label }); }
function reply() { return { threadId: "synthetic-thread", events: (async function* (): AsyncGenerator<SseFrame> { for (const data of commands) yield { event: "ui_command", data }; yield { event: "token", data: { text: "합성 완료" } }; })() }; }
beforeEach(() => { vi.mocked(getSchema).mockResolvedValue(schema); vi.mocked(getWorkspaces).mockResolvedValue({ workspaces: spaces, image_enabled: false }); vi.mocked(postChatAsk).mockImplementation(async () => reply()); });
afterEach(() => { cleanup(); vi.resetAllMocks(); });
function Harness() {
  const session = useSession();
  const [selected, select] = useState<number | null>(null);
  return <><button onClick={() => session.selectWorkspace("synthetic")}>합성 공간</button><button onClick={() => session.send(`합성 요청 ${session.state.nextTurnId}`)}>합성 실행</button><button onClick={session.newTab}>합성 새 탭</button><output aria-label="합성 상태">{session.state.activeTurnId === null ? "대기" : "실행"}</output><HistoryPage workspaces={spaces} selectedTurnId={selected} onSelectTurn={select} onPlan={vi.fn()} /></>;
}
it("shows an empty state and its plan action", () => {
  const action = vi.fn(); render(<SessionProvider><HistoryPage workspaces={spaces} selectedTurnId={null} onSelectTurn={vi.fn()} onPlan={action} /></SessionProvider>);
  expect(screen.getByRole("heading", { name: "아직 실행한 요청이 없습니다" })).toBeTruthy();
  expect(screen.getByText("이번 접속 중 0건 · 새로고침하면 지워집니다")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "광고 기획으로" })); expect(action).toHaveBeenCalledTimes(1);
});
it("lists every tab's turns newest first and opens the selected header then returns", async () => {
  let clock = 100; render(<SessionProvider clock={() => { clock += 1000; return clock; }}><Harness /></SessionProvider>);
  fireEvent.click(screen.getByRole("button", { name: "합성 공간" }));
  for (let i = 0; i < 2; i++) {
    if (i) fireEvent.click(screen.getByRole("button", { name: "합성 새 탭" }));
    fireEvent.click(screen.getByRole("button", { name: "합성 실행" }));
    await waitFor(() => expect(screen.getByLabelText("합성 상태").textContent).toBe("대기"));
  }
  const table = screen.getByRole("table", { name: "실행 요청 목록" });
  const rows = within(table).getAllByRole("row").slice(1);
  expect(rows).toHaveLength(2); expect(rows.map(row => within(row).getAllByRole("cell")[1].textContent)).toEqual(["합성 요청 2", "합성 요청 1"]);
  expect(screen.getByText("이번 접속 중 2건 · 새로고침하면 지워집니다")).toBeTruthy();
  fireEvent.click(rows[1]);
  const header = screen.getByLabelText("실행 요약");
  for (const text of ["합성 요청 1", "합성 브랜드 · 합성 제품", "시각", "총 시간", "총 비용", "$0.0623"]) expect(header.textContent).toContain(text);
  expect(within(header).getByText("정보 없음")).toBeTruthy(); // No step arrivals in this reply.
  expect(header.querySelector("time")?.getAttribute("datetime")).toBe(new Date(performance.timeOrigin + 1100).toISOString());
  fireEvent.click(screen.getByRole("button", { name: "목록으로" })); expect(screen.getByRole("table", { name: "실행 요청 목록" })).toBeTruthy();
});
it("renders recorded durations and rework counts, with only a check for image time", () => {
  detail(); const panel = screen.getByRole("tabpanel", { name: "단계" });
  expect(within(panel).getAllByText("1.0초")).toHaveLength(2); expect(within(panel).getByText("5.0초")).toBeTruthy();
  expect(within(panel).getByText("재작업 1회")).toBeTruthy(); expect(within(panel).getByText("기획 2회 · 평가 2회")).toBeTruthy();
  const image = within(panel).getByText("시안").closest("li")!;
  expect(within(image).getByRole("img", { name: "완료" })).toBeTruthy(); expect(image.textContent).toBe("시안"); expect(image.querySelector("time")).toBeNull(); expect(image.textContent).not.toMatch(/초|정보 없음/);
});
it("moves checks and all three aggregate blocks with labeled provenance and identical chart source values", () => {
  detail(); const panel = tab("검증");
  for (const text of ["근거 연결 없음 2건", "인증 연결 없음", "효능 근거 연결 없음", "코드 검사: 실패", "평가 상태: 검토 필요", "검증됨", "미검증", "제외됨", "합성 전체 10건 중 2건 표시", "전체 10건 · 표시 2건", "합성 모델 항목", "42", "합성 제외 항목"]) expect(within(panel).getByText(text)).toBeTruthy();
  expect(within(panel).getByText("검증됨").className).toContain("gs-badge-success"); expect(within(panel).getByText("미검증").className).toContain("gs-badge-warn"); expect(within(panel).getByText("제외됨").className).toContain("gs-badge-neutral");
  expect(within(panel).getAllByText(distribution.tool).every(node => node.classList.contains("gs-source-chip"))).toBe(true);
  const sourceTable = within(panel).getByRole("table", { name: "시장 인사이트 원천 데이터" });
  expect(within(sourceTable).getAllByRole("columnheader").map(node => node.textContent)).toEqual(["분류", "상위 25%", "하위 25%"]);
  const sourceRows = within(sourceTable).getAllByRole("row").slice(1).map(row => within(row).getAllByRole("cell").map(node => node.textContent));
  render(<DistributionChart data={distribution} names={taxonomyNames(schema)} />);
  const chart = screen.getByRole("region", { name: "분포" });
  const chartRows = within(chart).getAllByRole("row").slice(1).map(row => within(row).getAllByRole("cell").map(node => node.textContent));
  expect(sourceRows).toEqual([["질문형", "7", "2"], ["사용법", "3", "1"]]); expect(sourceRows).toEqual(chartRows);
});
it("keeps every attempt's exact check, score, review and cost wording, localizing only displayed rationale", () => {
  const snapshot = JSON.stringify(turn); detail(); const panel = tab("평가");
  expect(within(panel).getByText("되돌림 1회").className).toContain("gs-badge-warn");
  const attempts = panel.querySelectorAll(".gs-history-attempt"); expect(attempts).toHaveLength(2); expect([...attempts].every(item => item.classList.contains("gs-history-reworked"))).toBe(true);
  for (const text of ["시도 1", "시도 2", "차별성 (differentiation): 2", "요청 적합성 (fit): 3", "차별성 (differentiation): 4", "요청 적합성 (fit): 5", "시도 코드 검사: 실패 · 최종 판정: 실패", "시도 코드 검사: 통과 · 최종 판정: 통과", "재검토 항목: 차별성", "시도 텍스트 비용 $0.0123", "사유: 사용법 대비 차별성, 요청 적합성. profit"]) expect(within(panel).getByText(text)).toBeTruthy();
  expect(JSON.stringify(turn)).toBe(snapshot);
});
it("reuses the server cost label and cap with four decimals and missing attempt costs explicit", () => {
  detail(); const panel = tab("비용");
  expect(within(panel).getByText("이 요청의 합성 서버 비용(이미지 제외) $0.0623")).toBeTruthy(); expect(within(panel).getByText("텍스트 비용 상한 $1.0000")).toBeTruthy();
  expect(within(panel).getByText("시도 1 · 시도 텍스트 비용 $0.0123")).toBeTruthy(); expect(within(panel).getByText("시도 2 · 시도 텍스트 비용 정보 없음")).toBeTruthy();
});
it("opens the exact turn from one verification link in the marketer results", async () => {
  render(<Page />); await screen.findByLabelText("요청");
  fireEvent.click(screen.getByRole("button", { name: "작업 공간" })); fireEvent.click(screen.getByRole("option", { name: /합성 브랜드/ }));
  fireEvent.change(screen.getByLabelText("요청"), { target: { value: "합성 연결 요청" } }); fireEvent.click(screen.getByRole("button", { name: "기획하기" }));
  await screen.findByText("합성 완료");
  expect(screen.queryByRole("region", { name: "검사 결과" })).toBeNull(); expect(screen.queryByText("평가 시도 보기 · 되돌림 1회")).toBeNull(); expect(screen.queryByRole("region", { name: "검증된 집계(도구가 센 값)" })).toBeNull();
  expect(screen.getAllByRole("link", { name: "검증 상세 보기 →" })).toHaveLength(1); fireEvent.click(screen.getByRole("link", { name: "검증 상세 보기 →" }));
  expect(screen.getByRole("heading", { name: "실행 기록·검증" })).toBeTruthy(); expect(screen.getByRole("button", { name: "실행 기록·검증" }).getAttribute("aria-current")).toBe("page");
  expect(within(screen.getByLabelText("실행 요약")).getByText("합성 연결 요청")).toBeTruthy();
  tab("검증"); expect(screen.getByRole("region", { name: "검사 결과" })).toBeTruthy();
});
it("shows missing timing and cost explicitly and includes a zero rework count", () => {
  render(<HistoryDetail turn={{ ...base, startedAt: undefined, status: "stopped" }} workspace="정보 없음" onBack={vi.fn()} />);
  const header = screen.getByLabelText("실행 요약");
  expect(within(header).getAllByText("정보 없음")).toHaveLength(4); expect(header.querySelector("time")).toBeNull();
  const stages = screen.getByRole("tabpanel", { name: "단계" });
  expect(within(stages).getByText("기획 0회 · 평가 0회")).toBeTruthy();
  expect(within(stages).getByText("재작업 0회")).toBeTruthy();
  expect(within(stages).getAllByText("정보 없음")).toHaveLength(3);
  const costs = tab("비용"); expect(within(costs).getByText("텍스트 비용 정보 없음")).toBeTruthy(); expect(within(costs).getByText("정보 없음")).toBeTruthy();
});
it("opens the clicked request when several turns have equal result data and keeps their recorded totals", async () => {
  render(<Page />); await screen.findByLabelText("요청");
  fireEvent.click(screen.getByRole("button", { name: "작업 공간" })); fireEvent.click(screen.getByRole("option", { name: /합성 브랜드/ }));
  for (const message of ["합성 첫 요청", "합성 다음 요청"]) {
    fireEvent.change(screen.getByLabelText("요청"), { target: { value: message } }); fireEvent.click(screen.getByRole("button", { name: "기획하기" }));
    await waitFor(() => expect((screen.getByLabelText("요청") as HTMLTextAreaElement).disabled).toBe(false));
  }
  const links = screen.getAllByRole("link", { name: "검증 상세 보기 →" }); expect(links).toHaveLength(2);
  fireEvent.click(links[1]); expect(within(screen.getByLabelText("실행 요약")).getByText("합성 다음 요청")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "광고 기획" }));
  fireEvent.click(screen.getAllByRole("link", { name: "검증 상세 보기 →" })[0]);
  expect(within(screen.getByLabelText("실행 요약")).getByText("합성 첫 요청")).toBeTruthy();
  cleanup(); detail(); const header = screen.getByLabelText("실행 요약");
  expect(within(header).getByText("8.0초")).toBeTruthy(); expect(within(header).getByText("$0.0623")).toBeTruthy();
});
