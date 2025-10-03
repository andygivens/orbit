import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { format, formatDistanceToNow, parseISO } from "date-fns";
import { ArrowRight, ArrowRightLeft, Loader2, RefreshCcw } from "lucide-react";

import { Modal } from "../ui/modal";
import { Button } from "../ui/button";
import { DirectionBadge } from "./sync-elements";
import { ProviderChip } from "./provider-chip";
import { useApi } from "../../lib/api-context";
import { cn } from "../../lib/utils";
import type { SyncConfig, SyncEndpointSummary, SyncEventSummary } from "../../types/api";

type QuerySyncModalProps = {
  open: boolean;
  sync: SyncConfig;
  onClose: () => void;
};

type ScrollMarkers = {
  top: boolean;
  bottom: boolean;
};

export function QuerySyncModal({ open, sync, onClose }: QuerySyncModalProps) {
  const { client } = useApi();
  const [events, setEvents] = useState<SyncEventSummary[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [markers, setMarkers] = useState<ScrollMarkers>({ top: false, bottom: false });
  const listRef = useRef<HTMLDivElement | null>(null);

  const endpointLookup = useMemo(() => {
    return sync.endpoints.reduce<Record<string, SyncEndpointSummary>>((acc, endpoint) => {
      acc[endpoint.provider_id] = endpoint;
      return acc;
    }, {} as Record<string, SyncEndpointSummary>);
  }, [sync.endpoints]);

  const updateScrollMarkers = useCallback(() => {
    const node = listRef.current;
    if (!node) {
      setMarkers({ top: false, bottom: false });
      return;
    }
    const canScroll = node.scrollHeight > node.clientHeight + 1;
    if (!canScroll) {
      setMarkers({ top: false, bottom: false });
      return;
    }
    const top = node.scrollTop > 0;
    const bottom = node.scrollTop + node.clientHeight < node.scrollHeight - 1;
    setMarkers({ top, bottom });
  }, []);

  const refreshEvents = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await client.syncEvents(sync.id, 100);
      setEvents(response.events);
      setLastUpdated(new Date());
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to fetch sync events";
      setError(message);
    } finally {
      setIsLoading(false);
      requestAnimationFrame(updateScrollMarkers);
    }
  }, [client, sync.id, updateScrollMarkers]);

  useEffect(() => {
    if (!open) {
      return;
    }
    let cancelled = false;
    const load = async () => {
      setIsLoading(true);
      setError(null);
      try {
        const response = await client.syncEvents(sync.id, 100);
        if (!cancelled) {
          setEvents(response.events);
          setLastUpdated(new Date());
        }
      } catch (err) {
        if (!cancelled) {
          const message = err instanceof Error ? err.message : "Failed to fetch sync events";
          setError(message);
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
          requestAnimationFrame(updateScrollMarkers);
        }
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [client, open, sync.id, updateScrollMarkers]);

  useEffect(() => {
    updateScrollMarkers();
  }, [events, open, updateScrollMarkers]);

  useEffect(() => {
    const node = listRef.current;
    if (!node) {
      return;
    }
    node.addEventListener("scroll", updateScrollMarkers);
    return () => {
      node.removeEventListener("scroll", updateScrollMarkers);
    };
  }, [open, updateScrollMarkers]);

  const directionLabel = sync.direction;
  const hasEvents = events.length > 0;

  const footer = (
    <>
      <span className="text-xs text-[var(--color-text-soft)]">
        {lastUpdated ? `Last refreshed ${formatDistanceToNow(lastUpdated, { addSuffix: true })}` : ""}
      </span>
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="sm" onClick={onClose}>
          Close
        </Button>
        <Button variant="secondary" size="sm" onClick={refreshEvents} disabled={isLoading} className="gap-2">
          {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCcw className="h-4 w-4" />} Refresh
        </Button>
      </div>
    </>
  );

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Query ${sync.name}`}
      size="lg"
      footer={footer}
    >
      <div className="space-y-4 text-[var(--color-text-strong)]">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <DirectionBadge direction={directionLabel} />
          <div className="flex items-center gap-2 text-xs text-[var(--color-text-soft)]">
            <span>
              Window {(sync.window_days_back ?? sync.window_days_past ?? 0)}d past • {(sync.window_days_forward ?? sync.window_days_future ?? 0)}d future
            </span>
            <span>Interval {Math.round((sync.interval_seconds ?? 60) / 60)}m</span>
          </div>
        </div>

        {error && (
          <div className="rounded-xl border border-[var(--color-danger)]/50 bg-[var(--color-danger)]/10 px-4 py-3 text-sm text-[var(--color-danger)]">
            {error}
          </div>
        )}

        <div className="relative">
          <div
            ref={listRef}
            className={cn(
              "max-h-[400px] overflow-y-auto space-y-3", 
              !hasEvents && !isLoading && "min-h-[160px]"
            )}
          >
            {isLoading && !hasEvents ? (
              <div className="flex min-h-[160px] items-center justify-center text-sm text-[var(--color-text-soft)]">
                <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Loading event flow…
              </div>
            ) : hasEvents ? (
              events.map((event) => (
                <FlowEventCard key={event.id} event={event} direction={directionLabel} endpointLookup={endpointLookup} />
              ))
            ) : (
              <div className="flex min-h-[160px] items-center justify-center rounded-2xl border border-dashed border-border-subtle bg-[var(--color-hover)]/40 px-4 py-6 text-sm text-[var(--color-text-soft)]">
                No historical events recorded for this sync yet.
              </div>
            )}
          </div>
          <ScrollShadow position="top" visible={markers.top} />
          <ScrollShadow position="bottom" visible={markers.bottom} />
        </div>
      </div>
    </Modal>
  );
}

type FlowEventCardProps = {
  event: SyncEventSummary;
  direction: "bidirectional" | "one_way";
  endpointLookup: Record<string, SyncEndpointSummary>;
};

function FlowEventCard({ event, direction, endpointLookup }: FlowEventCardProps) {
  const started = event.start ? format(parseISO(event.start), "MMM d, HH:mm") : null;
  const occurred = event.occurred_at ? formatDistanceToNow(parseISO(event.occurred_at), { addSuffix: true }) : null;
  const source = event.source_provider_id ? endpointLookup[event.source_provider_id] : undefined;
  const target = event.target_provider_id ? endpointLookup[event.target_provider_id] : undefined;

  const hasExplicitPath = Boolean(source || target);

  const arrow = direction === "bidirectional" ? <ArrowRightLeft className="h-4 w-4 text-[var(--accent-600)]" /> : <ArrowRight className="h-4 w-4 text-[var(--accent-600)]" />;

  return (
    <div className="space-y-3 rounded-2xl border border-border-subtle bg-[var(--color-surface)] px-5 py-4 shadow-elev-1">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-[var(--color-text-strong)]">{event.title}</div>
          <div className="text-xs text-[var(--color-text-soft)]">
            {started ? `Starts ${started}` : "No start time"}
            {occurred ? ` • Updated ${occurred}` : ""}
          </div>
        </div>
        {event.provider_badges.length > 0 && !hasExplicitPath && (
          <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--color-text-soft)]">
            {event.provider_badges.map((badge) => (
              <span
                key={badge}
                className="rounded-full border border-border-subtle bg-[var(--color-hover)] px-3 py-1 text-[var(--color-text-soft)]"
              >
                {badge}
              </span>
            ))}
          </div>
        )}
      </div>

      {hasExplicitPath && (
        <div className="flex flex-wrap items-center gap-3">
          <ProviderChip endpoint={source} fallback={event.provider_badges[0]} showStatus />
          {arrow}
          <ProviderChip endpoint={target} fallback={event.provider_badges[1]} showStatus />
        </div>
      )}
    </div>
  );
}

type ScrollShadowProps = {
  position: "top" | "bottom";
  visible: boolean;
};

function ScrollShadow({ position, visible }: ScrollShadowProps) {
  return (
    <div
      className={cn(
        "pointer-events-none absolute inset-x-0 h-6 transition-opacity",
        position === "top" ? "top-0 bg-gradient-to-b from-[var(--color-surface)] to-transparent" : "bottom-0 bg-gradient-to-t from-[var(--color-surface)] to-transparent",
        visible ? "opacity-100" : "opacity-0"
      )}
    />
  );
}
