import { readFileSync } from "node:fs";
import { join } from "node:path";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Page from "../app/page";
import { SavedPage } from "../components/saved/SavedPage";
import * as api from "../lib/api";
import type { PlanView, SavedPlan, SchemaResponse } from "../lib/types";

const schema: SchemaResponse = {
  labels: [], relationships: [], taxonomy: {
    hook_type: [{ value: "question", name: "합성 질문형", definition: "합성 정의" }], angle: [], format: [],
  }, claims: [{ value: "hydration", name: "합성 수분" }],
};
const plan: SavedPlan = {
  plan_id: "a".repeat(32), title: "합성 저장 기획", hook_text: "합성 훅 문구", hook_type: "question",
  angle: "how_to", format: "demo", claimed_efficacy: ["hydration"],
  scenes: ["첫 합성 장면", "둘째 합성 장면"], copy_lines: ["첫 합성 카피", "둘째 합성 카피"],
  evidence_ids: ["youtube:a", "youtube:b", "youtube:c", "instagram:d"],
  has_image: false, decided_at: "2026-11-21T02:03:00Z", reason: "합성 승인 사유",
};
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
beforeEach(() => {
  vi.spyOn(api, "getSavedPlans").mockResolvedValue([plan]);
  vi.spyOn(api, "getSchema").mockResolvedValue(schema);
  vi.spyOn(api, "getPlanImage").mockResolvedValue(new Blob(["synthetic"], { type: "image/png" }));
  vi.stubGlobal("URL", class extends URL {
    static createObjectURL = vi.fn().mockReturnValue("blob:synthetic");
    static revokeObjectURL = vi.fn();
  });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("shows the card title, hook, approval time, reason and Korean taxonomy badges", async () => {
  render(<SavedPage tenantId="workspace-a" onPlan={vi.fn()} />);
  const card = await screen.findByRole("button", { name: plan.title });
  expect(within(card).getByText(plan.hook_text!)).toBeTruthy();
  expect(within(card).getByText(/승인 일시/)).toBeTruthy();
  const time = card.querySelector("time")!;
  expect(time.dateTime).toBe(plan.decided_at);
  expect(time.textContent).toBe(new Date(plan.decided_at).toLocaleString("ko-KR"));
  expect(within(card).getByText(`사유: ${plan.reason}`)).toBeTruthy();
  expect(within(card).getByText("합성 질문형")).toBeTruthy();
  expect(within(card).getByText("합성 수분")).toBeTruthy();
  expect(screen.getByText("승인 일시는 광고 기획 결과에서 승인을 저장한 시각입니다.")).toBeTruthy();
  expect(api.getSchema).toHaveBeenCalledExactlyOnceWith("workspace-a");
  expect(document.body.textContent).not.toMatch(/question|hydration|how_to|demo/);
});

it("offers the empty state and navigation action", async () => {
  vi.mocked(api.getSavedPlans).mockResolvedValue([]);
  const onPlan = vi.fn(); render(<SavedPage tenantId="workspace-a" onPlan={onPlan} />);
  expect(await screen.findByRole("heading", { name: "승인한 기획안이 없습니다" })).toBeTruthy();
  expect(screen.getByText("광고 기획 결과에서 승인을 누르면 여기에 모입니다.")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "광고 기획으로" }));
  expect(onPlan).toHaveBeenCalledTimes(1);
});

it("opens the shared panel with ordered scenes, quoted copy and platform counts, then restores focus", async () => {
  render(<SavedPage tenantId="workspace-a" onPlan={vi.fn()} />);
  const card = await screen.findByRole("button", { name: plan.title });
  expect(card.tagName).toBe("BUTTON"); card.focus(); fireEvent.click(card);
  const dialog = screen.getByRole("dialog", { name: plan.title });
  expect(document.activeElement).toBe(dialog);
  const scenes = within(dialog).getByRole("region", { name: "장면 구성" });
  expect(scenes.querySelector("ol")).toBeTruthy();
  expect(within(scenes).getAllByRole("listitem").map(node => node.textContent)).toEqual(plan.scenes);
  expect(Array.from(dialog.querySelectorAll("blockquote"), node => node.textContent)).toEqual(plan.copy_lines);
  expect(within(dialog).getByText("근거 소재 4건")).toBeTruthy();
  expect(within(dialog).getByText("YouTube 3건 · Instagram 1건")).toBeTruthy();
  expect(within(dialog).getByRole("region", { name: "주장 효능" }).textContent).toContain("합성 수분");
  expect(document.body.textContent).not.toMatch(/youtube:|instagram:/);
  for (const id of plan.evidence_ids!) expect(document.body.innerHTML).not.toContain(id);
  fireEvent.click(within(dialog).getByRole("button", { name: "닫기" }));
  expect(screen.queryByRole("dialog")).toBeNull(); expect(document.activeElement).toBe(card);
});

