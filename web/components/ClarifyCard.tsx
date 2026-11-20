import { useState } from "react";
import { buildChoice, validateChoice } from "../lib/claim";
import type { ClaimChoice, Clarification } from "../lib/types";
export function ClarifyCard({ clarification, onSubmit, onCancel, disabled = false }: {
  clarification: Clarification; onSubmit: (choice: ClaimChoice, label: string) => void;
  onCancel: () => void; disabled?: boolean;
}) {
  const [optionId, setOptionId] = useState<Clarification["options"][number]["id"] | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const choice = optionId ? buildChoice(optionId, clarification, selected) : null;
  const label = clarification.options.find(o => o.id === optionId)?.label;
  const multiple = optionId === "select_many";
  return <section className="notice" aria-label="효능 선택">
    <p>{clarification.text}</p>
    <div className="options">{clarification.options.map(option => <button key={option.id} type="button" disabled={disabled}
      aria-pressed={option.id === optionId} onClick={() => {
        if (option.id === "cancel") { onCancel(); return; }
        const next = buildChoice(option.id, clarification, []);
        if (option.id === "keep_requested" || option.id === "none") {
          if (next && validateChoice(next, clarification)) onSubmit(next, option.label);
        } else { setOptionId(option.id); setSelected([]); }
      }}>{option.label}</button>)}</div>
    {optionId?.startsWith("select") && <fieldset disabled={disabled}>
      <legend>{label}</legend>
      {clarification.available.map(item => <label className="claim-chip" key={item.claim}>
        <input type={multiple ? "checkbox" : "radio"} name="confirmed-claim" aria-label={item.label}
          checked={selected.includes(item.claim)} onChange={() => setSelected(current => multiple
            ? current.includes(item.claim) ? current.filter(c => c !== item.claim) : [...current, item.claim]
            : [item.claim])} />{item.label}
      </label>)}
      <button type="button" disabled={disabled || !validateChoice(choice, clarification) || (!multiple && selected.length !== 1)}
        onClick={() => { if (choice && label && validateChoice(choice, clarification)) onSubmit(choice, label); }}>선택 제출</button>
    </fieldset>}
  </section>;
}
