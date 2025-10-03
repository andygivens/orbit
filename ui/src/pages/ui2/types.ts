export type ScopeKey = "system" | `sync:${string}` | `provider:${string}`;
export type SyncStatus = "success" | "error" | "pending";
export type WindowRange = "24h" | "7d" | "14d" | "30d";

export type InventoryScope = {
  key: string;
  label: string;
  meta?: string;
  metaTone?: "critical" | "success";
};

export type SyncMappingSegment = {
  mappingId: string;
  providerId: string;
  providerLabel: string;
  providerUid: string;
  role: string;
  lastSeen: string;
};

export type SyncMappingRow = {
  id: string;
  event: string;
  eventTime: string;
  lastSynced: string;
  orbitEventId: string;
  notes: string;
  segments: SyncMappingSegment[];
  startAt?: string | null;
  endAt?: string | null;
  lastMergedAt?: string | null;
  syncId?: string | null;
};

export type SyncEventDetail = {
  runId: string;
  status: string;
  direction: string;
  duration: string;
  startedAt: string;
  finishedAt: string;
  eventsProcessed: string;
  eventsCreated: string;
  eventsUpdated: string;
  eventsDeleted: string;
  errors: string;
  phase: string;
  syncId: string;
  mode: string;
  sourceProvider: string;
  targetProvider: string;
  operationId: string;
  errorMessage: string;
};

export type SyncEventRow = {
  id: string;
  title: string;
  status: SyncStatus;
  lastAttempt: string;
  duration: string;
  notes: string;
  detail: SyncEventDetail;
};

export type ProviderEventDetail = {
  providerEventId: string;
  providerId: string;
  providerName: string;
  status: string;
  tombstoned: string;
  providerLastSeen: string;
  title: string;
  startAt: string;
  endAt: string;
  updatedAt: string;
  orbitEventId: string;
  syncId: string;
  mappingId: string;
};

export type ProviderEventRow = {
  id: string;
  title: string;
  when: string;
  attendees: string;
  statusLabel: string;
  detail: ProviderEventDetail;
};

export type OperationRow = {
  id: string;
  status: "failed" | "succeeded" | "running";
  resource: string;
  created: string;
  started: string;
  finished: string;
};

export type SystemMetric = {
  label: string;
  value: string;
  trend: string;
  tone?: "critical";
};

export type IncidentRow = {
  id: string;
  title: string;
  scope: string;
  status: "investigating" | "in queue" | "resolved";
  opened: string;
  owner: string;
};
