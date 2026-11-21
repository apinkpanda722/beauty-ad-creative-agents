import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { PlanPage } from "../components/plan/PlanPage";
import { EvidencePage } from "../components/evidence/EvidencePage";
import Page from "../app/page";
import { EvidenceSummary } from "../components/evidence/EvidenceSummary";
import { PlanResult } from "../components/results/PlanResult";
import { AggregatesPanel } from "../components/results/AggregatesPanel";
import { DistributionChart } from "../components/results/DistributionChart";
import { DesignImage } from "../components/results/DesignImage";
import { FeedbackBar, FeedbackSession } from "../components/results/FeedbackBar";
import { TurnCard } from "../components/plan/TurnCard";
import { ProgressTracker } from "../components/plan/ProgressTracker";
import { ResultsView, CommandTenantContext } from "../components/results/ResultsView";
import { initialState, reducer } from "../lib/reducer";
import { WorkspaceChip } from "../components/shell/WorkspaceChip";
import { SessionProvider, useSession } from "../lib/session";
import { deriveProgress } from "../lib/stages";
import { PLAN_INTRO_TEXT } from "../lib/text";
import { CostLine } from "../components/results/CostLine";
import { ApiError, getSchema, getDesignImage, postFeedback } from "../lib/api";
import { taxonomyNames } from "../lib/taxonomy";
import type { EvidenceCard, PlanView, SchemaResponse, SseFrame, UiCommand } from "../lib/types";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });
const schema: SchemaResponse = { labels: [], relationships: [], taxonomy: {
  hook_type: [{ value: "question", name: "합성 훅", definition: "합성 정의" }],
  angle: [{ value: "how_to", name: "합성 소구", definition: "합성 정의" }],
  format: [{ value: "demo", name: "합성 형식", definition: "합성 정의" }],
}, claims: [{ value: "hydration", name: "합성 효능" }] };
const card: EvidenceCard = { evidence_id: "youtube:abc_123-", source: "youtube", url: "https://example.test/a", brand: "합성 브랜드", title: "합성 근거", published_at: null, view_count: null, like_count: null, hook_type: null, angle: null, format: null, talent: null, cta_type: null, claims: null };
const plan: PlanView = {
  plan: { title: "합성 기획", hook_text: "합성 훅 문구", hook_type: "question", angle: "how_to", format: "demo", scenes: ["합성 장면"], copy_lines: ["합성 카피"], claimed_efficacy: ["hydration", "soothing"], evidence_ids: [card.evidence_id!, "youtube:absent"] },
  plan_id: null, passed: true, unknown_count: 0, unknown_codes: {}, efficacy_status: { hydration: "supported", soothing: "unknown" }, efficacy_summary: { supported: 1, unknown: 1 }, count_label: "합성 건수", result_counts: [], evidence_counts: { in_plan: 2, in_pool: 3 }, status: "needs_review",
  attempts: [{ attempt: 1, scores: { differentiation: 2, fit: 3 }, low_items: ["differentiation"], checks_passed: true, final_passed: false }],
  pattern_alignment: { axes: { hook_type: { plan: "question", dominant: ["question"], same: true, share: .25 }, angle: { plan: "how_to", dominant: ["desire"], same: false, share: null }, format: { plan: null, dominant: [], same: null, share: null } }, compared: 2, same_count: 1, skipped: 0 }, pattern_alignment_label: "코드 계산, 판정 아님", disclaimer: "합성 면책 그대로", image: null, design_disclaimer: null, product_display: { brand: null, display_name: null, product_name: null },
};
const aggregates: Extract<UiCommand, { kind: "show_aggregates" }>["data"] = { label: "모델 작성값 · 검증되지 않음", verified_counts: [{ tool: "synthetic_tool", row_count: 5, shown_count: 3, count_label: "합성 도구 건수" }], model_written: [{ name: "synthetic_model", value: "합성 모델 값" }], removed: ["synthetic_removed"] };
const image = { request_key: "synthetic/key", index: 0, mime: "image/png" as const, size: 1, sha256: "a".repeat(64) };
const names = taxonomyNames(schema);

