import { Fragment, useEffect, useMemo, useState } from "react";
import { addDays, addHours, format, formatDistanceToNow, parseISO, subDays, subHours } from "date-fns";
import { AlertTriangle, ArrowRight, ArrowRightLeft, Loader2, RefreshCcw } from "lucide-react";

import { Modal } from "../ui/modal";
import { Button } from "../ui/button";
import { Badge } from "../ui/badge";
import { ProviderChip } from "./provider-chip";
import { useApi } from "../../lib/api-context";
import { cn } from "../../lib/utils";
import { formatProviderName } from "../../lib/providers";
import type {
  Provider,
  ProviderEventRecord,
  SyncConfig,
  SyncEndpointSummary,
  SyncEventSummary
} from "../../types/api";

type ProviderPanelState = {
  data: ProviderEventRecord[];
  loading: boolean;
  error: string | null;
};

type LinkEditorState = {
  providerId: string;
  providerEventId: string;
  currentOrbitId: string | null;
};

type GroupMember = {
  key: string;
  providerId: string;
  providerName: string;
  endpoint?: SyncEndpointSummary;
  record: ProviderEventRecord;
  directionLabel: "Inbound" | "Outbound" | "Unmapped";
  directionText: string;
  duplicateCount: number;
  orbitLinkCount: number;
  tombstoned: boolean;
};

type TroubleshootGroup = {
  key: string;
  orbitEventId: string | null;
  title: string;
  start: string | null;
  orbitOccurredAt?: string | null;
  suspectCollision: boolean;
  providerCount: number;
  latestTimestamp: number;
  members: GroupMember[];
};

const TIMEFRAME_OPTIONS = [
  { value: "24h", label: "Past & next 24 hours" },
  { value: "7d", label: "Past & next 7 days" },
  { value: "30d", label: "Past & next 30 days" },
  { value: "all", label: "All events" }
] as const;

export type TroubleshootModalProps = {
  open: boolean;
  sync: SyncConfig;
  providers: Provider[];
  onClose: () => void;
};

