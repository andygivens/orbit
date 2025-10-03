export type ProblemDocument = {
  type: string;
  title: string;
  status: number;
  detail?: string;
  instance?: string;
  extensions?: Record<string, unknown> & { code?: string };
};

export type ProviderTypeV1 = {
  id: string;
  label: string;
  description?: string | null;
  config_schema: Record<string, unknown>;
  created_at?: string | null;
  adapter_version?: string | null;
  config_schema_hash?: string | null;
};

export type ProviderV1 = {
  id: string;
  type_id: string;
  name: string;
  enabled: boolean;
  status: string;
  status_detail?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  last_checked_at?: string | null;
  config: Record<string, unknown>;
  config_schema_version?: string | null;
  config_fingerprint?: string | null;
};

export type ProviderEventV1 = {
  id: string;
  provider_event_id?: string | null;
  title: string;
  start_at?: string | null;
  end_at?: string | null;
  location?: string | null;
  notes?: string | null;
  tombstoned: boolean;
  created_at?: string | null;
  updated_at?: string | null;
};

export type OperationStatus = "queued" | "running" | "succeeded" | "failed" | "error";

export type OperationRecordV1 = {
  id: string;
  kind: string;
  status: OperationStatus;
  resource_type?: string | null;
  resource_id?: string | null;
  payload: Record<string, unknown>;
  result: Record<string, unknown>;
  error: Record<string, unknown>;
  created_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
};

export type OperationListResponseV1 = {
  operations: OperationRecordV1[];
  next_cursor?: string | null;
};

export type TroubleshootMappingSegmentV1 = {
  mapping_id: string;
  provider_id: string;
  provider_type?: string | null;
  provider_uid: string;
  provider_label?: string | null;
  role?: string | null;
  first_seen_at?: string | null;
  last_seen_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  tombstoned?: boolean | null;
  extra?: Record<string, unknown> | null;
};

export type TroubleshootMappingV1 = {
  orbit_event_id: string;
  title: string;
  start_at: string;
  end_at?: string | null;
  sync_id?: string | null;
  segments: TroubleshootMappingSegmentV1[];
  last_merged_at?: string | null;
  notes?: string | null;
};

export type TroubleshootMappingsResponseV1 = {
  mappings: TroubleshootMappingV1[];
  next_cursor?: string | null;
};

export type TroubleshootProviderEventV1 = {
  orbit_event_id?: string | null;
  provider_event_id?: string | null;
  provider_id: string;
  provider_name?: string | null;
  title?: string | null;
  start_at?: string | null;
  end_at?: string | null;
  updated_at?: string | null;
  provider_last_seen_at?: string | null;
  tombstoned?: boolean | null;
};

export type TroubleshootProviderEventsResponseV1 = {
  events: TroubleshootProviderEventV1[];
  orphans?: TroubleshootProviderEventV1[];
  next_cursor?: string | null;
};

export type TroubleshootProviderConfirmationResponseV1 = {
  status: "confirmed";
  provider_id: string;
  provider_uid: string;
  mapping_id?: string | null;
  last_seen_at?: string | null;
  operation_id?: string | null;
};

export type TroubleshootRecreateResponseV1 = {
  status: "recreated";
  provider_id: string;
  provider_uid: string;
  mapping_id: string;
  created_at?: string | null;
  last_seen_at?: string | null;
  operation_id?: string | null;
};

export type SyncEndpointV1 = {
  provider_id: string;
  provider_name?: string | null;
  provider_type?: string | null;
  provider_type_label?: string | null;
  role: string;
  status: string;
  status_detail?: string | null;
};

export type SyncRunMetricsV1 = {
  events_processed: number;
  events_created: number;
  events_updated: number;
  events_deleted: number;
  errors: number;
};

export type SyncRunSummaryV1 = {
  id: string;
  status: string;
  started_at?: string | null;
  completed_at?: string | null;
  source_provider_id?: string | null;
  target_provider_id?: string | null;
  stats: SyncRunMetricsV1;
  error?: string | null;
  direction?: string | null;
};

export type SyncRunResponseV1 = {
  id: string;
  sync_id: string;
  status: string;
  direction: string;
  started_at: string;
  finished_at?: string | null;
  stats: SyncRunMetricsV1;
  error?: string | null;
  source_provider_id?: string | null;
  target_provider_id?: string | null;
  details: Record<string, unknown>;
};

export type SyncRunAcceptedV1 = {
  run_id: string;
  status: string;
};

export type SyncRunAggregateSummaryV1 = {
  total_runs: number;
  status_counts: Record<string, number>;
  direction_counts: Record<string, number>;
  mode_counts: Record<string, number>;
  stats_totals: SyncRunMetricsV1;
  first_started_at?: string | null;
  last_started_at?: string | null;
};

export type SyncResponseV1 = {
  id: string;
  name: string;
  direction: string;
  interval_seconds: number;
  window_days_back: number;
  window_days_forward: number;
  enabled: boolean;
  status: string;
  last_synced_at?: string | null;
  notes?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  endpoints: SyncEndpointV1[];
  runs: SyncRunSummaryV1[];
};

export type ConfigResponseV1 = {
  poll_interval_sec: number;
  sync_window_days_back: number;
  sync_window_days_forward: number;
  apple_username?: string | null;
  apple_calendar_name?: string | null;
  skylight_email?: string | null;
  skylight_category_name?: string | null;
  skylight_base_url?: string | null;
};

export type OAuthClientV1 = {
  client_id: string;
  name: string;
  description?: string | null;
  scopes: string;
  is_active: boolean;
  created_at: string;
};

export type TokenResponseV1 = {
  access_token: string;
  token_type: string;
  expires_in: number;
  scope: string;
  refresh_token?: string;
  subject?: string;
  username?: string;
};
