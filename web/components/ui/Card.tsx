import type { HTMLAttributes } from "react";
import "../../app/ui.css";

export type CardProps = HTMLAttributes<HTMLDivElement>;

export function Card({ children, className = "", ...props }: CardProps) {
  return <div {...props} className={`gs-ui gs-card ${className}`}>{children}</div>;
}
