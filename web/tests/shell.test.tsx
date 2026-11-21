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
const labels = ["광고 기획", "근거 소재", "저장한 기획", "지식 그래프", "실행 기록·검증"];
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
  await screen.findByLabelText("요청");
  const nav = screen.getByRole("navigation", { name: "주요 화면" });
  const items = within(nav).getAllByRole("button");
  expect(items.map(item => item.textContent)).toEqual(labels);
  expect(within(nav).getAllByRole("group").map(group => group.getAttribute("aria-label"))).toEqual(["작업", "관리"]);
  expect(within(within(nav).getByRole("group", { name: "작업" })).getAllByRole("button").map(item => item.textContent)).toEqual(labels.slice(0, 3));
  expect(within(within(nav).getByRole("group", { name: "관리" })).getAllByRole("button").map(item => item.textContent)).toEqual(labels.slice(3));
  expect(items.every(item => item.querySelector("svg[aria-hidden=true]"))).toBe(true);
  expect(items[0].classList.contains("gs-nav-pill")).toBe(true);
  expect(screen.getAllByRole("heading", { name: "광고 기획" })).toHaveLength(1);
  expect(items[0].getAttribute("aria-current")).toBe("page");
  expect(screen.getByRole("region", { name: "대화" })).toBeTruthy();
  for (const index of [1, 2, 3, 4, 0]) {
    fireEvent.click(items[index]);
    expect(screen.queryByText("Beauty Ad Creative Agents")).toBeNull();
    expect(screen.queryByRole("tablist", { name: "화면 선택" })).toBeNull();
    expect(screen.queryByRole("tab", { name: "대화" })).toBeNull();
    expect(screen.queryByRole("tab", { name: "전체 스키마" })).toBeNull();
    expect(screen.queryAllByRole("tablist", { name: "기획 탭" })).toHaveLength(index === 0 ? 1 : 0);
    expect(items.map(item => item.getAttribute("aria-current"))).toEqual(labels.map((_, i) => i === index ? "page" : null));
    if ([1, 2, 4].includes(index)) {
      expect(screen.getByRole("heading", { name: labels[index] })).toBeTruthy();
      if (index === 1) {
        expect(screen.getByRole("heading", { name: "아직 근거 소재가 없습니다" })).toBeTruthy();
        expect(screen.getByRole("button", { name: "광고 기획으로" })).toBeTruthy();
      } else if (index === 2) expect(screen.getByText("준비 중")).toBeTruthy();
      else { expect(screen.getByRole("heading", { name: "아직 실행한 요청이 없습니다" })).toBeTruthy(); expect(screen.queryByText("준비 중")).toBeNull(); }
    } else if (index === 3) {
      expect(screen.getByText("상단 바에서 작업 공간을 선택하세요.")).toBeTruthy();
    } else expect(screen.getByRole("region", { name: "대화" })).toBeTruthy();
  }
  fireEvent.click(screen.getByRole("button", { name: "작업 공간" }));
  fireEvent.click(screen.getByRole("option", { name: /합성 공간/ }));
  fireEvent.click(items[3]);
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
  await screen.findByLabelText("요청");
  fireEvent.click(screen.getByRole("button", { name: "작업 공간" }));
  fireEvent.click(screen.getByRole("option", { name: /합성 공간/ }));
  fireEvent.change(screen.getByLabelText("요청"), { target: { value: "합성 진행 요청" } });
  fireEvent.click(screen.getByRole("button", { name: "기획하기" }));
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
  fireEvent.click(screen.getByRole("button", { name: "실행 기록·검증" }));
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

it("opens the workspace chip by keyboard, moves options, selects and restores focus on Escape", async () => {
  vi.mocked(getWorkspaces).mockResolvedValue({ workspaces: [
    { tenant_id: "a", display_name: "합성 A", brand: null, product_name: null },
    { tenant_id: "b", display_name: "합성 B", brand: null, product_name: null },
  ], image_enabled: false });
  render(<Page />); await screen.findByLabelText("요청");
  const chip = screen.getByRole("button", { name: "작업 공간" });
  expect(chip.getAttribute("aria-haspopup")).toBe("listbox");
  expect(chip.getAttribute("aria-expanded")).toBe("false");
  for (const key of ["Enter", " ", "ArrowDown"]) {
    chip.focus(); fireEvent.keyDown(chip, { key });
    expect(screen.getByRole("listbox")).toBeTruthy();
    const options = screen.getAllByRole("option");
    expect(document.activeElement).toBe(options[0]);
    fireEvent.keyDown(options[0], { key: "ArrowDown" });
    expect(document.activeElement).toBe(options[1]);
    fireEvent.keyDown(options[1], { key: "ArrowUp" });
    expect(document.activeElement).toBe(options[0]);
    fireEvent.keyDown(options[0], { key: "Escape" });
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(document.activeElement).toBe(chip);
  }
  fireEvent.keyDown(chip, { key: "ArrowDown" });
  fireEvent.keyDown(document.activeElement!, { key: "ArrowDown" });
  fireEvent.keyDown(document.activeElement!, { key: "Enter" });
  expect(chip.textContent).toContain("합성 B");
  expect((screen.getByLabelText("요청") as HTMLTextAreaElement).disabled).toBe(false);
  fireEvent.click(chip); fireEvent.mouseDown(document.body);
  expect(screen.queryByRole("listbox")).toBeNull();
  expect(document.querySelector("select, .workspace-picker")).toBeNull();
});
