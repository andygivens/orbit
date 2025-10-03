import type { MouseEvent } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { format, formatDistanceToNow, parseISO } from "date-fns";
import { Activity, AlertCircle, CalendarCheck, ChevronDown, Edit, Loader2, PlugZap, RefreshCcw } from "lucide-react";

import { Card, CardContent } from "../ui/card";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Switch } from "../ui/switch";
import { ProviderPill } from "./provider-pill";
import { useApi } from "../../lib/api-context";
import { OrbitApiError } from "../../lib/api";
import { cn } from "../../lib/utils";
import type { Provider, ProviderEventRecord } from "../../types/api";

function formatRelativeTimestamp(value?: string | null): string {
  if (!value) {
    return "Never";
  }
  try {
    const parsed = parseISO(value);
    const now = new Date();
    if (parsed.getTime() > now.getTime() + 60_000) {
      return "Never";
    }
    return formatDistanceToNow(parsed, { addSuffix: true });
  } catch {
    return "Never";
  }
}

function formatShortTimestamp(value?: string | null): string {
  if (!value) {
    return "—";
  }
  try {
    return format(parseISO(value), "MM/dd/yy @ h:mma");
  } catch {
    return "—";
  }
}

function formatCompactRelative(value?: string | null): string {
  if (!value) {
    return "—";
  }
  try {
    const target = parseISO(value).getTime();
    const now = Date.now();
    const diffMs = Math.abs(now - target);
    const minutes = Math.round(diffMs / 60000);
    if (minutes < 60) {
      return `~${Math.max(minutes, 1)}m`;
    }
    const hours = Math.round(minutes / 60);
    if (hours < 24) {
      return `~${hours}h`;
    }
    const days = Math.round(hours / 24);
    if (days < 14) {
      return `>${days}d`;
    }
    const weeks = Math.round(days / 7);
    return `>${weeks}w`;
  } catch {
    return "—";
  }
}

