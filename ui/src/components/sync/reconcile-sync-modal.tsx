import { useCallback, useMemo, useState } from "react";
import { formatDistanceToNow, parseISO } from "date-fns";
import { Loader2, RefreshCcw } from "lucide-react";

import { Modal } from "../ui/modal";
import { Button } from "../ui/button";
import { Badge } from "../ui/badge";
import { DirectionBadge, SyncStatusChip } from "./sync-elements";
import { ProviderChip } from "./provider-chip";
import { useApi } from "../../lib/api-context";
import { cn } from "../../lib/utils";
import type { SyncConfig, SyncEndpointSummary, SyncRunSummary } from "../../types/api";
import type { SyncRunAcceptedV1 } from "../../types/api-v1";

type ReconcileSyncModalProps = {
  open: boolean;
  sync: SyncConfig;
  onClose: () => void;
  onFinished: () => Promise<void>;
};

export function ReconcileSyncModal({ open, sync, onClose, onFinished }: ReconcileSyncModalProps) {
  const { client } = useApi();
  const [isRunning, setIsRunning] = useState(false);
  const [result, setResult] = useState<SyncRunAcceptedV1 | null>(null);
  const [error, setError] = useState<string | null>(null);

  const endpointLookup = useMemo(() => {
    return sync.endpoints.reduce<Record<string, SyncEndpointSummary>>((acc, endpoint) => {
      acc[endpoint.provider_id] = endpoint;
      return acc;
    }, {} as Record<string, SyncEndpointSummary>);
  }, [sync.endpoints]);

  const handleReconcile = useCallback(async () => {
    setIsRunning(true);
    setError(null);
    try {
      const response = await client.reconcileSync(sync.id);
      setResult(response);
      if (response.status !== "succeeded") {
        setError(`Reconcile completed with status ${response.status}`);
      }
      await onFinished();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to start reconciliation";
      setError(message);
    } finally {
      setIsRunning(false);
    }
  }, [client, onFinished, sync.id]);

  const currentRuns = sync.runs as SyncRunSummary[];

  const chipState = computeChipState({ isRunning, error, result });

  const footer = (
    <>
      <span className="text-xs text-[var(--color-text-soft)]">
        {result
          ? result.status === "succeeded"
            ? "Last reconcile completed successfully"
            : `Reconcile completed with status ${result.status}`
          : "Run reconcile to generate a detailed diff report"}
      </span>
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="sm" onClick={onClose}>
          Close
        </Button>
        <Button
          variant="secondary"
          size="sm"
          className="gap-2"
          onClick={handleReconcile}
          disabled={isRunning}
        >
          {isRunning ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCcw className="h-4 w-4" />}
          {result ? "Run again" : "Start reconcile"}
        </Button>
      </div>
    </>
  );

  const orderedEndpoints = useMemo(() => orderEndpoints(sync.endpoints), [sync.endpoints]);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Reconcile ${sync.name}`}
      size="lg"
      footer={footer}
    >
      <div className="space-y-4 text-[var(--color-text-strong)]">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <DirectionBadge direction={sync.direction} />
            <div className="flex flex-wrap items-center gap-2">
              {orderedEndpoints.map((endpoint, index) => (
                <div key={endpoint.provider_id} className="flex items-center gap-2 text-xs">
                  <ProviderChip endpoint={endpoint} />
                  {index < orderedEndpoints.length - 1 && (
                    <span className="text-[var(--accent-600)]">→</span>
                  )}
                </div>
              ))}
            </div>
          </div>
          <SyncStatusChip status={chipState.status} label={chipState.label} detail={chipState.detail} />
        </div>

        {error && (
          <div className="rounded-xl border border-[var(--color-danger)]/50 bg-[var(--color-danger)]/10 px-4 py-3 text-sm text-[var(--color-danger)]">
            {error}
          </div>
        )}

        <section className="space-y-3">
          {isRunning && (
            <div className="flex items-center gap-2 rounded-2xl border border-dashed border-border-subtle bg-[var(--color-hover)]/40 px-4 py-3 text-sm text-[var(--color-text-soft)]">
              <Loader2 className="h-4 w-4 animate-spin" /> Reconciliation job is running…
            </div>
          )}

          {currentRuns.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-border-subtle bg-[var(--color-hover)]/40 px-5 py-6 text-sm text-[var(--color-text-soft)]">
              No reconcile runs available yet. Trigger a reconcile to generate a diff report.
            </div>
          ) : (
            currentRuns.map((run) => (
              <RunCard key={run.id} run={run} endpointLookup={endpointLookup} />
            ))
          )}
        </section>
      </div>
    </Modal>
  );
}

type ChipState = {
  status: "active" | "degraded" | "error" | "loading";
  label: string;
  detail?: string;
};

type ChipStateParams = {
  isRunning: boolean;
  error: string | null;
  result: SyncRunAcceptedV1 | null;
};

function computeChipState({ isRunning, error, result }: ChipStateParams): ChipState {
  if (isRunning) {
    return { status: "loading", label: "Reconciling", detail: "Running reconciliation" };
  }
  if (error) {
    return { status: "error", label: "Reconcile failed", detail: error };
  }
  if (!result) {
    return { status: "loading", label: "Idle", detail: "Trigger reconcile to inspect differences" };
  }
  if (result.status === "succeeded") {
    return { status: "active", label: "Reconcile complete", detail: "Latest job finished successfully" };
  }
  return { status: "degraded", label: "Completed", detail: `Status: ${result.status}` };
}

type RunCardProps = {
  run: SyncRunSummary;
  endpointLookup: Record<string, SyncEndpointSummary>;
};

function RunCard({ run, endpointLookup }: RunCardProps) {
  const started = run.started_at ? formatDistanceToNow(parseISO(run.started_at), { addSuffix: true }) : null;
  const completed = run.completed_at ? formatDistanceToNow(parseISO(run.completed_at), { addSuffix: true }) : null;
  const source = run.source_provider_id ? endpointLookup[run.source_provider_id] : undefined;
  const target = run.target_provider_id ? endpointLookup[run.target_provider_id] : undefined;
  const hasPath = Boolean(source || target);

  return (
    <article className="space-y-3 rounded-2xl border border-border-subtle bg-[var(--color-surface)] px-5 py-4 shadow-elev-1">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="space-y-1">
          <div className="text-sm font-semibold text-[var(--color-text-strong)]">Run {runLabel(run)}</div>
          <div className="text-xs text-[var(--color-text-soft)]">
            {started ? `Started ${started}` : "Start time unavailable"}
            {completed ? ` • Completed ${completed}` : run.status === "running" ? " • In progress" : ""}
          </div>
        </div>
        <Badge variant={runStatusVariant(run.status)} className="uppercase tracking-wide">
          {run.status}
        </Badge>
      </header>

      {hasPath && (
        <div className="flex flex-wrap items-center gap-3 text-xs">
          <ProviderChip endpoint={source} />
          <span className="text-[var(--accent-600)]">→</span>
          <ProviderChip endpoint={target} />
        </div>
      )}

      <dl className="grid grid-cols-2 gap-2 text-xs md:grid-cols-5">
        <Metric label="Processed" value={run.stats.events_processed} />
        <Metric label="Created" value={run.stats.events_created} />
        <Metric label="Updated" value={run.stats.events_updated} />
        <Metric label="Deleted" value={run.stats.events_deleted} />
        <Metric label="Errors" value={run.stats.errors} highlight={run.stats.errors > 0} />
      </dl>

      {run.error && (
        <div className="rounded-lg border border-[var(--color-danger)]/40 bg-[var(--color-danger)]/10 px-3 py-2 text-xs text-[var(--color-danger)]">
          {run.error}
        </div>
      )}
    </article>
  );
}

type MetricProps = {
  label: string;
  value: number;
  highlight?: boolean;
};

function Metric({ label, value, highlight }: MetricProps) {
  return (
    <div
      className={cn(
        "rounded-lg border border-border-subtle bg-[var(--color-hover)]/40 px-3 py-2",
        highlight && "border-[var(--color-danger)]/50 bg-[var(--color-danger)]/10 text-[var(--color-danger)]"
      )}
    >
      <div className="text-[var(--color-text-soft)]">{label}</div>
      <div className="text-sm font-semibold text-[var(--color-text-strong)]">{value}</div>
    </div>
  );
}

function runLabel(run: SyncRunSummary) {
  if (run.direction) {
    return run.direction.replace(/_/g, " → ");
  }
  return run.id.slice(0, 8);
}

function runStatusVariant(status: string) {
  switch (status.toLowerCase()) {
    case "success":
    case "completed":
      return "success" as const;
    case "error":
    case "failed":
      return "danger" as const;
    case "running":
    case "pending":
      return "warning" as const;
    default:
      return "muted" as const;
  }
}

function orderEndpoints(endpoints: SyncEndpointSummary[]) {
  return [...endpoints].sort((a, b) => {
    const normalize = (role: string) => role.toLowerCase();
    const roleA = normalize(a.role);
    const roleB = normalize(b.role);
    if (roleA.includes("primary") || roleA.includes("source")) {
      return -1;
    }
    if (roleB.includes("primary") || roleB.includes("source")) {
      return 1;
    }
    if (roleA.includes("secondary") || roleA.includes("target")) {
      return -1;
    }
    if (roleB.includes("secondary") || roleB.includes("target")) {
      return 1;
    }
    return a.provider_name.localeCompare(b.provider_name);
  });
}
