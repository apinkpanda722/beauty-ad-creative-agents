"use client";

import { useEffect, useId, useRef } from "react";
import type { ReactNode } from "react";
import { Button } from "./Button";

export type SidePanelProps = {
  title: string;
  value: boolean;
  onChange: (value: boolean) => void;
  children: ReactNode;
};

export function SidePanel({ title, value, onChange, children }: SidePanelProps) {
  const titleId = useId();
  const panel = useRef<HTMLElement>(null);
  const change = useRef(onChange);
  useEffect(() => { change.current = onChange; }, [onChange]);

  useEffect(() => {
    if (!value || !panel.current) return;
    const dialog = panel.current;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialog.focus();

    function containFocus(event: FocusEvent) {
      if (!dialog.contains(event.target as Node)) dialog.focus();
    }
    function handleKey(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        change.current(false);
      } else if (event.key === "Tab") {
        const focusable = Array.from(dialog.querySelectorAll<HTMLElement>(
          "a[href], button, input, select, textarea, [tabindex], [contenteditable='true']",
        )).filter(element => element.tabIndex >= 0 && !element.matches(":disabled, [aria-disabled='true']")
          && !element.closest("[hidden], [inert]")
          && getComputedStyle(element).display !== "none" && getComputedStyle(element).visibility !== "hidden");
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (!first || !last) {
          event.preventDefault(); dialog.focus();
        } else if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog)) {
          event.preventDefault(); last.focus();
        } else if (!event.shiftKey && (document.activeElement === last || document.activeElement === dialog)) {
          event.preventDefault(); first.focus();
        }
      }
    }
    document.addEventListener("keydown", handleKey);
    document.addEventListener("focusin", containFocus);
    return () => {
      document.removeEventListener("keydown", handleKey);
      document.removeEventListener("focusin", containFocus);
      if (opener?.isConnected) opener.focus();
    };
  }, [value]);

  if (!value) return null;
  return <div className="gs-ui gs-side-panel-layer">
    <section className="gs-side-panel" role="dialog" aria-modal="true" aria-labelledby={titleId}
      tabIndex={-1} ref={panel}>
      <header className="gs-side-panel-header">
        <h2 className="gs-side-panel-title" id={titleId}>{title}</h2>
        <Button variant="ghost" size="sm" onClick={() => onChange(false)}>닫기</Button>
      </header>
      <div className="gs-side-panel-content">{children}</div>
    </section>
  </div>;
}