export function ProviderCard({
  provider: initialProvider,
  onEdit,
  onProviderUpdated
}: {
  provider: Provider;
  onEdit?: (provider: Provider) => void;
  onProviderUpdated?: (provider: Provider) => void;
}) {
  const { client } = useApi();

  const [provider, setProvider] = useState<Provider>(initialProvider);
  const [collapsed, setCollapsed] = useState(true);
  const [events, setEvents] = useState<ProviderEventRecord[] | null>(null);
  const [eventsLoading, setEventsLoading] = useState(false);
  const [eventsError, setEventsError] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  const [updatingEnabled, setUpdatingEnabled] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [connectionMessage, setConnectionMessage] = useState<string | null>(initialProvider.status_detail ?? null);

  useEffect(() => {
    setProvider(initialProvider);
  }, [initialProvider]);

  useEffect(() => {
    setConnectionMessage(initialProvider.status_detail ?? null);
  }, [initialProvider.status_detail]);

  const lastConnectionLabel = useMemo(() => formatRelativeTimestamp(provider.last_checked_at), [provider.last_checked_at]);
  const lastSyncLabel = useMemo(() => formatRelativeTimestamp(provider.last_sync_at), [provider.last_sync_at]);

  const loadEvents = useCallback(async () => {
    setEventsLoading(true);
    setEventsError(null);
    try {
      const list = await client.listProviderEvents(provider.id, { limit: 7 }, provider.name);
      setEvents(list);
      setEventsError(null);
    } catch (err) {
      const message = err instanceof OrbitApiError ? err.message : "Failed to load recent events";
      setEventsError(message);
      setEvents(null);
    } finally {
      setEventsLoading(false);
    }
  }, [client, provider.id, provider.name]);

  const handleToggleCollapsed = () => {
    const next = !collapsed;
    setCollapsed(next);
    if (next && eventsError) {
      setEventsError(null);
      setEvents(null);
    }
  };

  useEffect(() => {
    if (!collapsed && events === null && !eventsLoading && eventsError === null) {
      void loadEvents();
    }
  }, [collapsed, events, eventsError, eventsLoading, loadEvents]);

  const handleTest = async (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    setTesting(true);
    setError(null);
    setConnectionMessage(null);
    try {
      const updated = await client.testProvider(provider.id);
      setProvider((prev) => ({ ...prev, ...updated }));
      onProviderUpdated?.(updated);
      if (updated.status_detail) {
        setConnectionMessage(updated.status_detail);
      }
    } catch (err) {
      const message = err instanceof OrbitApiError ? err.message : "Failed to test provider";
      setError(message);
      setConnectionMessage(null);
    } finally {
      setTesting(false);
    }
  };

  const handleToggleEnabled = async (checked: boolean) => {
    setUpdatingEnabled(true);
    setError(null);
    try {
      const fingerprint = provider.config_fingerprint ?? provider.updated_at ?? null;
      const ifMatch = fingerprint ? `W/"${fingerprint}"` : undefined;
      const updated = await client.updateProvider(provider.id, { enabled: checked }, { ifMatch });
      setProvider((prev) => ({ ...prev, ...updated }));
      onProviderUpdated?.(updated);
    } catch (err) {
      const message = err instanceof OrbitApiError ? err.message : "Failed to update provider";
      setError(message);
    } finally {
      setUpdatingEnabled(false);
    }
  };

  return (
    <Card className="overflow-hidden shadow-elev-2">
      <div
        className={cn(
          "flex items-start justify-between gap-4",
          !collapsed && "border-b border-border-subtle"
        )}
      >
        <button
          type="button"
          className="flex flex-1 flex-col items-start gap-2 text-left"
          onClick={handleToggleCollapsed}
        >
          <ProviderPill
            providerType={provider.type_id}
            providerName={provider.name}
            status={provider.status}
            statusDetail={provider.status_detail ?? undefined}
          />
          <div className="flex flex-wrap items-center gap-3 text-xs text-[var(--color-text-muted)]">
            <span>
              <CalendarCheck className="mr-1 inline h-3.5 w-3.5 text-[var(--color-text-soft)]" /> Last connection: {lastConnectionLabel}
            </span>
            <span>|</span>
            <span>
              <Activity className="mr-1 inline h-3.5 w-3.5 text-[var(--color-text-soft)]" /> Last sync: {lastSyncLabel}
            </span>
          </div>
        </button>
        <div className="flex items-center gap-3">
          <Button
            type="button"
            variant="secondary"
            size="sm"
            className="gap-1 text-xs font-medium"
            onClick={(event) => {
              event.stopPropagation();
              void handleToggleCollapsed();
            }}
          >
            <ChevronDown
              className={cn(
                "h-4 w-4 transition-transform",
                collapsed ? "-rotate-90" : "rotate-0"
              )}
            />
            {collapsed ? "Expand" : "Collapse"}
          </Button>
        </div>
      </div>

      {!collapsed && (
        <>
          {error && (
            <CardContent className="flex items-center gap-2 border border-[var(--color-danger)]/60 bg-[var(--color-danger)]/10 px-4 py-3 text-sm text-[var(--color-danger)]">
              <AlertCircle className="h-4 w-4" /> {error}
            </CardContent>
          )}
          <CardContent className="space-y-6 px-5 py-5">
            <section className="space-y-2">
              <div className="flex items-center justify-between gap-3">
                <h4 className="text-xs font-semibold uppercase tracking-wide text-[var(--color-text-muted)]">Recent events</h4>
                <Button
                  variant="ghost"
                  size="sm"
                  className="gap-2"
                  onClick={() => void loadEvents()}
                  disabled={eventsLoading}
                >
                  <RefreshCcw className={cn("h-4 w-4", eventsLoading && "animate-spin")} /> Refresh
                </Button>
              </div>
              <div className="rounded-[var(--radius-2)] border border-border-subtle shadow-elev-1">
                {eventsLoading ? (
                  <div className="flex items-center gap-2 px-4 py-5 text-sm text-[var(--color-text-soft)]">
                    <Loader2 className="h-4 w-4 animate-spin" /> Loading events…
                  </div>
                ) : eventsError ? (
                  <div className="px-4 py-4 text-sm text-[var(--color-danger)]">
                    {eventsError}
                  </div>
                ) : !events || events.length === 0 ? (
                  <div className="px-4 py-4 text-sm text-[var(--color-text-soft)]">No recent provider activity.</div>
                ) : (
                  <div className="max-h-96 overflow-y-auto">
                    <table className="w-full border-collapse text-sm">
                      <thead className="bg-[var(--color-hover)]/80 text-xs uppercase tracking-wide text-[var(--color-text-muted)]">
                        <tr>
                          <th className="px-4 py-2 text-left font-semibold">Event</th>
                          <th className="px-4 py-2 text-left font-semibold">Event time</th>
                          <th className="px-4 py-2 text-left font-semibold">Last change</th>
                          <th className="px-4 py-2 text-left font-semibold">Attendees</th>
                        </tr>
                      </thead>
                      <tbody>
                        {events.map((event, index) => {
                          const key = event.provider_event_id || event.orbit_event_id || `${provider.id}-${index}`;
                          const lastActivity = event.provider_last_seen ?? event.last_updated;
                          const attendees = event.categories ?? [];
                          return (
                            <tr
                              key={key}
                              className="border-t border-border-subtle first:border-t-0 text-xs text-[var(--color-text-soft)]"
                            >
                              <td className="px-4 py-2 align-top">
                                <span
                                  className="font-semibold text-[var(--color-text-strong)]"
                                  title={`Provider event ID: ${event.provider_event_id}`}
                                >
                                  {event.title || "Untitled"}
                                </span>
                              </td>
                              <td className="px-4 py-2 align-top">{formatShortTimestamp(event.start)}</td>
                              <td className="px-4 py-2 align-top">
                                <div>{formatCompactRelative(lastActivity)}</div>
                              </td>
                              <td className="px-4 py-2 align-top">
                                {attendees.length ? (
                                  <div className="flex flex-wrap gap-1">
                                    {attendees.map((attendee) => (
                                      <Badge key={`${event.provider_event_id}-${attendee}`} variant="muted" className="text-[10px]">
                                        {attendee}
                                      </Badge>
                                    ))}
                                  </div>
                                ) : (
                                  <span className="text-[var(--color-text-muted)]">—</span>
                                )}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </section>

            {connectionMessage && (
              <section className="space-y-3">
                <div className="rounded-[var(--radius-2)] border border-border-subtle bg-[var(--color-surface)] px-4 py-3 text-sm text-[var(--color-text-strong)]">
                  {connectionMessage}
                </div>
              </section>
            )}

            <div className="mt-6 border-t border-border-subtle pt-4">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                {onEdit && (
                  <Button
                    variant="primary"
                    size="sm"
                    className="gap-2"
                    icon={<Edit className="h-4 w-4" />}
                    onClick={(e) => {
                      e.stopPropagation();
                      onEdit(provider);
                    }}
                  >
                    Edit
                  </Button>
                )}
                <Button
                  variant="outline"
                  size="sm"
                  className="gap-2"
                  icon={testing ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlugZap className="h-4 w-4" />}
                  onClick={handleTest}
                  disabled={testing}
                >
                  {testing ? "Testing" : "Test"}
                </Button>
                <Switch
                  size="sm"
                  checked={!!provider.enabled}
                  disabled={updatingEnabled}
                  onClick={(e) => e.stopPropagation()}
                  onCheckedChange={handleToggleEnabled}
                  aria-label={provider.enabled ? "Disable provider" : "Enable provider"}
                />
              </div>
            </div>
          </CardContent>
        </>
      )}
    </Card>
  );
}

export default ProviderCard;