function TestWorkspace() {
  const { state, selectWorkspace } = useSession();
  return <WorkspaceChip workspaces={[{ tenant_id: "synthetic", display_name: "합성 공간", brand: null, product_name: null }]} value={state.tenantId} onChange={selectWorkspace} />;
}
function expandAll() { for (const button of screen.queryAllByRole("button", { name: "전체 보기 →", expanded: false })) fireEvent.click(button); }
function turnsWithCards(cards: EvidenceCard[][]) {
  return cards.map(cards => ({ commands: [{ kind: "show_evidence_cards" as const, data: { cards, missing: 0 } }] }));
}
it("groups platforms with direct YouTube thumbnails and neutral monogram tiles, including failed thumbnails", () => {
  const cards = [card, { ...card, evidence_id: "instagram:a", source: "instagram", title: "합성 인스타", hook_type: "question" }, { ...card, evidence_id: "tiktok:a", source: "tiktok", title: "합성 틱톡", hook_type: "question" }];
  render(<EvidencePage turns={turnsWithCards([cards])} workspaceBrand={null} onPlan={vi.fn()} />);
  expect(screen.getAllByRole("heading", { level: 2 }).map(node => node.textContent)).toEqual(["Instagram · 1건", "TikTok · 1건", "YouTube · 1건"]);
  for (const [source, label, monogram] of [["instagram", "Instagram", "I"], ["tiktok", "TikTok", "T"]]) {
    const tile = screen.getByLabelText(`${source} 출처`);
    expect(tile.textContent).toContain(label);
    expect(within(tile).getByText(monogram)).toBeTruthy();
    expect(within(tile.closest("article")!).getByText("question")).toBeTruthy();
    expect(tile.closest("article")!.querySelector("img")).toBeNull();
  }
  const thumbnail = screen.getByRole("img");
  expect(thumbnail.getAttribute("src")).toBe("https://i.ytimg.com/vi/abc_123-/hqdefault.jpg");
  fireEvent.error(thumbnail);
  const fallback = screen.getByLabelText("youtube 출처");
  expect(within(fallback).getByText("YouTube")).toBeTruthy();
  expect(within(fallback).getByText("Y")).toBeTruthy();
  expect(screen.queryByRole("img")).toBeNull();
});
it("marks only the workspace brand, filters own/platform cards and restores all cards", () => {
  const cards = [{ ...card, brand: "isntree" }, { ...card, evidence_id: "instagram:b", source: "instagram", title: "다른 브랜드", brand: "cosrx" }];
  render(<EvidencePage turns={turnsWithCards([cards])} workspaceBrand="isntree" onPlan={vi.fn()} />);
  expect(screen.getAllByText("자사")).toHaveLength(1);
  expect(screen.getByText("자사").closest("article")!.textContent).toContain("합성 근거");
  fireEvent.click(screen.getByRole("button", { name: "자사만" }));
  expect(screen.getByRole("button", { name: "자사만" }).getAttribute("aria-pressed")).toBe("true");
  expect(screen.getByRole("link", { name: "합성 근거" })).toBeTruthy();
  expect(screen.queryByRole("link", { name: "다른 브랜드" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "전체" }));
  fireEvent.click(screen.getByRole("button", { name: "Instagram" }));
  expect(screen.queryByRole("link", { name: "합성 근거" })).toBeNull();
  expect(screen.getByRole("link", { name: "다른 브랜드" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "전체" }));
  expect(screen.getAllByRole("article")).toHaveLength(2);
});
it("offers the plan action for empty sessions and empty filters, deduplicates across turns and retains unknown platforms", () => {
  const onPlan = vi.fn();
  const { rerender } = render(<EvidencePage turns={[]} workspaceBrand={null} onPlan={onPlan} />);
  expect(screen.getByRole("heading", { name: "아직 근거 소재가 없습니다" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "광고 기획으로" })); expect(onPlan).toHaveBeenCalledTimes(1);
  const unknown = { ...card, source: "new-platform", evidence_id: "new-platform:a" };
  rerender(<EvidencePage turns={turnsWithCards([[unknown], [unknown]])} workspaceBrand={null} onPlan={onPlan} />);
  expect(screen.getAllByRole("article")).toHaveLength(1);
  expect(screen.getByRole("heading", { name: "new-platform · 1건" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "자사만" }));
  expect(screen.queryByRole("article")).toBeNull();
  expect(screen.getByRole("heading", { name: "조건에 맞는 근거 소재가 없습니다" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "광고 기획으로" })).toBeTruthy();
});
it("keeps evidence anchors turn-local and unique when commands repeat within and across turns", () => {
  const commands: UiCommand[] = [{ kind: "show_plan", data: plan }, { kind: "show_evidence_cards", data: { cards: [card], missing: 0 } }, { kind: "show_evidence_cards", data: { cards: [card], missing: 1 } }];
  render(<><ResultsView commands={commands} /><ResultsView commands={commands} /></>);
  expandAll();
  const links = screen.getAllByRole("link", { name: card.evidence_id! });
  expect(links).toHaveLength(2);
  const targets = links.map(link => link.getAttribute("href")!.slice(1));
  expect(targets[0]).not.toBe(targets[1]);
  for (const target of targets) {
    expect(Array.from(document.querySelectorAll("[id]")).filter(node => node.id === target)).toHaveLength(1);
    expect(document.getElementById(target)!.textContent).toContain("합성 근거");
  }
});
it("connects the evidence navigation to session cards, own-brand summaries and the empty-state plan action", async () => {
  const command: UiCommand = { kind: "show_evidence_cards", data: { cards: [{ ...card, brand: "isntree" }], missing: 0 } };
  vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => Promise.resolve(new Response(url === "/api/workspaces" ? JSON.stringify({ workspaces: [{ tenant_id: "synthetic", display_name: "합성 공간", brand: "isntree", product_name: null }], image_enabled: false }) : url === "/api/graph/schema" ? JSON.stringify(schema) : `event: ui_command\ndata: ${JSON.stringify(command)}\n\nevent: token\ndata: {"text":"합성 응답"}\n\n`))));
  render(<Page />);
  await screen.findByLabelText("작업 공간");
  fireEvent.click(screen.getByRole("button", { name: "근거 소재" }));
  fireEvent.click(screen.getByRole("button", { name: "광고 기획으로" }));
  fireEvent.click(screen.getByRole("button", { name: "작업 공간" })); fireEvent.click(await screen.findByRole("option", { name: /합성 공간/ }));
  fireEvent.change(screen.getByLabelText("요청"), { target: { value: "합성 요청" } });
  fireEvent.click(screen.getByRole("button", { name: "기획하기" }));
  await screen.findByText("합성 응답");
  expect(screen.getByText("자사")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "근거 소재" }));
  expect(screen.getByRole("heading", { name: "YouTube · 1건" })).toBeTruthy();
  expect(screen.getAllByRole("link", { name: "합성 근거" })).toHaveLength(1);
  expect(within(screen.getByRole("region", { name: "YouTube · 1건" })).getByText("자사")).toBeTruthy();
});

