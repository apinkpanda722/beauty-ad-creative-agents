import "../../app/ui.css";

export type SkeletonProps = { label?: string };

export function Skeleton({ label = "불러오는 중" }: SkeletonProps) {
  return <div className="gs-ui gs-skeleton" role="status" aria-label={label} aria-busy="true">
    <span className="gs-skeleton-line" aria-hidden="true" />
  </div>;
}
