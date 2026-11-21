"use client";
import { useMemo, useState } from "react";
import { GRAPH_LEGEND, NODE_LABEL_NAMES, type GraphElement } from "../../lib/graph";
import { Button } from "../ui";

export function useGraphFilters(elements: GraphElement[]) {
  const [hiddenLayers, setHiddenLayers] = useState<number[]>([]);
  const [hiddenLabels, setHiddenLabels] = useState<string[]>([]);
  const labels = useMemo(() => Array.from(new Set(elements.flatMap(element => element.group === "nodes" ? [element.data.label] : []))), [elements]);
  const labelColors = useMemo(() => {
    const colors: Record<string, string> = {};
    for (const element of elements) if (element.group === "nodes" && !Object.hasOwn(colors, element.data.label)) colors[element.data.label] = element.data.color;
    return colors;
  }, [elements]);
  const filtered = useMemo(() => {
    if (!hiddenLayers.length && !hiddenLabels.length) return elements;
    const nodes = elements.filter(element => element.group === "nodes" && !hiddenLayers.includes(element.data.layer) && !hiddenLabels.includes(element.data.label));
    const ids = new Set(nodes.map(node => node.data.id));
    return elements.filter(element => element.group === "nodes" ? ids.has(element.data.id) : ids.has(element.data.source) && ids.has(element.data.target));
  }, [elements, hiddenLayers, hiddenLabels]);
  return { elements: filtered, labels, labelColors, hiddenLayers, hiddenLabels,
    toggleLayer: (layer: number) => setHiddenLayers(current => current.includes(layer) ? current.filter(value => value !== layer) : [...current, layer]),
    toggleLabel: (label: string) => setHiddenLabels(current => current.includes(label) ? current.filter(value => value !== label) : [...current, label]),
  };
}
export function GraphFilters({ labels, labelColors, colorBy, hiddenLayers, hiddenLabels, toggleLayer, toggleLabel }: ReturnType<typeof useGraphFilters> & { colorBy: "layer" | "kind" }) {
  return <div className="gs-graph-filters">
    <div className="gs-graph-filter-group gs-graph-segmented" role="group" aria-label="층 필터">
      {GRAPH_LEGEND[0].items.map((item, index) => <Button key={item.name} variant="ghost" size="sm" aria-pressed={!hiddenLayers.includes(index + 1)} onClick={() => toggleLayer(index + 1)}>{colorBy === "layer" && <span className="gs-graph-dot" style={{ backgroundColor: item.color }} aria-hidden="true" />}{item.name}</Button>)}
    </div>
    <div className="gs-graph-filter-group gs-graph-chips" role="group" aria-label="노드 종류 필터">
      {labels.map(label => <Button key={label} variant="ghost" size="sm" className="gs-graph-chip" aria-pressed={!hiddenLabels.includes(label)} onClick={() => toggleLabel(label)}><span className="gs-graph-dot" style={{ backgroundColor: labelColors[label] }} aria-hidden="true" />{NODE_LABEL_NAMES[label] ?? "기타"}</Button>)}
    </div>
  </div>;
}
