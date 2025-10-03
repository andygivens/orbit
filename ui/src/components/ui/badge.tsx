import type { HTMLAttributes } from "react";
import { cn } from "../../lib/utils";

export type BadgeVariant = "default" | "outline" | "success" | "danger" | "accent" | "muted" | "warning";

const variantClasses: Record<BadgeVariant, string> = {
  default: "bg-[var(--color-hover)] text-[var(--color-text)]",
  outline: "border border-border-subtle text-[var(--color-text-soft)]",
  accent: "bg-[var(--accent-600)] text-white",
  muted: "bg-[var(--color-muted)] text-[var(--color-text-soft)]",
  success: "bg-[var(--color-success)]/15 text-[var(--color-success)]",
  danger: "bg-[var(--color-danger)]/15 text-[var(--color-danger)]",
  warning: "bg-[var(--color-warning)]/15 text-[var(--color-warning)]"
};

export type BadgeProps = HTMLAttributes<HTMLSpanElement> & {
  variant?: BadgeVariant;
};

export function Badge({ className, variant = "default", ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium",
        variantClasses[variant],
        className
      )}
      {...props}
    />
  );
}
