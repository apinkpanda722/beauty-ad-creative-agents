import { readFileSync } from "node:fs";
import { join } from "node:path";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Page from "../app/page";
import { getSchema, getWorkspaces, postChatAsk } from "../lib/api";
import { BRAND } from "../lib/brand";
import type { SseFrame } from "../lib/types";

vi.mock("../lib/api", async original => ({
  ...await original<typeof import("../lib/api")>(),
  getWorkspaces: vi.fn(), getSchema: vi.fn(), postChatAsk: vi.fn(),
}));
const labels = ["광고 기획", "근거 소재", "지식 그래프", "실행 기록", "저장한 기획"];
beforeEach(() => {
  vi.mocked(getWorkspaces).mockResolvedValue({ workspaces: [
    { tenant_id: "synthetic-workspace", display_name: "합성 공간", brand: "합성 브랜드", product_name: "합성 제품" },
  ], image_enabled: false });
  vi.mocked(getSchema).mockResolvedValue({ labels: [], relationships: [], taxonomy: { hook_type: [], angle: [], format: [] }, claims: [] });
});
afterEach(() => { cleanup(); vi.resetAllMocks(); });

it("renders exactly five ordered navigation items and switches the current page and content", async () => {
  render(<Page />);
  expect(screen.getByText(BRAND.name)).toBeTruthy();
  expect(screen.getByText(BRAND.nameKo)).toBeTruthy();
  await screen.findByRole("option", { name: /합성 공간/ });
  const nav = screen.getByRole("navigation", { name: "주요 화면" });
  const items = within(nav).getAllByRole("button");
  expect(items.map(item => item.textContent)).toEqual(labels);
  expect(items[0].getAttribute("aria-current")).toBe("page");
  expect(screen.getByRole("region", { name: "대화" })).toBeTruthy();
  for (const index of [1, 2, 3, 4, 0]) {
    fireEvent.click(items[index]);
    expect(items.map(item => item.getAttribute("aria-current"))).toEqual(labels.map((_, i) => i === index ? "page" : null));
    if ([1, 3, 4].includes(index)) {
      expect(screen.getByRole("heading", { name: labels[index] })).toBeTruthy();
      expect(screen.getByText("준비 중")).toBeTruthy();
    } else if (index === 2) {
      expect(screen.getByText("대화 탭에서 작업 공간을 선택하세요.")).toBeTruthy();
    } else expect(screen.getByRole("region", { name: "대화" })).toBeTruthy();
  }
  fireEvent.change(screen.getByLabelText("작업 공간"), { target: { value: "synthetic-workspace" } });
  fireEvent.click(items[2]);
  expect(await screen.findByText("표시할 노드가 없습니다")).toBeTruthy();
  expect(getSchema).toHaveBeenCalledExactlyOnceWith("synthetic-workspace");
});

it("keeps the same running turn and stream across navigation, including results arriving while away", async () => {
  let finish!: () => void;
  const gate = new Promise<void>(resolve => { finish = resolve; });
  async function* events(): AsyncGenerator<SseFrame> {
    await gate;
    yield { event: "token", data: { text: "합성 완료 결과" } };
  }
  vi.mocked(postChatAsk).mockResolvedValue({ threadId: "synthetic:thread", events: events() });
  render(<Page />);
  await screen.findByRole("option", { name: /합성 공간/ });
  fireEvent.change(screen.getByLabelText("작업 공간"), { target: { value: "synthetic-workspace" } });
  fireEvent.change(screen.getByLabelText("요청"), { target: { value: "합성 진행 요청" } });
  fireEvent.click(screen.getByRole("button", { name: "전송" }));
  await waitFor(() => expect(postChatAsk).toHaveBeenCalledTimes(1));
  const signal = vi.mocked(postChatAsk).mock.calls[0][0].signal!;
  const turn = screen.getByText("합성 진행 요청");
  expect((screen.getByLabelText("요청") as HTMLTextAreaElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "근거 소재" }));
  expect(screen.queryByRole("region", { name: "대화" })).toBeNull();
  expect(signal.aborted).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "광고 기획" }));
  expect(screen.getByText("합성 진행 요청")).toBe(turn);
  expect((screen.getByLabelText("요청") as HTMLTextAreaElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "실행 기록" }));
  await act(async () => { finish(); await gate; });
  fireEvent.click(screen.getByRole("button", { name: "광고 기획" }));
  expect(screen.getAllByText("합성 진행 요청")).toHaveLength(1);
  expect(screen.getByText("합성 완료 결과")).toBeTruthy();
  expect((screen.getByLabelText("요청") as HTMLTextAreaElement).disabled).toBe(false);
  expect(postChatAsk).toHaveBeenCalledTimes(1);
  expect(signal.aborted).toBe(false);
});

it("defines a light-only color scheme", () => {
  const css = readFileSync(join(process.cwd(), "app/tokens.css"), "utf8");
  expect(css).toMatch(/color-scheme\s*:\s*light\s*;/);
  expect(css).not.toMatch(/prefers-color-scheme\s*:\s*dark/i);
});
