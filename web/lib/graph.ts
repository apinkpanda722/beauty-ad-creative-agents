import type { GraphFragment, GraphNode, SchemaResponse, UiCommand } from "./types";
import { ctaName, talentName, type TaxonomyNames } from "./taxonomy";

export const ZOOM_LIMITS = { min: 0.3, max: 2.5 } as const;
export const NODE_LABEL_NAMES: Record<string, string> = {
  Creative: "광고 소재", IngredientAlias: "성분 별칭", Ingredient: "성분", Product: "제품",
  ClaimRule: "표현 규칙", Form: "제형", Brand: "브랜드", Efficacy: "효능", SkinConcern: "피부 고민",
  Hook: "훅 유형", Angle: "소구", Format: "형식", Talent: "출연자", CtaType: "행동 유도",
  SkinType: "피부 타입", Category: "제품 카테고리", FunctionalCert: "기능성 인증", Feedback: "피드백",
};
export const RELATIONSHIP_NAMES: Record<string, string> = {
  CONTAINS: "포함", CLAIMS: "주장", ALIAS_OF: "별칭", USES_HOOK: "훅 사용", HAS_ANGLE: "소구",
  HAS_FORMAT: "형식", FEATURES: "출연", HAS_CTA: "행동 유도", MENTIONS: "언급", PROMOTES: "홍보",
  OWNS: "소유", IN_CATEGORY: "카테고리", HAS_EFFICACY: "효능", CERTIFIED_AS: "인증", HAS_FORM: "제형",
  APPLIES_TO: "적용 대상", ADDRESSES: "해결", SUITS: "적합", ABOUT: "피드백 대상",
};
export const PROPERTY_NAMES: Record<string, string> = {
  source: "출처", url: "원본 링크", brand: "브랜드", published_at: "게시일", latest_view_count: "조회수",
  latest_like_count: "좋아요", value: "값", source_url: "판매처 링크", name_ko: "제품명", name: "이름",
};

export function latestGraphIds(turns: readonly { commands: readonly UiCommand[] }[]): string[] | null {
  for (let index = turns.length - 1; index >= 0; index--) {
    const command = turns[index].commands.findLast(command => command.kind === "show_graph_fragment");
    if (command) return [...command.data.evidence_ids];
  }
  return null;
}

export const LAYER_COLORS = { 1: "#427c69", 2: "#527cac", 3: "#8961a8" } as const;
export const LABEL_COLORS: Record<string, string> = { Creative: "#365d89", Product: "#286550" };
export const GRAPH_LEGEND = [
  { title: "층", items: [
    { name: "1층 · 제품 지식", color: LAYER_COLORS[1] },
    { name: "2층 · 광고 관찰", color: LAYER_COLORS[2] },
    { name: "3층 · 피드백", color: LAYER_COLORS[3] },
  ] },
  { title: "노드 종류", items: [
    { name: "제품", color: LABEL_COLORS.Product },
    { name: "광고 소재", color: LABEL_COLORS.Creative },
  ] },
];
const OBSERVATION_LABELS = new Set(["Creative", "Hook", "Angle", "Format", "Talent", "CtaType"]);
export type GraphElement =
  | { group: "nodes"; data: GraphNode & { displayName: string; layer: number; color: string } }
  | { group: "edges"; data: { id: string; source: string; target: string; type: string; typeName: string } };

function nodeElement(node: GraphNode, displayName: string, layer: number): GraphElement {
  return { group: "nodes", data: { ...node, displayName, layer,
    color: LABEL_COLORS[node.label] ?? LAYER_COLORS[layer as keyof typeof LAYER_COLORS] } };
}
function edgeElement(source: string, target: string, type: string): GraphElement {
  return { group: "edges", data: { id: `edge:${JSON.stringify([source, target, type])}`, source, target, type, typeName: RELATIONSHIP_NAMES[type] ?? type } };
}
export function fragmentToElements(fragment: GraphFragment, names: TaxonomyNames): GraphElement[] {
  return [
    ...fragment.nodes.map(node => {
      const value = typeof node.props.value === "string" ? node.props.value : node.name ?? "";
      let name = value;
      switch (node.label) {
        case "Hook": name = names.axisName("hook_type", value); break;
        case "Angle": name = names.axisName("angle", value); break;
        case "Format": name = names.axisName("format", value); break;
        case "Efficacy": name = names.claimName(value); break;
        case "Talent": name = talentName(value); break;
        case "CtaType": name = ctaName(value); break;
      }
      const layer = node.label === "Feedback" ? 3 : OBSERVATION_LABELS.has(node.label) ? 2 : 1;
      return nodeElement(node, name !== value ? name : node.name ?? value, layer);
    }),
    ...fragment.edges.map(edge => edgeElement(edge.source, edge.target, edge.type)),
  ];
}
export function schemaToElements(schema: SchemaResponse): GraphElement[] {
  return [
    ...schema.labels.map(label => nodeElement({ id: label.label, label: label.label, name: label.name_ko, props: {} }, label.name_ko, label.layer)),
    ...schema.relationships.map(edge => edgeElement(edge.from, edge.to, edge.type)),
  ];
}
