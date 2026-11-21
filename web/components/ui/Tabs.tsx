"use client";

import { useId, useRef } from "react";
import type { KeyboardEvent, ReactNode } from "react";
import "../../app/ui.css";

export type TabItem = {
  value: string;
  label: string;
  disabled?: boolean;
  panel?: ReactNode;
};
export type TabsProps = {
  label: string;
  items: readonly TabItem[];
  value: string;
  onChange: (value: string) => void;
};

export function Tabs({ label, items, value, onChange }: TabsProps) {
  const id = useId();
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  const enabled = items.map((item, index) => ({ ...item, index })).filter(item => !item.disabled);
  const active = enabled.find(item => item.value === value) ?? enabled[0];

  function move(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const current = enabled.findIndex(item => item.index === index);
    let next: number;
    switch (event.key) {
      case "ArrowRight": case "ArrowDown": next = (current + 1) % enabled.length; break;
      case "ArrowLeft": case "ArrowUp": next = (current - 1 + enabled.length) % enabled.length; break;
      case "Home": next = 0; break;
      case "End": next = enabled.length - 1; break;
      default: return;
    }
    event.preventDefault();
    const target = enabled[next];
    if (target) {
      buttons.current[target.index]?.focus();
      onChange(target.value);
    }
  }

  return <div className="gs-ui gs-tabs">
    <div className="gs-tab-list" role="tablist" aria-label={label} aria-orientation="horizontal">
      {items.map((item, index) => <button key={item.value} type="button" role="tab"
        className="gs-tab" id={`${id}-tab-${index}`}
        ref={element => { buttons.current[index] = element; }}
        aria-controls={item.panel !== undefined ? `${id}-panel-${index}` : undefined}
        aria-selected={active?.index === index} tabIndex={active?.index === index ? 0 : -1}
        disabled={item.disabled} aria-disabled={Boolean(item.disabled)}
        onClick={() => onChange(item.value)} onKeyDown={event => move(event, index)}>{item.label}</button>)}
    </div>
    {items.map((item, index) => item.panel !== undefined && <div key={item.value}
      className="gs-tab-panel" role="tabpanel" id={`${id}-panel-${index}`}
      aria-labelledby={`${id}-tab-${index}`} hidden={active?.index !== index} tabIndex={0}>{item.panel}</div>)}
  </div>;
}
