import type { GraphFragment, GraphNode, SchemaResponse } from "./types";
import { ctaName, talentName, type TaxonomyNames } from "./taxonomy";

export const LAYER_COLORS = { 1: "#427c69", 2: "#527cac", 3: "#8961a8" } as const;
export const LABEL_COLORS: Record<string, string> = { Creative: "#365d89", Product: "#286550" };
export const GRAPH_LEGEND = [
  { name: "1층 · 제품 지식", color: LAYER_COLORS[1] },
  { name: "제품", color: LABEL_COLORS.Product },
  { name: "2층 · 광고 관찰", color: LAYER_COLORS[2] },
  { name: "광고 소재", color: LABEL_COLORS.Creative },
  { name: "3층 · 피드백", color: LAYER_COLORS[3] },
];
const OBSERVATION_LABELS = new Set(["Creative", "Hook", "Angle", "Format", "Talent", "CtaType"]);
export type GraphElement =
  | { group: "nodes"; data: GraphNode & { displayName: string; layer: number; color: string } }
  | { group: "edges"; data: { id: string; source: string; target: string; type: string } };

function nodeElement(node: GraphNode, displayName: string, layer: number): GraphElement {
  return { group: "nodes", data: { ...node, displayName, layer,
    color: LABEL_COLORS[node.label] ?? LAYER_COLORS[layer as keyof typeof LAYER_COLORS] } };
}
function edgeElement(source: string, target: string, type: string): GraphElement {
  return { group: "edges", data: { id: `edge:${JSON.stringify([source, target, type])}`, source, target, type } };
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