it("groups unknown prefixes under a Korean fallback without exposing IDs", async () => {
  vi.mocked(api.getSavedPlans).mockResolvedValue([{ ...plan, evidence_ids: ["new_source:secret", "missing-prefix", "tiktok:x"] }]);
  render(<SavedPage tenantId="workspace-a" onPlan={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: plan.title }));
  const panel = screen.getByRole("dialog");
  expect(within(panel).getByText("근거 소재 3건")).toBeTruthy();
  expect(within(panel).getByText("TikTok 1건 · 출처 정보 없음 2건")).toBeTruthy();
  expect(panel.textContent).not.toMatch(/new_source|secret|missing-prefix|tiktok:x/);
});

it("renders successful blob images in the card and panel, and revokes the URL on unmount", async () => {
  vi.mocked(api.getSavedPlans).mockResolvedValue([{ ...plan, has_image: true }]);
  const { unmount } = render(<SavedPage tenantId="workspace-a" onPlan={vi.fn()} />);
  const thumbnail = await screen.findByRole("img", { name: "기획안 시안 이미지" });
  expect(thumbnail.getAttribute("src")).toBe("blob:synthetic");
  expect(api.getPlanImage).toHaveBeenCalledExactlyOnceWith("workspace-a", plan.plan_id);
  fireEvent.click(screen.getByRole("button", { name: plan.title }));
  expect(within(screen.getByRole("dialog")).getByRole("img").getAttribute("src")).toBe("blob:synthetic");
  unmount(); expect(URL.revokeObjectURL).toHaveBeenCalledExactlyOnceWith("blob:synthetic");
});

it("revokes replaced workspace images and ignores late image bytes after unmount", async () => {
  vi.mocked(api.getSavedPlans).mockResolvedValue([{ ...plan, has_image: true }]);
  const late = deferred<Blob>();
  vi.mocked(api.getPlanImage).mockResolvedValueOnce(new Blob(["a"])).mockReturnValueOnce(late.promise);
  const { rerender, unmount } = render(<SavedPage tenantId="workspace-a" onPlan={vi.fn()} />);
  await screen.findByRole("img");
  rerender(<SavedPage tenantId="workspace-b" onPlan={vi.fn()} />);
  await waitFor(() => expect(api.getPlanImage).toHaveBeenCalledTimes(2));
  expect(URL.revokeObjectURL).toHaveBeenCalledExactlyOnceWith("blob:synthetic");
  unmount(); await act(async () => { late.resolve(new Blob(["b"])); });
  expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
});

it("shows an image failure tile when the image API rejects", async () => {
  vi.mocked(api.getSavedPlans).mockResolvedValue([{ ...plan, has_image: true }]);
  vi.mocked(api.getPlanImage).mockRejectedValue(new api.ApiError(404, "DESIGN_NOT_FOUND"));
  render(<SavedPage tenantId="workspace-a" onPlan={vi.fn()} />);
  expect(await screen.findByText("시안 이미지를 불러오지 못했습니다")).toBeTruthy();
  expect(screen.queryByRole("img")).toBeNull();
});

it("falls back when blob image decoding fails", async () => {
  vi.mocked(api.getSavedPlans).mockResolvedValue([{ ...plan, has_image: true }]);
  render(<SavedPage tenantId="workspace-a" onPlan={vi.fn()} />);
  fireEvent.error(await screen.findByRole("img"));
  expect(screen.getByText("시안 이미지를 불러오지 못했습니다")).toBeTruthy();
  expect(screen.queryByRole("img")).toBeNull();
});

it("does not request an image for plans without one", async () => {
  render(<SavedPage tenantId="workspace-a" onPlan={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: plan.title }));
  expect(within(screen.getByRole("dialog")).getByText("시안 없음")).toBeTruthy();
  expect(api.getPlanImage).not.toHaveBeenCalled();
});

