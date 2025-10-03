import { ArrowRight, ArrowRightLeft, Loader2, ShieldAlert, ShieldCheck } from "lucide-react";
import { Badge } from "../ui/badge";

export type SyncStatusKind = "active" | "degraded" | "error" | "disabled" | "loading";

export type SyncStatusChipProps = {
  label: string;
  detail?: string;
  status: SyncStatusKind;
};

const chipStyles: Record<SyncStatusKind, string> = {
  active: "border-border-subtle bg-[var(--color-surface)] text-[var(--color-text)]",
  degraded: "border-[var(--color-warning)]/40 bg-[var(--color-warning)]/10 text-[var(--color-warning)]",
  error: "border-[var(--color-danger)]/40 bg-[var(--color-danger)]/10 text-[var(--color-danger)]",
  disabled: "border-border-subtle bg-[var(--color-hover)]/40 text-[var(--color-text-muted)]",
  loading: "border-border-subtle bg-[var(--color-hover)] text-[var(--color-text-soft)]"
};

export function SyncStatusChip({ label, detail, status }: SyncStatusChipProps) {
  return (
    <div
      className={[
        "inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium shadow-elev-1",
        chipStyles[status]
      ].join(" ")}
    >
      {status === "loading" ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
      ) : status === "active" ? (
        <ShieldCheck className="h-3.5 w-3.5" />
      ) : (
        <ShieldAlert className="h-3.5 w-3.5" />
      )}
      <span>{label}</span>
      {detail && <span className="text-[var(--color-text-soft)]">{detail}</span>}
    </div>
  );
}

export function EndpointBadge({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center rounded-md border border-border-subtle bg-[var(--color-hover)] px-2 py-0.5 text-xs text-[var(--color-text-soft)]">
      {label}
    </span>
  );
}

export function DirectionBadge({ direction }: { direction: "bidirectional" | "one_way" }) {
  const isBidirectional = direction === "bidirectional";
  return (
    <Badge variant="accent" className="flex items-center gap-1">
      {isBidirectional ? <ArrowRightLeft className="h-3.5 w-3.5" /> : <ArrowRight className="h-3.5 w-3.5" />}
      {isBidirectional ? "Bidirectional" : "One-way"}
    </Badge>
  );
}

export function HealthPill({ status }: { status: "active" | "degraded" | "error" | "disabled" }) {
  const variants = {
    active: { text: "Active", variant: "success" as const },
    degraded: { text: "Degraded", variant: "warning" as const },
    error: { text: "Error", variant: "danger" as const },
    disabled: { text: "Disabled", variant: "muted" as const }
  };

  const selected = variants[status];

  return (
    <Badge variant={selected.variant} className="px-2 py-0.5 text-xs">
      {selected.text}
    </Badge>
  );
}
