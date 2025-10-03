import { useCallback, useEffect, useMemo, useState } from "react";
import { format, formatDistanceToNow, parseISO } from "date-fns";
import { AlertCircle, CalendarClock, Copy, Loader2, PlugZap, RefreshCcw } from "lucide-react";

import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { Switch } from "../components/ui/switch";
import { useApi } from "../lib/api-context";
import { formatProviderName, providerGlyphFor, statusBadgeVariant, statusColorFor, statusLabel } from "../lib/providers";
import type { Provider, ProviderEventRecord } from "../types/api";
import { OrbitApiError } from "../lib/api";
import { cn } from "../lib/utils";

function formatLongTimestamp(value?: string | null, fallback = "—") {
  if (!value) {
    return fallback;
  }
  try {
    return format(parseISO(value), "MMM d, yyyy • h:mm a");
  } catch {
    return fallback;
  }
}

function formatShortTimestamp(value?: string | null, fallback = "—") {
  if (!value) {
    return fallback;
  }
  try {
    return format(parseISO(value), "MM/dd/yy @ h:mma");
  } catch {
    return fallback;
  }
}

function formatRelative(value?: string | null, fallback = "—") {
  if (!value) {
    return fallback;
  }
  try {
    return formatDistanceToNow(parseISO(value), { addSuffix: true });
  } catch {
    return fallback;
  }
}

function MetaRow({ label, value }: { label: string; value: string | null | undefined }) {
  const display = value ?? "—";
  const handleCopy = useCallback(() => {
    void navigator.clipboard.writeText(display ?? "");
  }, [display]);

  return (
    <div className="flex items-center gap-2 rounded-[var(--radius-2)] border border-border-subtle bg-[var(--color-surface)] px-3 py-2">
      <div className="flex-1 min-w-0">
        <div className="text-[10px] uppercase tracking-wide text-[var(--color-text-muted)]">{label}</div>
        <div className="truncate text-sm text-[var(--color-text-strong)]" title={display ?? undefined}>
          {display}
        </div>
      </div>
      <Button variant="ghost" size="icon" className="h-7 w-7" onClick={handleCopy} aria-label={`Copy ${label}`}>
        <Copy className="h-3.5 w-3.5" />
      </Button>
    </div>
  );
}

