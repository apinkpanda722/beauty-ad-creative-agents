import { Button } from "./Button";

export type EmptyStateProps = {
  title: string;
  description: string;
  action: { label: string; onClick: () => void; disabled?: boolean };
};

export function EmptyState({ title, description, action }: EmptyStateProps) {
  return <div className="gs-ui gs-empty-state">
    <h2 className="gs-empty-title">{title}</h2>
    <p className="gs-empty-description">{description}</p>
    <Button variant="secondary" onClick={action.onClick} disabled={action.disabled}>{action.label}</Button>
  </div>;
}
