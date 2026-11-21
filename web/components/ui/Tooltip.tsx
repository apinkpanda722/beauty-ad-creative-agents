"use client";

import { useEffect, useId, useState } from "react";
import type { ReactNode } from "react";
import "../../app/ui.css";

export type TooltipProps = {
  content: ReactNode;
  placement?: "top" | "bottom";
  align?: "start" | "end";
  children: ReactNode;
};

export function Tooltip({ content, placement = "top", align = "start", children }: TooltipProps) {
  const [open, setOpen] = useState(false);
  const id = useId();
  useEffect(() => {
    if (!open) return;
    const dismiss = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    document.addEventListener("keydown", dismiss);
    return () => document.removeEventListener("keydown", dismiss);
  }, [open]);
  return <span className="gs-tooltip-trigger" tabIndex={0} aria-describedby={open ? id : undefined}
    onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}
    onFocus={() => setOpen(true)} onBlur={() => setOpen(false)}
    onKeyDown={event => { if (event.key === "Escape") setOpen(false); }}>
    {children}
    {open && <span role="tooltip" id={id} className="gs-tooltip" data-placement={placement} data-align={align}>{content}</span>}
  </span>;
}
