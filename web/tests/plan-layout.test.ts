import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, it } from "vitest";

const plan = readFileSync(join(process.cwd(), "app/plan.css"), "utf8");
const tokens = readFileSync(join(process.cwd(), "app/tokens.css"), "utf8");
function rule(css: string, selector: string) {
  const block = css.slice(css.indexOf(`${selector} {`) + selector.length + 2).split("}")[0];
  expect(css.includes(`${selector} {`)).toBe(true);
  return block;
}
it("centers a square close button without typographic offsets", () => {
  const close = rule(plan, ".gs-tab-close");
  expect(close).toMatch(/display:\s*inline-flex/);
  expect(close).toMatch(/align-items:\s*center/);
  expect(close).toMatch(/justify-content:\s*center/);
  expect(close).toMatch(/line-height:\s*1\s*;/);
  expect(close).toMatch(/padding:\s*0\s*;/);
  const width = close.match(/width:\s*(var\(--gs-[\w-]+\))/)?.[1];
  expect(width).toBeTruthy();
  expect(close).toContain(`height: ${width}`);
  expect(close).not.toMatch(/margin-bottom|padding-bottom/);
  expect(rule(plan, ".gs-plan-tab-item")).toMatch(/align-items:\s*center/);
});
it("shares action column width and gap at desktop and narrow widths", () => {
  expect(tokens).toMatch(/--gs-action-col-width:\s*\d+px/);
  expect(tokens).toMatch(/--gs-action-gap:\s*var\(--gs-space-3\)/);
  expect(tokens).toMatch(/@media\s*\(width < 600px\)\s*\{\s*:root\s*\{[^}]*--gs-action-gap:\s*var\(--gs-space-2\)/);
  for (const selector of [".gs-plan-tabs > .gs-button", ".gs-composer-bar .gs-button"]) {
    const button = rule(plan, selector);
    expect(button).toMatch(/flex:\s*0 0 var\(--gs-action-col-width\)/);
    expect(button).toMatch(/width:\s*var\(--gs-action-col-width\)/);
    expect(button).toMatch(/padding-inline:\s*0/);
    expect(button).toMatch(/white-space:\s*nowrap/);
  }
  for (const selector of [".gs-plan-tabs", ".gs-composer-bar"]) {
    expect(rule(plan, selector)).toMatch(/gap:\s*var\(--gs-action-gap\)/);
  }
  const narrow = plan.split("@media (width < 600px)")[1]?.split("@media")[0] ?? "";
  expect(narrow).not.toMatch(/gap\s*:/);
});
