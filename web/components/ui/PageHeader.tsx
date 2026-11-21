import type { ReactNode } from "react";
import "../../app/ui.css";

export type PageHeaderProps = { title: string; description?: string; actions?: ReactNode };

export function PageHeader({ title, description, actions }: PageHeaderProps) {
  return <header className="gs-ui gs-page-header">
    <div className="gs-page-header-copy">
      <h1 className="gs-page-title">{title}</h1>
      {description && <p className="gs-page-description">{description}</p>}
    </div>
    {actions && <div className="gs-page-actions">{actions}</div>}
  </header>;
}
