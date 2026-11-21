"use client";

import { useEffect, useRef, useState, type TransitionEvent } from "react";

export function useGridAccordion() {
  const [expanded, setExpanded] = useState(false);
  const [visible, setVisible] = useState(false);
  const [open, setOpen] = useState(false);
  const gridRef = useRef<HTMLDivElement>(null);
  const frame = useRef<number | undefined>(undefined);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => { if (frame.current !== undefined) cancelAnimationFrame(frame.current); clearTimeout(timer.current); }, []);
  function toggle() {
    if (frame.current !== undefined) cancelAnimationFrame(frame.current);
    clearTimeout(timer.current);
    if (!expanded) {
      setVisible(true); setExpanded(true);
      frame.current = requestAnimationFrame(() => { setOpen(true); frame.current = undefined; });
    } else {
      setExpanded(false); setOpen(false);
      const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
      const style = gridRef.current ? getComputedStyle(gridRef.current) : null;
      const milliseconds = (value: string) => value.split(",").map(part => parseFloat(part) * (part.trim().endsWith("ms") ? 1 : 1000) || 0);
      const duration = Math.max(0, ...milliseconds(style?.transitionDuration ?? ""));
      const delay = Math.max(0, ...milliseconds(style?.transitionDelay ?? ""));
      if (reduced || duration === 0) setVisible(false);
      else timer.current = setTimeout(() => setVisible(false), Math.max(300, duration + delay + 50));
    }
  }
  function onTransitionEnd(event: TransitionEvent<HTMLDivElement>) {
    if (event.target === event.currentTarget && (!event.propertyName || event.propertyName === "grid-template-rows") && !expanded) { clearTimeout(timer.current); setVisible(false); }
  }
  return { expanded, visible, open, gridRef, toggle, onTransitionEnd };
}
