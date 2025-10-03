import { cn } from "../../lib/utils";
import { formatProviderName, providerGlyphFor, statusColorFor, statusLabel } from "../../lib/providers";
import type { SyncEndpointSummary } from "../../types/api";

type ProviderChipProps = {
  endpoint?: SyncEndpointSummary;
  fallback?: string;
  className?: string;
  showStatus?: boolean;
};

export function ProviderChip({ endpoint, fallback, className, showStatus = false }: ProviderChipProps) {
  if (!endpoint) {
    const fallbackLabel = fallback ?? "Unknown provider";
    return (
      <span
        className={cn(
          "orbit-pill orbit-pill-muted inline-flex items-center gap-2 px-3 py-1 text-xs text-[var(--color-text-soft)]",
          className
        )}
      >
        <span className="inline-flex h-6 w-6 items-center justify-center rounded-md bg-[var(--color-border)]/60 text-[var(--color-text-soft)]">
          {fallbackLabel.slice(0, 1).toUpperCase() || "?"}
        </span>
        <span className="pr-1 text-[var(--color-text-soft)]">{fallbackLabel}</span>
      </span>
    );
  }

  const glyph = providerGlyphFor(endpoint.provider_type);
  const formattedName = formatProviderName(endpoint.provider_name);
  const statusIndicator = showStatus ? statusColorFor(endpoint.status) : null;
  const statusTitle = showStatus ? `Status: ${statusLabel(endpoint.status)}` : undefined;

  return (
    <span
      className={cn("orbit-pill inline-flex max-w-[220px] items-center gap-2 px-3 py-1 text-xs text-[var(--color-text-strong)]", className)}
      title={statusTitle}
    >
      {showStatus && (
        <span className="inline-flex h-2 w-2 flex-none rounded-full" style={{ background: statusIndicator ?? "hsl(var(--color-muted-foreground) / 0.5)" }} />
      )}
      <span
        className="inline-flex h-6 w-6 flex-none items-center justify-center rounded-md"
        style={{ background: glyph.bg, color: glyph.fg }}
      >
        {glyph.label}
      </span>
      <span className="truncate">{formattedName}</span>
    </span>
  );
}
