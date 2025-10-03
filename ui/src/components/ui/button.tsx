import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cn } from "../../lib/utils";

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "outline";
type ButtonSize = "default" | "sm" | "lg" | "xs" | "icon";

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: React.ReactNode;
  iconPosition?: "left" | "right";
};

const variantClasses: Record<ButtonVariant, string> = {
  primary:
    "bg-[var(--accent-600)] text-white shadow-elev-2 transition-transform duration-200 hover:bg-[var(--accent-700)] active:scale-[0.97]",
  secondary:
    "bg-[var(--color-hover)] text-[var(--color-text-strong)] hover:bg-[var(--color-hover)]/80",
  outline:
    "border border-border-strong text-[var(--color-text-strong)] hover:bg-[var(--color-hover)]/50",
  ghost:
    "bg-transparent text-[var(--color-text-strong)] hover:bg-[var(--color-hover)]/60",
  danger:
    "bg-[var(--color-danger)] text-white shadow-elev-2 hover:bg-[var(--color-danger)]/90"
};

const sizeClasses: Record<ButtonSize, string> = {
  default: "h-9 px-5",
  sm: "h-8 px-4 text-sm",
  lg: "h-10 px-6 text-base",
  xs: "h-7 px-3 text-xs",
  icon: "h-8 w-8 px-0"
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "primary", size = "default", icon, iconPosition = "left", children, ...props }, ref) => {
    return (
      <button
        ref={ref}
        className={cn(
          "inline-flex items-center justify-center whitespace-nowrap rounded-[var(--radius-2)] text-sm font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-500)] disabled:pointer-events-none disabled:opacity-60 gap-2",
          variantClasses[variant],
          sizeClasses[size],
          className
        )}
        {...props}
      >
        {icon && iconPosition === "left" ? icon : null}
        {children}
        {icon && iconPosition === "right" ? icon : null}
      </button>
    );
  }
);

Button.displayName = "Button";
