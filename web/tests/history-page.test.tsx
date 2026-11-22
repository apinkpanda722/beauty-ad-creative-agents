import { useState } from "react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { AggregatesPanel } from "../components/results/AggregatesPanel";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
async function completedPage() {
  render(<Page />); await screen.findByLabelText("요청");
  fireEvent.click(screen.getByRole("button", { name: "작업 공간" })); fireEvent.click(screen.getByRole("option", { name: /합성 브랜드/ }));
  fireEvent.click(screen.getByRole("button", { name: "+ 새 기획" }));
  fireEvent.change(screen.getByLabelText("요청"), { target: { value: "합성 복귀 요청" } });
  fireEvent.click(screen.getByRole("button", { name: "기획하기" }));
  await screen.findByText("합성 완료");
}
it("returns from a result's detail to the exact plan tabs and result DOM", async () => {
  await completedPage();
  const list = screen.getByRole("tablist", { name: "기획 탭" });
  const selected = within(list).getByRole("tab", { selected: true });
  const result = screen.getByText("합성 기획안");
  fireEvent.click(screen.getByRole("link", { name: "검증 상세 보기 →" }));
  const back = screen.getByRole("button", { name: "광고 기획으로 돌아가기" });
  expect(back.classList.contains("gs-button-secondary")).toBe(true);
  expect(screen.getByRole("button", { name: "목록으로" })).toBeTruthy();
  fireEvent.click(back);
  expect(screen.getByRole("button", { name: "광고 기획" }).getAttribute("aria-current")).toBe("page");
  expect(screen.getByRole("tablist", { name: "기획 탭" })).toBe(list);
  expect(within(list).getAllByRole("tab")).toHaveLength(2);
  expect(within(list).getByRole("tab", { selected: true })).toBe(selected);
  expect(screen.getByText("합성 기획안")).toBe(result);
  expect(screen.getByText("합성 완료")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "광고 기획으로 돌아가기" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "실행 기록·검증" }));
  expect(within(screen.getByLabelText("실행 요약")).getByText("합성 복귀 요청")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "광고 기획으로 돌아가기" })).toBeNull();
});
it("clears the result origin on returning to the list and reopening its row", async () => {
  await completedPage(); fireEvent.click(screen.getByRole("link", { name: "검증 상세 보기 →" }));
  expect(screen.getByRole("button", { name: "광고 기획으로 돌아가기" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "목록으로" }));
  const table = screen.getByRole("table", { name: "실행 요청 목록" });
  fireEvent.click(within(table).getAllByRole("row")[1]);
  expect(screen.getByRole("button", { name: "목록으로" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "광고 기획으로 돌아가기" })).toBeNull();
});
it("has no return action when opening history directly from its list", async () => {
  await completedPage(); fireEvent.click(screen.getByRole("button", { name: "실행 기록·검증" }));
  fireEvent.click(within(screen.getByRole("table", { name: "실행 요청 목록" })).getAllByRole("row")[1]);
  expect(screen.getByRole("button", { name: "목록으로" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "광고 기획으로 돌아가기" })).toBeNull();
});
it("clears the result origin when leaving history through the sidebar", async () => {
  await completedPage(); fireEvent.click(screen.getByRole("link", { name: "검증 상세 보기 →" }));
  expect(screen.getByRole("button", { name: "광고 기획으로 돌아가기" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "근거 소재" }));
  fireEvent.click(screen.getByRole("button", { name: "실행 기록·검증" }));
  expect(screen.getByRole("button", { name: "목록으로" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "광고 기획으로 돌아가기" })).toBeNull();
});
it("omits the optional plan return in a standalone history detail", () => {
  detail();
  expect(screen.getByRole("button", { name: "목록으로" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "광고 기획으로 돌아가기" })).toBeNull();
});
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
it("renders recorded durations and rework counts in the stage table, with only a check for image time", () => {
  detail(); const panel = screen.getByRole("tabpanel", { name: "단계" });
  const table = within(panel).getByRole("table", { name: "단계별 처리 결과" });
  expect(tableCells(table)).toEqual([
    ["요청 해석", "완료", "1.0초"], ["리서치", "완료", "1.0초"], ["기획·평가", "완료 재작업 1회", "5.0초"],
    ["시도 1", "검사 실패 · 최종 실패 · 차별성 2/5 · 요청 적합성 3/5 · 재검토: 차별성", ""],
    ["시도 2", "검사 통과 · 최종 통과 · 차별성 4/5 · 요청 적합성 5/5", ""],
    ["시안", "완료", ""], ["총 시간", "", "8.0초"],
  ]);
  expect(within(panel).getByText("재작업 1회")).toBeTruthy(); expect(within(panel).getByText("기획 2회 · 평가 2회")).toBeTruthy();
  const image = within(table).getByText("시안").closest("tr")!;
  expect(within(image).getByRole("img", { name: "완료" })).toBeTruthy();
  expect(within(image).getAllByRole("cell")[2].textContent).toBe(""); expect(image.querySelector("time")).toBeNull(); expect(image.textContent).not.toMatch(/초|정보 없음/);
});
it("moves checks, verified insight charts and removed values into labeled blocks and hides model values, with identical chart source values", () => {
  detail(); const panel = tab("검증");
  for (const text of ["근거 연결 없음 2건", "인증 연결 없음", "효능 근거 연결 없음", "코드 검사: 실패", "평가 상태: 검토 필요", "검증됨", "제외됨", "합성 제외 항목"]) expect(within(panel).getByText(text)).toBeTruthy();
  for (const text of ["미검증", "합성 모델 항목", "42"]) expect(within(panel).queryByText(text)).toBeNull();
  expect(within(panel).getByText("검증됨").className).toContain("gs-badge-success"); expect(within(panel).getByText("제외됨").className).toContain("gs-badge-neutral");
  expect(within(panel).queryByText("전체 10건 · 표시 2건")).toBeNull();
  expect(within(panel).queryByText("합성 전체 10건 중 2건 표시")).toBeNull();
  expect(panel.querySelectorAll(".gs-source-chip")).toHaveLength(0);
  const verified = within(panel).getByRole("region", { name: "검증된 집계(도구가 센 값)" });
  expect(within(verified).getByRole("heading", { level: 3, name: "검증된 집계(도구가 센 값)" })).toBeTruthy();
  expect(within(verified).getAllByRole("heading", { name: "조회수 상위·하위 25% 광고 비교" })).toHaveLength(1);
  expect(within(panel).queryByRole("table", { name: "시장 인사이트 원천 데이터" })).toBeNull();
  fireEvent.click(within(panel).getByRole("button", { name: "표로 보기" }));
  const sourceTable = within(panel).getByRole("table", { name: "시장 인사이트 원천 데이터" });
  expect(within(sourceTable).getAllByRole("columnheader").map(node => node.textContent)).toEqual(["분류", "상위 25% 광고 수", "하위 25% 광고 수"]);
  const sourceRows = within(sourceTable).getAllByRole("row").slice(1).map(row => within(row).getAllByRole("cell").map(node => node.textContent));
  const standalone = render(<DistributionChart data={distribution} names={taxonomyNames(schema)} />);
  const chart = within(standalone.container).getByRole("region", { name: "분포" });
  const chartRows = within(chart).getAllByRole("row").slice(1).map(row => within(row).getAllByRole("cell").map(node => node.textContent));
  expect(sourceRows).toEqual([["질문형", "7", "2"], ["사용법", "3", "1"]]); expect(sourceRows).toEqual(chartRows);
});
it("keeps exact attempt lines in the stage tab without rationale and preserves the input", () => {
  const snapshot = JSON.stringify(turn); const { container } = detail(); const panel = tab("단계");
  const attempts = [...panel.querySelectorAll(".gs-attempt-line")].map(line => line.closest("tr")!);
  expect(attempts.map(row => within(row).getAllByRole("cell").map(cell => cell.textContent))).toEqual([
    ["시도 1", "검사 실패 · 최종 실패 · 차별성 2/5 · 요청 적합성 3/5 · 재검토: 차별성", ""],
    ["시도 2", "검사 통과 · 최종 통과 · 차별성 4/5 · 요청 적합성 5/5", ""],
  ]);
  expect(screen.getAllByRole("tab").map(item => item.textContent)).toEqual(["단계", "검증", "비용"]);
  expect(screen.queryByRole("tab", { name: "평가" })).toBeNull();
  expect(container.textContent).not.toMatch(/\(differentiation\)|사유:/);
  expect(JSON.stringify(turn)).toBe(snapshot);
});
it("reuses the server cost label and cap with four decimals and missing attempt costs explicit", () => {
  detail(); const panel = tab("비용");
  expect(tableCells(within(panel).getByRole("table", { name: "비용 내역" }))).toEqual([
    ["시도 1", "$0.0123"], ["시도 2", "정보 없음"], ["합성 서버 비용(이미지 제외)", "$0.0623"], ["시안 이미지 생성", "이미지 없음"], ["총 비용", "$0.0623"],
  ]);
  expect(within(panel).queryByText("그 외 텍스트 모델 호출")).toBeNull();
  expect(within(panel).getByText((_, node) => node?.tagName === "P" && node.textContent === "텍스트 비용 상한 $1.0000 중 6% 사용")).toBeTruthy();
  expect(within(panel).getByRole("meter", { name: "텍스트 비용 사용률" }).getAttribute("aria-valuenow")).toBe("6");
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
  expect(tableCells(within(stages).getByRole("table", { name: "단계별 처리 결과" })).map(row => [row[0], row[2]])).toEqual([
    ["요청 해석", "정보 없음"], ["리서치", "정보 없음"], ["기획·평가", "정보 없음"], ["총 시간", "정보 없음"],
  ]);
  const costs = tab("비용"); expect(costs.innerHTML).toBe("<p>비용 정보 없음</p>");
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

it("groups attempts under each plan and omits only missing scores or review items", () => {
  const second = { ...plan, attempts: [
    { attempt: 1, checks_passed: null, final_passed: null, scores: { fit: 4 }, low_items: ["unknown"] },
    { attempt: 2, checks_passed: false, final_passed: false, scores: null },
  ] };
  const input = { ...turn, commands: [{ kind: "show_plan" as const, data: plan }, { kind: "show_plan" as const, data: second }] };
  const snapshot = JSON.stringify(input);
  const { container } = render(<HistoryDetail turn={input} workspace="합성" onBack={vi.fn()} names={taxonomyNames(schema)} />);
  const attempts = [...container.querySelectorAll(".gs-attempt-line")].map(line => line.closest("tr")!);
  expect(attempts.map(row => within(row).getAllByRole("cell")[0].textContent)).toEqual(["기획안 1 · 시도 1", "기획안 1 · 시도 2", "기획안 2 · 시도 1", "기획안 2 · 시도 2"]);
  expect(attempts.slice(2).map(row => within(row).getAllByRole("cell")[1].textContent)).toEqual([
    "검사 미실행 · 최종 미실행 · 요청 적합성 4/5 · 재검토: 기타", "검사 실패 · 최종 실패",
  ]);
  expect(container.textContent).not.toMatch(/사유:|\(fit\)/);
  expect(JSON.stringify(input)).toBe(snapshot);
});
it("adds no placeholder or attempt list when a plan has no attempts", () => {
  const { container } = render(<HistoryDetail turn={{ ...turn, stepAt: undefined, commands: [{ kind: "show_plan", data: { ...plan, attempts: [] } }] }} workspace="합성" onBack={vi.fn()} names={taxonomyNames(schema)} />);
  const panel = screen.getByRole("tabpanel", { name: "단계" });
  expect(panel.querySelector(".gs-attempt-line")).toBeNull();
  expect(tableCells(within(panel).getByRole("table", { name: "단계별 처리 결과" })).map(row => [row[0], row[2]])).toEqual([
    ["요청 해석", "정보 없음"], ["리서치", "정보 없음"], ["기획·평가", "정보 없음"], ["시안", ""], ["총 시간", "정보 없음"],
  ]);
  expect(within(panel).getAllByText("정보 없음")).toHaveLength(4);
  expect(container.querySelector(".gs-history-evaluation")).toBeNull();
  tab("검증"); expect(screen.queryByRole("button", { name: /표로 보기/ })).toBeNull();
});
it("toggles the active axis table in each insight card with localized titles and no empty-rendered columns", () => {
  const input = { ...turn, commands: [
    { kind: "show_distribution" as const, data: { ...distribution, rows: distribution.rows.map((row, index) => ({ ...row, object: { value: 1 }, absent: null, mixed: index ? "표시 값" : null })) } },
    { kind: "show_distribution" as const, data: { tool: "compare_axis_by_category", rows: [{ value: "question", creatives: 2 }] } },
  ] };
  render(<HistoryDetail turn={input} workspace="합성" onBack={vi.fn()} names={taxonomyNames(schema)} />); const panel = tab("검증");
  const cards = [within(panel).getByRole("region", { name: "시장 광고 분포" }), within(panel).getByRole("region", { name: "조회수 상위·하위 25% 광고 비교" })];
  const toggles = cards.map(card => within(card).getByRole("button", { name: "표로 보기" }));
  const contents = toggles.map(toggle => document.getElementById(toggle.getAttribute("aria-controls")!)!);
  expect(toggles.map(toggle => toggle.getAttribute("aria-expanded"))).toEqual(["false", "false"]);
  expect(contents.map(content => content.hidden)).toEqual([true, true]);
  for (const card of cards) expect(within(card).queryByRole("table", { name: "시장 인사이트 원천 데이터" })).toBeNull();
  fireEvent.click(toggles[1]);
  expect(contents.map(content => content.hidden)).toEqual([true, false]);
  expect(toggles[1].getAttribute("aria-expanded")).toBe("true"); expect(toggles[1].textContent).toBe("표 접기");
  const table = within(cards[1]).getByRole("table", { name: "시장 인사이트 원천 데이터" });
  expect(within(table).getAllByRole("columnheader").map(node => node.textContent)).toEqual(["분류", "상위 25% 광고 수", "하위 25% 광고 수", "항목"]);
  expect(within(table).getByText("표시 값")).toBeTruthy();
  fireEvent.click(toggles[0]);
  expect(contents.map(content => content.hidden)).toEqual([false, false]);
  expect(toggles.map(toggle => toggle.textContent)).toEqual(["표 접기", "표 접기"]);
  expect(within(panel).getAllByRole("table", { name: "시장 인사이트 원천 데이터" })).toHaveLength(2);
  expect(within(panel).getAllByRole("heading", { level: 3 }).map(node => node.textContent)).toEqual(["검증된 집계(도구가 센 값)", "시장 광고 분포", "조회수 상위·하위 25% 광고 비교"]);
  expect(panel.querySelector(".gs-source-chip")).toBeNull();
  expect(panel.textContent).not.toMatch(/top_vs_bottom_axis|compare_axis_by_category/);
});
it("matches comparison source and chart column arrays and descriptions exactly", () => {
  detail(); const panel = tab("검증");
  const toggle = within(panel).getByRole("button", { name: "표로 보기" }); fireEvent.click(toggle);
  expect(within(panel).getByRole("button", { name: "표 접기" }).getAttribute("aria-expanded")).toBe("true");
  const table = within(panel).getByRole("table", { name: "시장 인사이트 원천 데이터" });
  const standalone = render(<DistributionChart data={distribution} names={taxonomyNames(schema)} />);
  const chart = within(standalone.container).getByRole("region", { name: "분포" });
  const headers = (element: HTMLElement) => within(element).getAllByRole("columnheader").map(node => node.textContent);
  expect(headers(table)).toEqual(["분류", "상위 25% 광고 수", "하위 25% 광고 수"]);
  expect(headers(chart)).toEqual(headers(table));
  const description = "같은 플랫폼·브랜드 안에서 조회수 상위 25%와 하위 25% 광고가 각 방식을 쓴 광고 수입니다.";
  for (const element of [panel, chart]) expect(within(element).getByText(description).className).toBe("gs-insight-note");
});
it("opens source content synchronously, animates next frame and hides after transition", () => {
  let frame!: FrameRequestCallback;
  vi.stubGlobal("requestAnimationFrame", vi.fn(callback => { frame = callback; return 1; }));
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
  detail(); tab("검증");
  const toggle = screen.getByRole("button", { name: "표로 보기" });
  const content = document.getElementById(toggle.getAttribute("aria-controls")!)!;
  const grid = content.parentElement!;
  fireEvent.click(toggle); expect(content.hidden).toBe(false); expect(grid.classList.contains("gs-open")).toBe(false);
  act(() => frame(0)); expect(grid.classList.contains("gs-open")).toBe(true);
  vi.spyOn(window, "getComputedStyle").mockReturnValue({ transitionDuration: "0.2s", transitionDelay: "0s" } as CSSStyleDeclaration);
  fireEvent.click(toggle); expect(content.hidden).toBe(false); expect(grid.classList.contains("gs-open")).toBe(false);
  fireEvent.transitionEnd(grid, { propertyName: "grid-template-rows" }); expect(content.hidden).toBe(true);
});
it.each([false, true])("hides source content immediately for zero duration or reduced motion=%s", reduced => {
  vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: reduced })));
  detail(); tab("검증");
  const toggle = screen.getByRole("button", { name: "표로 보기" });
  const content = document.getElementById(toggle.getAttribute("aria-controls")!)!;
  fireEvent.click(toggle);
  vi.spyOn(window, "getComputedStyle").mockReturnValue({ transitionDuration: reduced ? "0.2s" : "0ms", transitionDelay: "0s" } as CSSStyleDeclaration);
  fireEvent.click(toggle); expect(content.hidden).toBe(true);
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
it("does not render model-written names and values and leaves the input unchanged", () => {
  const data = { label: "모델 작성값 · 검증되지 않음", verified_counts: [
    { tool: "top_vs_bottom_axis", row_count: 10, shown_count: 2, count_label: "합성 건수" },
    { tool: "unknown_tool", row_count: 2, shown_count: 1, count_label: "합성 다른 건수" },
  ], model_written: [{ name: "sun_protection hook_type", value: "person_first angle how_to format ugc_style" }, { name: "unknown_name", value: "unknown_value" }], removed: [] };
  const inputSchema = { ...schema, taxonomy: { ...schema.taxonomy, hook_type: [{ value: "person_first", name: "인물 먼저 제시형", definition: "합성" }], format: [{ value: "ugc_style", name: "일반인 후기형", definition: "합성" }] }, claims: [{ value: "sun_protection", name: "자외선 차단" }] };
  const snapshot = JSON.stringify({ data, inputSchema });
  const { container } = render(<AggregatesPanel data={data} names={taxonomyNames(inputSchema)} />);
  expect(container.innerHTML).toBe("");
  for (const text of ["자외선 차단 훅", "인물 먼저 제시형 소구 사용법 형식 일반인 후기형", "unknown_name", "unknown_value"]) expect(screen.queryByText(text)).toBeNull();
  expect(container.textContent).not.toMatch(/전체 10건 · 표시 2건|sun_protection|hook_type|person_first|ugc_style/);
  expect(JSON.stringify({ data, inputSchema })).toBe(snapshot);
});
it("keeps check labels, aggregate cards and source area as siblings", () => {
  detail(); const panel = tab("검증");
  const checks = within(panel).getByRole("region", { name: "검사 결과" });
  const label = within(checks).getByText(plan.pattern_alignment_label);
  expect(label.tagName).toBe("SMALL"); expect(label.classList.contains("gs-pattern-label")).toBe(true); expect(label.classList.contains("muted")).toBe(true);
  const aggregateCard = panel.querySelector(".gs-aggregates")!;
  const source = within(panel).getByRole("region", { name: "검증된 집계(도구가 센 값)" });
  expect(checks.parentElement).toBe(aggregateCard.parentElement); expect(source.parentElement).toBe(checks.parentElement);
  expect(aggregateCard.querySelector(".gs-card")).toBeNull();
  for (const card of source.querySelectorAll(".gs-insight-card")) expect(card.querySelector(".gs-card")).toBeNull();
});
it("uses shared card spacing tokens and a reduced-motion grid accordion without full-width block fills", () => {
  const css = (file: string) => readFileSync(join(process.cwd(), `app/${file}.css`), "utf8");
  const globals = css("globals");
  for (const rule of globals.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    if (/\.(verified-block|model-block|removed-block)/.test(rule[1])) expect(rule[2]).not.toMatch(/background|!important/);
  }
  expect(css("tokens")).toMatch(/--gs-card-padding:\s*var\(--gs-space-5\)/);
  expect(css("tokens")).toMatch(/--gs-section-gap:\s*var\(--gs-space-4\)/);
  for (const [file, selector] of [["results", ".gs-aggregates"], ["history", ".gs-history-page .gs-plan-checks"], ["results", ".gs-insight-card"]]) {
    const rules = [...css(file).matchAll(/([^{}]+)\{([^{}]*)\}/g)];
    expect(rules.some(rule => rule[1].split(",").map(value => value.trim()).includes(selector) && /padding:\s*var\(--gs-card-padding\)/.test(rule[2]))).toBe(true);
    expect(css(file)).toContain("var(--gs-section-gap)");
  }
  const history = css("history");
  expect(history).toMatch(/grid-template-rows:\s*0fr/); expect(history).toMatch(/grid-template-rows:\s*1fr/);
  expect(history).toMatch(/transition:\s*grid-template-rows/);
  expect(history.slice(history.indexOf("@media (prefers-reduced-motion: reduce)"))).toMatch(/transition:\s*none/);
});
it("omits nonnumeric score fields individually without changing the server attempt", () => {
  const data = { ...plan, attempts: [
    { attempt: 1, checks_passed: true, final_passed: false, scores: { differentiation: "2", fit: 4, rationale: "합성 숨김 문장" } },
    { attempt: 2, checks_passed: true, final_passed: true, scores: { differentiation: 5, fit: false } },
  ] };
  const snapshot = JSON.stringify(data);
  render(<HistoryDetail turn={{ ...turn, commands: [{ kind: "show_plan", data }] }} workspace="합성" onBack={vi.fn()} names={taxonomyNames(schema)} />);
  const panel = screen.getByRole("tabpanel", { name: "단계" });
  expect([...panel.querySelectorAll(".gs-attempt-line")].map(line => within(line.closest("tr")!).getAllByRole("cell").map(cell => cell.textContent))).toEqual([
    ["시도 1", "검사 통과 · 최종 실패 · 요청 적합성 4/5", ""],
    ["시도 2", "검사 통과 · 최종 통과 · 차별성 5/5", ""],
  ]);
  expect(document.body.textContent).not.toContain("합성 숨김 문장");
  expect(JSON.stringify(data)).toBe(snapshot);
});

