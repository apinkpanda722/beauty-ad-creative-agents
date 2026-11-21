import type { EvidenceCard, UiCommand } from "./types";

export function safeLink(value: string | null): string | undefined {
  if (!value) return;
  try {
    const url = new URL(value);
    if (url.protocol === "https:" || url.protocol === "http:") return url.href;
  } catch { /* Missing or invalid URLs have no link. */ }
}

export function isOwnBrand(cardBrand: string | null | undefined, workspaceBrand: string | null | undefined): boolean {
  const normalize = (brand: string | null | undefined) => brand?.trim().toLowerCase().replace(/[\s-]+/g, "_") ?? "";
  const brand = normalize(cardBrand);
  return Boolean(brand) && brand === normalize(workspaceBrand);
}

export function platformLabel(source: string | null): string {
  switch (source) {
    case "youtube": return "YouTube";
    case "instagram": return "Instagram";
    case "tiktok": return "TikTok";
    case null: return "출처 정보 없음";
    default: return source;
  }
}

export function groupByPlatform(cards: readonly EvidenceCard[]): { source: string | null; cards: EvidenceCard[] }[] {
  const groups = new Map<string | null, EvidenceCard[]>();
  for (const card of cards) {
    const group = groups.get(card.source);
    if (group) group.push(card);
    else groups.set(card.source, [card]);
  }
  return Array.from(groups, ([source, cards]) => ({ source, cards })).sort((a, b) => {
    const difference = b.cards.length - a.cards.length;
    if (difference) return difference;
    const left = a.source ?? "";
    const right = b.source ?? "";
    return left < right ? -1 : left > right ? 1 : 0;
  });
}

export function dedupeCards(cards: readonly EvidenceCard[]): EvidenceCard[] {
  const seen = new Set<string>();
  return cards.filter(card => {
    if (!card.evidence_id) return true;
    if (seen.has(card.evidence_id)) return false;
    seen.add(card.evidence_id);
    return true;
  });
}

export function collectSessionCards(turns: readonly { commands: readonly UiCommand[] }[]): EvidenceCard[] {
  return dedupeCards(turns.flatMap(turn => turn.commands.flatMap(command => command.kind === "show_evidence_cards" ? command.data.cards : [])));
}
