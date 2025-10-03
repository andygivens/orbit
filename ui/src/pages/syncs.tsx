import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { addSeconds, format, formatDistanceToNow, parseISO } from "date-fns";
import {
  ArrowRight,
  ArrowRightLeft,
  CalendarClock,
  CalendarRange,
  ChevronDown,
  CircleCheck,
  CircleX,
  Clock3,
  Edit,
  GitCompare,
  History,
  Loader2,
  Plus,
  RefreshCcw,
  Repeat,
  ShieldAlert
} from "lucide-react";

import { useApi } from "../lib/api-context";
import type { Provider, SyncConfig, SyncEndpointSummary, SyncEventSummary } from "../types/api";
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import { cn } from "../lib/utils";
import { formatProviderName, providerGlyphFor } from "../lib/providers";
import { EditSyncModal } from "../components/sync/edit-sync-modal";
import { CreateSyncModal } from "../components/sync/create-sync-modal";
import { TroubleshootModal } from "../components/sync/troubleshoot-modal";
import { ProviderPill } from "../components/providers/provider-pill";

export function SyncsPage() {
  const { auth, client } = useApi();
  const [syncs, setSyncs] = useState<SyncConfig[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [editingSync, setEditingSync] = useState<SyncConfig | null>(null);
  const [troubleshootSync, setTroubleshootSync] = useState<SyncConfig | null>(null);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [providersError, setProvidersError] = useState<string | null>(null);
  const [isLoadingProviders, setIsLoadingProviders] = useState(false);
  const providersLoadedRef = useRef(false);
  const [isCreateModalOpen, setCreateModalOpen] = useState(false);

  const refreshSyncs = useCallback(async () => {
    try {
      const syncConfigs = await client.syncConfigs();
      setSyncs(syncConfigs);
      setSyncError(null);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to load syncs";
      setSyncError(message);
      throw error;
    }
  }, [client]);

  const ensureProviders = useCallback(async () => {
    if (providersLoadedRef.current) {
      return;
    }
    setIsLoadingProviders(true);
    try {
      const list = await client.providers();
      setProviders(list);
      setProvidersError(null);
      providersLoadedRef.current = true;
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to load providers";
      setProvidersError(message);
      throw error;
    } finally {
      setIsLoadingProviders(false);
    }
  }, [client]);

  const handleEditRequest = useCallback(
    async (sync: SyncConfig) => {
      try {
        await ensureProviders();
        setEditingSync(sync);
      } catch (error) {
        const message = error instanceof Error ? error.message : "Failed to load providers";
        setSyncError(message);
      }
    },
    [ensureProviders]
  );

  const handleModalClose = useCallback(() => {
    setEditingSync(null);
  }, []);

  const handleTroubleshootRequest = useCallback(
    async (syncConfig: SyncConfig) => {
      try {
        await ensureProviders();
        setTroubleshootSync(syncConfig);
      } catch (error) {
        const message = error instanceof Error ? error.message : "Failed to load providers";
        setSyncError(message);
      }
    },
    [ensureProviders]
  );

  const handleTroubleshootClose = useCallback(() => {
    setTroubleshootSync(null);
  }, []);

  const handleCreateRequest = useCallback(async () => {
    try {
      await ensureProviders();
      setCreateModalOpen(true);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to load providers";
      setSyncError(message);
    }
  }, [ensureProviders, setSyncError]);

  const handleCreateClose = useCallback(() => {
    setCreateModalOpen(false);
  }, []);

  const handleCreateSuccess = useCallback(
    async () => {
      try {
        await refreshSyncs();
      } catch (error) {
        const message = error instanceof Error ? error.message : "Failed to load syncs";
        setSyncError(message);
      } finally {
        setCreateModalOpen(false);
      }
    },
    [refreshSyncs, setSyncError]
  );

  useEffect(() => {
    if (auth.status !== "authenticated") {
      return;
    }

    let cancelled = false;

    const load = async () => {
      setIsLoading(true);
      try {
        await refreshSyncs();
      } catch (error) {
        if (!cancelled) {
          const message = error instanceof Error ? error.message : "Failed to load syncs";
          setSyncError(message);
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    };

    load();

    return () => {
      cancelled = true;
    };
  }, [auth.status, refreshSyncs]);

  return (
    <>
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
        <header className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <p className="max-w-2xl text-sm text-[var(--color-text-soft)]">
            Review active sync definitions, trigger manual runs, and jump into troubleshooting.
          </p>
          <Button variant="primary" size="sm" onClick={handleCreateRequest}>
            + New
          </Button>
        </header>

        {syncError && (
          <Card className="border-[var(--color-danger)]/40 bg-[var(--color-danger)]/5">
            <CardContent className="flex items-center gap-2 px-5 py-4 text-sm text-[var(--color-danger)]">
              <ShieldAlert className="h-4 w-4" /> {syncError}
            </CardContent>
          </Card>
        )}

        <section className="space-y-4">
          {isLoading ? (
            <SkeletonList />
          ) : syncs.length === 0 ? (
            <EmptyState onCreate={handleCreateRequest} />
          ) : (
            <div className="space-y-4">
              {syncs.map((sync) => (
                <SyncCard
                  key={sync.id}
                  sync={sync}
                  onEdit={() => handleEditRequest(sync)}
                  onTroubleshoot={() => handleTroubleshootRequest(sync)}
                  onRefresh={refreshSyncs}
                />
              ))}
            </div>
          )}
        </section>
      </div>

      {editingSync && (
        <EditSyncModal
          open={Boolean(editingSync)}
          sync={editingSync}
          providers={providers}
          isLoadingProviders={isLoadingProviders}
          providersError={providersError}
          onClose={handleModalClose}
          onSaved={refreshSyncs}
        />
      )}

      {troubleshootSync && (
        <TroubleshootModal
          open={Boolean(troubleshootSync)}
          sync={troubleshootSync}
          providers={providers}
          onClose={handleTroubleshootClose}
        />
      )}

      <CreateSyncModal
        open={isCreateModalOpen}
        providers={providers}
        isLoadingProviders={isLoadingProviders}
        providersError={providersError}
        onClose={handleCreateClose}
        onCreated={handleCreateSuccess}
      />
    </>
  );
}

function SyncCard({
  sync,
  onEdit,
  onTroubleshoot,
  onRefresh
}: {
  sync: SyncConfig;
  onEdit: () => void;
  onTroubleshoot: () => void;
  onRefresh: () => Promise<void>;
}) {
  const { client } = useApi();
  const [collapsed, setCollapsed] = useState(true);
  const [events, setEvents] = useState<SyncEventSummary[]>(Array.isArray(sync.events) ? sync.events : []);
  const [eventsLoading, setEventsLoading] = useState(false);
  const [eventsError, setEventsError] = useState<string | null>(null);
  const eventsLoadedRef = useRef(false);
  const [isSyncing, setIsSyncing] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    eventsLoadedRef.current = false;
    const initialEvents = Array.isArray(sync.events) ? sync.events : [];
    setEvents(initialEvents);
    setEventsError(null);
  }, [sync.events, sync.id]);

  useEffect(() => {
    if (Array.isArray(sync.events) && sync.events.length > 0) {
      setEvents(sync.events);
      eventsLoadedRef.current = true;
    }
  }, [sync.events]);

  const loadEvents = useCallback(async (force = false) => {
    if (eventsLoading) {
      return;
    }
    if (!force && eventsLoadedRef.current && !eventsError) {
      return;
    }
    setEventsLoading(true);
    setEventsError(null);
    try {
      const response = await client.syncEvents(sync.id, 10);
      const fetched = Array.isArray(response.events) ? response.events : [];
      setEvents(fetched);
      eventsLoadedRef.current = true;
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to load events";
      setEventsError(message);
      eventsLoadedRef.current = false;
    } finally {
      setEventsLoading(false);
    }
  }, [client, eventsError, eventsLoading, sync.id]);

  const handleToggleCollapsed = useCallback(() => {
    const next = !collapsed;
    setCollapsed(next);
    if (next) {
      return;
    }
    void loadEvents(true);
  }, [collapsed, loadEvents]);

  const latestRun = sync.runs[0];
  const lastCompleted = useMemo(() => resolveTimestamp(latestRun?.completed_at ?? sync.last_synced_at), [latestRun?.completed_at, sync.last_synced_at]);
  const lastRunLabel = lastCompleted
    ? formatDistanceToNow(lastCompleted, { addSuffix: true })
    : latestRun?.started_at
    ? formatDistanceToNow(resolveTimestamp(latestRun.started_at) ?? new Date(), { addSuffix: true })
    : "No completed runs";
  const nextRunLabel = useMemo(
    () => deriveNextRunLabel(lastCompleted, sync.interval_seconds, sync.enabled),
    [lastCompleted, sync.interval_seconds, sync.enabled]
  );
  const intervalLabel = useMemo(
    () => (sync.enabled ? formatInterval(sync.interval_seconds) : "Sync disabled"),
    [sync.enabled, sync.interval_seconds]
  );
  const windowLabel = useMemo(() => {
    const past = sync.window_days_back ?? sync.window_days_past ?? 0;
    const future = sync.window_days_forward ?? sync.window_days_future ?? 0;
    return `${past}d past • ${future}d future`;
  }, [sync.window_days_back, sync.window_days_forward, sync.window_days_future, sync.window_days_past]);
  const lastRunStatusMeta = useMemo(() => {
    if (!latestRun) {
      return {
        label: "No runs yet",
        color: "var(--color-text-soft)",
        icon: null
      };
    }

    const status = (latestRun.status ?? "").toLowerCase();
    switch (status) {
      case "succeeded":
        return {
          label: "Succeeded",
          color: "var(--color-success)",
          icon: <CircleCheck className="h-3.5 w-3.5" style={{ color: "var(--color-success)" }} aria-hidden="true" />
        };
      case "failed":
        return {
          label: "Failed",
          color: "var(--color-danger)",
          icon: <CircleX className="h-3.5 w-3.5" style={{ color: "var(--color-danger)" }} aria-hidden="true" />
        };
      case "running":
        return {
          label: "In progress",
          color: "var(--color-warning)",
          icon: <Loader2 className="h-3.5 w-3.5 animate-spin" style={{ color: "var(--color-warning)" }} aria-hidden="true" />
        };
      case "queued":
        return {
          label: "Queued",
          color: "var(--color-warning)",
          icon: <Clock3 className="h-3.5 w-3.5" style={{ color: "var(--color-warning)" }} aria-hidden="true" />
        };
      default:
        return {
          label: status ? status.charAt(0).toUpperCase() + status.slice(1) : "Unknown",
          color: "var(--color-text-soft)",
          icon: null
        };
    }
  }, [latestRun]);

  const directionGlyph = sync.direction === "bidirectional" ? "↔" : "→";
  const orderedEndpoints = useMemo(() => orderEndpoints(sync.endpoints), [sync.endpoints]);
  const providerLookup = useMemo(() => {
    return sync.endpoints.reduce<Record<string, SyncEndpointSummary>>((acc, endpoint) => {
      acc[endpoint.provider_id] = endpoint;
      return acc;
    }, {} as Record<string, SyncEndpointSummary>);
  }, [sync.endpoints]);

  const handleSyncNow = useCallback(async () => {
    setFeedback(null);
    setActionError(null);
    setIsSyncing(true);
    try {
      const response = await client.runSync(sync.id);
      if (response.status === "succeeded") {
        setFeedback("Manual sync completed");
      } else {
        setActionError(`Manual sync completed with status ${response.status}`);
      }
      await onRefresh();
      eventsLoadedRef.current = false;
      setEvents([]);
      setEventsError(null);
      if (!collapsed) {
        await loadEvents(true);
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "Manual sync failed";
      setActionError(message);
    } finally {
      setIsSyncing(false);
    }
  }, [client, collapsed, loadEvents, onRefresh, sync.id]);

  return (
    <Card className="shadow-elev-2">
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            {orderedEndpoints.map((endpoint, index) => (
              <Fragment key={endpoint.provider_id}>
                {index > 0 && (
                  <span className="text-base text-[var(--accent-600)]">{directionGlyph}</span>
                )}
                <ProviderPill
                  providerType={endpoint.provider_type}
                  providerName={endpoint.provider_name}
                  status={endpoint.status}
                  statusDetail={endpoint.status_detail ?? undefined}
                />
              </Fragment>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--color-text-soft)]">
            <span className="inline-flex items-center gap-1.5">
              <History className="h-3.5 w-3.5 text-[var(--color-text-muted)]" aria-hidden="true" />
              <span className="font-medium text-[var(--color-text-strong)]">Last run</span>
              <span>{lastRunLabel}</span>
            </span>
            <span className="text-border-subtle" aria-hidden="true">|</span>
            <span className="inline-flex items-center gap-1.5">
              <span className="font-medium text-[var(--color-text-strong)]">Last run result</span>
              <span className="inline-flex items-center gap-1.5" style={{ color: lastRunStatusMeta.color }}>
                {lastRunStatusMeta.icon}
                <span>{lastRunStatusMeta.label}</span>
              </span>
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleToggleCollapsed}
            className="inline-flex items-center gap-1 rounded-md bg-[var(--color-hover)] px-3 py-1 text-xs font-medium text-[var(--color-text-soft)] transition-colors hover:text-[var(--color-text-strong)]"
          >
            <ChevronDown className={cn("h-4 w-4 transition-transform", collapsed ? "-rotate-90" : "rotate-0")} />
            {collapsed ? "Expand" : "Collapse"}
          </button>
        </div>
      </div>

      {!collapsed && (
        <div className="mt-4 space-y-5 border-t border-border-subtle pt-5">
          <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--color-text-soft)]">
            <span className="inline-flex items-center gap-1.5">
              <CalendarClock className="h-3.5 w-3.5 text-[var(--color-text-muted)]" aria-hidden="true" />
              <span className="font-medium text-[var(--color-text-strong)]">Next run</span>
              <span>{nextRunLabel}</span>
            </span>
            <span className="text-border-subtle" aria-hidden="true">|</span>
            <span className="inline-flex items-center gap-1.5">
              <Repeat className="h-3.5 w-3.5 text-[var(--color-text-muted)]" aria-hidden="true" />
              <span className="font-medium text-[var(--color-text-strong)]">Interval</span>
              <span>{intervalLabel}</span>
            </span>
            <span className="text-border-subtle" aria-hidden="true">|</span>
            <span className="inline-flex items-center gap-1.5">
              <CalendarRange className="h-3.5 w-3.5 text-[var(--color-text-muted)]" aria-hidden="true" />
              <span className="font-medium text-[var(--color-text-strong)]">Window</span>
              <span>{windowLabel}</span>
            </span>
          </div>
          <div>
            <div className="mb-3 flex items-center justify-between text-xs uppercase tracking-wide text-[var(--color-text-soft)]">
              <span>Recent events</span>
            </div>
            {eventsLoading ? (
              <div className="flex items-center gap-2 rounded-2xl border border-border-subtle bg-[var(--color-hover)]/40 px-4 py-6 text-sm text-[var(--color-text-soft)]">
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Loading events…
              </div>
            ) : eventsError ? (
              <div className="rounded-2xl border border-[var(--color-danger)]/50 bg-[var(--color-danger)]/10 px-4 py-3 text-sm text-[var(--color-danger)]">
                {eventsError}
              </div>
            ) : events.length ? (
              <EventFlowList
                events={events}
                providerLookup={providerLookup}
                fallbackGlyph={directionGlyph}
              />
            ) : (
              <div className="flex items-center gap-2 rounded-2xl border border-border-subtle bg-[var(--color-hover)]/40 px-4 py-6 text-sm text-[var(--color-text-soft)]">
                No events captured for this sync yet.
              </div>
            )}
          </div>

          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <Button variant="primary" size="sm" className="gap-2" onClick={onEdit}>
                <Edit className="h-4 w-4" /> Edit
              </Button>
              <Button
                variant="primary"
                size="sm"
                className="gap-2"
                onClick={handleSyncNow}
                disabled={isSyncing}
              >
                <RefreshCcw className={cn("h-4 w-4", isSyncing && "animate-spin")}/> {isSyncing ? "Syncing" : "Sync now"}
              </Button>
              <Button
                variant="primary"
                size="sm"
                className="gap-2"
                onClick={onTroubleshoot}
              >
                <GitCompare className="h-4 w-4" /> Troubleshoot
              </Button>
            </div>
            {(feedback || actionError) && (
              <div className={cn("text-xs", actionError ? "text-[var(--color-danger)]" : "text-[var(--color-success)]")}
              >
                {actionError ?? feedback}
              </div>
            )}
          </div>
        </div>
      )}
    </Card>
  );
}

