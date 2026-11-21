import { readFileSync } from "node:fs";
import { join } from "node:path";
import { StrictMode, useState } from "react";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { Badge, Button, Card, DataTable, EmptyState, PageHeader, SidePanel, Skeleton, Tabs, Tooltip } from "../components/ui";

afterEach(cleanup);

const tabs = [
  { value: "first", label: "첫 탭", panel: "첫 내용" },
  { value: "disabled", label: "비활성 탭", disabled: true, panel: "숨긴 내용" },
  { value: "second", label: "둘째 탭", panel: "둘째 내용" },
  { value: "third", label: "셋째 탭", panel: "셋째 내용" },
];

it("moves tab focus and controlled selection with arrows, wrapping and skipping disabled tabs", () => {
  function Example() {
    const [value, onChange] = useState("first");
    return <Tabs label="합성 탭" items={tabs} value={value} onChange={onChange} />;
  }
  render(<Example />);
  const items = within(screen.getByRole("tablist", { name: "합성 탭" })).getAllByRole("tab");
  expect(items.map(item => item.getAttribute("aria-selected"))).toEqual(["true", "false", "false", "false"]);
  items[0].focus();
  for (const [key, index] of [["ArrowRight", 2], ["ArrowRight", 3], ["ArrowRight", 0], ["ArrowLeft", 3], ["Home", 0], ["End", 3]] as const) {
    fireEvent.keyDown(document.activeElement!, { key });
    expect(document.activeElement).toBe(items[index]);
    expect(items.map(item => item.getAttribute("aria-selected"))).toEqual(items.map((_, i) => String(i === index)));
    expect(items.map(item => item.tabIndex)).toEqual(items.map((_, i) => i === index ? 0 : -1));
    const panel = screen.getByRole("tabpanel");
    expect(panel.id).toBe(items[index].getAttribute("aria-controls"));
    expect(panel.getAttribute("aria-labelledby")).toBe(items[index].id);
  }
});

it("leaves tab selection to the parent on click", () => {
  const onChange = vi.fn();
  const { rerender } = render(<Tabs label="제어 탭" items={tabs} value="first" onChange={onChange} />);
  fireEvent.click(screen.getByRole("tab", { name: "둘째 탭" }));
  expect(onChange).toHaveBeenCalledExactlyOnceWith("second");
  expect(screen.getByRole("tab", { name: "첫 탭" }).getAttribute("aria-selected")).toBe("true");
  rerender(<Tabs label="제어 탭" items={tabs} value="second" onChange={onChange} />);
  expect(screen.getByRole("tab", { name: "둘째 탭" }).getAttribute("aria-selected")).toBe("true");
});

function PanelExample() {
  const [value, onChange] = useState(false);
  return <>
    <Button onClick={() => onChange(true)}>패널 열기</Button>
    <SidePanel title="합성 상세" value={value} onChange={onChange}>
      <Button>마지막 행동</Button>
    </SidePanel>
  </>;
}

