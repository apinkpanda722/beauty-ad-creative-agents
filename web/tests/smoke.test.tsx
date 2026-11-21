import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import Page from "../app/page";
import { BRAND } from "../lib/brand";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("renders the product shell and one plan heading without the old scaffold", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ workspaces: [], image_enabled: false }))));
  render(<Page />);
  expect(screen.getByText(BRAND.name)).toBeTruthy();
  expect(screen.getByText(BRAND.nameKo)).toBeTruthy();
  expect(await screen.findByRole("heading", { name: "광고 기획", level: 1 })).toBeTruthy();
  expect(screen.getAllByRole("heading", { name: "광고 기획", level: 1 })).toHaveLength(1);
  expect(within(screen.getByRole("navigation", { name: "주요 화면" })).getAllByRole("button")).toHaveLength(5);
  expect(screen.queryByRole("heading", { name: "Beauty Ad Creative Agents" })).toBeNull();
  expect(screen.queryByRole("tablist", { name: "화면 선택" })).toBeNull();
  expect(screen.queryByRole("tab", { name: "대화" })).toBeNull();
  expect(screen.queryByRole("tab", { name: "전체 스키마" })).toBeNull();
  expect(screen.queryAllByRole("tablist", { name: "기획 탭" })).toHaveLength(1);
});