function formatRelativeSyncTime(value?: string | null): string {
  if (!value) {
    return "—";
  }
  try {
    const normalized = normalizeTimestamp(value);
    if (!normalized) {
      return "—";
    }
    const timestamp = parseISO(normalized);
    const diffMs = Date.now() - timestamp.getTime();
    const absDiff = Math.abs(diffMs);

    if (absDiff < 60000) {
      return diffMs >= 0 ? "just now" : "in < 1m";
    }

    const minutes = Math.max(Math.round(absDiff / 60000), 1);
    if (minutes < 60) {
      return diffMs >= 0 ? `~ ${minutes}m ago` : `in ${minutes}m`;
    }

    const hours = Math.max(Math.round(minutes / 60), 1);
    if (hours < 24) {
      const unit = hours === 1 ? "hr" : "hrs";
      return diffMs >= 0 ? `~ ${hours} ${unit} ago` : `in ${hours} ${unit}`;
    }

    const days = Math.max(Math.round(hours / 24), 1);
    if (days < 14) {
      const unit = days === 1 ? "day" : "days";
      return diffMs >= 0 ? `${days} ${unit} ago` : `in ${days} ${unit}`;
    }

    const weeks = Math.max(Math.round(days / 7), 1);
    const unit = weeks === 1 ? "week" : "weeks";
    return diffMs >= 0 ? `${weeks} ${unit} ago` : `in ${weeks} ${unit}`;
  } catch {
    return "—";
  }
}

