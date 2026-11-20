import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { Chat } from "../components/Chat";
import { EvidenceCards } from "../components/EvidenceCards";
import { PlanCard } from "../components/PlanCard";
import { AggregatesPanel } from "../components/AggregatesPanel";
import { DistributionChart } from "../components/DistributionChart";
import { DesignImage } from "../components/DesignImage";
import { FeedbackBar, FeedbackSession } from "../components/FeedbackBar";
import { CostLine } from "../components/CostLine";
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

it("renders separate code checks, evaluation state, unknown badge, neutral pattern and raw taxonomy fallback", () => {
  const { container, rerender } = render(<PlanCard data={plan} tenantId="synthetic" evidenceAnchors={{ [card.evidence_id!]: "synthetic-anchor" }} />);
  expect(screen.getByText("근거 연결 없음 0건").className).toContain("clear");
  expect(screen.getByText("코드 검사: 통과")).toBeTruthy();
  expect(screen.getByText("평가 상태: 검토 필요")).toBeTruthy();
  expect(screen.getByText("question")).toBeTruthy();
  for (const label of ["같음", "다름", "비교 불가", "점유율 비교 불가", "비교한 축 2개 중 같은 축 1개", plan.pattern_alignment_label, plan.disclaimer]) expect(screen.getAllByText(label).length).toBeGreaterThan(0);
  expect(container.textContent).not.toMatch(/좋음|나쁨|우수|미달/);
  expect(screen.getByRole("link", { name: card.evidence_id! }).getAttribute("href")).toBe("#synthetic-anchor");
  expect(screen.queryByRole("link", { name: "youtube:absent" })).toBeNull();
  expect(screen.getByText(/되돌림 0회/)).toBeTruthy();
  expect(screen.getByText(/차별성 \(differentiation\): 2/)).toBeTruthy();
  rerender(<PlanCard data={{ ...plan, unknown_count: 3, unknown_codes: { CERT_REQUIRED_UNVERIFIED: 1, EFFICACY_UNKNOWN: 1, SYNTHETIC_UNKNOWN: 1 }, passed: false, status: "failed" }} tenantId="synthetic" names={names} />);
  expect(screen.getByText("근거 연결 없음 3건").className).toContain("attention");
  expect(screen.getByText(/인증 연결 없음.*1건/)).toBeTruthy();
  expect(screen.getByText(/효능 근거 연결 없음.*1건/)).toBeTruthy();
  expect(screen.getByText(/SYNTHETIC_UNKNOWN.*1건/)).toBeTruthy();
  expect(screen.getByText("코드 검사: 실패")).toBeTruthy();
  expect(screen.getByText("평가 상태: 실패")).toBeTruthy();
  expect(screen.getByText("합성 효능 · 확인됨")).toBeTruthy();
  expect(screen.getByText("soothing · 근거 연결 없음")).toBeTruthy();
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
  const { rerender, container } = render(<EvidenceCards data={{ cards: [labeled], missing: 0 }} names={names} />);
  for (const text of ["합성 훅", "합성 소구", "합성 형식", "일반 출연자", "구매 유도", "합성 효능", "synthetic_claim"]) expect(screen.getByText(text)).toBeTruthy();
  expect(container.textContent).not.toMatch(/좋음|효과적|인기|우수|나쁨/);
  rerender(<EvidenceCards data={{ cards: [card], missing: 0 }} />);
  expect(screen.getByText("분석 대상 아님").className).toBe("muted");
  rerender(<EvidenceCards data={{ cards: [{ ...card, talent: "synthetic_talent", cta_type: "synthetic_cta" }], missing: 0 }} />);
  expect(screen.getByText("synthetic_talent")).toBeTruthy(); expect(screen.getByText("synthetic_cta")).toBeTruthy();
  expect(screen.queryByText("분석 대상 아님")).toBeNull(); expect(screen.queryByText("합성 훅")).toBeNull();
});
it("validates thumbnail IDs and external schemes, handles nulls, missing and image load failure", () => {
  const { rerender } = render(<EvidenceCards data={{ cards: [card], missing: 2 }} />);
  const thumbnail = screen.getByRole("img") as HTMLImageElement;
  expect(thumbnail.getAttribute("src")).toBe("https://i.ytimg.com/vi/abc_123-/hqdefault.jpg");
  expect(thumbnail.getAttribute("referrerpolicy")).toBe("no-referrer"); expect(thumbnail.getAttribute("loading")).toBe("lazy");
  const link = screen.getByRole("link"); expect(link.getAttribute("rel")).toBe("noopener noreferrer"); expect(link.getAttribute("target")).toBe("_blank");
  expect(screen.getByText("조회수 정보 없음")).toBeTruthy(); expect(screen.getByText("게시일 정보 없음")).toBeTruthy(); expect(screen.getByText(/2건.*불러오지 못/)).toBeTruthy();
  fireEvent.error(thumbnail); expect(screen.queryByRole("img")).toBeNull(); expect(screen.getByLabelText("youtube 출처")).toBeTruthy();
  rerender(<EvidenceCards data={{ cards: [{ ...card, evidence_id: "youtube:bad/id", url: "javascript:alert(1)" }, { ...card, evidence_id: "instagram:b", source: "instagram", url: "" }, { ...card, evidence_id: "tiktok:c", source: "tiktok", url: "http://example.test/" }], missing: 0 }} />);
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
  rerender(<CostLine data={{ label: "합성 비용 레이블", text_spent_usd: .012345, max_text_cost_usd: 1 }} />);
  expect(container.textContent).toContain("합성 비용 레이블"); expect(container.textContent).toContain("$0.0123"); expect(container.textContent).toContain("이미지 제외");
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
it.each([true, false])("renders ordered command components in Chat with schema success=%s and display_text only", async success => {
  const commands: UiCommand[] = [{ kind: "show_cost", data: { label: "합성 비용", text_spent_usd: .01, max_text_cost_usd: 1 } }, { kind: "show_aggregates", data: aggregates }, { kind: "show_distribution", data: { tool: "synthetic", rows: [{ value: "합성 분포", creatives: 1 }] } }, { kind: "show_plan", data: plan }, { kind: "show_plan", data: { ...plan, plan: { title: "합성 두 번째 기획" } } }, { kind: "show_evidence_cards", data: { cards: [card], missing: 0 } }];
  const frames: SseFrame[] = [...commands.map(data => ({ event: "ui_command" as const, data })), { event: "token", data: { text: "합성 숨긴 원문", display_text: "합성 화면 문장" } }];
  const bytes = new TextEncoder().encode(frames.map(f => `event: ${f.event}\ndata: ${JSON.stringify(f.data)}\n\n`).join(""));
  const fetch = vi.fn().mockImplementation((url: string) => Promise.resolve(url === "/api/graph/schema" ? new Response(JSON.stringify(success ? schema : { detail: "GRAPH_UNAVAILABLE" }), { status: success ? 200 : 503 }) : new Response(new ReadableStream({ start(c) { c.enqueue(bytes); c.close(); } })))); vi.stubGlobal("fetch", fetch);
  render(<Chat workspaces={[{ tenant_id: "synthetic", display_name: "합성 공간", brand: null, product_name: null }]} imageEnabled={false} />);
  fireEvent.change(screen.getByLabelText("작업 공간"), { target: { value: "synthetic" } }); fireEvent.change(screen.getByLabelText("요청"), { target: { value: "합성 요청" } }); fireEvent.click(screen.getByRole("button", { name: "전송" }));
  await screen.findByText("합성 화면 문장"); await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  const nodes = [screen.getByRole("region", { name: "근거 소재" }), screen.getByRole("heading", { name: "합성 기획" }), screen.getByRole("heading", { name: "합성 두 번째 기획" }), screen.getByRole("region", { name: "분포" }), screen.getByRole("region", { name: "검증된 집계(도구가 센 값)" }), screen.getByText(/합성 비용.*\$0.0100/)];
  for (let i = 1; i < nodes.length; i++) expect(nodes[i - 1].compareDocumentPosition(nodes[i]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
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
