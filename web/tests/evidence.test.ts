import { expect, it } from "vitest";
import { collectSessionCards, dedupeCards, groupByPlatform, isOwnBrand, platformLabel, safeLink } from "../lib/evidence";
import type { EvidenceCard, UiCommand } from "../lib/types";

const card: EvidenceCard = { evidence_id: "youtube:a", source: "youtube", url: null, brand: "isntree", title: null, published_at: null, view_count: null, like_count: null, hook_type: null, angle: null, format: null, talent: null, cta_type: null, claims: null };

it.each([
  ["isntree", "isntree", true], ["beauty_of_joseon", "beauty_of_joseon", true],
  ["Beauty-of-Joseon", "beauty_of_joseon", true], [" Beauty Of Joseon ", "beauty_of_joseon", true],
  ["mixsoon", "mixsoon", true], ["cosrx", "cosrx", true], ["cosrx", "isntree", false],
  ["이즈앤트리", "isntree", false], ["", "isntree", false], ["  ", " ", false],
  [null, "isntree", false], ["isntree", null, false], ["isntree", "", false],
])("normalizes workspace slugs without alias translation: %s / %s", (brand, workspace, expected) => {
  expect(isOwnBrand(brand, workspace)).toBe(expected);
});

it("groups largest platforms first and breaks ties by source name, retaining unknown sources", () => {
  const cards = [card, { ...card, source: "tiktok" }, { ...card, source: "instagram" }, { ...card, source: "tiktok" }, { ...card, source: "z-new" }, { ...card, source: null }];
  expect(groupByPlatform(cards).map(group => [group.source, group.cards])).toEqual([
    ["tiktok", [cards[1], cards[3]]], [null, [cards[5]]], ["instagram", [cards[2]]], ["youtube", [cards[0]]], ["z-new", [cards[4]]],
  ]);
  expect(platformLabel("youtube")).toBe("YouTube");
  expect(platformLabel("instagram")).toBe("Instagram");
  expect(platformLabel("tiktok")).toBe("TikTok");
  expect(platformLabel("z-new")).toBe("z-new");
  expect(platformLabel(null)).toBe("출처 정보 없음");
});

it("keeps first occurrences and every card without an ID without mutating the input", () => {
  const noId = { ...card, evidence_id: null };
  const emptyId = { ...card, evidence_id: "" };
  const cards = [card, { ...card, title: "later" }, noId, noId, emptyId, emptyId];
  expect(dedupeCards(cards)).toEqual([card, noId, noId, emptyId, emptyId]);
  expect(cards).toHaveLength(6);
});

it("collects only evidence commands from every turn in first-seen order", () => {
  const evidence: UiCommand = { kind: "show_evidence_cards", data: { cards: [card], missing: 0 } };
  const noId = { ...card, evidence_id: null };
  expect(collectSessionCards([
    { commands: [{ kind: "show_cost", data: { label: "synthetic", text_spent_usd: 0, max_text_cost_usd: 1 } }, evidence] },
    { commands: [evidence, { kind: "show_evidence_cards", data: { cards: [noId, noId], missing: 1 } }] },
  ])).toEqual([card, noId, noId]);
  expect(collectSessionCards([])).toEqual([]);
});

it.each([["https://example.test/a", "https://example.test/a"], ["http://example.test/", "http://example.test/"], ["javascript:alert(1)", undefined], ["data:text/plain,a", undefined], ["invalid", undefined], [null, undefined]])("accepts only web links: %s", (value, expected) => {
  expect(safeLink(value)).toBe(expected);
});