function formatEventTimestamp(value?: string | null): string {
  if (!value) {
    return "—";
  }
  try {
    const raw = String(value).trim();
    const normalized = normalizeTimestamp(raw);
    if (!normalized) {
      return "—";
    }
    const parsed = parseISO(normalized);
    const isAllDay = /^\d{4}-\d{2}-\d{2}$/.test(raw);
    if (isAllDay) {
      return `${format(parsed, "MM/dd/yy")} all day`;
    }
    return format(parsed, "MM/dd/yy @ h:mma");
  } catch {
    return "—";
  }
}

function formatAbsoluteTimestamp(value?: string | null): string | null {
  if (!value) {
    return null;
  }
  try {
    const normalized = normalizeTimestamp(value);
    if (!normalized) {
      return null;
    }
    const parsed = parseISO(normalized);
    return format(parsed, "MMM d, yyyy @ h:mmaaa");
  } catch {
    return null;
  }
}

function normalizeTimestamp(value?: string | null): string | null {
  if (!value) {
    return null;
  }
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  if (trimmed.includes("T")) {
    return trimmed;
  }

  const spaceIndex = trimmed.indexOf(" ");
  if (spaceIndex > 0) {
    const datePart = trimmed.slice(0, spaceIndex);
    const timePart = trimmed.slice(spaceIndex + 1);
    if (!timePart) {
      return datePart;
    }
    const hasOffset = /(?:Z|[+-]\d{2}:?\d{2})$/.test(timePart);
    const normalizedTime = hasOffset ? timePart : `${timePart}Z`;
    return `${datePart}T${normalizedTime}`;
  }

  return trimmed;
}