it("does not draw model breakdowns or list items beside verified charts and leaves aggregates unchanged", () => {
  const data = { ...aggregate.data, model_written: [
    { name: " 오프닝 유형 ", value: "question 3/7; problem 2/7" },
    { name: "합성 모델 항목", value: 42 }, { name: "알 수 없는 축", value: "question 1/7" },
  ] };
  const input: UiCommand[] = [{ kind: "show_distribution", data: { tool: "compare_axis_by_category", rows: [{ value: "question", creatives: 4 }] } }, { kind: "show_aggregates", data }];
  const snapshot = JSON.stringify(input);
  render(<HistoryDetail turn={{ ...turn, commands: input }} workspace="합성" onBack={vi.fn()} names={taxonomyNames({ ...schema, taxonomy: { ...schema.taxonomy, hook_type: [...schema.taxonomy.hook_type, { value: "problem", name: "문제 제시형", definition: "합성" }] } })} />);
  const panel = tab("검증");
  expect(within(panel).queryByRole("region", { name: "모델 작성값 차트" })).toBeNull();
  expect(within(panel).queryByRole("region", { name: "모델 작성값" })).toBeNull();
  expect(within(panel).getAllByRole("meter").map(node => [node.getAttribute("aria-label"), node.getAttribute("value")])).toEqual([["질문형", "4"]]);
  for (const text of ["3/7", "2/7", "합성 모델 항목", "42", "알 수 없는 축", "질문형 1/7", "오프닝 유형"]) expect(within(panel).queryByText(text)).toBeNull();
  expect(within(panel).queryByRole("region", { name: "시장 인사이트 원천" })).toBeNull();
  expect(within(panel).queryByText("시장 인사이트 원천")).toBeNull();
  expect(within(panel).queryByRole("button", { name: /원천 데이터 보기/ })).toBeNull();
  expect(JSON.stringify(input)).toBe(snapshot);
});
it("does not list model values when the competitor card is absent", () => {
  render(<HistoryDetail turn={{ ...turn, commands: [{ kind: "show_distribution", data: distribution }, { kind: "show_aggregates", data: { ...aggregate.data, model_written: [{ name: "훅", value: "question 3/7" }] } }] }} workspace="합성" onBack={vi.fn()} names={taxonomyNames(schema)} />);
  const panel = tab("검증");
  expect(within(panel).queryByRole("region", { name: "모델 작성값 차트" })).toBeNull();
  expect(within(panel).queryByRole("region", { name: "모델 작성값" })).toBeNull();
  expect(within(panel).queryByText("질문형 3/7")).toBeNull();
});
function tableCells(table: HTMLElement) { return within(table).getAllByRole("row").slice(1).map(row => within(row).getAllByRole("cell").map(cell => cell.textContent)); }
it("uses first supplied text and image costs in the summary and itemized table with a calculated remainder", () => {
  const first = { ...cost, data: { ...cost.data, image_cost_usd: .0336 } };
  const input: UiCommand[] = [{ kind: "show_plan", data: { ...plan, attempts: [{ attempt: 1, cost_usd: .012345 }, { attempt: 2, cost_usd: .02 }] } }, first, { ...cost, data: { ...cost.data, label: "합성 무시할 비용", text_spent_usd: 5, image_cost_usd: 10 } }];
  const snapshot = JSON.stringify(input);
  render(<HistoryDetail turn={{ ...turn, commands: input }} workspace="합성" onBack={vi.fn()} />);
  expect(within(screen.getByLabelText("실행 요약")).getByText("$0.0959")).toBeTruthy();
  const panel = tab("비용");
  expect(tableCells(within(panel).getByRole("table", { name: "비용 내역" }))).toEqual([
    ["시도 1", "$0.0123"], ["시도 2", "$0.0200"], ["그 외 텍스트 모델 호출", "$0.0300"],
    ["합성 서버 비용(이미지 제외)", "$0.0623"], ["시안 이미지 생성", "$0.0336"], ["총 비용", "$0.0959"],
  ]);
  expect(within(panel).getByText("그 외 텍스트 모델 호출은 텍스트 모델 비용에서 시도별 비용 합계를 뺀 계산값입니다.")).toBeTruthy();
  expect(within(panel).getByText("$0.0959").tagName).toBe("STRONG");
  expect(panel.textContent).not.toContain("합성 무시할 비용");
  expect(JSON.stringify(input)).toBe(snapshot);
});
it("keeps the server label verbatim and four decimal costs from the first command, and omits missing costs", () => {
  const first: UiCommand = { kind: "show_cost", data: { label: "합성 비용 레이블(이미지 제외)", text_spent_usd: .012345, max_text_cost_usd: 1 } };
  const { rerender } = render(<HistoryDetail turn={{ ...turn, commands: [first, cost] }} workspace="합성" onBack={vi.fn()} />);
  const panel = tab("비용");
  expect(tableCells(within(panel).getByRole("table", { name: "비용 내역" }))).toContainEqual(["합성 비용 레이블(이미지 제외)", "$0.0123"]);
  expect(panel.textContent?.match(/이미지 제외/g)).toHaveLength(1);
  expect(panel.textContent).not.toContain("합성 서버 비용");
  expect(within(screen.getByLabelText("실행 요약")).getByText("$0.0123")).toBeTruthy();
  rerender(<HistoryDetail turn={{ ...turn, commands: [] }} workspace="합성" onBack={vi.fn()} />);
  expect(screen.getByRole("tabpanel", { name: "비용" }).innerHTML).toBe("<p>비용 정보 없음</p>");
});
it.each([0, -1])("omits the cap line and meter for a nonpositive cap=%s", cap => {
  render(<HistoryDetail turn={{ ...turn, commands: [{ ...cost, data: { ...cost.data, max_text_cost_usd: cap } }] }} workspace="합성" onBack={vi.fn()} />);
  const panel = tab("비용"); expect(within(panel).queryByRole("meter")).toBeNull(); expect(panel.textContent).not.toContain("텍스트 비용 상한");
});
it("caps only the cost meter at 100 and explains the text cap on focus", () => {
  render(<HistoryDetail turn={{ ...turn, commands: [{ ...cost, data: { ...cost.data, text_spent_usd: .6, max_text_cost_usd: .3, image_cost_usd: 0 } }] }} workspace="합성" onBack={vi.fn()} />);
  const panel = tab("비용");
  expect(within(panel).getByText((_, node) => node?.tagName === "P" && node.textContent === "텍스트 비용 상한 $0.3000 중 200% 사용")).toBeTruthy();
  const meter = within(panel).getByRole("meter", { name: "텍스트 비용 사용률" }); expect(meter.getAttribute("value")).toBe("100");
  fireEvent.focus(within(panel).getByText("상한"));
  expect(screen.getByRole("tooltip").textContent).toBe("요청 하나가 쓸 수 있는 텍스트 비용 한도입니다.");
  expect(tableCells(within(panel).getByRole("table", { name: "비용 내역" }))).toContainEqual(["시안 이미지 생성", "$0.0000"]);
});
it("explains only the score words in the stage table on focus", () => {
  detail(); const panel = screen.getByRole("tabpanel", { name: "단계" });
  const line = panel.querySelector<HTMLElement>(".gs-attempt-line")!;
  const triggers = line.querySelectorAll<HTMLElement>(".gs-tooltip-trigger");
  expect([...triggers].map(node => node.textContent)).toEqual(["차별성", "요청 적합성"]);
  for (const trigger of triggers) { fireEvent.focus(trigger); expect(screen.getByRole("tooltip").textContent).toContain("1~5점"); fireEvent.blur(trigger); }
});
