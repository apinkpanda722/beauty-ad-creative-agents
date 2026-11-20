"use client";
import { useEffect, useRef, useState } from "react";
import type { Core } from "cytoscape";
import { GRAPH_LEGEND, type GraphElement } from "../lib/graph";

export function GraphLegend() {
  return <div aria-label="그래프 범례">{GRAPH_LEGEND.map(group => <section key={group.title} aria-label={group.title}>
    <h4>{group.title}</h4><ul className="graph-legend">{group.items.map(item => <li key={item.name}>
      <span style={{ backgroundColor: item.color }} aria-hidden="true" />{item.name}</li>)}</ul>
  </section>)}</div>;
}
export function GraphCanvas({ elements, layout = "cose", onNodeClick }: {
  elements: GraphElement[]; layout?: "cose" | "breadthfirst"; onNodeClick: (id: string) => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    let cy: Core | undefined;
    // Cytoscape needs a browser container; do not load it during SSR.
    void import("cytoscape").then(({ default: cytoscape }) => {
      if (!active || !container.current) return;
      cy = cytoscape({ container: container.current, elements,
        layout: layout === "cose"
          ? { name: layout, animate: false, padding: 36, nodeRepulsion: 8192, idealEdgeLength: 100, nodeOverlap: 16, nodeDimensionsIncludeLabels: true }
          : { name: layout, animate: false, padding: 36 },
        style: [
          { selector: "node", style: { "background-color": "data(color)", label: "data(displayName)", color: "#202124", "font-size": 10, "text-wrap": "wrap", "text-max-width": "110px", "text-valign": "bottom", "text-margin-y": 4, width: 28, height: 28 } },
          { selector: "edge", style: { label: "data(type)", width: 1.5, "line-color": "#bbc5cc", "target-arrow-color": "#bbc5cc", "target-arrow-shape": "triangle", "curve-style": "bezier", "font-size": 7, color: "#565e64", "text-background-color": "#fff", "text-background-opacity": 0.85 } },
          { selector: "node:selected", style: { "border-color": "#202124", "border-width": 3 } },
        ],
      });
      cy.on("tap", "node", event => onNodeClick(event.target.id()));
    }).catch(() => { if (active) setFailed(true); });
    return () => { active = false; cy?.destroy(); };
  }, [elements, layout, onNodeClick, attempt]);
  return <div>{failed && <div role="alert">그래프를 그리지 못했습니다. GRAPH_RENDER_FAILED <button type="button" onClick={() => { setFailed(false); setAttempt(value => value + 1); }}>다시 시도</button></div>}
    <div ref={container} className="graph-canvas" aria-label="그래프 캔버스" style={{ height: "28rem" }} />
  </div>;
}
