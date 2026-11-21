"use client";

import type { ComponentPropsWithRef } from "react";
import "../../app/ui.css";

export type ButtonProps = ComponentPropsWithRef<"button"> & {
  variant?: "primary" | "secondary" | "ghost";
  size?: "sm" | "md";
  loading?: boolean;
};

export function Button({ variant = "primary", size = "md", loading = false, disabled,
  "aria-disabled": ariaDisabled, className = "", type = "button", children, ...props }: ButtonProps) {
  const unavailable = disabled || loading || ariaDisabled === true || ariaDisabled === "true";
  return <button {...props} type={type}
    className={`gs-ui gs-button gs-button-${variant} gs-button-${size} ${className}`}
    disabled={unavailable} aria-disabled={Boolean(unavailable)} aria-busy={loading}>
    {loading && <span className="gs-button-spinner" aria-hidden="true" />}
    {children}
  </button>;
}
