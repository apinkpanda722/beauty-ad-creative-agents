export function ClarifySummary({ label }: { label: string }) {
  return <p className="gs-clarify-summary" aria-label="효능 선택 요약">효능 선택 · {label}</p>;
}
