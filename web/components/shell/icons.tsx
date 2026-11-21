import type { View } from "./AppShell";
const paths: Record<View, string> = {
  plan: "m4 16 10-10 4 4L8 20H4v-4ZM12 8l4 4M5 3v4M3 5h4M18 16v4M16 18h4",
  evidence: "M4 4h16v16H4V4Zm0 11 5-5 4 4 3-2 4 4M16 8h.01",
  graph: "M12 4v6M5 18l5-5M19 18l-5-5M10 12a2 2 0 1 0 4 0 2 2 0 1 0-4 0M10 3a2 2 0 1 0 4 0 2 2 0 1 0-4 0M2 19a2 2 0 1 0 4 0 2 2 0 1 0-4 0M18 19a2 2 0 1 0 4 0 2 2 0 1 0-4 0",
  history: "M2 12h5l3-8 4 16 3-8h5",
  saved: "M6 3h12v18l-6-4-6 4V3Z",
};
export function NavIcon({ view }: { view: View }) {
  return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[view]} /></svg>;
}
