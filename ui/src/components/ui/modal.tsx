import { useCallback, useEffect } from "react";
import { createPortal } from "react-dom";
import { cn } from "../../lib/utils";
import type { ReactNode } from "react";

export type ModalProps = {
  open: boolean;
  title?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  onClose: () => void;
  size?: "sm" | "md" | "lg";
};

const sizeClasses: Record<NonNullable<ModalProps["size"]>, string> = {
  sm: "max-w-md",
  md: "max-w-2xl",
  lg: "max-w-4xl"
};

export function Modal({ open, title, children, footer, onClose, size = "md" }: ModalProps) {
  useEffect(() => {
    if (!open) {
      return;
    }
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      }
    };
    document.addEventListener("keydown", handleKey);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", handleKey);
      document.body.style.overflow = previousOverflow;
    };
  }, [onClose, open]);

  const handleBackdropClick = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      if (event.target === event.currentTarget) {
        onClose();
      }
    },
    [onClose]
  );

  if (!open) {
    return null;
  }

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-[var(--color-text)]/40 py-10 backdrop-blur-sm"
      onClick={handleBackdropClick}
    >
      <div
        className={cn(
          "mx-4 w-full max-h-[calc(100vh-4rem)] overflow-hidden rounded-[var(--radius-3)] border border-border-subtle bg-[var(--color-surface)] shadow-elev-3",
          sizeClasses[size]
        )}
      >
        <div className="flex h-full flex-col">
          <div className="flex items-start justify-between gap-4 border-b border-border-subtle px-6 py-4">
            <div>
              {title && <h2 className="orbit-type-h1 font-semibold text-[var(--color-text-strong)]">{title}</h2>}
            </div>
            <button
              type="button"
              onClick={onClose}
              className="text-sm text-[var(--color-text-soft)] transition-colors hover:text-[var(--color-text)]"
            >
              Close
            </button>
          </div>
          <div className="flex-1 overflow-y-auto px-6 py-5 text-sm text-[var(--color-text-soft)]">
            {children}
          </div>
          {footer && (
            <div className="flex items-center justify-between gap-3 border-t border-border-subtle bg-[var(--color-hover)]/60 px-6 py-4">
              {footer}
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body
  );
}
