import type { ComponentProps } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, expect, it, vi } from "vitest";
import { PlanPage } from "../components/plan/PlanPage";
import { EvidencePage } from "../components/evidence/EvidencePage";
import Page from "../app/page";
import { BrandNamesContext } from "../lib/brandNames";
import { scoreExplanations } from "../lib/localize";
import { EvidenceCardView, EvidenceChip } from "../components/evidence/EvidenceCardView";
import { EvidenceSummary } from "../components/evidence/EvidenceSummary";
import { PlanResult } from "../components/results/PlanResult";
import { HistoryDetail } from "../components/history/HistoryDetail";
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

function Audit({ commands, names }: { commands: UiCommand[]; names?: ComponentProps<typeof HistoryDetail>["names"] }) {
  const base = reducer({ ...initialState, tenantId: "synthetic" }, { type: "request_started", message: "합성 검증 요청" }).turns[0];
  return <HistoryDetail turn={{ ...base, status: "done", commands }} workspace="합성 공간" onBack={vi.fn()} names={names} />;
}
function PlanWithAudit(props: ComponentProps<typeof PlanResult>) {
  return <><PlanResult {...props} /><Audit commands={[{ kind: "show_plan", data: props.data }]} names={props.names} /></>;
}
function selectAuditTab(label: string) { fireEvent.click(screen.getByRole("tab", { name: label })); return screen.getByRole("tabpanel", { name: label }); }

