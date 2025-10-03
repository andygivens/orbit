export type HealthResponse = {
  status: string;
  version: string;
  service?: string;
};

export type ReadyStatus = "ready" | "degraded" | "error";

export type OrbitStatus = "active" | "degraded" | "error" | "disabled";

export type ProviderReadiness = {
  id: string;
  name: string;
  status: string;
  detail?: string | null;
};

export type ReadyResponse = {
  status: ReadyStatus;
  providers: ProviderReadiness[];
  reason?: string | null;
  checked_at?: string | null;
};

export type OAuthClient = {
  client_id: string;
  name: string;
  description: string;
  scopes: string;
  is_active: boolean;
  created_at: string;
};

export type Provider = {
  id: string;
  type_id: string;
  name: string;
  enabled: boolean;
  status: OrbitStatus;
  status_detail?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  last_checked_at?: string | null;
  last_sync_at?: string | null;
  config_schema_version?: string | null;
  config_fingerprint?: string | null;
  config: Record<string, unknown>;
  syncs?: ProviderSyncSummary[];
};

export type ProviderSyncSummary = {
  id: string;
  name: string;
  role?: string | null;
  direction?: string | null;
  enabled: boolean;
  last_run_status?: string | null;
  last_run_at?: string | null;
};

export type ProviderCreatePayload = {
  type_id: string;
  name: string;
  config?: Record<string, unknown>;
  enabled?: boolean;
};

export type ProviderTypeDescriptor = {
  id: string;
  label: string;
  description?: string | null;
  config_schema: Record<string, unknown>;
  created_at?: string | null;
  updated_at?: string | null;
  adapter_locator?: string | null;
  adapter_version?: string | null;
  sdk_min?: string | null;
  sdk_max?: string | null;
  capabilities?: string[] | null;
  config_schema_hash?: string | null;
};

export type ProviderUpdatePayload = {
  name?: string;
  enabled?: boolean;
  config?: Record<string, unknown>;
};

export type ApiError = {
  status: number;
  message: string;
};

export type TokenResponse = {
  access_token: string;
  token_type: string;
  expires_in: number;
  scope: string;
  refresh_token?: string;
  subject?: string;
  username?: string;
};

export type SyncEndpointSummary = {
  provider_id: string;
  provider_name: string;
  provider_type: string;
  provider_type_label?: string | null;
  role: string;
  status?: OrbitStatus | null;
  status_detail?: string | null;
  enabled: boolean;
};

export type SyncRunMetrics = {
  events_processed: number;
  events_created: number;
  events_updated: number;
  events_deleted: number;
  errors: number;
};

export type SyncRunSummary = {
  id: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  source_provider_id?: string | null;
  target_provider_id?: string | null;
  stats: SyncRunMetrics;
  error?: string | null;
  direction?: string | null;
};

export type SyncConfig = {
  id: string;
  name: string;
  direction: "bidirectional" | "one_way";
  interval_seconds: number;
  enabled: boolean;
  status: OrbitStatus;
  last_synced_at: string | null;
  notes?: string | null;
  window_days_back: number;
  window_days_forward: number;
  /** @deprecated prefer window_days_back */
  window_days_past?: number;
  /** @deprecated prefer window_days_forward */
  window_days_future?: number;
  endpoints: SyncEndpointSummary[];
  runs: SyncRunSummary[];
  events?: SyncEventSummary[];
};

export type SyncHistoryItem = {
  id: string;
  sync_id?: string | null;
  direction: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  source_provider_id?: string | null;
  target_provider_id?: string | null;
  stats: SyncRunMetrics;
  error_message?: string | null;
};

export type SyncEventSummary = {
  id: string;
  title: string;
  start: string | null;
  start_at?: string | null;
  provider_badges: string[];
  source_provider_id?: string | null;
  target_provider_id?: string | null;
  direction?: string | null;
  occurred_at?: string | null;
};

export type SyncEventsResponse = {
  events: SyncEventSummary[];
};

export type SyncEndpointPayload = {
  provider_id: string;
  role: string;
};

export type SyncCreatePayload = {
  name: string;
  direction?: string;
  interval_seconds?: number;
  enabled?: boolean;
  endpoints: SyncEndpointPayload[];
  window_days_back?: number;
  window_days_forward?: number;
};

export type SyncUpdatePayload = {
  name?: string;
  direction?: string;
  interval_seconds?: number;
  enabled?: boolean;
  endpoints?: SyncEndpointPayload[];
  window_days_back?: number;
  window_days_forward?: number;
};

export type ProviderEventRecord = {
  orbit_event_id: string | null;
  provider_event_id: string;
  provider_id: string;
  provider_name: string;
  title: string;
  start: string | null;
  end: string | null;
  last_updated: string | null;
  provider_last_seen: string | null;
  tombstoned: boolean;
  categories?: string[] | null;
};

export type ProviderEventsResponse = {
  events: ProviderEventRecord[];
};