it("renders separate code checks, evaluation state, unknown badge, neutral pattern and raw taxonomy fallback", () => {
  const { container, rerender } = render(<PlanResult data={plan} tenantId="synthetic" evidenceAnchors={{ [card.evidence_id!]: "synthetic-anchor" }} />);
  expect(screen.getByText("근거 연결 없음 0건").className).toContain("clear");
  expect(screen.getByText("코드 검사: 통과")).toBeTruthy();
  expect(screen.getByText("평가 상태: 검토 필요")).toBeTruthy();
  expect(screen.getByText("question")).toBeTruthy();
  for (const label of ["같음", "다름", "비교 불가", "점유율 비교 불가", "비교한 축 2개 중 같은 축 1개", plan.pattern_alignment_label, plan.disclaimer]) expect(screen.getAllByText(label).length).toBeGreaterThan(0);
  expect(container.textContent).not.toMatch(/좋음|나쁨|우수|미달/);
  expandAll();
  expect(screen.getByRole("link", { name: card.evidence_id! }).getAttribute("href")).toBe("#synthetic-anchor");
  expect(screen.queryByRole("link", { name: "youtube:absent" })).toBeNull();
  expect(screen.getByText(/되돌림 0회/)).toBeTruthy();
  expect(screen.getByText(/차별성 \(differentiation\): 2/)).toBeTruthy();
  rerender(<PlanResult data={{ ...plan, unknown_count: 3, unknown_codes: { CERT_REQUIRED_UNVERIFIED: 1, EFFICACY_UNKNOWN: 1, SYNTHETIC_UNKNOWN: 1 }, passed: false, status: "failed" }} tenantId="synthetic" names={names} />);
  expect(screen.getByText("근거 연결 없음 3건").className).toContain("attention");
  expect(screen.getByText("인증 연결 없음").textContent).toBe("인증 연결 없음");
  expect(screen.getByText("효능 근거 연결 없음").textContent).toBe("효능 근거 연결 없음");
  expect(screen.getByText("SYNTHETIC_UNKNOWN").textContent).toBe("SYNTHETIC_UNKNOWN");
  expect(screen.getByText("코드 검사: 실패")).toBeTruthy();
  expect(screen.getByText("평가 상태: 실패")).toBeTruthy();
  expect(screen.getAllByText("합성 효능 · 확인됨")).toHaveLength(2);
  expect(screen.getAllByText("soothing · 근거 연결 없음")).toHaveLength(2);
});
it("keeps aggregate provenance in three distinct blocks, including removed-only and empty", () => {
  const { rerender, container } = render(<AggregatesPanel data={aggregates} />);
  const verified = screen.getByRole("region", { name: "검증된 집계(도구가 센 값)" });
  expect(within(verified).getByText("합성 도구 건수")).toBeTruthy();
  expect(verified.textContent).not.toMatch(/synthetic_model|합성 모델 값/);
  const model = screen.getByRole("region", { name: "모델 작성값" });
  expect(within(model).getByText(aggregates.label)).toBeTruthy();
  expect(model.textContent).toContain("합성 모델 값");
  expect(model.textContent).not.toMatch(/확인됨|검증됨/);
  expect(screen.getByRole("region", { name: "제외된 값" }).textContent).toContain("synthetic_removed");
  rerender(<AggregatesPanel data={{ ...aggregates, verified_counts: [], model_written: [] }} />);
  expect(screen.getByText("synthetic_removed")).toBeTruthy();
  expect(screen.queryByRole("region", { name: "모델 작성값" })).toBeNull();
  rerender(<AggregatesPanel data={{ ...aggregates, verified_counts: [], model_written: [], removed: [] }} />);
  expect(container.innerHTML).toBe("");
});
it("shows all six analysis attributes using schema and closed maps, raw unknown values and neutral absent analysis", () => {
  const labeled = { ...card, hook_type: "question", angle: "how_to", format: "demo", talent: "ordinary_person", cta_type: "shop_now", claims: ["hydration", "synthetic_claim"] };
  const { rerender, container } = render(<EvidenceSummary data={{ cards: [labeled], missing: 0 }} names={names} />);
  for (const text of ["합성 훅", "합성 소구", "합성 형식", "일반 출연자", "구매 유도", "합성 효능", "synthetic_claim"]) expect(screen.getByText(text)).toBeTruthy();
  expect(container.textContent).not.toMatch(/좋음|효과적|인기|우수|나쁨/);
  rerender(<EvidenceSummary data={{ cards: [card], missing: 0 }} />);
  expect(screen.getByText("분석 대상 아님").className).toBe("muted");
  rerender(<EvidenceSummary data={{ cards: [{ ...card, talent: "synthetic_talent", cta_type: "synthetic_cta" }], missing: 0 }} />);
  expect(screen.getByText("synthetic_talent")).toBeTruthy(); expect(screen.getByText("synthetic_cta")).toBeTruthy();
  expect(screen.queryByText("분석 대상 아님")).toBeNull(); expect(screen.queryByText("합성 훅")).toBeNull();
});
it("validates thumbnail IDs and external schemes, handles nulls, missing and image load failure", () => {
  const { rerender } = render(<EvidenceSummary data={{ cards: [card], missing: 2 }} />);
  const thumbnail = screen.getByRole("img") as HTMLImageElement;
  expect(thumbnail.getAttribute("src")).toBe("https://i.ytimg.com/vi/abc_123-/hqdefault.jpg");
  expect(thumbnail.getAttribute("referrerpolicy")).toBe("no-referrer"); expect(thumbnail.getAttribute("loading")).toBe("lazy");
  const link = screen.getByRole("link"); expect(link.getAttribute("rel")).toBe("noopener noreferrer"); expect(link.getAttribute("target")).toBe("_blank");
  expect(screen.getByText("조회수 정보 없음")).toBeTruthy(); expect(screen.getByText("게시일 정보 없음")).toBeTruthy(); expect(screen.getByText(/2건.*불러오지 못/)).toBeTruthy();
  fireEvent.error(thumbnail); expect(screen.queryByRole("img")).toBeNull(); expect(screen.getByLabelText("youtube 출처")).toBeTruthy();
  rerender(<EvidenceSummary data={{ cards: [{ ...card, evidence_id: "youtube:bad/id", url: "javascript:alert(1)" }, { ...card, evidence_id: "instagram:b", source: "instagram", url: "" }, { ...card, evidence_id: "tiktok:c", source: "tiktok", url: "http://example.test/" }], missing: 0 }} />);
  expect(screen.queryByRole("img")).toBeNull(); expect(screen.getAllByRole("link")).toHaveLength(1);
  expect(screen.getByLabelText("instagram 출처")).toBeTruthy(); expect(screen.getByLabelText("tiktok 출처")).toBeTruthy();
});
it("uses bars only for string value + integer creatives, tables for other rows, tolerating nested values", () => {
  render(<DistributionChart data={{ tool: "synthetic", rows: [{ value: "합성 축", creatives: 3, total: 6 }, { value: "합성 축 B", creatives: 0 }, { category: "합성 열", count: 2, nested: [{ a: 1 }] }, { value: "합성 소수", creatives: 1.5, object: { a: 1 } }] }} />);
  expect(screen.getAllByRole("meter")).toHaveLength(2);
  expect(screen.getByRole("meter", { name: "합성 축" }).getAttribute("aria-valuenow")).toBe("3");
  expect(screen.getByRole("table").textContent).toContain("합성 열"); expect(screen.getByRole("table").textContent).toContain("합성 소수");
});
it("fetches images with tenant headers, encodes path and revokes blobs on unmount", async () => {
  const fetch = vi.fn().mockResolvedValue(new Response(new Blob(["synthetic"]))); vi.stubGlobal("fetch", fetch);
  const create = vi.fn().mockReturnValue("blob:synthetic"); const revoke = vi.fn();
  vi.stubGlobal("URL", Object.assign(class extends URL {}, { createObjectURL: create, revokeObjectURL: revoke }));
  const { unmount } = render(<DesignImage tenantId="synthetic" image={image} disclaimer="합성 이미지 면책" />);
  await screen.findByRole("img"); expect(fetch).toHaveBeenCalledExactlyOnceWith("/api/design/synthetic%2Fkey/0", { headers: { "X-Tenant-Id": "synthetic" } });
  expect(create).toHaveBeenCalledTimes(1); expect(screen.getByRole("img").getAttribute("src")).toBe("blob:synthetic");
  expect(screen.getByText("합성 이미지 면책")).toBeTruthy(); unmount(); expect(revoke).toHaveBeenCalledExactlyOnceWith("blob:synthetic");
});
it.each([[404, "DESIGN_NOT_FOUND", true], [500, "SYNTHETIC_ERROR", false]])("shows image failure for %s without leaking other error codes", async (status, code, showCode) => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: code }), { status })));
  render(<DesignImage tenantId="synthetic" image={image} disclaimer={null} />);
  expect(await screen.findByText(/시안 이미지를 불러오지 못했습니다/)).toBeTruthy();
  expect(document.body.textContent?.includes(code)).toBe(showCode);
});
it("does not create a blob after unmount while a request is pending", async () => {
  let resolve!: (r: Response) => void;
  vi.stubGlobal("fetch", vi.fn().mockImplementation(() => new Promise<Response>(r => { resolve = r; })));
  const create = vi.fn(); vi.stubGlobal("URL", Object.assign(class extends URL {}, { createObjectURL: create, revokeObjectURL: vi.fn() }));
  const { unmount } = render(<DesignImage tenantId="synthetic" image={image} disclaimer={null} />); unmount();
  await act(async () => resolve(new Response(new Blob(["synthetic"])))); expect(create).not.toHaveBeenCalled();
});
it.each(["approved", "rejected"] as const)("validates reasons and submits exact %s body only once while pending and after success", async decision => {
  let resolve!: (r: Response) => void;
  const fetch = vi.fn().mockImplementation(() => new Promise<Response>(r => { resolve = r; })); vi.stubGlobal("fetch", fetch);
  render(<FeedbackBar tenantId="synthetic" planId="synthetic-plan" />);
  expect((screen.getByRole("button", { name: "반려" }) as HTMLButtonElement).disabled).toBe(true);
  if (decision === "rejected") fireEvent.change(screen.getByLabelText("피드백 사유"), { target: { value: "합성 사유" } });
  const button = screen.getByRole("button", { name: decision === "approved" ? "승인" : "반려" });
  fireEvent.click(button); fireEvent.click(button);
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ plan_id: "synthetic-plan", decision, reason: decision === "approved" ? "" : "합성 사유" });
  expect(fetch.mock.calls[0][1].headers["X-Tenant-Id"]).toBe("synthetic");
  await act(async () => resolve(new Response('{"status":"ok"}')));
  expect(await screen.findByText("저장했습니다")).toBeTruthy(); expect(screen.queryByRole("button")).toBeNull();
});
it("hides feedback with null ID and shows server error codes", async () => {
  const { rerender } = render(<FeedbackBar tenantId="synthetic" planId={null} />); expect(screen.queryByRole("button")).toBeNull();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response('{"detail":"PLAN_NOT_FOUND"}', { status: 404 })));
  rerender(<FeedbackBar tenantId="synthetic" planId="synthetic" />); fireEvent.click(screen.getByRole("button", { name: "승인" })); expect(await screen.findByText("PLAN_NOT_FOUND")).toBeTruthy();
});
it("shows cost only when supplied with verbatim label and four decimals", () => {
  const { rerender, container } = render(<CostLine />); expect(container.innerHTML).toBe("");
  rerender(<CostLine data={{ label: "합성 비용 레이블(이미지 제외)", text_spent_usd: .012345, max_text_cost_usd: 1 }} />);
  expect(container.textContent).toContain("합성 비용 레이블"); expect(container.textContent).toContain("$0.0123"); expect(container.textContent?.match(/이미지 제외/g)).toHaveLength(1);
  expect(container.textContent).toBe("이 요청의 합성 비용 레이블(이미지 제외) $0.0123");
});
it("fetches schema and reports non-200 API errors with status-first parsing", async () => {
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(schema))); vi.stubGlobal("fetch", fetch);
  expect(await getSchema("synthetic")).toEqual(schema); expect(fetch).toHaveBeenCalledExactlyOnceWith("/api/graph/schema", { headers: { "X-Tenant-Id": "synthetic" } });
  expect(taxonomyNames().axisName("hook_type", "other")).toBe("other"); expect(names.claimName("synthetic_unknown")).toBe("synthetic_unknown");
  for (const [status, body, code] of [[404, '{"detail":"PLAN_NOT_FOUND"}', "PLAN_NOT_FOUND"], [422, '{"detail":[]}', null], [500, "not JSON", null], [201, "null", null]] as const) {
    for (const invoke of [() => postFeedback({ tenantId: "synthetic", planId: "synthetic", decision: "approved", reason: "" }), () => getSchema("synthetic"), () => getDesignImage("synthetic", "key", 0)]) {
      fetch.mockImplementation(() => Promise.resolve(new Response(body, { status })));
      const result = invoke(); await expect(result).rejects.toBeInstanceOf(ApiError);
      await expect(result).rejects.toMatchObject({ status, code });
    }
  }
});
it.each([true, false])("renders ordered command components in PlanPage with schema success=%s and display_text only", async success => {
  const commands: UiCommand[] = [{ kind: "show_cost", data: { label: "합성 비용", text_spent_usd: .01, max_text_cost_usd: 1 } }, { kind: "show_aggregates", data: aggregates }, { kind: "show_distribution", data: { tool: "synthetic", rows: [{ value: "합성 분포", creatives: 1 }] } }, { kind: "show_plan", data: plan }, { kind: "show_plan", data: { ...plan, plan: { title: "합성 두 번째 기획" } } }, { kind: "show_evidence_cards", data: { cards: [card], missing: 0 } }];
  const frames: SseFrame[] = [...commands.map(data => ({ event: "ui_command" as const, data })), { event: "token", data: { text: "합성 숨긴 원문", display_text: "합성 화면 문장" } }];
  const bytes = new TextEncoder().encode(frames.map(f => `event: ${f.event}\ndata: ${JSON.stringify(f.data)}\n\n`).join(""));
  const fetch = vi.fn().mockImplementation((url: string) => Promise.resolve(url === "/api/graph/schema" ? new Response(JSON.stringify(success ? schema : { detail: "GRAPH_UNAVAILABLE" }), { status: success ? 200 : 503 }) : new Response(new ReadableStream({ start(c) { c.enqueue(bytes); c.close(); } })))); vi.stubGlobal("fetch", fetch);
  render(<><TestWorkspace /><PlanPage workspaces={[{ tenant_id: "synthetic", display_name: "합성 공간", brand: null, product_name: null }]} imageEnabled={false} /></>, { wrapper: SessionProvider });
  fireEvent.click(screen.getByRole("button", { name: "작업 공간" })); fireEvent.click(await screen.findByRole("option", { name: /합성 공간/ })); fireEvent.change(screen.getByLabelText("요청"), { target: { value: "합성 요청" } }); fireEvent.click(screen.getByRole("button", { name: "기획하기" }));
  await screen.findByText("합성 화면 문장"); await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  const nodes = [screen.getByLabelText("합성 비용"), screen.getByText("합성 화면 문장"), screen.getByRole("heading", { name: "합성 기획" }), screen.getByRole("heading", { name: "합성 두 번째 기획" }), screen.getByRole("region", { name: "근거 소재" }), screen.getByRole("region", { name: "분포" }), screen.getByRole("region", { name: "검증된 집계(도구가 센 값)" })];
  for (let i = 1; i < nodes.length; i++) expect(nodes[i - 1].compareDocumentPosition(nodes[i]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(screen.getByLabelText("합성 비용").textContent).toBe("$0.010");
  expandAll();
  expect(screen.queryByText("합성 숨긴 원문")).toBeNull(); expect(screen.getByRole("link", { name: card.evidence_id! }).getAttribute("href")).toBe(`#${screen.getByRole("region", { name: "근거 소재" }).querySelector("article")!.id}`);
});
it("shares pending and saved feedback across copies of the same plan in the conversation", async () => {
  let resolve!: (r: Response) => void;
  const fetch = vi.fn().mockImplementation(() => new Promise<Response>(r => { resolve = r; })); vi.stubGlobal("fetch", fetch);
  render(<FeedbackSession><FeedbackBar tenantId="synthetic" planId="same-plan" /><FeedbackBar tenantId="synthetic" planId="same-plan" /></FeedbackSession>);
  const buttons = screen.getAllByRole("button", { name: "승인" }); fireEvent.click(buttons[0]); fireEvent.click(buttons[1]); expect(fetch).toHaveBeenCalledTimes(1);
  await act(async () => resolve(new Response('{"status":"ok"}')));
  expect(screen.getAllByText("저장했습니다")).toHaveLength(2); expect(screen.queryByRole("button")).toBeNull();
});


it.each([
  ["2026-10-01T00:00:00+00:00", "2026-10-01"],
  ["2026-10-01T23:30:00-05:00", "2026-10-01"],
  ["2026-10-01", "2026-10-01"],
  ["합성 날짜 원문", "합성 날짜 원문"],
  [null, "게시일 정보 없음"],
])("displays the date prefix without timezone conversion: %s", (published_at, expected) => {
  render(<EvidenceSummary data={{ cards: [{ ...card, published_at }], missing: 0 }} />);
  expect(screen.getByText(expected).textContent).toBe(expected);
});
it("uses schema names across four distribution axes and preserves values without names", () => {
  const values = ["question", "how_to", "demo", "hydration", "other", "synthetic_unknown", "none", "ordinary_person", "shop_now"];
  const data = { tool: "synthetic", rows: values.map(value => ({ value, creatives: 1 })) };
  const { rerender } = render(<DistributionChart data={data} names={names} />);
  expect(screen.getAllByRole("meter").map(node => node.getAttribute("aria-label"))).toEqual([
    "합성 훅", "합성 소구", "합성 형식", "합성 효능", ...values.slice(4),
  ]);
  for (const value of values.slice(4)) expect(screen.getByText(value).textContent).toBe(value);
  rerender(<DistributionChart data={data} />);
  expect(screen.getAllByRole("meter").map(node => node.getAttribute("aria-label"))).toEqual(values);
});
it.each([true, false])("fetches schema for distribution-only commands and falls back on failure=%s", async failed => {
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(failed ? { detail: "GRAPH_UNAVAILABLE" } : schema), { status: failed ? 503 : 200 }));
  vi.stubGlobal("fetch", fetch);
  render(<CommandTenantContext.Provider value="synthetic"><ResultsView commands={[{ kind: "show_distribution", data: { tool: "synthetic", rows: [{ value: "question", creatives: 2 }] } }]} /></CommandTenantContext.Provider>);
  await waitFor(() => expect(fetch).toHaveBeenCalledExactlyOnceWith("/api/graph/schema", { headers: { "X-Tenant-Id": "synthetic" } }));
  expect(await screen.findByRole("meter", { name: failed ? "question" : "합성 훅" })).toBeTruthy();
});
it.each([true, false])("filters only the plan intro line when show_plan=%s, keeping all other text above cards", showPlan => {
  const state = reducer({ ...initialState, tenantId: "synthetic" }, { type: "request_started", message: "합성 요청" });
  const text = `합성 한도 도달 안내\n${PLAN_INTRO_TEXT}\n합성 안내: ${PLAN_INTRO_TEXT}\n합성 다른 안내`;
  const commands: UiCommand[] = [{ kind: "show_evidence_cards", data: { cards: [card], missing: 0 } }, ...(showPlan ? [{ kind: "show_plan" as const, data: plan }] : [])];
  render(<TurnCard turn={{ ...state.turns[0], status: "done", displayText: text, commands }} busy={false} onChoice={vi.fn()} onCancel={vi.fn()} onRetry={vi.fn()} />);
  const answer = document.querySelector(".answer")!;
  expect(answer.textContent).toBe(showPlan ? `합성 한도 도달 안내\n합성 안내: ${PLAN_INTRO_TEXT}\n합성 다른 안내` : text);
  const stages = screen.getByLabelText("진행 단계");
  expect(stages.nextElementSibling).toBe(answer);
  expect(answer.nextElementSibling).toBe(showPlan ? screen.getByRole("article", { name: "합성 기획" }) : screen.getByRole("region", { name: "근거 소재" }));
});
it("omits an empty answer after filtering an intro-only plan turn", () => {
  const state = reducer({ ...initialState, tenantId: "synthetic" }, { type: "request_started", message: "합성 요청" });
  const { container } = render(<TurnCard turn={{ ...state.turns[0], status: "done", displayText: PLAN_INTRO_TEXT, commands: [{ kind: "show_plan", data: plan }] }} busy={false} onChoice={vi.fn()} onCancel={vi.fn()} onRetry={vi.fn()} />);
  expect(container.querySelector(".answer")).toBeNull();
});
it("shows only the choice status, hides unavailable/stopped stages and preserves running/done stages", () => {
  const { rerender, container } = render(<ProgressTracker turnStatus="needs_choice" stepEvents={[]} />);
  const bar = screen.getByLabelText("진행 단계");
  expect(bar.textContent).toBe("요청 해석 완료 · 선택을 기다리는 중");
  expect(bar.textContent).not.toContain("대기");
  for (const status of ["unavailable", "stopped"] as const) {
    rerender(<ProgressTracker turnStatus={status} stepEvents={[]} />);
    expect(container.innerHTML).toBe("");
  }
  for (const status of ["running", "done"] as const) {
    const events = status === "done" ? [{ agent: "supervisor", phase: "done", status: "research" }] : [];
    rerender(<ProgressTracker turnStatus={status} stepEvents={events} />);
    const labels = { pending: "대기", running: "진행 중", done: "완료", failed: "실패" };
    const stages = deriveProgress(events, status);
    expect(screen.getAllByRole("listitem").map(node => node.textContent)).toEqual(stages.map(stage => stage.label));
    expect(screen.getAllByRole("listitem").map(node => node.getAttribute("data-status"))).toEqual(stages.map(stage => stage.status));
    expect(screen.getAllByRole("img").map(node => node.getAttribute("aria-label"))).toEqual(stages.map(stage => labels[stage.status]));
  }
});
it("keeps evaluation attempts collapsed initially and reveals every attempt's checks, scores, review items and costs", () => {
  const attempts = [...plan.attempts, { attempt: 2, scores: { differentiation: 4, fit: 5 }, low_items: ["fit"], checks_passed: false, final_passed: false, cost_usd: .012345 }];
  const { container } = render(<PlanResult data={{ ...plan, attempts }} tenantId={null} />);
  expandAll();
  const details = container.querySelector("details")!;
  expect(details).toBeTruthy(); expect(details.hasAttribute("open")).toBe(false);
  const summary = screen.getByText("평가 시도 보기 · 되돌림 1회");
  expect(summary.tagName).toBe("SUMMARY"); fireEvent.click(summary);
  expect(details.open).toBe(true);
  const items = details.querySelector("ol")!.children;
  expect(items).toHaveLength(2);
  expect(items[0].textContent).toContain("시도 1");
  expect(items[0].textContent).toContain("차별성 (differentiation): 2");
  expect(items[0].textContent).toContain("재검토 항목: 차별성");
  expect(items[0].textContent).toContain("시도 코드 검사: 통과 · 최종 판정: 실패");
  expect(items[1].textContent).toContain("시도 2");
  expect(items[1].textContent).toContain("요청 적합성 (fit): 5");
  expect(items[1].textContent).toContain("재검토 항목: 요청 적합성");
  expect(items[1].textContent).toContain("시도 코드 검사: 실패 · 최종 판정: 실패");
  expect(items[1].textContent).toContain("시도 텍스트 비용 $0.0123");
});
it("orders plan sections, disclaimer, image and feedback after the folded attempts", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(new Blob(["synthetic"]))));
  vi.stubGlobal("URL", Object.assign(class extends URL {}, { createObjectURL: () => "blob:synthetic", revokeObjectURL: vi.fn() }));
  const { container } = render(<PlanResult data={{ ...plan, plan_id: "synthetic", image }} tenantId="synthetic" />);
  await screen.findByRole("img");
  const root = container.querySelector(".plan-card")!;
  expect(root.querySelector(".gs-plan-media img")).toBeTruthy();
  expect(root.querySelector(".gs-plan-summary h3")?.textContent).toBe(plan.plan.title);
  expect(root.querySelector(".gs-plan-actions [aria-label='기획안 피드백']")).toBeTruthy();
  const expanded = root.querySelector<HTMLElement>(".gs-plan-expanded")!;
  expect(expanded.hidden).toBe(true);
  expect(Array.from(expanded.children).map(node => node.getAttribute("aria-label") ?? node.tagName)).toEqual([
    "장면 구성", "카피", "주장 효능", "검사 결과", "경쟁사 패턴 반영", "기획안 근거", "DETAILS", "P",
  ]);
  expect(expanded.children[7].textContent).toBe(plan.disclaimer);
  expect(screen.getByText("합성 장면")).toBeTruthy();
  expect(screen.queryByRole("region", { name: "장면 구성" })).toBeNull();
  const toggle = screen.getByRole("button", { name: "전체 보기 →" });
  fireEvent.click(toggle);
  expect(toggle.getAttribute("aria-expanded")).toBe("true");
  expect(expanded.hidden).toBe(false);
  for (const label of ["장면 구성", "카피", "주장 효능", "검사 결과", "경쟁사 패턴 반영", "기획안 근거"]) expect(screen.getByRole("region", { name: label })).toBeTruthy();
  expect(screen.getByText("합성 카피")).toBeTruthy();
  expect(screen.getByText("평가 시도 보기 · 되돌림 0회")).toBeTruthy();
  fireEvent.click(toggle);
  expect(expanded.hidden).toBe(true);
});

