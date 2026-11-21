import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, it } from "vitest";
import { LAYER_COLORS, LAYER_BORDER_COLORS, LABEL_COLORS, LABEL_BORDER_COLORS } from "../lib/graph";

const css = readFileSync(join(process.cwd(), "app/tokens.css"), "utf8");
const colors = {
  "--gs-text": "#0F172A",
  "--gs-text-muted": "#475569",
  "--gs-accent": "#0F766E",
  "--gs-danger": "#B91C1C",
  "--gs-accent-weak": "#F0FDFA",
  "--gs-success": "#166534",
  "--gs-success-weak": "#F0FDF4",
  "--gs-bg": "#FFFFFF",
};
const pairs = [
  ["--gs-accent", "--gs-accent-weak"],
  ["--gs-success", "--gs-bg"],
  ["--gs-success", "--gs-success-weak"],
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

function tokenColor(token: string, expected: string) {
  const actual = css.match(new RegExp(`${token}\\s*:\\s*(#[0-9a-f]{6})\\s*;`, "i"))?.[1].toUpperCase();
  expect(actual, token).toBe(expected); return actual!;
}
function contrast(a: string, b: string) { const x = luminance(a), y = luminance(b); return (Math.max(x, y) + .05) / (Math.min(x, y) + .05); }
it("defines six exact low-saturation tag pairs above WCAG AA", () => {
  for (const [category, background, foreground] of [["hook", "#EFF6FF", "#1E40AF"], ["angle", "#FFF7ED", "#9A3412"], ["format", "#F5F3FF", "#5B21B6"], ["talent", "#FDF2F8", "#9D174D"], ["cta", "#ECFEFF", "#155E75"], ["claim", "#FEFCE8", "#854D0E"]]) {
    expect(contrast(tokenColor(`--gs-tag-${category}-bg`, background), tokenColor(`--gs-tag-${category}-fg`, foreground))).toBeGreaterThanOrEqual(4.5);
  }
});
it("keeps white platform glyphs readable against every gradient stop and TikTok", () => {
  const white = tokenColor("--gs-platform-on-color", "#FFFFFF");
  for (const [token, value] of [["--gs-platform-instagram-from", "#6D28D9"], ["--gs-platform-instagram-via", "#BE185D"], ["--gs-platform-instagram-to", "#C2410C"], ["--gs-platform-tiktok-bg", "#111827"]]) expect(contrast(tokenColor(token, value), white)).toBeGreaterThanOrEqual(4.5);
});
it("keeps the amber model warning readable on its weak background", () => {
  expect(contrast(tokenColor("--gs-warn", "#92400E"), tokenColor("--gs-warn-weak", "#FFFBEB"))).toBeGreaterThanOrEqual(4.5);
});
it("keeps graph borders above nontext contrast and each fill palette distinct", () => {
  const background = tokenColor("--gs-bg", colors["--gs-bg"]);
  const layers = [1, 2, 3] as const;
  const kinds = ["Brand", "Product", "Efficacy", "Creative", "Other"];
  for (const color of [...layers.map(layer => LAYER_BORDER_COLORS[layer]), ...kinds.map(kind => LABEL_BORDER_COLORS[kind])]) expect(contrast(color, background)).toBeGreaterThanOrEqual(3);
  for (const fills of [layers.map(layer => LAYER_COLORS[layer]), kinds.map(kind => LABEL_COLORS[kind])]) {
    for (let i = 0; i < fills.length; i++) for (let j = i + 1; j < fills.length; j++) expect(fills[i]).not.toBe(fills[j]);
  }
});
