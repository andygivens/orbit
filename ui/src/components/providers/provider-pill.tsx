import { Loader2 } from "lucide-react";

import { cn } from "../../lib/utils";
import { formatProviderName, providerGlyphFor, statusColorFor, statusLabel } from "../../lib/providers";

type ProviderPillProps = {
  providerType: string;
  providerName?: string | null;
  status?: string | null;
  statusDetail?: string | null;
  className?: string;
};

export function ProviderPill({
  providerType,
  providerName,
  status,
  statusDetail,
  className
}: ProviderPillProps) {
  const glyph = providerGlyphFor(providerType);
  const normalizedStatus = status ?? "unknown";
  const statusColor = statusColorFor(normalizedStatus);
  const statusTitle = statusDetail ?? (normalizedStatus !== "unknown" ? `Status: ${statusLabel(normalizedStatus)}` : undefined);
  const isStatusLoading = status == null || normalizedStatus === "unknown";
  const isDegraded = normalizedStatus === "degraded";
  const isError = normalizedStatus === "error";
  const isDisabled = normalizedStatus === "disabled";
  const displayName = formatProviderName(providerName) || "Untitled provider";

  return (
    <span
      className={cn(
        "orbit-pill px-4 py-1.5 text-xs text-[var(--color-text-strong)] border border-border-subtle bg-[var(--color-hover)]/80",
        isDegraded && "bg-[var(--color-warning)]/12 border-[var(--color-warning)]/60",
        isError && "bg-[var(--color-danger)]/10 border-[var(--color-danger)]/50",
        isDisabled && "opacity-75",
        className
      )}
      title={statusTitle}
    >
      {isStatusLoading ? (
        <Loader2 className="h-3 w-3 flex-none animate-spin text-[var(--color-text-muted)]" aria-label="Checking status" />
      ) : (
        <span className="inline-flex h-2 w-2 flex-none rounded-full" style={{ background: statusColor }} />
      )}
      <span
        className="inline-flex h-5 w-5 flex-none items-center justify-center rounded-md"
        style={{ background: glyph.bg, color: glyph.fg }}
      >
        {glyph.label}
      </span>
      <span className="truncate">{displayName}</span>
    </span>
  );
}
