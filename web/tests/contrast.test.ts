import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, it } from "vitest";

const css = readFileSync(join(process.cwd(), "app/tokens.css"), "utf8");
const colors = {
  "--gs-text": "#0F172A",
  "--gs-text-muted": "#475569",
  "--gs-accent": "#0F766E",
  "--gs-danger": "#B91C1C",
  "--gs-bg": "#FFFFFF",
};
const pairs = [
  ["--gs-text", "--gs-bg"],
  ["--gs-text-muted", "--gs-bg"],
  ["--gs-accent", "--gs-bg"],
  ["--gs-danger", "--gs-bg"],
] as const;

function luminance(hex: string): number {
  const channels = [1, 3, 5].map(start => {
    const value = parseInt(hex.slice(start, start + 2), 16) / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
}

it("keeps the actual CSS token pairs above WCAG AA contrast", () => {
  expect(pairs.length).toBeGreaterThan(0);
  for (const [token, expected] of Object.entries(colors)) {
    const actual = css.match(new RegExp(`${token}\\s*:\\s*(#[0-9a-f]{6})\\s*;`, "i"));
    expect(actual?.[1].toUpperCase(), token).toBe(expected);
  }
  for (const [foreground, background] of pairs) {
    const a = luminance(colors[foreground]);
    const b = luminance(colors[background]);
    expect((Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05), foreground).toBeGreaterThanOrEqual(4.5);
  }
});