it("focuses the open panel, traps Tab in both directions and restores its opener after Escape", () => {
  render(<StrictMode><PanelExample /></StrictMode>);
  const opener = screen.getByRole("button", { name: "패널 열기" });
  expect(screen.queryByRole("dialog")).toBeNull();
  opener.focus();
  fireEvent.click(opener);
  const panel = screen.getByRole("dialog", { name: "합성 상세" });
  expect(document.activeElement).toBe(panel);
  expect(panel.getAttribute("aria-modal")).toBe("true");
  const close = within(panel).getByRole("button", { name: "닫기" });
  const last = within(panel).getByRole("button", { name: "마지막 행동" });
  fireEvent.keyDown(panel, { key: "Tab", shiftKey: true });
  expect(document.activeElement).toBe(last);
  fireEvent.keyDown(last, { key: "Tab" });
  expect(document.activeElement).toBe(close);
  fireEvent.keyDown(close, { key: "Tab", shiftKey: true });
  expect(document.activeElement).toBe(last);
  opener.focus();
  expect(document.activeElement).toBe(panel);
  fireEvent.keyDown(panel, { key: "Escape" });
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(document.activeElement).toBe(opener);
  fireEvent.click(opener);
  fireEvent.click(screen.getByRole("button", { name: "닫기" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(document.activeElement).toBe(opener);
});

it("requests panel closure without changing the controlled value and restores focus on unmount", () => {
  const onChange = vi.fn();
  const opener = document.createElement("button");
  document.body.append(opener);
  opener.focus();
  const { unmount } = render(<SidePanel title="제어 패널" value onChange={onChange}>내용</SidePanel>);
  fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
  expect(onChange).toHaveBeenCalledExactlyOnceWith(false);
  expect(screen.getByRole("dialog")).toBe(document.activeElement);
  unmount();
  expect(document.activeElement).toBe(opener);
  opener.remove();
});

const rows = [{ id: "a", name: "합성 A" }, { id: "b", name: "합성 B" }];
const columns = [{ key: "name", header: "이름", render: (row: typeof rows[number]) => row.name }];
const emptyState = { title: "결과 없음", description: "조건을 바꾸어 보세요.", action: { label: "조건 초기화", onClick: vi.fn() } };

it("renders a table header row and controlled click or keyboard selection", () => {
  const onChange = vi.fn();
  const { rerender } = render(<DataTable caption="합성 목록" columns={columns} rows={rows} rowKey={row => row.id} value="a" onChange={onChange} emptyState={emptyState} />);
  const table = screen.getByRole("table", { name: "합성 목록" });
  expect(within(table).getAllByRole("row")).toHaveLength(3);
  expect(within(table).getByRole("columnheader", { name: "이름" }).getAttribute("scope")).toBe("col");
  const dataRows = within(table).getAllByRole("row").slice(1);
  expect(dataRows.map(row => row.getAttribute("aria-selected"))).toEqual(["true", "false"]);
  fireEvent.click(dataRows[1]);
  expect(onChange).toHaveBeenNthCalledWith(1, "b");
  expect(dataRows.map(row => row.getAttribute("aria-selected"))).toEqual(["true", "false"]);
  fireEvent.keyDown(dataRows[1], { key: "Enter" });
  fireEvent.keyDown(dataRows[1], { key: " " });
  expect(onChange.mock.calls).toEqual([["b"], ["b"], ["b"]]);
  rerender(<DataTable caption="합성 목록" columns={columns} rows={rows} rowKey={row => row.id} value="b" onChange={onChange} emptyState={emptyState} />);
  expect(dataRows.map(row => row.getAttribute("aria-selected"))).toEqual(["false", "true"]);
});

it("renders EmptyState inside an empty table with one working action", () => {
  const onClick = vi.fn();
  render(<DataTable caption="빈 목록" columns={columns} rows={[]} rowKey={row => row.id} emptyState={{ ...emptyState, action: { label: "조건 초기화", onClick } }} />);
  expect(screen.getByRole("columnheader", { name: "이름" })).toBeTruthy();
  expect(screen.getByRole("heading", { name: "결과 없음" })).toBeTruthy();
  expect(screen.getByText("조건을 바꾸어 보세요.")).toBeTruthy();
  expect(screen.getAllByRole("button")).toHaveLength(1);
  fireEvent.click(screen.getByRole("button", { name: "조건 초기화" }));
  expect(onClick).toHaveBeenCalledTimes(1);
});

it("does not select rows when their nested action is used", () => {
  const onChange = vi.fn();
  const onClick = vi.fn();
  render(<DataTable caption="행동 목록" columns={[{ key: "action", header: "행동", render: () => <Button onClick={onClick}>행동</Button> }]} rows={[rows[0]]} rowKey={row => row.id} onChange={onChange} emptyState={emptyState} />);
  const action = screen.getByRole("button", { name: "행동" });
  fireEvent.click(action);
  fireEvent.keyDown(action, { key: "Enter" });
  expect(onClick).toHaveBeenCalledTimes(1);
  expect(onChange).not.toHaveBeenCalled();
});

it("blocks loading, disabled and aria-disabled button clicks while exposing busy state", () => {
  const onClick = vi.fn();
  const { rerender } = render(<Button loading onClick={onClick}>저장</Button>);
  const button = screen.getByRole("button", { name: "저장" }) as HTMLButtonElement;
  expect(button.type).toBe("button");
  expect(button.disabled).toBe(true);
  expect(button.getAttribute("aria-disabled")).toBe("true");
  expect(button.getAttribute("aria-busy")).toBe("true");
  fireEvent.click(button);
  expect(onClick).not.toHaveBeenCalled();
  rerender(<Button disabled onClick={onClick}>저장</Button>);
  fireEvent.click(button);
  rerender(<Button aria-disabled="true" onClick={onClick}>저장</Button>);
  fireEvent.click(button);
  expect(onClick).not.toHaveBeenCalled();
  rerender(<Button onClick={onClick}>저장</Button>);
  expect(button.disabled).toBe(false);
  expect(button.getAttribute("aria-busy")).toBe("false");
  fireEvent.click(button);
  expect(onClick).toHaveBeenCalledTimes(1);
});

it.each(["primary", "secondary", "ghost"] as const)("exposes %s button styling in both sizes", variant => {
  const { rerender } = render(<Button variant={variant} size="sm">행동</Button>);
  const button = screen.getByRole("button");
  expect(button.classList.contains(`gs-button-${variant}`)).toBe(true);
  expect(button.classList.contains("gs-button-sm")).toBe(true);
  rerender(<Button variant={variant} size="md">행동</Button>);
  expect(button.classList.contains("gs-button-md")).toBe(true);
});

it.each(["neutral", "accent", "success", "warn", "danger"] as const)("requires a visible text label for the %s badge and omits blank labels", variant => {
  const { container, rerender } = render(<Badge variant={variant} label="합성 상태" />);
  expect(screen.getByText("합성 상태").classList.contains(`gs-badge-${variant}`)).toBe(true);
  rerender(<Badge variant={variant} label="" />);
  expect(container.childElementCount).toBe(0);
  rerender(<Badge variant={variant} label={"  \n "} />);
  expect(container.childElementCount).toBe(0);
});

it("renders the remaining presentation components with their content and accessible loading status", () => {
  render(<Card>
    <PageHeader title="합성 화면" description="한 줄 설명" actions={<Button>새 행동</Button>} />
    <Skeleton label="합성 로딩" />
    <EmptyState {...emptyState} />
  </Card>);
  expect(screen.getByRole("heading", { level: 1, name: "합성 화면" })).toBeTruthy();
  expect(screen.getByText("한 줄 설명")).toBeTruthy();
  expect(screen.getByRole("button", { name: "새 행동" })).toBeTruthy();
  expect(screen.getByRole("status", { name: "합성 로딩" })).toBeTruthy();
});

it("defines scoped reduced motion, a two-pixel token focus ring and full-opacity disabled buttons", () => {
  const css = readFileSync(join(process.cwd(), "app/ui.css"), "utf8");
  expect(css).toMatch(/@media\s*\(prefers-reduced-motion:\s*reduce\)/);
  expect(css).toMatch(/animation:\s*none\s*!important/);
  expect(css).toMatch(/transition:\s*none\s*!important/);
  expect(css).toMatch(/:focus-visible[^}]*outline:\s*2px solid var\(--gs-accent\)/s);
  expect(css).toMatch(/\.gs-button:disabled[^}]*opacity:\s*1/s);
  expect(css).not.toMatch(/#[0-9a-f]{3,8}\b|\brgba?\(/i);
});


it("opens tooltips only on hover or focus, links descriptions and dismisses on leave, blur and Escape", () => {
  render(<Tooltip content={<strong>합성 설명</strong>} placement="bottom" align="end">합성 용어</Tooltip>);
  const trigger = screen.getByText("합성 용어");
  expect(trigger.tabIndex).toBe(0); expect(trigger.hasAttribute("title")).toBe(false);
  const closed = () => { expect(screen.queryByRole("tooltip")).toBeNull(); expect(trigger.hasAttribute("aria-describedby")).toBe(false); };
  const opened = () => {
    const tip = screen.getByRole("tooltip"); expect(tip.textContent).toBe("합성 설명");
    expect(trigger.getAttribute("aria-describedby")).toBe(tip.id);
    expect(tip.getAttribute("data-placement")).toBe("bottom"); expect(tip.getAttribute("data-align")).toBe("end");
  };
  closed(); fireEvent.mouseEnter(trigger); opened(); fireEvent.mouseLeave(trigger); closed();
  fireEvent.focus(trigger); opened(); fireEvent.blur(trigger); closed();
  fireEvent.focus(trigger); opened(); fireEvent.keyDown(trigger, { key: "Escape" }); closed();
  fireEvent.mouseEnter(trigger); opened(); fireEvent.keyDown(document, { key: "Escape" }); closed();
});
it("exports Tooltip and bounds tooltip styling with tokens and reduced motion", () => {
  const css = readFileSync(join(process.cwd(), "app/ui.css"), "utf8");
  const tokens = readFileSync(join(process.cwd(), "app/tokens.css"), "utf8");
  expect(css).toMatch(/\.gs-tooltip\s*\{[^}]*max-width:\s*min\(var\(--gs-tooltip-max-width\), 90vw\)/);
  expect(tokens).toMatch(/--gs-tooltip-max-width:\s*280px/);
  expect(css.slice(css.indexOf("@media (prefers-reduced-motion: reduce)"))).toMatch(/transition:\s*none/);
  expect(readFileSync(join(process.cwd(), "components/ui/index.ts"), "utf8")).toContain('export { Tooltip }');
});