function TestWorkspace() {
  const { state, selectWorkspace } = useSession();
  return <WorkspaceChip workspaces={[{ tenant_id: "synthetic", display_name: "합성 공간", brand: null, product_name: null }]} value={state.tenantId} onChange={selectWorkspace} />;
}
function expandAll() { for (const button of screen.queryAllByRole("button", { name: "전체 보기 →", expanded: false })) fireEvent.click(button); }
function turnsWithCards(cards: EvidenceCard[][]) {
  return cards.map(cards => ({ commands: [{ kind: "show_evidence_cards" as const, data: { cards, missing: 0 } }] }));
}
it("combines separate platform and brand filters with independent pressed states", () => {
  const onPlan = vi.fn();
  render(<EvidencePage turns={turnsWithCards([[{ ...card, brand: "isntree" }, { ...card, evidence_id: "instagram:synthetic", source: "instagram", title: "합성 다른 브랜드", brand: "cosrx" }]])} workspaceBrand="isntree" onPlan={onPlan} />);
  const platform = within(screen.getByRole("group", { name: "플랫폼" }));
  const brand = within(screen.getByRole("group", { name: "브랜드" }));
  expect(screen.queryByRole("group", { name: "근거 소재 필터" })).toBeNull();
  expect(platform.getAllByRole("button").map(button => button.textContent)).toEqual(["전체", "Instagram", "YouTube"]);
  expect(brand.getAllByRole("button").map(button => button.textContent)).toEqual(["전체 브랜드", "자사만"]);
  function pressed(platformStates: string[], brandStates: string[]) {
    expect(platform.getAllByRole("button").map(button => button.getAttribute("aria-pressed"))).toEqual(platformStates);
    expect(brand.getAllByRole("button").map(button => button.getAttribute("aria-pressed"))).toEqual(brandStates);
  }
  pressed(["true", "false", "false"], ["true", "false"]);
  fireEvent.click(platform.getByRole("button", { name: "Instagram" }));
  pressed(["false", "true", "false"], ["true", "false"]);
  fireEvent.click(brand.getByRole("button", { name: "자사만" }));
  pressed(["false", "true", "false"], ["false", "true"]);
  expect(screen.getByRole("heading", { name: "조건에 맞는 근거 소재가 없습니다" })).toBeTruthy();
  expect(screen.queryByRole("article")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "광고 기획으로" })); expect(onPlan).toHaveBeenCalledTimes(1);
  fireEvent.click(brand.getByRole("button", { name: "전체 브랜드" }));
  pressed(["false", "true", "false"], ["true", "false"]);
  expect(screen.getAllByRole("article")).toHaveLength(1);
  expect(screen.getByRole("link", { name: "합성 다른 브랜드" })).toBeTruthy();
  fireEvent.click(platform.getByRole("button", { name: "전체" }));
  pressed(["true", "false", "false"], ["true", "false"]);
  expect(screen.getAllByRole("article")).toHaveLength(2);
  fireEvent.click(brand.getByRole("button", { name: "자사만" }));
  fireEvent.click(platform.getByRole("button", { name: "전체" }));
  pressed(["true", "false", "false"], ["false", "true"]);
  expect(screen.getAllByRole("article")).toHaveLength(1);
  expect(screen.getByRole("link", { name: "합성 근거" })).toBeTruthy();
});
it("hides both filter rows for an empty session and filters a null platform", () => {
  const { rerender } = render(<EvidencePage turns={[]} workspaceBrand={null} onPlan={vi.fn()} />);
  expect(screen.queryByRole("group", { name: "플랫폼" })).toBeNull();
  expect(screen.queryByRole("group", { name: "브랜드" })).toBeNull();
  rerender(<EvidencePage turns={turnsWithCards([[card, { ...card, evidence_id: "synthetic:null", source: null, title: "합성 출처 없음" }]])} workspaceBrand={null} onPlan={vi.fn()} />);
  fireEvent.click(within(screen.getByRole("group", { name: "플랫폼" })).getByRole("button", { name: "출처 정보 없음" }));
  expect(screen.getAllByRole("article")).toHaveLength(1);
  expect(screen.getByRole("heading", { name: "출처 정보 없음 · 1건" })).toBeTruthy();
});
it("groups platforms with direct YouTube thumbnails and neutral monogram tiles, including failed thumbnails", () => {
  const cards = [card, { ...card, evidence_id: "instagram:a", source: "instagram", title: "합성 인스타", hook_type: "question" }, { ...card, evidence_id: "tiktok:a", source: "tiktok", title: "합성 틱톡", hook_type: "question" }];
  render(<EvidencePage turns={turnsWithCards([cards])} workspaceBrand={null} onPlan={vi.fn()} />);
  expect(screen.getAllByRole("heading", { level: 2 }).map(node => node.textContent)).toEqual(["Instagram · 1건", "TikTok · 1건", "YouTube · 1건"]);
  for (const [source, label] of [["instagram", "Instagram"], ["tiktok", "TikTok"]]) {
    const tile = screen.getByLabelText(`${source} 출처`);
    expect(tile.textContent).toContain(label);
    expect(tile.getAttribute("data-platform")).toBe(source);
    expect(tile.querySelector('svg[aria-hidden="true"]')).toBeTruthy();
    expect(tile.querySelector(".gs-platform-monogram")).toBeNull();
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
  fireEvent.click(screen.getByRole("button", { name: "전체 브랜드" }));
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
  const { container, rerender } = render(<PlanWithAudit data={plan} tenantId="synthetic" evidenceAnchors={{ [card.evidence_id!]: "synthetic-anchor" }} />);
  selectAuditTab("검증");
  expect(screen.getByText("근거 연결 없음 0건").className).toContain("clear");
  expect(screen.getByText("코드 검사: 통과")).toBeTruthy();
  expect(screen.getByText("평가 상태: 검토 필요")).toBeTruthy();
  const raw = screen.getAllByText("question"); expect(raw).toHaveLength(3);
  expect(raw.filter(node => node.closest(".gs-plan-summary .gs-result-badges"))).toHaveLength(1);
  expect(raw.filter(node => node.closest('[aria-label="경쟁사 패턴 반영"]'))).toHaveLength(2);
  for (const label of ["같음", "다름", "비교 불가", "비교한 축 2개 중 같은 축 1개", plan.pattern_alignment_label, plan.disclaimer]) expect(screen.getAllByText(label).length).toBeGreaterThan(0);
  expect(container.textContent).not.toMatch(/좋음|나쁨|우수|미달/);
  expandAll();
  expect(screen.getByRole("link", { name: card.evidence_id! }).getAttribute("href")).toBe("#synthetic-anchor");
  expect(screen.queryByRole("link", { name: "youtube:absent" })).toBeNull();
  const stages = selectAuditTab("단계");
  expect(screen.getByText("재작업 0회")).toBeTruthy();
  expect(stages.querySelector(".gs-attempt-line")!.textContent).toBe("검사 통과 · 최종 실패 · 차별성 2/5 · 요청 적합성 3/5 · 재검토: 차별성");
  expect(within(stages).getByText("시도 1")).toBeTruthy();
  rerender(<PlanWithAudit data={{ ...plan, unknown_count: 3, unknown_codes: { CERT_REQUIRED_UNVERIFIED: 1, EFFICACY_UNKNOWN: 1, SYNTHETIC_UNKNOWN: 1 }, passed: false, status: "failed" }} tenantId="synthetic" names={names} />);
  selectAuditTab("검증");
  expect(screen.getByText("근거 연결 없음 3건").className).toContain("attention");
  expect(screen.getByText("인증 연결 없음").textContent).toBe("인증 연결 없음");
  expect(screen.getByText("효능 근거 연결 없음").textContent).toBe("효능 근거 연결 없음");
  expect(screen.getByText("SYNTHETIC_UNKNOWN").textContent).toBe("SYNTHETIC_UNKNOWN");
  expect(screen.getByText("코드 검사: 실패")).toBeTruthy();
  expect(screen.getByText("평가 상태: 실패")).toBeTruthy();
  expect(screen.getAllByText("합성 효능 · 확인됨")).toHaveLength(2);
  expect(screen.getAllByText("soothing · 근거 연결 없음")).toHaveLength(2);
});
it("keeps verified charts, model values and removed values in distinct blocks, including removed-only and empty", () => {
  const { rerender } = render(<Audit commands={[{ kind: "show_aggregates", data: aggregates }]} />);
  selectAuditTab("검증");
  expect(screen.queryByRole("region", { name: "검증된 집계(도구가 센 값)" })).toBeNull();
  expect(screen.queryByText("합성 도구 건수")).toBeNull();
  const model = screen.getByRole("region", { name: "모델 작성값" });
  expect(within(model).getByText(aggregates.label)).toBeTruthy();
  expect(model.textContent).toContain("합성 모델 값");
  expect(model.textContent).not.toMatch(/확인됨|검증됨/);
  expect(screen.getByRole("region", { name: "제외된 값" }).textContent).toContain("synthetic_removed");
  rerender(<Audit commands={[{ kind: "show_aggregates", data: { ...aggregates, verified_counts: [], model_written: [] } }]} />);
  expect(screen.getByText("synthetic_removed")).toBeTruthy();
  expect(screen.queryByRole("region", { name: "모델 작성값" })).toBeNull();
  rerender(<Audit commands={[{ kind: "show_aggregates", data: { ...aggregates, verified_counts: [], model_written: [], removed: [] } }]} />);
  expect(screen.getByRole("tabpanel", { name: "검증" }).innerHTML).toBe("");
  rerender(<Audit commands={[{ kind: "show_aggregates", data: aggregates }, { kind: "show_distribution", data: { tool: "compare_axis_by_category", rows: [{ value: "question", creatives: 1 }] } }]} />);
  const verified = screen.getByRole("region", { name: "검증된 집계(도구가 센 값)" });
  expect(within(verified).getByText("검증됨")).toBeTruthy();
  expect(within(verified).getByRole("heading", { name: "경쟁사 광고 분포" })).toBeTruthy();
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
  expect((screen.getByRole("button", { name: "반려" }) as HTMLButtonElement).disabled).toBe(false);
  if (decision === "rejected") { fireEvent.click(screen.getByRole("button", { name: "반려" })); fireEvent.change(screen.getByLabelText("피드백 사유"), { target: { value: "합성 사유" } }); }
  const button = screen.getByRole("button", { name: decision === "approved" ? "승인" : "반려 제출" });
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
  const nodes = [screen.getByText("합성 화면 문장"), screen.getByRole("heading", { name: "합성 기획" }), screen.getByRole("heading", { name: "합성 두 번째 기획" }), screen.getByRole("region", { name: "근거 소재" }), screen.getByRole("region", { name: "분포" })];
  for (let i = 1; i < nodes.length; i++) expect(nodes[i - 1].compareDocumentPosition(nodes[i]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(screen.getAllByRole("link", { name: "검증 상세 보기 →" })).toHaveLength(1);
  expect(screen.queryByLabelText("합성 비용")).toBeNull(); expect(document.body.textContent).not.toMatch(/\$\d/);
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
    const items = screen.getAllByRole("listitem");
    expect(items.map(node => [...node.querySelectorAll(".gs-stage-copy")].map(label => label.textContent))).toEqual(stages.map(stage => [stage.label]));
    expect(items.map(node => node.textContent)).toEqual(stages.map(stage => stage.status === "running" ? `진행 중${stage.label}0초 경과` : stage.label));
    const elapsed = screen.getByLabelText("경과 시간");
    expect(elapsed.textContent).toBe("0초 경과");
    if (status === "running") expect(elapsed.closest("li")).toBe(items.find(node => node.getAttribute("data-status") === "running"));
    else {
      expect(elapsed.closest("li")).toBeNull();
      expect(elapsed.classList.contains("gs-sr-only")).toBe(true);
    }
    expect(screen.getAllByRole("listitem").map(node => node.getAttribute("data-status"))).toEqual(stages.map(stage => stage.status));
    expect(screen.getAllByRole("img").map(node => node.getAttribute("aria-label"))).toEqual(stages.map(stage => labels[stage.status]));
  }
});
it("keeps every evaluation attempt's checks, scores and review items in the default stage tab and costs in the cost tab", () => {
  const attempts = [...plan.attempts, { attempt: 2, scores: { differentiation: 4, fit: 5 }, low_items: ["fit"], checks_passed: false, final_passed: false, cost_usd: .012345 }];
  render(<Audit commands={[{ kind: "show_plan", data: { ...plan, attempts } }, { kind: "show_cost", data: { label: "합성 비용", text_spent_usd: .02, max_text_cost_usd: 1 } }]} />);
  const details = screen.getByRole("tabpanel", { name: "단계" });
  expect(screen.getByRole("tab", { name: "단계" }).getAttribute("aria-selected")).toBe("true");
  const items = [...details.querySelectorAll(".gs-attempt-line")].map(line => line.closest("tr")!);
  expect(items.map(row => within(row).getAllByRole("cell").slice(0, 2).map(cell => cell.textContent))).toEqual([
    ["시도 1", "검사 통과 · 최종 실패 · 차별성 2/5 · 요청 적합성 3/5 · 재검토: 차별성"],
    ["시도 2", "검사 실패 · 최종 실패 · 차별성 4/5 · 요청 적합성 5/5 · 재검토: 요청 적합성"],
  ]);
  for (const item of items) expect(item.closest("[hidden]")).toBeNull();
  const costTable = within(selectAuditTab("비용")).getByRole("table", { name: "비용 내역" });
  expect(within(costTable).getAllByRole("row").slice(1).map(row => within(row).getAllByRole("cell").map(cell => cell.textContent))).toContainEqual(["시도 2", "$0.0123"]);
  expect(screen.queryByRole("tab", { name: "평가" })).toBeNull();
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
    "장면 구성", "카피", "주장 효능", "경쟁사 패턴 반영", "기획안 근거", "P",
  ]);
  expect(expanded.children[5].textContent).toBe(plan.disclaimer);
  expect(screen.getByText("합성 장면")).toBeTruthy();
  expect(screen.queryByRole("region", { name: "장면 구성" })).toBeNull();
  const toggle = screen.getByRole("button", { name: "전체 보기 →" });
  fireEvent.click(toggle);
  expect(toggle.getAttribute("aria-expanded")).toBe("true");
  expect(expanded.hidden).toBe(false);
  for (const label of ["장면 구성", "카피", "주장 효능", "경쟁사 패턴 반영", "기획안 근거"]) expect(screen.getByRole("region", { name: label })).toBeTruthy();
  expect(screen.getByText("합성 카피")).toBeTruthy();
  expect(screen.queryByText("평가 시도 보기 · 되돌림 0회")).toBeNull();
  expect(screen.queryByRole("region", { name: "검사 결과" })).toBeNull();
  fireEvent.click(toggle);
  expect(expanded.hidden).toBe(true);
});