it("reloads for the new workspace and ignores an old list and schema response", async () => {
  const old = deferred<SavedPlan[]>(); const oldSchema = deferred<SchemaResponse>();
  vi.mocked(api.getSavedPlans).mockReturnValueOnce(old.promise).mockResolvedValueOnce([{ ...plan, title: "새 작업 공간 기획" }]);
  vi.mocked(api.getSchema).mockReturnValueOnce(oldSchema.promise).mockResolvedValueOnce(schema);
  const { rerender } = render(<SavedPage tenantId="workspace-a" onPlan={vi.fn()} />);
  expect(screen.getByRole("status").textContent).toContain("불러오는 중");
  rerender(<SavedPage tenantId="workspace-b" onPlan={vi.fn()} />);
  await screen.findByRole("button", { name: "새 작업 공간 기획" });
  await act(async () => { old.resolve([plan]); oldSchema.resolve({ ...schema, claims: [{ value: "hydration", name: "이전 작업 공간 효능" }] }); });
  expect(api.getSavedPlans).toHaveBeenNthCalledWith(1, "workspace-a");
  expect(api.getSavedPlans).toHaveBeenNthCalledWith(2, "workspace-b");
  expect(screen.queryByRole("button", { name: plan.title })).toBeNull();
  expect(screen.queryByText("이전 작업 공간 효능")).toBeNull();
  expect(screen.getByText("합성 수분")).toBeTruthy();
});

it("clears the previous workspace list and open panel immediately", async () => {
  const next = deferred<SavedPlan[]>();
  vi.mocked(api.getSavedPlans).mockResolvedValueOnce([plan]).mockReturnValueOnce(next.promise);
  const { rerender } = render(<SavedPage tenantId="workspace-a" onPlan={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: plan.title }));
  rerender(<SavedPage tenantId="workspace-b" onPlan={vi.fn()} />);
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(screen.queryByRole("button", { name: plan.title })).toBeNull();
  expect(screen.getByRole("status")).toBeTruthy();
  await act(async () => { next.resolve([]); });
});

it("shows HTTP status and code, then retries the list without refetching the schema", async () => {
  vi.mocked(api.getSavedPlans).mockRejectedValueOnce(new api.ApiError(403, "TENANT_INVALID")).mockResolvedValueOnce([plan]);
  render(<SavedPage tenantId="workspace-a" onPlan={vi.fn()} />);
  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toContain("403"); expect(alert.textContent).toContain("TENANT_INVALID");
  fireEvent.click(screen.getByRole("button", { name: "다시 시도" }));
  expect(await screen.findByRole("button", { name: plan.title })).toBeTruthy();
  expect(api.getSavedPlans).toHaveBeenCalledTimes(2); expect(api.getSchema).toHaveBeenCalledTimes(1);
});

it.each(["missing", "failure"])("keeps the list and uses 기타 for %s schema names", async mode => {
  if (mode === "failure") vi.mocked(api.getSchema).mockRejectedValue(new Error("synthetic"));
  vi.mocked(api.getSavedPlans).mockResolvedValue([{ ...plan, hook_type: "unknown_hook", claimed_efficacy: ["unknown_claim"] }]);
  render(<SavedPage tenantId="workspace-a" onPlan={vi.fn()} />);
  const card = await screen.findByRole("button", { name: plan.title });
  expect(within(card).getAllByText("기타")).toHaveLength(2);
  fireEvent.click(card);
  expect(within(screen.getByRole("region", { name: "주장 효능" })).getByText("기타")).toBeTruthy();
  expect(document.body.textContent).not.toMatch(/unknown_hook|unknown_claim/);
});

it("uses 기타 even for known codes when the schema cannot load", async () => {
  vi.mocked(api.getSchema).mockRejectedValue(new Error("synthetic"));
  render(<SavedPage tenantId="workspace-a" onPlan={vi.fn()} />);
  const card = await screen.findByRole("button", { name: plan.title });
  expect(within(card).getAllByText("기타")).toHaveLength(2);
  expect(card.textContent).not.toMatch(/question|hydration/);
});

it("shows the workspace guidance without fetching or rendering list controls when unselected", () => {
  render(<SavedPage tenantId={null} onPlan={vi.fn()} />);
  expect(screen.getByRole("heading", { name: "저장한 기획" })).toBeTruthy();
  expect(screen.getByText("상단 바에서 작업 공간을 선택하세요.")).toBeTruthy();
  expect(screen.queryByRole("button")).toBeNull(); expect(screen.queryByRole("status")).toBeNull();
  expect(api.getSavedPlans).not.toHaveBeenCalled(); expect(api.getSchema).not.toHaveBeenCalled();
  expect(api.getPlanImage).not.toHaveBeenCalled();
});

