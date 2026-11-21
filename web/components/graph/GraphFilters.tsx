"use client";
import { useMemo, useState } from "react";
import { GRAPH_LEGEND, NODE_LABEL_NAMES, type GraphElement } from "../../lib/graph";
import { Button } from "../ui";

export function useGraphFilters(elements: GraphElement[]) {
  const [hiddenLayers, setHiddenLayers] = useState<number[]>([]);
  const [hiddenLabels, setHiddenLabels] = useState<string[]>([]);
  const labels = useMemo(() => Array.from(new Set(elements.flatMap(element => element.group === "nodes" ? [element.data.label] : []))), [elements]);
  const filtered = useMemo(() => {
    if (!hiddenLayers.length && !hiddenLabels.length) return elements;
    const nodes = elements.filter(element => element.group === "nodes" && !hiddenLayers.includes(element.data.layer) && !hiddenLabels.includes(element.data.label));
    const ids = new Set(nodes.map(node => node.data.id));
    return elements.filter(element => element.group === "nodes" ? ids.has(element.data.id) : ids.has(element.data.source) && ids.has(element.data.target));
  }, [elements, hiddenLayers, hiddenLabels]);
  return { elements: filtered, labels, hiddenLayers, hiddenLabels,
    toggleLayer: (layer: number) => setHiddenLayers(current => current.includes(layer) ? current.filter(value => value !== layer) : [...current, layer]),
    toggleLabel: (label: string) => setHiddenLabels(current => current.includes(label) ? current.filter(value => value !== label) : [...current, label]),
  };
}
export function GraphFilters({ labels, hiddenLayers, hiddenLabels, toggleLayer, toggleLabel }: ReturnType<typeof useGraphFilters>) {
  return <div className="gs-graph-filters">
    <div className="gs-graph-filter-group" role="group" aria-label="층 필터">
      {GRAPH_LEGEND[0].items.map((item, index) => <Button key={item.name} variant="ghost" size="sm" aria-pressed={!hiddenLayers.includes(index + 1)} onClick={() => toggleLayer(index + 1)}>{item.name}</Button>)}
    </div>
    <div className="gs-graph-filter-group" role="group" aria-label="노드 종류 필터">
      {labels.map(label => <Button key={label} variant="ghost" size="sm" aria-pressed={!hiddenLabels.includes(label)} onClick={() => toggleLabel(label)}>{NODE_LABEL_NAMES[label] ?? label}</Button>)}
    </div>
  </div>;
}