export function TroubleshootModal({ open, sync, providers, onClose }: TroubleshootModalProps) {
  const { client } = useApi();
  const [flowEvents, setFlowEvents] = useState<SyncEventSummary[]>(Array.isArray(sync.events) ? sync.events : []);
  const [flowLoading, setFlowLoading] = useState(false);
  const [flowError, setFlowError] = useState<string | null>(null);
  const [providerEvents, setProviderEvents] = useState<Record<string, ProviderPanelState>>({});
  const [timeframe, setTimeframe] = useState<(typeof TIMEFRAME_OPTIONS)[number]["value"]>("7d");
  const [refreshTick, setRefreshTick] = useState(0);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionState, setActionState] = useState<{ type: "link" | "unlink"; key: string } | null>(null);
  const [linkEditor, setLinkEditor] = useState<LinkEditorState | null>(null);
  const [linkTargetOrbit, setLinkTargetOrbit] = useState<string>("");

  const providerLookup = useMemo(() => {
    const map: Record<string, Provider> = {};
    providers.forEach((provider) => {
      map[provider.id] = provider;
    });
    return map;
  }, [providers]);

  const providerIds = useMemo(() => sync.endpoints.map((endpoint) => endpoint.provider_id), [sync.endpoints]);

  const endpointsByProvider = useMemo(() => {
    const map = new Map<string, SyncEndpointSummary>();
    sync.endpoints.forEach((endpoint) => {
      map.set(endpoint.provider_id, endpoint);
    });
    return map;
  }, [sync.endpoints]);

  useEffect(() => {
    if (!open) {
      setProviderEvents({});
      setFlowError(null);
      setActionError(null);
      setLinkEditor(null);
      setLinkTargetOrbit("");
    }
  }, [open]);

  useEffect(() => {
    if (!open) {
      return;
    }
    let cancelled = false;
    const loadFlows = async () => {
      setFlowLoading(true);
      setFlowError(null);
      try {
        const response = await client.syncEvents(sync.id, 50);
        if (!cancelled) {
          setFlowEvents(Array.isArray(response.events) ? response.events : []);
        }
      } catch (err) {
        if (!cancelled) {
          const message = err instanceof Error ? err.message : "Failed to load flow details";
          setFlowError(message);
        }
      } finally {
        if (!cancelled) {
          setFlowLoading(false);
        }
      }
    };
    loadFlows();
    return () => {
      cancelled = true;
    };
  }, [client, open, refreshTick, sync.id]);

  useEffect(() => {
    if (!open) {
      return;
    }
    setFlowEvents(Array.isArray(sync.events) ? sync.events : []);
  }, [open, sync.events]);

  useEffect(() => {
    if (!open) {
      return;
    }
    const { since, until } = computeRange(timeframe);
    const sinceIso = since ? since.toISOString() : undefined;
    const untilIso = until ? until.toISOString() : undefined;

    providerIds.forEach((id) => {
      setProviderEvents((prev) => ({
        ...prev,
        [id]: {
          data: prev[id]?.data ?? [],
          loading: true,
          error: null
        }
      }));
    });

    let cancelled = false;

    const load = async () => {
      await Promise.all(
        providerIds.map(async (providerId) => {
          try {
            const providerName =
              providerLookup[providerId]?.name ||
              endpointsByProvider.get(providerId)?.provider_name ||
              providerId;
            const response = await client.syncProviderEvents(sync.id, providerId, {
              since: sinceIso,
              until: untilIso,
              limit: 200
            }, providerName);
            if (!cancelled) {
              setProviderEvents((prev) => ({
                ...prev,
                [providerId]: {
                  data: response.events,
                  loading: false,
                  error: null
                }
              }));
            }
          } catch (err) {
            if (!cancelled) {
              const message = err instanceof Error ? err.message : "Failed to load provider events";
              setProviderEvents((prev) => ({
                ...prev,
                [providerId]: {
                  data: prev[providerId]?.data ?? [],
                  loading: false,
                  error: message
                }
              }));
            }
          }
        })
      );
    };

    load();

    return () => {
      cancelled = true;
    };
  }, [client, open, providerIds, timeframe, refreshTick, sync.id, providerLookup, endpointsByProvider]);

  const flowByOrbit = useMemo(() => {
    const map = new Map<string, SyncEventSummary>();
    flowEvents.forEach((event) => {
      map.set(event.id, event);
    });
    return map;
  }, [flowEvents]);

  const anyLoading = useMemo(
    () => providerIds.some((id) => providerEvents[id]?.loading),
    [providerEvents, providerIds]
  );

  const allRecords = useMemo(() => {
    const rows: Array<{ providerId: string; record: ProviderEventRecord }> = [];
    providerIds.forEach((providerId) => {
      const panel = providerEvents[providerId];
      panel?.data?.forEach((record) => {
        rows.push({ providerId, record });
      });
    });
    return rows;
  }, [providerEvents, providerIds]);

  const providerEventCounts = useMemo(() => {
    const counts = new Map<string, number>();
    allRecords.forEach(({ providerId, record }) => {
      const key = `${providerId}::${record.provider_event_id}`;
      counts.set(key, (counts.get(key) ?? 0) + 1);
    });
    return counts;
  }, [allRecords]);

  const orbitMembershipCounts = useMemo(() => {
    const map = new Map<string, Set<string>>();
    allRecords.forEach(({ providerId, record }) => {
      if (!record.orbit_event_id) {
        return;
      }
      const set = map.get(record.orbit_event_id) ?? new Set<string>();
      set.add(providerId);
      map.set(record.orbit_event_id, set);
    });
    const counts = new Map<string, number>();
    map.forEach((set, orbitId) => counts.set(orbitId, set.size));
    return counts;
  }, [allRecords]);

  const groups = useMemo<TroubleshootGroup[]>(() => {
    type WorkingGroup = TroubleshootGroup & { members: GroupMember[] };
    const map = new Map<string, WorkingGroup>();

    allRecords.forEach(({ providerId, record }) => {
      const groupKey = record.orbit_event_id ?? `unlinked:${providerId}:${record.provider_event_id}`;
      let group = map.get(groupKey);
      if (!group) {
        const flow = record.orbit_event_id ? flowByOrbit.get(record.orbit_event_id) : undefined;
        group = {
          key: groupKey,
          orbitEventId: record.orbit_event_id ?? null,
          title: record.title,
          start: record.start,
          orbitOccurredAt: flow?.occurred_at,
          suspectCollision: false,
          providerCount: 0,
          latestTimestamp: Math.max(
            parseTimestamp(record.last_updated),
            parseTimestamp(record.start),
            parseTimestamp(flow?.occurred_at)
          ),
          members: []
        };
        map.set(groupKey, group);
      } else {
        const flow = record.orbit_event_id ? flowByOrbit.get(record.orbit_event_id) : undefined;
        group.latestTimestamp = Math.max(
          group.latestTimestamp,
          parseTimestamp(record.last_updated),
          parseTimestamp(record.start),
          parseTimestamp(flow?.occurred_at)
        );
      }

      const endpoint = endpointsByProvider.get(providerId);
      const provider = providerLookup[providerId];
      const flow = record.orbit_event_id ? flowByOrbit.get(record.orbit_event_id) : undefined;

      let directionLabel: "Inbound" | "Outbound" | "Unmapped" = "Unmapped";
      let counterpartName: string | undefined;
      if (flow) {
        if (providerId === flow.source_provider_id) {
          directionLabel = "Outbound";
          if (flow.target_provider_id) {
            const target = endpointsByProvider.get(flow.target_provider_id);
            counterpartName =
              formatProviderName(target?.provider_name ?? providerLookup[flow.target_provider_id]?.name ?? flow.target_provider_id) ||
              flow.target_provider_id;
          }
        } else if (providerId === flow.target_provider_id) {
          directionLabel = "Inbound";
          if (flow.source_provider_id) {
            const source = endpointsByProvider.get(flow.source_provider_id);
            counterpartName =
              formatProviderName(source?.provider_name ?? providerLookup[flow.source_provider_id]?.name ?? flow.source_provider_id) ||
              flow.source_provider_id;
          }
        }
      }

      const duplicateCount = providerEventCounts.get(`${providerId}::${record.provider_event_id}`) ?? 0;
      const orbitLinkCount = record.orbit_event_id
        ? orbitMembershipCounts.get(record.orbit_event_id) ?? 0
        : 0;

      const providerName =
        formatProviderName(provider?.name ?? endpoint?.provider_name ?? providerId) || providerId;

      const directionText =
        directionLabel === "Unmapped"
          ? "Unmapped"
          : directionLabel === "Outbound"
          ? counterpartName
            ? `Outbound → ${counterpartName}`
            : "Outbound"
          : counterpartName
          ? `Inbound ← ${counterpartName}`
          : "Inbound";

      group.members.push({
        key: `${providerId}-${record.provider_event_id}-${record.orbit_event_id ?? "unlinked"}`,
        providerId,
        providerName,
        endpoint,
        record,
        directionLabel,
        directionText,
        duplicateCount,
        orbitLinkCount,
        tombstoned: record.tombstoned
      });
    });

    return Array.from(map.values()).map((group) => {
      group.members.sort((a, b) => a.providerName.localeCompare(b.providerName));
      const providerSet = new Set(group.members.map((member) => member.providerId));
      const hasDuplicates = group.members.some((member) => member.duplicateCount > 1);
      const suspectCollision = group.members.length > 1 || hasDuplicates;
      return {
        key: group.key,
        orbitEventId: group.orbitEventId,
        title: group.title,
        start: group.start,
        orbitOccurredAt: group.orbitOccurredAt,
        suspectCollision,
        providerCount: providerSet.size,
        latestTimestamp: group.latestTimestamp,
        members: group.members
      };
    }).sort((a, b) => {
      if (a.suspectCollision !== b.suspectCollision) {
        return a.suspectCollision ? -1 : 1;
      }
      return b.latestTimestamp - a.latestTimestamp;
    });
  }, [allRecords, endpointsByProvider, flowByOrbit, orbitMembershipCounts, providerEventCounts, providerLookup]);

  const collisionCount = useMemo(
    () => groups.filter((group) => group.suspectCollision).length,
    [groups]
  );

  const orbitOptions = useMemo(() => {
    const seen = new Map<string, string>();
    groups.forEach((group) => {
      if (group.orbitEventId && !seen.has(group.orbitEventId)) {
        const label = group.title
          ? group.title
          : `Orbit ${shortenId(group.orbitEventId)}`;
        seen.set(group.orbitEventId, label);
      }
    });
    return Array.from(seen.entries()).map(([id, label]) => ({ id, label }));
  }, [groups]);

  const hasRecords = groups.length > 0;

  const providerErrors = useMemo(
    () =>
      providerIds
        .map((id) => providerEvents[id]?.error)
        .filter((value): value is string => Boolean(value)),
    [providerEvents, providerIds]
  );

  const combinedErrors = useMemo(() => {
    const messages: string[] = [];
    if (actionError) {
      messages.push(actionError);
    }
    if (flowError) {
      messages.push(flowError);
    }
    messages.push(...providerErrors);
    return messages;
  }, [actionError, flowError, providerErrors]);

  const startLink = (providerId: string, providerEventId: string, currentOrbitId: string | null) => {
    const options = orbitOptions.filter((option) => option.id !== currentOrbitId);
    if (options.length === 0) {
      setActionError("No other Orbit events available to link.");
      return;
    }
    setActionError(null);
    setLinkEditor({ providerId, providerEventId, currentOrbitId });
    setLinkTargetOrbit(options[0].id);
  };

  const cancelLink = () => {
    setLinkEditor(null);
    setLinkTargetOrbit("");
  };

  const submitLink = async () => {
    if (!linkEditor) {
      return;
    }
    if (!linkTargetOrbit || linkTargetOrbit === linkEditor.currentOrbitId) {
      setActionError("Select a different Orbit event to link.");
      return;
    }
    const actionKey = `${linkEditor.providerId}-${linkEditor.providerEventId}`;
    setActionState({ type: "link", key: actionKey });
    setActionError(null);
    try {
      await client.linkProviderEvent(
        sync.id,
        linkEditor.providerId,
        linkEditor.providerEventId,
        linkTargetOrbit
      );
      setLinkEditor(null);
      setLinkTargetOrbit("");
      setRefreshTick((tick) => tick + 1);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to relink provider event";
      setActionError(message);
    } finally {
      setActionState(null);
    }
  };

  const unlinkProviderEvent = async (providerId: string, providerEventId: string) => {
    const actionKey = `${providerId}-${providerEventId}`;
    setActionState({ type: "unlink", key: actionKey });
    setActionError(null);
    try {
      await client.unlinkProviderEvent(sync.id, providerId, providerEventId);
      if (linkEditor && linkEditor.providerId === providerId && linkEditor.providerEventId === providerEventId) {
        cancelLink();
      }
      setRefreshTick((tick) => tick + 1);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to unlink provider event";
      setActionError(message);
    } finally {
      setActionState(null);
    }
  };

  const isActionLoading = (type: "link" | "unlink", key: string) =>
    actionState?.type === type && actionState.key === key;

  const orderedEndpoints = useMemo(
    () => [...sync.endpoints].sort((a, b) => roleWeight(a.role) - roleWeight(b.role)),
    [sync.endpoints]
  );

  const DirectionIcon = sync.direction === "bidirectional" ? ArrowRightLeft : ArrowRight;

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="lg"
      title={
        <span className="flex flex-col gap-1">
          <span className="text-xs font-semibold uppercase tracking-wide text-[var(--color-text-soft)]">
            Troubleshoot
          </span>
          <span className="flex flex-wrap items-center gap-2 text-sm font-medium text-[var(--color-text-strong)]">
            {orderedEndpoints.map((endpoint, index) => (
              <Fragment key={endpoint.provider_id}>
                {index > 0 && (
                  <span className="flex h-6 w-6 items-center justify-center rounded-full bg-[var(--accent-600)]/10 text-[var(--accent-600)]">
                    <DirectionIcon className="h-3.5 w-3.5" />
                  </span>
                )}
                <ProviderChip endpoint={endpoint} showStatus />
              </Fragment>
            ))}
          </span>
        </span>
      }
    >
      <div className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-sm text-[var(--color-text-soft)]">
            <label htmlFor="troubleshoot-timeframe" className="text-xs uppercase tracking-wide text-[var(--color-text-soft)]">
              Activity window
            </label>
            <select
              id="troubleshoot-timeframe"
              value={timeframe}
              onChange={(event) => setTimeframe(event.target.value as typeof timeframe)}
              className="rounded-md border border-border-subtle bg-[var(--color-surface)] px-3 py-1 text-sm"
            >
              {TIMEFRAME_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setRefreshTick((tick) => tick + 1)}
            disabled={flowLoading || anyLoading}
            className="flex items-center gap-2"
          >
            <RefreshCcw className={cn("h-4 w-4", (flowLoading || anyLoading) && "animate-spin")} />
            Refresh
          </Button>
        </div>

        <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--color-text-soft)]">
          <span>
            {collisionCount > 0
              ? `${collisionCount} potential collision${collisionCount > 1 ? "s" : ""} detected`
              : "No collisions detected in the selected window"}
          </span>
          <Badge variant="muted">{groups.length} groups</Badge>
        </div>

        {combinedErrors.length > 0 && (
          <div className="flex items-center gap-2 rounded-lg border border-[var(--color-danger)]/60 bg-[var(--color-danger)]/10 px-3 py-2 text-sm text-[var(--color-danger)]">
            <AlertTriangle className="h-4 w-4" /> {combinedErrors.join(" • ")}
          </div>
        )}

        {(flowLoading || anyLoading) && !hasRecords && (
          <div className="flex items-center gap-2 text-sm text-[var(--color-text-soft)]">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading event history
          </div>
        )}

        {hasRecords ? (
          <div className="overflow-hidden rounded-[var(--radius-3)] bg-[var(--color-surface)] shadow-elev-1">
            <table className="w-full border-collapse text-sm">
              <thead className="bg-[var(--color-hover)]/40 text-[0.7rem] uppercase tracking-wide text-[var(--color-text-soft)]">
                <tr>
                  <th className="px-3 py-2 text-left text-[var(--color-text-strong)]">Event</th>
                  <th className="px-3 py-2 text-left text-[var(--color-text-strong)]">Provider</th>
                  <th className="px-3 py-2 text-left text-[var(--color-text-strong)]">Provider Event</th>
                  <th className="px-3 py-2 text-left text-[var(--color-text-strong)]">Activity</th>
                  <th className="px-3 py-2 text-left text-[var(--color-text-strong)]">Status</th>
                  <th className="px-3 py-2 text-left text-[var(--color-text-strong)]">Actions</th>
                </tr>
              </thead>
              <tbody>
                {groups.map((group) =>
                  group.members.map((member, index) => {
                    const actionKey = `${member.providerId}-${member.record.provider_event_id}`;
                    const isLinking =
                      linkEditor?.providerId === member.providerId &&
                      linkEditor?.providerEventId === member.record.provider_event_id;
                    const availableLinkTargets = orbitOptions.filter(
                      (option) => option.id !== member.record.orbit_event_id
                    );

                    return (
                      <tr
                        key={`${group.key}-${member.key}`}
                        className={cn(
                          "border-t border-border-subtle",
                          group.suspectCollision && index === 0 && "bg-[var(--color-danger)]/8"
                        )}
                      >
                        {index === 0 && (
                          <td className="w-[28%] px-3 py-3 align-top" rowSpan={group.members.length}>
                            <div className="flex flex-col gap-2 text-[var(--color-text-strong)]">
                              <div className="flex flex-wrap items-center gap-2">
                                <span className="font-semibold">{group.title || "Untitled Event"}</span>
                                {group.suspectCollision ? <Badge variant="danger">Collision</Badge> : null}
                                {group.orbitEventId ? (
                                  <Badge variant="success">Orbit linked</Badge>
                                ) : (
                                  <Badge variant="warning">Unlinked</Badge>
                                )}
                                <Badge variant="muted">{group.providerCount} providers</Badge>
                              </div>
                              <div className="text-xs text-[var(--color-text-soft)]">
                                {group.start ? safelyFormatDate(group.start) : "Start unknown"}
                              </div>
                              {group.orbitEventId ? (
                                <div className="font-mono text-[0.65rem] text-[var(--color-text-soft)]">
                                  Orbit ID: {shortenId(group.orbitEventId)}
                                </div>
                              ) : null}
                            </div>
                          </td>
                        )}

                        <td className="px-3 py-3 align-top">
                          <div className="flex items-center gap-2">
                            {member.endpoint ? <ProviderChip endpoint={member.endpoint} showStatus /> : null}
                            <div className="flex flex-col text-xs text-[var(--color-text-soft)]">
                              <span className="font-medium text-[var(--color-text-strong)]">{member.providerName}</span>
                              <span>{member.directionText}</span>
                            </div>
                          </div>
                        </td>

                        <td className="px-3 py-3 align-top font-mono text-xs text-[var(--color-text-soft)]">
                          {member.record.provider_event_id}
                        </td>

                        <td className="px-3 py-3 align-top text-xs text-[var(--color-text-soft)]">
                          <div>{member.record.start ? safelyFormatDate(member.record.start) : "Unknown"}</div>
                          <div>
                            Last activity {formatRelative(member.record.last_updated ?? member.record.provider_last_seen)}
                          </div>
                        </td>

                        <td className="px-3 py-3 align-top">
                          <div className="flex flex-wrap items-center gap-2 text-[0.65rem]">
                            <Badge variant={member.record.orbit_event_id ? "success" : "warning"}>
                              {member.record.orbit_event_id ? "Linked" : "Needs link"}
                            </Badge>
                            {member.duplicateCount > 1 ? (
                              <Badge variant="danger">{member.duplicateCount} duplicates</Badge>
                            ) : null}
                            {member.orbitLinkCount > 1 ? (
                              <Badge variant="accent">{member.orbitLinkCount} providers</Badge>
                            ) : null}
                            {member.tombstoned ? <Badge variant="muted">Tombstoned</Badge> : null}
                          </div>
                        </td>

                        <td className="px-3 py-3 align-top text-xs text-[var(--color-text-soft)]">
                          <div className="flex flex-col gap-2">
                            <div className="flex flex-wrap gap-2">
                              <Button
                                variant="outline"
                                size="sm"
                                disabled={!member.record.orbit_event_id || isActionLoading("unlink", actionKey)}
                                onClick={() => unlinkProviderEvent(member.providerId, member.record.provider_event_id)}
                              >
                                {isActionLoading("unlink", actionKey) ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
                                Unlink
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                disabled={availableLinkTargets.length === 0 || isActionLoading("link", actionKey)}
                                onClick={() => startLink(member.providerId, member.record.provider_event_id, member.record.orbit_event_id ?? null)}
                              >
                                {member.record.orbit_event_id ? "Relink" : "Link"}
                              </Button>
                            </div>
                            {isLinking ? (
                              <div className="flex flex-col gap-2 rounded-md border border-border-subtle px-2 py-2">
                                <label className="text-[0.65rem] uppercase tracking-wide text-[var(--color-text-soft)]">
                                  Relink to orbit
                                </label>
                                <select
                                  value={linkTargetOrbit}
                                  onChange={(event) => setLinkTargetOrbit(event.target.value)}
                                  className="rounded-md border border-border-subtle bg-[var(--color-surface)] px-2 py-1 text-sm"
                                >
                                  {availableLinkTargets.map((option) => (
                                    <option key={option.id} value={option.id}>
                                      {option.label}
                                    </option>
                                  ))}
                                </select>
                                <div className="flex gap-2">
                                  <Button
                                    variant="primary"
                                    size="sm"
                                    disabled={isActionLoading("link", actionKey)}
                                    onClick={submitLink}
                                  >
                                    {isActionLoading("link", actionKey) ? (
                                      <Loader2 className="h-3 w-3 animate-spin" />
                                    ) : null}
                                    Save
                                  </Button>
                                  <Button variant="ghost" size="sm" onClick={cancelLink}>
                                    Cancel
                                  </Button>
                                </div>
                              </div>
                            ) : null}
                          </div>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="rounded-[var(--radius-3)] border border-dashed border-border-subtle px-4 py-6 text-sm text-[var(--color-text-soft)]">
            No provider events captured for the selected window.
          </div>
        )}

        <div className="orbit-surface shadow-elev-1 px-4 py-4 text-xs text-[var(--color-text-soft)]">
          Use the relink and unlink controls above to resolve collisions. Refresh after each fix to confirm.
        </div>
      </div>
    </Modal>
  );
}

function computeRange(value: (typeof TIMEFRAME_OPTIONS)[number]["value"]): { since?: Date; until?: Date } {
  const now = new Date();
  switch (value) {
    case "24h":
      return { since: subHours(now, 24), until: addHours(now, 24) };
    case "7d":
      return { since: subDays(now, 7), until: addDays(now, 7) };
    case "30d":
      return { since: subDays(now, 30), until: addDays(now, 30) };
    default:
      return { since: undefined, until: undefined };
  }
}

function roleWeight(role: string) {
  const value = role.toLowerCase();
  if (value.includes("primary") || value.includes("source")) {
    return 0;
  }
  if (value.includes("secondary") || value.includes("target")) {
    return 1;
  }
  return 2;
}

function shortenId(value: string, visible: number = 6): string {
  if (value.length <= visible * 2 + 3) {
    return value;
  }
  return `${value.slice(0, visible)}...${value.slice(-visible)}`;
}

function parseTimestamp(value?: string | null): number {
  if (!value) {
    return 0;
  }
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function safelyFormatDate(value?: string | null): string {
  if (!value) {
    return "Unknown";
  }
  try {
    return format(parseISO(value), "MMM d, yyyy HH:mm");
  } catch {
    return value;
  }
}

function formatRelative(value?: string | null): string {
  if (!value) {
    return "unknown";
  }
  try {
    return formatDistanceToNow(parseISO(value), { addSuffix: true });
  } catch {
    return "unknown";
  }
}
