import type { HTMLAttributes } from "react";
import "../../app/ui.css";

export type BadgeProps = Omit<HTMLAttributes<HTMLSpanElement>, "children"> & {
  label: string;
  variant?: "neutral" | "accent" | "success" | "warn" | "danger";
};

export function Badge({ label, variant = "neutral", className = "", ...props }: BadgeProps) {
  if (!label.trim()) return null;
  return <span {...props} className={`gs-ui gs-badge gs-badge-${variant} ${className}`}>{label}</span>;
}