it("shows a compact horizontal plan summary with a placeholder and preserves every detail in the DOM", () => {
  const { container } = render(<PlanWithAudit data={{ ...plan, plan_id: "synthetic", unknown_count: 1, unknown_codes: { EFFICACY_UNKNOWN: 1 }, design_disclaimer: "합성 시안 고지" }} names={names} tenantId="synthetic" />);
  expect(screen.getByText("시안 이미지").closest(".gs-plan-media")).toBeTruthy();
  expect(screen.getAllByText("합성 효능 · 확인됨")).toHaveLength(2);
  expect(screen.getByText("근거 연결 없음 1건")).toBeTruthy();
  expect(screen.getByText("경쟁사 패턴 반영 · 비교한 축 2개 중 같은 축 1개")).toBeTruthy();
  for (const name of ["승인", "반려", "전체 보기 →"]) expect(screen.getByRole("button", { name })).toBeTruthy();
  expect((screen.getByLabelText("피드백 사유") as HTMLInputElement).tagName).toBe("INPUT");
  for (const text of ["합성 장면", "합성 카피", "주장 효능", "효능 근거 연결 없음", "코드 검사: 통과", "평가 상태: 검토 필요", plan.pattern_alignment_label, "근거 소재 목록", plan.disclaimer, "합성 시안 고지"]) expect(screen.getByText(text).closest("[hidden]")).toBeTruthy();
  const verification = selectAuditTab("검증");
  for (const text of ["근거 연결 없음 1건", "효능 근거 연결 없음", "코드 검사: 통과", "평가 상태: 검토 필요"]) expect(within(verification).getByText(text).closest("[hidden]")).toBeNull();
  const attempt = selectAuditTab("단계").querySelector(".gs-attempt-line")!;
  expect(attempt.closest("[hidden]")).toBeNull();
  expect(attempt.textContent).toBe("검사 통과 · 최종 실패 · 차별성 2/5 · 요청 적합성 3/5 · 재검토: 차별성");
  expect(screen.queryByRole("tab", { name: "평가" })).toBeNull();
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

const restoredCost: Extract<UiCommand, { kind: "show_cost" }> = {
  kind: "show_cost", data: { label: "텍스트 모델 비용(이미지 제외)", text_spent_usd: .012345, max_text_cost_usd: 1 },
};
it.each([false, true])("omits all request cost details when show_cost is absent, with plan=%s", showPlan => {
  const { container } = render(<ResultsView commands={showPlan ? [{ kind: "show_plan", data: plan }] : []} />);
  expandAll();
  expect(screen.queryByText(/이 요청의 .*비용/)).toBeNull();
  expect(screen.queryByText(/텍스트 비용 상한/)).toBeNull();
  expect(container.querySelector(".gs-cost-line")).toBeNull();
});


it.each([false, true])("shows no request cost anywhere in the marketer results with plan=%s", showPlan => {
  for (const imageCost of [undefined, .0336]) {
    const { unmount, container } = render(<ResultsView commands={[{ ...restoredCost, data: { ...restoredCost.data, image_cost_usd: imageCost } }, ...(showPlan ? [{ kind: "show_plan" as const, data: plan }] : [])]} />);
    expandAll();
    expect(document.body.textContent).not.toMatch(/\$\d/);
    for (const text of ["이 요청의", "텍스트 비용 상한", "텍스트 모델 비용"]) expect(document.body.textContent).not.toContain(text);
    expect(container.querySelector(".gs-cost-line")).toBeNull();
    unmount();
  }
});

it("reveals rejection reasons on demand and never stores blank or whitespace-only rejections", async () => {
  const fetch = vi.fn().mockResolvedValue(new Response('{"status":"ok"}')); vi.stubGlobal("fetch", fetch);
  render(<FeedbackBar tenantId="synthetic" planId="synthetic-plan" />);
  const input = screen.getByLabelText("피드백 사유") as HTMLInputElement;
  expect(input.tagName).toBe("INPUT"); expect(input.hidden).toBe(true);
  const reject = screen.getByRole("button", { name: "반려" }) as HTMLButtonElement;
  expect(reject.disabled).toBe(false); fireEvent.click(reject);
  expect(input.hidden).toBe(false);
  const submit = screen.getByRole("button", { name: "반려 제출" }) as HTMLButtonElement;
  expect(submit.disabled).toBe(true); fireEvent.click(submit); expect(fetch).toHaveBeenCalledTimes(0);
  fireEvent.change(input, { target: { value: "   " } });
  expect(submit.disabled).toBe(true); fireEvent.click(submit); expect(fetch).toHaveBeenCalledTimes(0);
  fireEvent.click(screen.getByRole("button", { name: "취소" })); expect(input.hidden).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "반려" }));
  fireEvent.change(input, { target: { value: "합성 반려 사유" } });
  expect(submit.disabled).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "반려 제출" }));
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ plan_id: "synthetic-plan", reason: "합성 반려 사유", decision: "rejected" });
  expect(await screen.findByText("저장했습니다")).toBeTruthy();
});
it("fills the media slot with a contained image over a blurred backdrop and falls back on failure", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(new Blob(["synthetic"]))));
  vi.stubGlobal("URL", Object.assign(class extends URL {}, { createObjectURL: () => "blob:synthetic", revokeObjectURL: vi.fn() }));
  const { container } = render(<PlanResult data={{ ...plan, image }} tenantId="synthetic" />);
  const media = container.querySelector<HTMLElement>(".gs-plan-media")!;
  expect(media.style.aspectRatio).toBe("");
  const img = await screen.findByRole("img");
  Object.defineProperties(img, { naturalWidth: { value: 800 }, naturalHeight: { value: 1200 } }); fireEvent.load(img);
  expect(media.style.aspectRatio).toBe("");
  expect(screen.getAllByRole("img")).toEqual([screen.getByRole("img", { name: "기획안 시안 이미지" })]);
  const backdrop = container.querySelector("img.gs-design-backdrop")!;
  expect(backdrop.getAttribute("alt")).toBe(""); expect(backdrop.getAttribute("aria-hidden")).toBe("true");
  expect(backdrop.getAttribute("src")).toBe(img.getAttribute("src"));
  expect(img.style.objectFit).not.toBe("cover");
  const css = readFileSync(join(process.cwd(), "app/results.css"), "utf8");
  const mainRule = css.match(/\.gs-design-image img\s*\{([^}]*)\}/)![1];
  expect(mainRule).toMatch(/object-fit:\s*contain/); expect(mainRule).not.toMatch(/object-fit:\s*cover/);
  const backdropRule = css.match(/[^{}]*\.gs-design-backdrop\s*\{([^}]*)\}/)![1];
  expect(backdropRule).toMatch(/object-fit:\s*cover/); expect(backdropRule).toContain("blur(");
  expect(css.match(/object-fit:\s*cover/g)).toHaveLength(1);
  const mediaRule = css.match(/\.gs-plan-media\s*\{([^}]*)\}/)![1];
  expect(mediaRule).toMatch(/position:\s*relative/); expect(mediaRule).toMatch(/overflow:\s*hidden/);
  expect(css).toMatch(/align-items:\s*stretch/); expect(css).not.toContain("position: sticky");
  fireEvent.error(img); expect(screen.getByRole("status").textContent).toBe("시안 이미지를 불러오지 못했습니다");
  expect(container.querySelector(".gs-design-backdrop")).toBeNull();
});
it("shows Korean brand, review reasons with an on-demand tooltip and the original check details", () => {
  const { container, rerender } = render(<PlanWithAudit data={{ ...plan, product_display: { brand: "beauty_of_joseon", display_name: "조선미녀 평가 작업 공간", product_name: "합성 제품" }, unknown_count: 4, unknown_codes: { EFFICACY_UNKNOWN: 1, CERT_REQUIRED_UNVERIFIED: 3 } }} tenantId={null} />);
  const summary = container.querySelector(".gs-plan-summary")!;
  expect(summary.querySelector("header small")!.textContent).toBe("기획안 · 조선미녀 · 합성 제품");
  expect(summary.textContent).not.toMatch(/beauty_of_joseon|작업 공간/);
  const badge = within(summary as HTMLElement).getByText("확인 필요 4건 · 인증 자료 연결 없음 · 효능 근거 연결 없음");
  const explanation = "코드 검사가 확인하지 못한 항목의 수입니다. 실패가 아니라 근거가 연결되지 않아 확인이 필요한 항목입니다.";
  expect(badge.hasAttribute("title")).toBe(false);
  const trigger = badge.closest(".gs-tooltip-trigger")!;
  expect(trigger.hasAttribute("title")).toBe(false); expect(screen.queryByRole("tooltip")).toBeNull();
  expect(trigger.hasAttribute("aria-describedby")).toBe(false);
  fireEvent.focus(trigger);
  const tooltip = screen.getByRole("tooltip"); expect(tooltip.textContent).toBe(explanation);
  expect(trigger.getAttribute("aria-describedby")).toBe(tooltip.id);
  fireEvent.keyDown(trigger, { key: "Escape" }); expect(screen.queryByRole("tooltip")).toBeNull(); expect(trigger.hasAttribute("aria-describedby")).toBe(false);
  selectAuditTab("검증");
  const checks = container.querySelector('[aria-label="검사 결과"]') as HTMLElement;
  expect(within(checks).getByText("근거 연결 없음 4건")).toBeTruthy();
  expect(within(checks).getByText("인증 연결 없음").tagName).toBe("LI");
  rerender(<PlanWithAudit data={plan} tenantId={null} />);
  expect(screen.getByText("확인 필요 없음")).toBeTruthy();
  expect(container.querySelector(".gs-review-badge")).toBeNull(); expect(screen.queryByRole("tooltip")).toBeNull();
  expect(container.querySelector("header small")!.textContent).toBe("기획안 · 브랜드 정보 없음");
});
it("opens in the next frame and waits for a grid transition before hiding", () => {
  let frame!: FrameRequestCallback;
  vi.stubGlobal("requestAnimationFrame", vi.fn(callback => { frame = callback; return 1; }));
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
  const { container } = render(<PlanResult data={plan} tenantId={null} />);
  const expanded = container.querySelector<HTMLElement>(".gs-plan-expanded")!;
  const toggle = screen.getByRole("button", { name: "전체 보기 →" });
  fireEvent.click(toggle); expect(expanded.hidden).toBe(false); expect(expanded.classList.contains("gs-open")).toBe(false);
  act(() => frame(0)); expect(expanded.classList.contains("gs-open")).toBe(true);
  vi.spyOn(window, "getComputedStyle").mockReturnValue({ transitionDuration: "0.2s", transitionDelay: "0s" } as CSSStyleDeclaration);
  fireEvent.click(toggle); expect(expanded.classList.contains("gs-open")).toBe(false); expect(expanded.hidden).toBe(false);
  fireEvent.transitionEnd(expanded.parentElement!, { propertyName: "grid-template-rows" }); expect(expanded.hidden).toBe(true);
});
it.each([false, true])("hides synchronously for zero duration or reduced motion=%s", reduced => {
  vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: reduced })));
  const computedStyle = window.getComputedStyle;
  vi.spyOn(window, "getComputedStyle").mockImplementation((...args) => {
    const style = computedStyle(...args);
    Object.defineProperties(style, { transitionDuration: { configurable: true, value: reduced ? "0.2s" : "0ms" }, transitionDelay: { configurable: true, value: "0s" } });
    return style;
  });
  const { container } = render(<PlanResult data={plan} tenantId={null} />);
  const expanded = container.querySelector<HTMLElement>(".gs-plan-expanded")!;
  const toggle = screen.getByRole("button", { name: "전체 보기 →" });
  fireEvent.click(toggle); expect(expanded.hidden).toBe(false);
  fireEvent.click(toggle); expect(expanded.hidden).toBe(true);
  const css = readFileSync(join(process.cwd(), "app/results.css"), "utf8");
  expect(css).toMatch(/grid-template-rows:\s*0fr/); expect(css).toMatch(/grid-template-rows:\s*1fr/);
  expect(css).toMatch(/transition:\s*grid-template-rows/);
  expect(css.slice(css.indexOf("@media (prefers-reduced-motion: reduce)"))).toMatch(/transition:\s*none/);
});
it("cards each detail section, numbers scenes, quotes copies and tabulates neutral pattern facts", () => {
  const { container } = render(<PlanResult data={plan} tenantId={null} />); expandAll();
  const expanded = container.querySelector(".gs-plan-expanded")!;
  for (const section of expanded.querySelectorAll(":scope > section")) expect(section.classList.contains("gs-detail-card")).toBe(true);
  expect(screen.getByRole("region", { name: "장면 구성" }).querySelector("ol li")!.textContent).toBe("합성 장면");
  expect(screen.getByText("합성 카피").tagName).toBe("BLOCKQUOTE");
  const table = within(screen.getByRole("region", { name: "경쟁사 패턴 반영" })).getByRole("table");
  expect(within(table).getAllByRole("columnheader").map(node => node.textContent)).toEqual(["축", "기획안", "경쟁사 최다 방식", "일치 여부", "시장 내 비중"]);
  for (const text of ["같음", "다름", "비교 불가"]) expect(within(table).getAllByText(text).every(node => node.textContent === text)).toBe(true);
  expect(within(table).getByText("25.0%")).toBeTruthy();
});
it("keeps evidence link names and anchors while displaying thumbnail chips with brand text", () => {
  render(<ResultsView commands={[{ kind: "show_plan", data: plan }, { kind: "show_evidence_cards", data: { cards: [card], missing: 0 } }]} />); expandAll();
  const evidence = screen.getByRole("region", { name: "기획안 근거" });
  const link = within(evidence).getByRole("link", { name: card.evidence_id! });
  expect(link.textContent).not.toContain("youtube:"); expect(link.textContent).toContain(card.brand);
  const img = link.querySelector("img")!; expect(img.src).toBe("https://i.ytimg.com/vi/abc_123-/hqdefault.jpg");
  expect(document.getElementById(link.getAttribute("href")!.slice(1))).toBeTruthy();
  fireEvent.error(img); expect(link.querySelector("img")).toBeNull(); expect(link.querySelector(".gs-platform-monogram")).toBeTruthy();
  expect(within(evidence).getByText("근거 소재 2")).toBeTruthy();
  expect(evidence.textContent).not.toContain("youtube:");
});
it("styles disclaimer and image notice as one footnote block", () => {
  const { container } = render(<PlanResult data={{ ...plan, design_disclaimer: "합성 고지" }} tenantId={null} />);
  const expanded = container.querySelector(".gs-plan-expanded")!;
  expect(expanded.children[5].textContent).toBe(plan.disclaimer);
  for (const node of Array.from(expanded.children).slice(5)) expect(node.classList.contains("gs-footnote")).toBe(true);
  expect(Array.from(expanded.children).slice(5).map(node => node.textContent)).toEqual([plan.disclaimer, "합성 고지"]);
});
it("never displays the model-written rationale and leaves the input object unchanged", () => {
  const scores = { differentiation: 3, fit: 4, rationale: "how_to 대비 differentiation, fit. profit youtube:how_to" };
  const data = { ...plan, attempts: [{ attempt: 1, checks_passed: true, scores }] };
  const snapshot = JSON.stringify(data);
  render(<PlanWithAudit data={data} tenantId={null} names={names} />); expandAll();
  expect(document.querySelector(".gs-quality-summary")!.textContent).toBe("품질 검사 통과 · AI 평가 차별성 3/5 · 요청 적합성 4/5");
  selectAuditTab("단계");
  const attempt = screen.getByRole("tabpanel", { name: "단계" }).querySelector(".gs-attempt-line")!;
  expect(attempt.textContent).toBe("검사 통과 · 최종 미실행 · 차별성 3/5 · 요청 적합성 4/5");
  expect(attempt.closest("[hidden]")).toBeNull();
  expect(document.body.textContent).not.toMatch(/사유:|rationale|합성 소구 대비|\(differentiation\)/);
  expect(JSON.stringify(data)).toBe(snapshot);
});
it("summarizes only the latest attempt with absent scores omitted and failed checks explicit", () => {
  const { rerender } = render(<PlanResult data={{ ...plan, attempts: [...plan.attempts, { attempt: 2, checks_passed: false, scores: null }] }} tenantId={null} />);
  expect(screen.getByText("품질 검사 실패")).toBeTruthy();
  rerender(<PlanResult data={{ ...plan, attempts: [] }} tenantId={null} />);
  expect(screen.getByText("품질 검사 통과")).toBeTruthy();
  rerender(<PlanResult data={{ ...plan, attempts: [{ attempt: 1, checks_passed: true, scores: { fit: 5 } }] }} tenantId={null} />);
  expect(document.querySelector(".gs-quality-summary")!.textContent).toBe("품질 검사 통과 · AI 평가 요청 적합성 5/5");
});
it("renders market insights with Korean titles and columns, without tool captions, and retains meter names", () => {
  const { rerender } = render(<DistributionChart data={{ tool: "top_vs_bottom_axis", rows: [{ value: "question", n_top: 3, n_bottom: 1 }] }} names={names} />);
  const region = screen.getByRole("region", { name: "분포" });
  expect(region.getAttribute("data-tool")).toBe("top_vs_bottom_axis");
  expect(within(region).getByRole("heading").textContent).toBe("조회수 상위·하위 25% 광고 비교");
  expect(within(region).getAllByRole("columnheader").map(node => node.textContent)).toEqual(["분류", "상위 25% 광고 수", "하위 25% 광고 수"]);
  expect(region.querySelector("caption")).toBeNull(); expect(region.textContent).not.toContain("top_vs_bottom_axis");
  rerender(<DistributionChart data={{ tool: "compare_axis_by_category", rows: [{ value: "question", creatives: 3 }, { value: "other", creatives: 1 }] }} names={names} />);
  expect(within(region).getByRole("heading").textContent).toBe("오프닝 방식 분포");
  expect(within(region).getByText("기타")).toBeTruthy(); expect(within(region).getByRole("meter", { name: "other" })).toBeTruthy();
  expect(within(region).getAllByRole("meter")).toHaveLength(2);
  const css = readFileSync(join(process.cwd(), "app/results.css"), "utf8");
  expect(css).toMatch(/accent-color:\s*var\(--gs-accent\)/);
});

