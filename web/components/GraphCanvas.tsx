"use client";
import { useEffect, useRef, useState } from "react";
import type { Core } from "cytoscape";
import { GRAPH_LEGEND, ZOOM_LIMITS, type GraphElement } from "../lib/graph";
import { Button } from "./ui";
import "../app/graph.css";

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
  const core = useRef<Core | null>(null);
  const [zoom, setZoom] = useState<number | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    let cy: Core | undefined;
    // Cytoscape needs a browser container; do not load it during SSR.
    void import("cytoscape").then(({ default: cytoscape }) => {
      if (!active || !container.current) return;
      const tokens = getComputedStyle(container.current);
      const color = (name: string) => tokens.getPropertyValue(name).trim();
      const fontSize = Number.parseFloat(color("--gs-text-xs")) || 12;
      const space = Number.parseFloat(color("--gs-space-1")) || 4;
      const border = Number.parseFloat(color("--gs-border-width")) || 1;
      cy = cytoscape({ container: container.current, elements,
        minZoom: ZOOM_LIMITS.min, maxZoom: ZOOM_LIMITS.max, wheelSensitivity: 0.2,
        layout: layout === "cose"
          ? { name: layout, animate: false, padding: space * 9, nodeRepulsion: 8192, idealEdgeLength: space * 25, nodeOverlap: space * 4, nodeDimensionsIncludeLabels: true }
          : { name: layout, animate: false, padding: space * 9 },
        style: [
          { selector: "node", style: { "background-color": "data(color)", label: "data(displayName)", color: color("--gs-text"), "font-size": fontSize * 5 / 6, "text-wrap": "wrap", "text-max-width": `${space * 28}px`, "text-valign": "bottom", "text-margin-y": space, width: space * 7, height: space * 7 } },
          { selector: "edge", style: { label: "data(typeName)", width: border * 1.5, "line-color": color("--gs-border"), "target-arrow-color": color("--gs-border"), "target-arrow-shape": "triangle", "curve-style": "bezier", "font-size": fontSize * 7 / 12, color: color("--gs-text-muted"), "text-background-color": color("--gs-bg"), "text-background-opacity": 0.85 } },
          { selector: "node:selected", style: { "border-color": color("--gs-text"), "border-width": border * 3 } },
        ],
      });
      cy.on("tap", "node", event => onNodeClick(event.target.id()));
      core.current = cy;
      const updateZoom = () => { if (active) setZoom(cy?.zoom?.() ?? 1); };
      cy.on("zoom", updateZoom);
      updateZoom();
    }).catch(() => { if (active) setFailed(true); });
    return () => { active = false; cy?.destroy(); core.current = null; };
  }, [elements, layout, onNodeClick, attempt]);
  function changeZoom(factor: number) {
    if (!core.current) return;
    const next = Math.max(ZOOM_LIMITS.min, Math.min(ZOOM_LIMITS.max, (core.current.zoom?.() ?? 1) * factor));
    core.current.zoom(next);
    setZoom(next);
  }
  return <div className="gs-graph-canvas-wrap">{failed && <div role="alert">그래프를 그리지 못했습니다. GRAPH_RENDER_FAILED <button type="button" onClick={() => { setFailed(false); setAttempt(value => value + 1); }}>다시 시도</button></div>}
    <div className="gs-graph-controls" role="group" aria-label="그래프 배율">
      <Button variant="secondary" size="sm" aria-label="확대" disabled={failed || zoom === null || zoom >= ZOOM_LIMITS.max} onClick={() => changeZoom(1.2)}><svg aria-hidden="true" viewBox="0 0 24 24"><path d="M5 12h14M12 5v14" /></svg></Button>
      <Button variant="secondary" size="sm" aria-label="축소" disabled={failed || zoom === null || zoom <= ZOOM_LIMITS.min} onClick={() => changeZoom(1 / 1.2)}><svg aria-hidden="true" viewBox="0 0 24 24"><path d="M5 12h14" /></svg></Button>
      <Button variant="secondary" size="sm" aria-label="화면에 맞춤" disabled={failed || zoom === null} onClick={() => { core.current?.fit(); setZoom(core.current?.zoom?.() ?? 1); }}><svg aria-hidden="true" viewBox="0 0 24 24"><path d="M9 4H4v5m11-5h5v5M4 15v5h5m11-5v5h-5" /></svg></Button>
    </div>
    <div ref={container} className="graph-canvas" aria-label="그래프 캔버스" />
  </div>;
}
