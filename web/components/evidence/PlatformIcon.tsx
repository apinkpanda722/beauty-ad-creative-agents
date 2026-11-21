export function PlatformGlyph({ source }: { source: string | null }) {
  const path = source === "youtube" ? "M3 5h18v14H3V5Zm7 4 5 3-5 3V9Z" : source === "instagram" ? "M7 3h10a4 4 0 0 1 4 4v10a4 4 0 0 1-4 4H7a4 4 0 0 1-4-4V7a4 4 0 0 1 4-4ZM12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8ZM17.5 6.5h.01" : source === "tiktok" ? "M14 4v10.5a3.5 3.5 0 1 1-3.5-3.5M14 4c.4 2.4 2 4 4.5 4.2" : "M4 4h16v16H4V4Zm4 4h8M8 12h8M8 16h5";
  return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={path} /></svg>;
}

export function PlatformIcon({ source }: { source: string | null }) {
  return <PlatformGlyph source={source} />;
}