it("keeps only marketer summaries, insight, pattern facts and one verification link in results", () => {
  const { container } = render(<ResultsView commands={[{ kind: "show_plan", data: plan }, { kind: "show_distribution", data: { tool: "synthetic", rows: [{ value: "합성 분포", creatives: 1 }] } }, { kind: "show_aggregates", data: aggregates }]} />);
  expandAll();
  expect(document.querySelector(".gs-quality-summary")!.textContent).toBe("품질 검사 통과 · AI 평가 차별성 2/5 · 요청 적합성 3/5");
  expect(screen.getByRole("region", { name: "분포" })).toBeTruthy();
  expect(within(screen.getByRole("region", { name: "경쟁사 패턴 반영" })).getByRole("table")).toBeTruthy();
  expect(screen.getAllByRole("link", { name: "검증 상세 보기 →" })).toHaveLength(1);
  expect(screen.queryByRole("region", { name: "검사 결과" })).toBeNull();
  expect(container.querySelector("details")).toBeNull();
  expect(screen.queryByRole("region", { name: "검증된 집계(도구가 센 값)" })).toBeNull();
});

it("explains pattern facts with titled columns and keeps the server calculation label only in checks", () => {
  render(<PlanWithAudit data={plan} tenantId={null} />); expandAll();
  const panel = screen.getByRole("region", { name: "경쟁사 패턴 반영" });
  const descriptions = ["경쟁사 최다 방식: 같은 분류의 경쟁사 광고 중 가장 많이 쓰인 방식", "시장 내 비중: 경쟁사 광고 전체 중 기획안과 같은 방식을 쓴 광고의 비율"];
  const elements = descriptions.map(text => within(panel).getByText(text));
  expect(elements[0]).not.toBe(elements[1]);
  for (const [index, element] of elements.entries()) expect(element.textContent).toBe(descriptions[index]);
  expect(panel.textContent).not.toMatch(/기획안: |경쟁사 지배 패턴: |코드 계산, 판정 아님/);
  for (const header of within(panel).getAllByRole("columnheader")) expect(header.getAttribute("title")?.trim()).toBeTruthy();
  const rows = within(panel).getAllByRole("row").slice(1);
  expect(within(rows[2]).getAllByRole("cell").slice(2).map(node => node.textContent)).toEqual(["비교 불가", "비교 불가"]);
  expect(within(rows[0]).getByText("25.0%")).toBeTruthy();
  const checks = within(selectAuditTab("검증")).getByRole("region", { name: "검사 결과" });
  expect(within(checks).getByText(plan.pattern_alignment_label).classList.contains("gs-pattern-label")).toBe(true);
});
it("places the comparison note below one heading and omits it for other tools", () => {
  const { rerender } = render(<DistributionChart data={{ tool: "top_vs_bottom_axis", rows: [{ value: "question", n_top: 3, n_bottom: 1 }] }} />);
  const panel = screen.getByRole("region", { name: "분포" });
  const note = "같은 플랫폼·브랜드 안에서 조회수 상위 25%와 하위 25% 광고가 각 방식을 쓴 광고 수입니다.";
  expect(panel.querySelectorAll("h3")).toHaveLength(1);
  expect(panel.querySelector("h3")!.nextElementSibling).toBe(within(panel).getByText(note));
  expect(within(panel).getByText(note).className).toBe("gs-insight-note");
  rerender(<DistributionChart data={{ tool: "compare_axis_by_category", rows: [{ value: "question", creatives: 3 }] }} />);
  expect(within(panel).queryByText(note)).toBeNull();
});