function FlowGlyphGroup({
  event,
  fallbackGlyph,
  providerLookup
}: {
  event: SyncEventSummary;
  fallbackGlyph: string;
  providerLookup: Record<string, SyncEndpointSummary>;
}) {
  const sourceEndpoint = event.source_provider_id ? providerLookup[event.source_provider_id] : undefined;
  const targetEndpoint = event.target_provider_id ? providerLookup[event.target_provider_id] : undefined;

  const directionLabel = event.direction ?? "";
  const hasBidirectionalArrow = directionLabel.includes("<->") || directionLabel.includes("↔") || fallbackGlyph === "↔";
  const ArrowIcon = hasBidirectionalArrow ? ArrowRightLeft : ArrowRight;

  return (
    <div className="flex items-center gap-2 text-[var(--color-text-soft)]">
      <GlyphBubble endpoint={sourceEndpoint} fallback={event.provider_badges?.[0]} />
      <span
        className="flex h-6 w-6 flex-none items-center justify-center rounded-md bg-[var(--accent-600)]/10 text-[var(--accent-600)]"
        title={directionLabel || undefined}
      >
        <ArrowIcon className="h-3.5 w-3.5" aria-hidden="true" />
      </span>
      <GlyphBubble endpoint={targetEndpoint} fallback={event.provider_badges?.[1]} />
    </div>
  );
}

