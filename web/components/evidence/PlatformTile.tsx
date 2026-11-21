import { PlatformGlyph } from "./PlatformIcon";

export function PlatformTile({ source, label }: { source: string | null; label: string }) {
  return <div className="gs-platform-tile" data-platform={source} aria-label={`${source ?? "알 수 없는"} 출처`}>
    {source === "instagram" || source === "tiktok" ? <PlatformGlyph source={source} />
      : <span className="gs-platform-monogram" aria-hidden="true">{source?.slice(0, 1).toUpperCase() || "?"}</span>}
    <span>{label}</span>
  </div>;
}