it("shows ordered accessible category tags and publication metrics without folded details", () => {
  const { container } = render(<EvidenceCardView anchor="synthetic" names={names} card={{ ...card, hook_type: "question", angle: "how_to", format: "demo", talent: "ordinary_person", cta_type: "shop_now", claims: ["hydration"], published_at: "2026-01-02T00:00:00Z", view_count: 1234, like_count: 56 }} />);
  const tags = [...container.querySelectorAll(".gs-tag")];
  expect(tags.map(tag => tag.getAttribute("data-category"))).toEqual(["hook", "angle", "format", "talent", "cta", "claim"]);
  expect(tags.map(tag => tag.querySelector(".gs-sr-only")!.textContent)).toEqual(["훅: ", "소구: ", "형식: ", "출연자: ", "CTA: ", "효능: "]);
  for (const value of ["합성 훅", "합성 소구", "합성 형식", "일반 출연자", "구매 유도", "합성 효능"]) expect(screen.getByText(value)).toBeTruthy();
  expect(container.querySelector("details")).toBeNull(); expect(screen.getByText("2026-01-02")).toBeTruthy(); expect(screen.getByText("조회수 1,234")).toBeTruthy(); expect(screen.getByText("좋아요 56")).toBeTruthy();
});
it("uses readable missing titles and stretches only a safe original link across its card", () => {
  const { container, rerender } = render(<EvidenceCardView anchor="synthetic" card={{ ...card, title: "  " }} />);
  const link = screen.getByRole("link", { name: "합성 브랜드 · YouTube 광고" });
  expect(link.closest("article")!.getAttribute("data-linked")).toBe("true"); expect(screen.getAllByRole("link")).toHaveLength(1); expect(link.getAttribute("target")).toBe("_blank"); expect(link.textContent).not.toBe(card.evidence_id);
  rerender(<EvidenceCardView anchor="synthetic" card={{ ...card, title: null, brand: null }} />); expect(screen.getByRole("link", { name: "브랜드 정보 없음 · YouTube 광고" })).toBeTruthy();
  rerender(<EvidenceCardView anchor="synthetic" card={{ ...card, url: null }} />); expect(screen.queryByRole("link")).toBeNull(); expect(container.querySelector("article")!.hasAttribute("data-linked")).toBe(false);
  const css = readFileSync(join(process.cwd(), "app/evidence.css"), "utf8");
  expect(css).toMatch(/\.gs-evidence-card h4 a::after\s*\{[^}]*position:\s*absolute[^}]*inset:\s*0/);
  expect(css).toMatch(/\[data-linked="true"\][^{]*\{[^}]*cursor:\s*pointer/);
});
it("shares brand names between card metadata, fallback titles and chips without changing evidence", () => {
  const source = { ...card, source: "instagram", evidence_id: "instagram:synthetic", brand: "beauty_of_joseon", title: null }; const snapshot = JSON.stringify(source);
  const content = <><EvidenceCardView anchor="synthetic" card={source} /><EvidenceChip id={source.evidence_id} card={source} /></>;
  const { rerender, container } = render(<BrandNamesContext.Provider value={new Map([["beauty_of_joseon", "조선미녀"]])}>{content}</BrandNamesContext.Provider>);
  expect(screen.getByText("조선미녀 · Instagram")).toBeTruthy(); expect(screen.getByText("조선미녀").closest(".gs-evidence-chip")).toBeTruthy(); expect(screen.getByRole("link", { name: "조선미녀 · Instagram 광고" })).toBeTruthy();
  expect(container.querySelector('.gs-evidence-chip svg[aria-hidden="true"]')).toBeTruthy(); expect(container.querySelector(".gs-evidence-chip .gs-platform-monogram")).toBeNull();
  rerender(content); expect(screen.getByText("beauty of joseon · Instagram")).toBeTruthy(); expect(screen.getByText("beauty of joseon")).toBeTruthy(); expect(JSON.stringify(source)).toBe(snapshot);
});
it("explains each scored label on focus and omits AI evaluation and triggers when no scores exist", () => {
  const { container, rerender } = render(<PlanResult data={plan} tenantId={null} />);
  const summary = container.querySelector(".gs-quality-summary") as HTMLElement;
  expect(summary.textContent).toBe("품질 검사 통과 · AI 평가 차별성 2/5 · 요청 적합성 3/5");
  for (const [label, name] of [["차별성", "differentiation"], ["요청 적합성", "fit"]] as const) {
    const trigger = within(summary).getByText(label); expect(screen.queryByRole("tooltip")).toBeNull(); fireEvent.focus(trigger);
    const tooltip = screen.getByRole("tooltip"); expect(tooltip.textContent).toBe(scoreExplanations[name]); expect(trigger.getAttribute("aria-describedby")).toBe(tooltip.id); fireEvent.blur(trigger);
  }
  rerender(<PlanResult data={{ ...plan, attempts: [{ attempt: 1, checks_passed: true, scores: null }] }} tenantId={null} />);
  expect(summary.textContent).toBe("품질 검사 통과"); expect(summary.querySelector(".gs-tooltip-trigger")).toBeNull(); expect(screen.queryByText(/AI 평가/)).toBeNull();
});