export function ProviderCardPreviewPage() {
  const { client } = useApi();
  const [providers, setProviders] = useState<Provider[]>([]);
  const [selectedProviderId, setSelectedProviderId] = useState<string | null>(null);
  const [provider, setProvider] = useState<Provider | null>(null);
  const [providerLoading, setProviderLoading] = useState(false);
  const [providerError, setProviderError] = useState<string | null>(null);
  const [events, setEvents] = useState<ProviderEventRecord[]>([]);
  const [eventsLoading, setEventsLoading] = useState(false);
  const [eventsError, setEventsError] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  const [testError, setTestError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const loadProviders = async () => {
      try {
        const list = await client.providers();
        if (!cancelled) {
          setProviders(list);
          if (list.length && !selectedProviderId) {
            setSelectedProviderId(list[0].id);
          }
        }
      } catch (err) {
        if (!cancelled) {
          const message = err instanceof Error ? err.message : "Failed to load providers";
          setProviderError(message);
        }
      }
    };
    loadProviders();
    return () => {
      cancelled = true;
    };
  }, [client, selectedProviderId]);

  const refreshProvider = useCallback(async (providerId: string) => {
    setProviderLoading(true);
    setProviderError(null);
    try {
      const detail = await client.provider(providerId);
      setProvider(detail);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to load provider";
      setProviderError(message);
      setProvider(null);
    } finally {
      setProviderLoading(false);
    }
  }, [client]);

  const refreshEvents = useCallback(async (providerId: string, providerName?: string | null) => {
    setEventsLoading(true);
    setEventsError(null);
    try {
      const list = await client.listProviderEvents(providerId, { limit: 20 }, providerName);
      setEvents(list);
    } catch (err) {
      const message = err instanceof OrbitApiError ? err.message : "Failed to load events";
      setEventsError(message);
      setEvents([]);
    } finally {
      setEventsLoading(false);
    }
  }, [client]);

  useEffect(() => {
    if (!selectedProviderId) {
      return;
    }
    void refreshProvider(selectedProviderId);
  }, [refreshProvider, selectedProviderId]);

  useEffect(() => {
    if (!selectedProviderId) {
      return;
    }
    void refreshEvents(selectedProviderId, provider?.name);
  }, [provider?.name, refreshEvents, selectedProviderId]);

  const glyph = useMemo(() => providerGlyphFor(provider?.type_id ?? ""), [provider?.type_id]);
  const connectionLabel = useMemo(() => statusLabel(provider?.status ?? "degraded"), [provider?.status]);
  const connectionColor = useMemo(() => statusColorFor(provider?.status ?? "degraded"), [provider?.status]);
  const connectionBadge = useMemo(() => statusBadgeVariant(provider?.status ?? "degraded"), [provider?.status]);

  const handleTestConnection = useCallback(async () => {
    if (!provider) {
      return;
    }
    setTesting(true);
    setTestError(null);
    try {
      const updated = await client.testProvider(provider.id);
      setProvider(updated);
      await refreshEvents(provider.id, updated.name);
    } catch (err) {
      const message = err instanceof OrbitApiError ? err.message : "Failed to test connection";
      setTestError(message);
    } finally {
      setTesting(false);
    }
  }, [client, provider, refreshEvents]);

  const pageStatusMessage = providerError ?? testError;

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 py-6">
      <header className="flex flex-col gap-3">
        <div className="flex items-center justify-between gap-3">
          <h1 className="text-2xl font-semibold text-[var(--color-text-strong)]">Provider card redesign</h1>
          <Badge variant="outline" className="px-3 py-1 text-xs uppercase tracking-wide text-[var(--color-text-muted)]">Preview</Badge>
        </div>
        <p className="max-w-3xl text-sm text-[var(--color-text-soft)]">
          Explore a revised expanded state for provider cards. Pick a provider to load real data from the API and
          experiment with the condensed layout.
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <label className="text-sm text-[var(--color-text-soft)]" htmlFor="provider-select">
            Select provider
          </label>
          <select
            id="provider-select"
            className="min-w-[240px] rounded-md border border-border-subtle bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-text-strong)]"
            value={selectedProviderId ?? ""}
            onChange={(event) => setSelectedProviderId(event.target.value || null)}
          >
            {providers.map((item) => (
              <option key={item.id} value={item.id}>
                {formatProviderName(item.name)}
              </option>
            ))}
          </select>
          {provider && (
            <Button variant="ghost" size="sm" className="gap-2" onClick={() => void refreshProvider(provider.id)}>
              <RefreshCcw className="h-4 w-4" /> Refresh metadata
            </Button>
          )}
        </div>
      </header>

      {pageStatusMessage && (
        <div className="flex items-center gap-2 rounded-md border border-[var(--color-danger)]/60 bg-[var(--color-danger)]/10 px-3 py-2 text-sm text-[var(--color-danger)]">
          <AlertCircle className="h-4 w-4" /> {pageStatusMessage}
        </div>
      )}

      {providerLoading ? (
        <div className="flex items-center gap-2 rounded-md border border-border-subtle bg-[var(--color-surface)] px-4 py-6 text-sm text-[var(--color-text-soft)]">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading provider…
        </div>
      ) : provider ? (
        <Card className="shadow-elev-3">
          <CardContent className="space-y-6 p-6">
            <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
              <div className="flex flex-1 items-start gap-3">
                <span
                  className="inline-flex h-14 w-14 items-center justify-center rounded-[var(--radius-3)] text-lg font-semibold"
                  style={{ background: glyph.bg, color: glyph.fg }}
                >
                  {glyph.label}
                </span>
                <div className="space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="text-xl font-semibold text-[var(--color-text-strong)]">
                      {formatProviderName(provider.name)}
                    </h2>
                    <Badge variant="outline">{provider.type_id}</Badge>
                  </div>
                  <div className="flex flex-wrap items-center gap-3 text-xs text-[var(--color-text-muted)]">
                    <span className="inline-flex items-center gap-2">
                      Status
                      <Badge variant={connectionBadge} className="gap-1 text-xs font-semibold">
                        <span className="h-2 w-2 flex-none rounded-full" style={{ background: connectionColor }} />
                        {connectionLabel}
                      </Badge>
                    </span>
                    <span className="text-border-subtle" aria-hidden="true">|</span>
                    <span className="inline-flex items-center gap-2">
                      <CalendarClock className="h-3.5 w-3.5 text-[var(--color-text-soft)]" /> Last check {formatRelative(provider.last_checked_at)}
                    </span>
                  </div>
                </div>
              </div>
              <Switch size="md" rounded="rounded-[12px]" checked={!!provider.enabled} disabled className="opacity-80" />
            </div>

            <div className="grid gap-6">
              <div className="grid gap-6 lg:grid-cols-2">
                <section className="space-y-3">
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-[var(--color-text-muted)]">Meta details</h3>
                  <div className="space-y-2">
                    <MetaRow label="Provider ID" value={provider.id} />
                    <MetaRow label="Fingerprint" value={provider.config_fingerprint} />
                    <MetaRow label="Created" value={formatLongTimestamp(provider.created_at)} />
                    <MetaRow label="Updated" value={formatLongTimestamp(provider.updated_at)} />
                  </div>
                  <div className="space-y-2">
                    <h4 className="text-xs font-semibold uppercase tracking-wide text-[var(--color-text-muted)]">Sync participation</h4>
                    <div className="flex flex-wrap gap-2">
                      {(provider.syncs ?? []).length === 0 ? (
                        <span className="text-sm text-[var(--color-text-muted)]">Not linked to any sync definitions.</span>
                      ) : (
                        provider.syncs!.map((sync) => (
                          <Badge key={sync.id} variant="outline" className="gap-2 text-xs">
                            {sync.name}
                            <span className="text-[var(--color-text-muted)]">
                              • {sync.direction ?? "unknown"}
                              {sync.role ? ` • ${sync.role}` : ""}
                              {sync.last_run_status ? ` • ${sync.last_run_status}` : ""}
                            </span>
                          </Badge>
                        ))
                      )}
                    </div>
                  </div>
                </section>

                <section className="space-y-3">
                  <div className="flex items-center justify-between">
                    <h3 className="text-xs font-semibold uppercase tracking-wide text-[var(--color-text-muted)]">
                      Connection tools
                    </h3>
                    <Button
                      variant="primary"
                      size="sm"
                      className="gap-2"
                      onClick={handleTestConnection}
                      disabled={testing}
                    >
                      {testing ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlugZap className="h-4 w-4" />} {testing ? "Testing" : "Test connection"}
                    </Button>
                  </div>
                  {provider.status_detail ? (
                    <div className="rounded-[var(--radius-2)] border border-border-subtle bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-text-soft)]">
                      {provider.status_detail}
                    </div>
                  ) : (
                    <div className="rounded-[var(--radius-2)] border border-dashed border-border-subtle px-3 py-8 text-center text-xs text-[var(--color-text-muted)]">
                      No recent connection notes.
                    </div>
                  )}
                </section>
              </div>

              <section className="space-y-3">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <h3 className="text-xs font-semibold uppercase tracking-wide text-[var(--color-text-muted)]">Recent events</h3>
                    <p className="text-xs text-[var(--color-text-soft)]">Each entry shows the event time, attendees, and when the provider last reported changes.</p>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="gap-2"
                    onClick={() => provider && void refreshEvents(provider.id, provider.name)}
                    disabled={eventsLoading}
                  >
                    <RefreshCcw className={cn("h-4 w-4", eventsLoading && "animate-spin")} /> Refresh events
                  </Button>
                </div>

                {eventsLoading ? (
                  <div className="flex items-center gap-2 rounded-[var(--radius-2)] border border-border-subtle bg-[var(--color-surface)] px-4 py-5 text-sm text-[var(--color-text-soft)]">
                    <Loader2 className="h-4 w-4 animate-spin" /> Loading events…
                  </div>
                ) : eventsError ? (
                  <div className="rounded-[var(--radius-2)] border border-[var(--color-danger)]/50 bg-[var(--color-danger)]/10 px-4 py-3 text-sm text-[var(--color-danger)]">
                    {eventsError}
                  </div>
                ) : events.length === 0 ? (
                  <div className="rounded-[var(--radius-2)] border border-border-subtle bg-[var(--color-surface)] px-4 py-5 text-sm text-[var(--color-text-soft)]">
                    No recent provider activity.
                  </div>
                ) : (
                  <div className="rounded-[var(--radius-2)] border border-border-subtle shadow-elev-1">
                    <div className="max-h-80 overflow-y-auto">
                      <table className="w-full border-collapse text-sm">
                        <thead className="bg-[var(--color-hover)]/80 text-xs uppercase tracking-wide text-[var(--color-text-muted)]">
                        <tr>
                          <th className="px-4 py-3 text-left font-semibold">Event</th>
                          <th className="px-4 py-3 text-left font-semibold">Event time</th>
                          <th className="px-4 py-3 text-left font-semibold">Last change</th>
                          <th className="px-4 py-3 text-left font-semibold">Attendees</th>
                        </tr>
                        </thead>
                        <tbody>
                          {events.map((event) => {
                            const lastActivity = event.provider_last_seen ?? event.last_updated;
                            const relative = formatRelative(lastActivity);
                            const absolute = formatShortTimestamp(lastActivity);
                            return (
                              <tr
                                key={`${event.provider_event_id}-${event.orbit_event_id ?? "unlinked"}`}
                                className="border-t border-border-subtle first:border-t-0 transition-colors hover:bg-[var(--color-hover)]/40"
                              >
                              <td className="px-4 py-3 align-top">
                                <div
                                  className="font-semibold text-[var(--color-text-strong)]"
                                  title={`Provider event ID: ${event.provider_event_id}`}
                                >
                                  {event.title || "Untitled"}
                                </div>
                              </td>
                              <td className="px-4 py-3 align-top text-sm text-[var(--color-text-soft)]">
                                {formatShortTimestamp(event.start)}
                              </td>
                              <td className="px-4 py-3 align-top text-sm text-[var(--color-text-soft)]">
                                {absolute}
                                <div className="text-xs text-[var(--color-text-muted)]">{relative}</div>
                              </td>
                              <td className="px-4 py-3 align-top text-sm">
                                {event.categories && event.categories.length > 0 ? (
                                  <div className="flex flex-wrap gap-2">
                                    {event.categories.map((category) => (
                                      <Badge key={`${event.provider_event_id}-${category}`} variant="muted" className="text-xs">
                                        {category}
                                      </Badge>
                                    ))}
                                  </div>
                                ) : (
                                  <span className="text-xs text-[var(--color-text-muted)]">—</span>
                                )}
                              </td>
                            </tr>
                          );
                        })}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </section>
            </div>
          </CardContent>
        </Card>
      ) : (
        <div className="rounded-md border border-border-subtle bg-[var(--color-surface)] px-4 py-6 text-sm text-[var(--color-text-soft)]">
          Select a provider to preview the redesigned layout.
        </div>
      )}
    </div>
  );
}

export default ProviderCardPreviewPage;