it("shows a compact horizontal plan summary with a placeholder and preserves every detail in the DOM", () => {
  const { container } = render(<PlanResult data={{ ...plan, plan_id: "synthetic", unknown_count: 1, unknown_codes: { EFFICACY_UNKNOWN: 1 }, design_disclaimer: "합성 시안 고지" }} names={names} tenantId="synthetic" />);
  expect(screen.getByText("시안 이미지").closest(".gs-plan-media")).toBeTruthy();
  expect(screen.getAllByText("합성 효능 · 확인됨")).toHaveLength(2);
  expect(screen.getByText("근거 연결 없음 1건")).toBeTruthy();
  expect(screen.getByText("경쟁사 패턴 반영 · 비교한 축 2개 중 같은 축 1개")).toBeTruthy();
  for (const name of ["승인", "반려", "전체 보기 →"]) expect(screen.getByRole("button", { name })).toBeTruthy();
  expect((screen.getByLabelText("피드백 사유") as HTMLInputElement).tagName).toBe("INPUT");
  for (const text of ["합성 장면", "합성 카피", "주장 효능", "효능 근거 연결 없음", "코드 검사: 통과", "평가 상태: 검토 필요", plan.pattern_alignment_label, "근거 소재 목록", "평가 시도 보기 · 되돌림 0회", plan.disclaimer, "합성 시안 고지"]) expect(screen.getByText(text).closest("[hidden]")).toBeTruthy();
  expect(container.querySelector(".gs-plan-summary .gs-result-badges")).toBeTruthy();
  expandAll();
  for (const text of ["합성 장면", "합성 카피", "합성 시안 고지"]) expect(screen.getByText(text).closest("[hidden]")).toBeNull();
});
it("groups compact evidence summaries under platform headings with icons and counts", () => {
  render(<EvidenceSummary data={{ cards: [card, { ...card, evidence_id: "instagram:a", source: "instagram", hook_type: "question" }], missing: 1 }} />);
  expect(screen.getAllByRole("heading", { level: 4 }).filter(node => node.classList.contains("gs-platform-heading")).map(node => node.textContent)).toEqual(["Instagram · 1건", "YouTube · 1건"]);
  for (const heading of document.querySelectorAll(".gs-platform-heading")) {
    expect(heading.querySelector("svg[aria-hidden=true]")).toBeTruthy();
    expect(heading.nextElementSibling?.classList.contains("gs-evidence-grid")).toBe(true);
  }
  expect(document.querySelectorAll(".gs-evidence-card")).toHaveLength(2);
  expect(screen.getByText("근거 소재 1건을 불러오지 못했습니다.")).toBeTruthy();
});
