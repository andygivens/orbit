import * as SwitchPrimitive from "@radix-ui/react-switch";
import { forwardRef } from "react";

import { cn } from "../../lib/utils";

export type SwitchSize = "sm" | "md" | "lg";

const sizeClasses: Record<SwitchSize, { root: string; thumb: string; translate: { on: string; off: string } }> = {
  sm: {
    root: "h-8 w-[52px]",
    thumb: "h-6 w-6",
    translate: { on: "translate-x-[24px]", off: "translate-x-[4px]" }
  },
  md: {
    root: "h-9 w-[60px]",
    thumb: "h-7 w-7",
    translate: { on: "translate-x-[28px]", off: "translate-x-[4px]" }
  },
  lg: {
    root: "h-10 w-[68px]",
    thumb: "h-8 w-8",
    translate: { on: "translate-x-[32px]", off: "translate-x-[4px]" }
  }
};

type SwitchRadius = "full" | "xl" | "lg" | (string & {});

export type SwitchProps = React.ComponentPropsWithoutRef<typeof SwitchPrimitive.Root> & {
  label?: string;
  size?: SwitchSize;
  rounded?: SwitchRadius;
};

export const Switch = forwardRef<React.ElementRef<typeof SwitchPrimitive.Root>, SwitchProps>(
  ({ className, label, size = "sm", rounded = "xl", ...props }, ref) => {
    const sizing = sizeClasses[size];
    const radius = rounded === "full"
      ? "rounded-full"
      : rounded === "xl"
        ? "rounded-[var(--radius-2)]"
        : rounded === "lg"
          ? "rounded-[var(--radius-1)]"
          : typeof rounded === "string"
            ? rounded
            : "rounded-full";
    return (
      <label className="inline-flex items-center gap-2 text-xs font-medium text-[var(--color-text-soft)]">
        {label && <span>{label}</span>}
        <SwitchPrimitive.Root
          ref={ref}
          className={cn(
            "relative inline-flex shrink-0 cursor-pointer items-center justify-start overflow-hidden border border-border-subtle bg-[var(--color-hover)] shadow-elev-1 transition-all focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-500)] disabled:cursor-not-allowed disabled:opacity-60",
            "data-[state=checked]:bg-[var(--accent-600)] data-[state=checked]:border-transparent",
            sizing.root,
            radius,
            className
          )}
          {...props}
        >
          <SwitchPrimitive.Thumb
            className={cn(
              "pointer-events-none block bg-white shadow-elev-1 transition-transform",
              radius,
              sizing.thumb,
              `data-[state=checked]:${sizing.translate.on}`,
              `data-[state=unchecked]:${sizing.translate.off}`
            )}
          />
        </SwitchPrimitive.Root>
      </label>
    );
  }
);

Switch.displayName = "Switch";