it("merges marketer distributions in one card while keeping embedded regions and meter names", () => {
  const commands: UiCommand[] = [
    { kind: "show_distribution", data: { tool: "compare_axis_by_category", rows: [{ value: "question", creatives: 2 }] } },
    { kind: "show_distribution", data: { tool: "compare_axis_by_category", rows: [{ value: "desire", creatives: 1 }] } },
  ];
  const snapshot = JSON.stringify(commands);
  render(<ResultsView commands={commands} />);
  expect(screen.getAllByRole("heading", { name: "경쟁사 광고 분포" })).toHaveLength(1);
  expect(screen.getAllByRole("tab").map(node => node.textContent)).toEqual(["훅", "소구"]);
  expect(screen.getByRole("region", { name: "분포" }).getAttribute("data-tool")).toBe("compare_axis_by_category");
  expect(screen.getByRole("meter", { name: "question" }).getAttribute("aria-valuenow")).toBe("2");
  fireEvent.click(screen.getByRole("tab", { name: "소구" }));
  expect(screen.getByRole("meter", { name: "이상형 제시형" }).getAttribute("aria-valuenow")).toBe("1");
  expect(JSON.stringify(commands)).toBe(snapshot);
});

it("softens backdrop edges underneath the unmasked main image using surface-token bands", () => {
  const css = readFileSync(join(process.cwd(), "app/results.css"), "utf8");
  const main = css.match(/\.gs-design-image img\s*\{([^}]*)\}/)![1];
  const backdrop = css.match(/\.gs-design-image img\.gs-design-backdrop\s*\{([^}]*)\}/)![1];
  expect(backdrop).toContain("blur(32px)"); expect(backdrop).toContain("brightness(0.78)"); expect(backdrop).toContain("scale(1.2)");
  expect(main).not.toContain("mask-image"); expect(main).toContain("position: relative");
  const layer = (rule: string) => Number(rule.match(/z-index:\s*(\d+)/)?.[1]);
  for (const [pseudo, direction, edge] of [["before", "bottom", "top"], ["after", "top", "bottom"]]) {
    const rule = css.match(new RegExp(`\\.gs-design-image::${pseudo}\\s*\\{([^}]*)\\}`))![1];
    expect(rule).toContain("height: 14%"); expect(rule).toContain("position: absolute"); expect(rule).toContain("inset-inline: 0");
    expect(rule).toContain("pointer-events: none"); expect(rule).toContain(`linear-gradient(to ${direction}, var(--gs-surface), transparent)`);
    expect(rule).toContain(`${edge}: 0`); expect(rule).not.toMatch(/#[0-9a-f]{3,8}\b/i);
    expect(layer(rule)).toBeGreaterThan(layer(backdrop)); expect(layer(rule)).toBeLessThan(layer(main));
  }
  expect(css.match(/object-fit:\s*cover/g)).toHaveLength(1);
});
it("uses shared tokens for insight totals and comparison column emphasis", () => {
  const css = readFileSync(join(process.cwd(), "app/results.css"), "utf8");
  const rule = (name: string) => css.match(new RegExp(`\\.${name}\\s*\\{([^}]*)\\}`))![1];
  expect(rule("gs-insight-head")).toContain("display: flex"); expect(rule("gs-insight-head")).toContain("justify-content: space-between");
  expect(rule("gs-insight-head")).toContain("align-items: baseline"); expect(rule("gs-insight-head")).toContain("gap: var(--gs-space-3)");
  expect(rule("gs-insight-total")).toContain("color: var(--gs-text-muted)"); expect(rule("gs-insight-total")).toContain("font-size: var(--gs-text-sm)");
  expect(rule("gs-col-primary")).toContain("font-weight: 700"); expect(rule("gs-col-muted")).toContain("color: var(--gs-text-muted)");
});
it("adds comparison column spans and a limit note without sorting standalone rows", () => {
  const rows = [{ n_bottom: 1, n_top: 1, value: "other", count: 2 }, { n_bottom: 5, n_top: 3, value: "question", count: 8 }];
  const snapshot = JSON.stringify(rows);
  render(<DistributionChart data={{ tool: "top_vs_bottom_axis", rows }} names={names} />);
  const table = screen.getByRole("table");
  expect(within(table).getAllByRole("columnheader").map(node => node.textContent)).toEqual(["분류", "상위 25% 광고 수", "하위 25% 광고 수", "건수"]);
  expect(within(table).getAllByRole("row").slice(1).map(row => within(row).getAllByRole("cell")[0].textContent)).toEqual(["기타", names.valueName("question")]);
  expect([...table.querySelectorAll(".gs-col-primary")].map(node => node.textContent)).toEqual(["상위 25% 광고 수", "1", "3"]);
  expect([...table.querySelectorAll(".gs-col-muted")].map(node => node.textContent)).toEqual(["하위 25% 광고 수", "1", "5"]);
  const title = screen.getByRole("heading");
  expect(title.nextElementSibling?.textContent).toBe("같은 플랫폼·브랜드 안에서 조회수 상위 25%와 하위 25% 광고가 각 방식을 쓴 광고 수입니다.");
  expect(title.nextElementSibling?.nextElementSibling?.textContent).toBe("상위 25% 광고 수가 많은 분류부터 5개까지 표시합니다.");
  expect(JSON.stringify(rows)).toBe(snapshot);
});
