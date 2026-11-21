export function PlatformIcon({ source }: { source: string | null }) {
  const path = source === "youtube" ? "M3 5h18v14H3V5Zm7 4 5 3-5 3V9Z" : source === "instagram" ? "M3 3h18v18H3V3Zm4 14 4-5 3 3 3-2 4 4M16 7h.01" : source === "tiktok" ? "M4 17h3V7h4v10h4V3h5v14" : "M4 4h16v16H4V4Zm4 4h8M8 12h8M8 16h5";
  return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={path} /></svg>;
}