it("uses container columns, token spacing, clamped copy and reduced-motion styles without sidebar geometry", () => {
  const css = readFileSync(join(process.cwd(), "app/saved.css"), "utf8");
  expect(css).not.toMatch(/--gs-sidebar/);
  expect(css).toMatch(/container-type:\s*inline-size/);
  expect(css).toMatch(/@container/);
  expect(css).toMatch(/repeat\(\d+, minmax\(0, 1fr\)\)/);
  expect(css).toMatch(/-webkit-line-clamp:\s*2/);
  expect(css).toMatch(/prefers-reduced-motion:\s*reduce/);
  expect(css).toMatch(/gap:\s*var\(--gs-space-/);
});

it("fetches fresh cards after each approval and navigation from the complete Page", async () => {
  vi.restoreAllMocks();
  const approved: SavedPlan[] = []; let asked = 0;
  const second: SavedPlan = { ...plan, plan_id: "b".repeat(32), title: "두 번째 저장 기획" };
  const candidates = [plan, second];
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/workspaces") return Response.json({ workspaces: [{ tenant_id: "workspace-a", display_name: "합성 공간", brand: null, product_name: null }], image_enabled: false });
    if (url === "/api/graph/schema") return Response.json(schema);
    if (url === "/api/ask") {
      const chosen = candidates[asked++];
      const data: PlanView = { plan: chosen, plan_id: chosen.plan_id, passed: true, unknown_count: 0, unknown_codes: {}, efficacy_status: {}, efficacy_summary: { supported: 0, unknown: 0 }, count_label: "합성 건수", result_counts: [], evidence_counts: {}, status: "approved", attempts: [], pattern_alignment: {}, pattern_alignment_label: "합성 비교", disclaimer: "합성 안내", image: null, design_disclaimer: null, product_display: { brand: null, display_name: null, product_name: null } };
      return new Response(`event: ui_command\ndata: ${JSON.stringify({ kind: "show_plan", data })}\n\n`, { headers: { "X-Thread-Id": "workspace-a:synthetic" } });
    }
    if (url === "/api/feedback") {
      const body = JSON.parse(String(init?.body));
      expect(init?.method).toBe("POST"); expect(body.decision).toBe("approved");
      approved.push(candidates.find(item => item.plan_id === body.plan_id)!);
      return Response.json({ status: "ok" });
    }
    if (url === "/api/plans") return Response.json({ plans: [...approved] });
    throw new Error(`Unexpected synthetic fetch: ${url}`);
  });
  vi.stubGlobal("fetch", fetch);
  render(<Page />); await screen.findByLabelText("요청");
  fireEvent.click(screen.getByRole("button", { name: "작업 공간" }));
  fireEvent.click(screen.getByRole("option", { name: "합성 공간" }));
  const nav = within(screen.getByRole("navigation", { name: "주요 화면" }));
  for (const [index, candidate] of candidates.entries()) {
    fireEvent.change(screen.getByLabelText("요청"), { target: { value: `합성 요청 ${index + 1}` } });
    fireEvent.click(screen.getByRole("button", { name: "기획하기" }));
    fireEvent.click(await screen.findByRole("button", { name: "승인" }));
    await waitFor(() => expect(screen.getAllByText("저장했습니다")).toHaveLength(index + 1));
    fireEvent.click(nav.getByRole("button", { name: "저장한 기획" }));
    expect(await screen.findByRole("button", { name: candidate.title })).toBeTruthy();
    expect(screen.getAllByRole("button", { name: /저장 기획/ })).toHaveLength(index + 1);
    const calls = fetch.mock.calls.map(call => call[0]);
    const feedbackIndices = calls.flatMap((url, i) => url === "/api/feedback" ? [i] : []);
    const listIndices = calls.flatMap((url, i) => url === "/api/plans" ? [i] : []);
    expect(listIndices).toHaveLength(index + 1);
    expect(listIndices[index]).toBeGreaterThan(feedbackIndices[index]);
    if (index === 1) expect(feedbackIndices[1]).toBeGreaterThan(listIndices[0]);
    fireEvent.click(nav.getByRole("button", { name: "광고 기획" }));
  }
  expect(approved.map(item => item.plan_id)).toEqual(candidates.map(item => item.plan_id));
});