function EventFlowList({
  events,
  providerLookup,
  fallbackGlyph
}: {
  events: SyncEventSummary[];
  providerLookup: Record<string, SyncEndpointSummary>;
  fallbackGlyph: string;
}) {
  const sortedEvents = useMemo(() => {
    return [...events].sort((a, b) => {
      const aTs = timestampFrom(a.occurred_at);
      const bTs = timestampFrom(b.occurred_at);
      if (aTs === null && bTs === null) {
        return 0;
      }
      if (aTs === null) {
        return 1;
      }
      if (bTs === null) {
        return -1;
      }
      return bTs - aTs;
    });
  }, [events]);

  const latestActivity = useMemo(() => {
    return sortedEvents.find((event) => timestampFrom(event.occurred_at) !== null) ?? null;
  }, [sortedEvents]);

  return (
    <div className="space-y-2">
      {latestActivity && (
        <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--color-text-soft)]">
          <span className="font-medium text-[var(--color-text-strong)]">Last movement:</span>
          <span className="truncate" title={latestActivity.title}>
            {latestActivity.title}
          </span>
          <span className="text-[var(--color-text-muted)]">
            {formatRelativeSyncTime(latestActivity.occurred_at)}
          </span>
          {formatAbsoluteTimestamp(latestActivity.occurred_at) && (
            <span className="text-[var(--color-text-muted)]">
              ({formatAbsoluteTimestamp(latestActivity.occurred_at)})
            </span>
          )}
        </div>
      )}
      <div className="rounded-[var(--radius-2)] border border-border-subtle bg-[var(--color-surface)] shadow-elev-1">
        <div className="max-h-64 overflow-y-auto">
          <table className="w-full border-collapse text-sm">
            <thead className="sticky top-0 bg-[var(--color-hover)]/80 text-xs uppercase tracking-wide text-[var(--color-text-soft)]">
              <tr>
                <th className="px-4 py-2 text-left font-semibold">Event</th>
                <th className="px-4 py-2 text-left font-semibold">Event Time</th>
                <th className="px-4 py-2 text-left font-semibold">Last Sync</th>
                <th className="px-4 py-2 text-left font-semibold">Flow</th>
              </tr>
            </thead>
            <tbody>
              {sortedEvents.map((event) => (
                <EventFlowRow
                  key={event.id}
                  event={event}
                  providerLookup={providerLookup}
                  fallbackGlyph={fallbackGlyph}
                />
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function EventFlowRow({
  event,
  providerLookup,
  fallbackGlyph
}: {
  event: SyncEventSummary;
  providerLookup: Record<string, SyncEndpointSummary>;
  fallbackGlyph: string;
}) {
  const eventStart = event.start ?? event.start_at ?? null;
  const eventTime = formatEventTimestamp(eventStart);
  const syncAbsolute = formatAbsoluteTimestamp(event.occurred_at);
  const hasSynced = Boolean(event.occurred_at);
  const rawRelative = hasSynced ? formatRelativeSyncTime(event.occurred_at) : null;
  const syncRelative = rawRelative && rawRelative !== "—" ? rawRelative : null;
  const displaySyncLabel = syncRelative ?? syncAbsolute ?? "—";
  const syncTitle = syncAbsolute ?? undefined;
  const directionLabel = directionLabelFor(event, providerLookup);

  return (
    <tr className="border-t border-border-subtle text-xs text-[var(--color-text-soft)] first:border-t-0 hover:bg-[var(--color-hover)]/50">
      <td className="max-w-[18rem] px-4 py-2 text-[var(--color-text-strong)]">
        <div className="truncate" title={event.title}>
          {event.title}
        </div>
      </td>
      <td className="px-4 py-2 whitespace-nowrap">
        {eventTime}
      </td>
      <td className="px-4 py-2 whitespace-nowrap" title={syncTitle}>
        <div>{displaySyncLabel}</div>
      </td>
      <td className="px-4 py-2">
        <div className="flex items-center gap-2" title={directionLabel || undefined}>
          <FlowGlyphGroup event={event} fallbackGlyph={fallbackGlyph} providerLookup={providerLookup} />
          {directionLabel && <span className="sr-only">{directionLabel}</span>}
        </div>
      </td>
    </tr>
  );
}

function GlyphBubble({
  endpoint,
  fallback
}: {
  endpoint?: SyncEndpointSummary;
  fallback?: string;
}) {
  if (!endpoint) {
    const fallbackLabel = fallback?.slice(0, 1).toUpperCase() || "?";
    return (
      <span className="flex h-6 w-6 flex-none items-center justify-center rounded-md bg-[var(--color-hover)]/70 text-[var(--color-text-muted)]">
        {fallbackLabel}
      </span>
    );
  }

  const glyph = providerGlyphFor(endpoint.provider_type);
  const formattedName = formatProviderName(endpoint.provider_name);

  return (
    <span
      className="flex h-6 w-6 flex-none items-center justify-center rounded-md"
      style={{ background: glyph.bg, color: glyph.fg }}
      title={formattedName}
    >
      {glyph.label}
    </span>
  );
}

function SkeletonList() {
  return (
    <div className="space-y-4">
      {Array.from({ length: 3 }).map((_, index) => (
        <div key={`sync-skeleton-${index}`} className="h-40 animate-pulse orbit-surface" />
      ))}
    </div>
  );
}

function EmptyState({ onCreate }: { onCreate: () => void }) {
  return (
    <div className="orbit-surface flex flex-col items-center gap-3 px-6 py-10 text-center text-sm text-[var(--color-text-soft)]">
      <p>No sync definitions configured yet. Create one to connect your providers.</p>
      <Button variant="primary" className="inline-flex items-center gap-2" onClick={onCreate}>
        <Plus className="h-4 w-4" /> Create your first sync
      </Button>
    </div>
  );
}

function orderEndpoints(endpoints: SyncEndpointSummary[]) {
  return [...endpoints].sort((a, b) => roleWeight(a.role) - roleWeight(b.role));
}

function roleWeight(role: string) {
  const value = role.toLowerCase();
  if (value.includes("source")) {
    return 0;
  }
  if (value.includes("target")) {
    return 1;
  }
  return 2;
}

function resolveTimestamp(value?: string | null) {
  if (!value) {
    return null;
  }
  try {
    return parseISO(value);
  } catch (error) {
    console.warn("Failed to parse timestamp", value, error);
    return null;
  }
}

function deriveNextRunLabel(lastCompleted: Date | null, intervalSeconds: number, enabled: boolean) {
  if (!enabled) {
    return "paused";
  }
  if (!lastCompleted || intervalSeconds <= 0) {
    return "unscheduled";
  }
  const next = addSeconds(lastCompleted, intervalSeconds);
  const diff = next.getTime() - Date.now();
  if (Math.abs(diff) < 1000) {
    return "due now";
  }
  if (diff < 0) {
    return `${formatDistanceToNow(next)} overdue`;
  }
  return formatDistanceToNow(next, { addSuffix: true });
}

function formatInterval(seconds: number) {
  if (!seconds || seconds <= 0) {
    return "Interval not set";
  }
  if (seconds % 3600 === 0) {
    const hours = seconds / 3600;
    return hours === 1 ? "Every hour" : `Every ${hours} hours`;
  }
  if (seconds % 60 === 0) {
    const minutes = seconds / 60;
    if (minutes === 1) {
      return "Every minute";
    }
    if (minutes === 60) {
      return "Every hour";
    }
    return `Every ${minutes} minutes`;
  }
  return `Every ${(seconds / 60).toFixed(1)} minutes`;
}

export default SyncsPage;

function providerNameFor(
  providerId: string | null | undefined,
  providerLookup: Record<string, SyncEndpointSummary>,
  fallback?: string
): string {
  if (!providerId) {
    return fallback ? formatProviderName(fallback) : "";
  }
  const endpoint = providerLookup[providerId];
  const rawName = endpoint?.provider_name ?? fallback ?? providerId;
  return formatProviderName(rawName);
}

function directionLabelFor(
  event: SyncEventSummary,
  providerLookup: Record<string, SyncEndpointSummary>
): string {
  const badges = event.provider_badges ?? [];
  const sourceName = providerNameFor(event.source_provider_id, providerLookup, badges[0]);
  const targetName = providerNameFor(event.target_provider_id, providerLookup, badges[1]);
  if (sourceName && targetName) {
    return `${sourceName} → ${targetName}`;
  }
  return event.direction ?? "";
}

function timestampFrom(value?: string | null): number | null {
  const normalized = normalizeTimestamp(value);
  if (!normalized) {
    return null;
  }
  try {
    const parsed = parseISO(normalized);
    const ms = parsed.getTime();
    return Number.isNaN(ms) ? null : ms;
  } catch {
    return null;
  }
}
