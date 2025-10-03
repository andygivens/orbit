import { useCallback, useEffect, useMemo, useState } from "react";
import type { ChangeEvent, FormEvent } from "react";
import { AlertCircle, Loader2 } from "lucide-react";

import { ProviderCard } from "../components/providers/provider-card";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import { Modal } from "../components/ui/modal";
import { Switch } from "../components/ui/switch";
import { useApi } from "../lib/api-context";
import { OrbitApiError } from "../lib/api";
import { formatProviderName } from "../lib/providers";
import type { Provider, ProviderCreatePayload, ProviderTypeDescriptor } from "../types/api";

const APPLE_PROVIDER_TYPE_ID = "apple_caldav";

export function ProvidersPage() {
  const { auth, client } = useApi();
  const [providers, setProviders] = useState<Provider[]>([]);
  const [types, setTypes] = useState<ProviderTypeDescriptor[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isAddOpen, setAddOpen] = useState(false);
  const [editingProvider, setEditingProvider] = useState<Provider | null>(null);
  const [refreshTick, setRefreshTick] = useState(0);

  useEffect(() => {
    if (auth.status !== "authenticated") {
      return;
    }

    let cancelled = false;
    setIsLoading(true);
    setError(null);

    const load = async () => {
      try {
        const [providerList, providerTypes] = await Promise.all([
          client.providers(),
          client.providerTypes()
        ]);
        if (cancelled) {
          return;
        }
        setProviders(providerList);
        setTypes(providerTypes);
      } catch (err) {
        if (cancelled) {
          return;
        }
        const message = err instanceof Error ? err.message : "Failed to load providers";
        setError(message);
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    };

    void load();

    return () => {
      cancelled = true;
    };
  }, [auth.status, client, refreshTick]);

  const typeLookup = useMemo(() => {
    return types.reduce<Record<string, ProviderTypeDescriptor>>((acc, item) => {
      acc[item.id] = item;
      return acc;
    }, {});
  }, [types]);

  const sortedProviders = useMemo(() => {
    return [...providers].sort((a, b) => {
      const left = (formatProviderName(a.name) || "Untitled provider").toLowerCase();
      const right = (formatProviderName(b.name) || "Untitled provider").toLowerCase();
      return left.localeCompare(right);
    });
  }, [providers]);

  const handleProviderCreated = (provider: Provider) => {
    setProviders((prev) => {
      const exists = prev.some((item) => item.id === provider.id);
      if (exists) {
        return prev.map((item) => (item.id === provider.id ? provider : item));
      }
      return [...prev, provider];
    });
    setAddOpen(false);
  };

  const handleProviderUpdated = (provider: Provider) => {
    setProviders((prev) => prev.map((item) => (item.id === provider.id ? { ...item, ...provider } : item)));
  };

  const handleEditProvider = (provider: Provider) => {
    setEditingProvider(provider);
  };

  const handleEditClosed = () => {
    setEditingProvider(null);
  };

  const handleEditSaved = () => {
    setEditingProvider(null);
    setRefreshTick((tick) => tick + 1);
  };

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <p className="max-w-2xl text-sm text-[var(--color-text-soft)]">
          Monitor connection health, sync participation, and recent activity across configured providers.
        </p>
        <Button variant="primary" size="sm" onClick={() => setAddOpen(true)}>
          + New
        </Button>
      </header>

      {isLoading ? (
        <Card className="shadow-elev-2">
          <CardContent className="flex items-center justify-center gap-3 py-16 text-sm text-[var(--color-text-soft)]">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading providers…
          </CardContent>
        </Card>
      ) : error ? (
        <Card className="shadow-elev-2">
          <CardContent className="flex items-center gap-2 border border-[var(--color-danger)]/60 bg-[var(--color-danger)]/10 px-4 py-3 text-sm text-[var(--color-danger)]">
            <AlertCircle className="h-4 w-4" /> {error}
          </CardContent>
        </Card>
      ) : sortedProviders.length === 0 ? (
        <Card className="shadow-elev-2">
          <CardContent className="flex flex-col items-center gap-3 py-16 text-center text-sm text-[var(--color-text-soft)]">
            <span>No providers configured yet. Add one to start pairing calendars.</span>
            <Button variant="primary" size="sm" onClick={() => setAddOpen(true)}>
              + New
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="flex flex-col gap-4">
          {sortedProviders.map((provider) => (
            <ProviderCard
              key={provider.id}
              provider={provider}
              onEdit={handleEditProvider}
              onProviderUpdated={handleProviderUpdated}
            />
          ))}
        </div>
      )}

      {isAddOpen && (
        <AddProviderModal
          open={isAddOpen}
          types={types}
          onClose={() => setAddOpen(false)}
          onCreated={(provider: Provider) => {
            handleProviderCreated(provider);
            setRefreshTick((tick) => tick + 1);
          }}
        />
      )}

      {editingProvider && (
        <EditProviderModal
          open
          provider={editingProvider}
          providerType={typeLookup[editingProvider.type_id ?? ""]}
          onClose={handleEditClosed}
          onUpdated={handleEditSaved}
        />
      )}
    </div>
  );
}

type AddProviderModalProps = {
  open: boolean;
  types: ProviderTypeDescriptor[];
  onClose: () => void;
  onCreated: (provider: Provider) => void;
};

function AddProviderModal({ open, types, onClose, onCreated }: AddProviderModalProps) {
  const { client } = useApi();
  const [selectedTypeId, setSelectedTypeId] = useState<string>(() => types[0]?.id ?? "");
  const [name, setName] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [configValues, setConfigValues] = useState<Record<string, string | boolean>>({});
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [isSubmitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) {
      return;
    }
    if (!selectedTypeId && types.length > 0) {
      setSelectedTypeId(types[0].id);
    } else if (selectedTypeId && !types.some((type) => type.id === selectedTypeId)) {
      setSelectedTypeId(types[0]?.id ?? "");
    }
  }, [open, selectedTypeId, types]);

  useEffect(() => {
    if (open) {
      return;
    }
    setName("");
    setEnabled(true);
    setConfigValues({});
    setSubmitError(null);
    setSelectedTypeId(types[0]?.id ?? "");
  }, [open, types]);

  const selectedType = useMemo(
    () => (open ? types.find((type) => type.id === selectedTypeId) ?? null : null),
    [open, selectedTypeId, types]
  );

  const derivedFields = useMemo(
    () => deriveFieldsFromSchema(selectedType?.config_schema),
    [selectedType]
  );
  const fields = useMemo(
    () => filterProviderFields(derivedFields, selectedType?.id),
    [derivedFields, selectedType?.id]
  );

  const isAppleProvider = selectedType?.id === APPLE_PROVIDER_TYPE_ID;

  useEffect(() => {
    if (!open) {
      return;
    }
    const defaults: Record<string, string | boolean> = {};
    fields.forEach((field) => {
      defaults[field.name] = field.type === "boolean" ? false : "";
    });
    setConfigValues(defaults);
    setSubmitError(null);
  }, [fields, open]);

  const handleTypeChange = (event: ChangeEvent<HTMLSelectElement>) => {
    setSelectedTypeId(event.target.value);
    setSubmitError(null);
  };

  const handleFieldChange = (field: ProviderConfigField, value: string | boolean) => {
    setConfigValues((prev) => ({
      ...prev,
      [field.name]: value,
    }));
    setSubmitError(null);
  };

  const trimmedName = name.trim();
  const missingRequiredField = fields.some((field) => {
    if (field.type === "boolean") {
      return configValues[field.name] === undefined;
    }
    if (field.optional) {
      return false;
    }
    const raw = configValues[field.name];
    return typeof raw !== "string" || raw.trim().length === 0;
  });

  const disableSubmit =
    isSubmitting || !selectedType || trimmedName.length === 0 || missingRequiredField;

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!open || !selectedType || disableSubmit) {
      return;
    }

    setSubmitting(true);
    setSubmitError(null);

    try {
      const config: Record<string, unknown> = {};
      fields.forEach((field) => {
        const value = configValues[field.name];
        if (field.type === "boolean") {
          if (typeof value === "boolean") {
            config[field.name] = value;
          }
          return;
        }
        if (typeof value !== "string") {
          return;
        }
        const trimmed = value.trim();
        if (trimmed.length === 0) {
          return;
        }
        const normalizedType = field.type.toLowerCase();
        if (normalizedType === "number" || normalizedType === "integer") {
          const numeric = Number(trimmed);
          if (!Number.isNaN(numeric)) {
            config[field.name] = normalizedType === "integer" ? Math.trunc(numeric) : numeric;
            return;
          }
        }
        config[field.name] = trimmed;
      });
      const payload: ProviderCreatePayload = {
        type_id: selectedType.id,
        name: trimmedName,
        enabled,
      };
      if (Object.keys(config).length > 0) {
        payload.config = config;
      }

      const provider = await client.createProvider(payload);
      onCreated(provider);
    } catch (error) {
      if (error instanceof OrbitApiError) {
        setSubmitError(error.message);
      } else if (error instanceof Error) {
        setSubmitError(error.message);
      } else {
        setSubmitError("Failed to create provider");
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
      <Modal
        open={open}
        onClose={onClose}
        title="Add provider"
        footer={
          <div className="flex items-center justify-end gap-3">
            <Button type="button" variant="ghost" onClick={onClose} disabled={isSubmitting}>
              Cancel
            </Button>
            <Button
              type="submit"
              form="add-provider-form"
              disabled={disableSubmit}
              icon={isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : undefined}
            >
              {isSubmitting ? "Creating" : "Create provider"}
            </Button>
          </div>
        }
      >
        {types.length === 0 ? (
          <div className="flex items-center justify-center gap-2 py-10 text-sm text-[var(--color-text-soft)]">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading provider types…
          </div>
        ) : (
          <form id="add-provider-form" onSubmit={handleSubmit} className="space-y-6 text-sm text-[var(--color-text-soft)]">
            {submitError && (
              <div className="rounded-[var(--radius-2)] border border-[var(--color-danger)]/50 bg-[var(--color-danger)]/10 px-3 py-2 text-sm text-[var(--color-danger)]">
                {submitError}
              </div>
            )}

            <div className="space-y-2">
              <label className="text-xs font-semibold uppercase tracking-wide text-[var(--color-text-soft)]">
                Provider type
              </label>
              <select
                value={selectedTypeId}
                onChange={handleTypeChange}
                className="w-full rounded-[var(--radius-2)] border border-border-subtle bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-text-strong)] shadow-sm focus:border-[var(--accent-600)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]/60"
              >
                {types.map((providerType) => (
                  <option key={providerType.id} value={providerType.id}>
                    {providerType.label ?? providerType.id}
                  </option>
                ))}
              </select>
              {selectedType && (
                <div className="orbit-panel space-y-2 text-xs text-[var(--color-text-soft)]">
                  {selectedType.description && <p>{selectedType.description}</p>}
                  <ProviderMetadata providerType={selectedType} />
                </div>
              )}
            </div>

            <div className="space-y-2">
              <label className="text-xs font-semibold uppercase tracking-wide text-[var(--color-text-soft)]" htmlFor="provider-name">
                Display name
              </label>
              <input
                id="provider-name"
                type="text"
                value={name}
                onChange={(event) => {
                  setName(event.target.value);
                  setSubmitError(null);
                }}
                placeholder="My CalDAV account"
                className="w-full rounded-[var(--radius-2)] border border-border-subtle bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-text-strong)] shadow-sm focus:border-[var(--accent-600)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]/60"
                required
              />
            </div>

            <Switch
              checked={enabled}
              onCheckedChange={setEnabled}
              size="sm"
              label="Enable provider immediately"
            />

            <div className="space-y-4">
              <h3 className="text-sm font-semibold text-[var(--color-text-strong)]">Configuration</h3>
              {fields.length === 0 ? (
                <p className="text-xs text-[var(--color-text-soft)]">
                  Selected provider does not require additional configuration.
                </p>
              ) : (
                fields.map((field) => {
                  const normalizedType = field.type.toLowerCase();
                  const value = configValues[field.name];
                  const id = `provider-config-${field.name}`;
                  return (
                    <div key={field.name} className="space-y-2">
                      <label className="text-xs font-semibold uppercase tracking-wide text-[var(--color-text-soft)]" htmlFor={id}>
                        {field.label}
                      </label>
                      {normalizedType === "boolean" ? (
                        <select
                          id={id}
                          value={typeof value === "boolean" ? String(value) : ""}
                          onChange={(event) => handleFieldChange(field, event.target.value === "true")}
                          className="w-full rounded-[var(--radius-2)] border border-border-subtle bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-text-strong)] shadow-sm focus:border-[var(--accent-600)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]/60"
                        >
                          <option value="true">True</option>
                          <option value="false">False</option>
                        </select>
                      ) : field.secret ? (
                        <input
                          id={id}
                          type="password"
                          value={typeof value === "string" ? value : ""}
                          onChange={(event) => handleFieldChange(field, event.target.value)}
                          className="w-full rounded-[var(--radius-2)] border border-border-subtle bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-text-strong)] shadow-sm focus:border-[var(--accent-600)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]/60"
                        />
                      ) : (
                        <input
                          id={id}
                          type={normalizedType === "number" || normalizedType === "integer" ? "number" : "text"}
                          value={typeof value === "string" ? value : ""}
                          onChange={(event) => handleFieldChange(field, event.target.value)}
                          className="w-full rounded-[var(--radius-2)] border border-border-subtle bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-text-strong)] shadow-sm focus:border-[var(--accent-600)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]/60"
                        />
                      )}
                      {isAppleProvider && field.name === "app_password" && (
                        <p className="text-xs text-[var(--color-text-soft)]">
                          Generate an app-specific password for your CalDAV account. Visit appleid.apple.com to create one.
                        </p>
                      )}
                    </div>
                  );
                })
              )}
            </div>
          </form>
        )}
      </Modal>
    );
}

function ProviderMetadata({ providerType }: { providerType: ProviderTypeDescriptor }) {
  const { adapter_version, sdk_min, sdk_max, capabilities } = providerType;

  const versionParts: string[] = [];
  if (adapter_version) {
    versionParts.push(`Adapter v${adapter_version}`);
  }
  if (sdk_min || sdk_max) {
    if (sdk_min && sdk_max) {
      versionParts.push(`SDK ${sdk_min} - ${sdk_max}`);
    } else if (sdk_min) {
      versionParts.push(`SDK ≥ ${sdk_min}`);
    } else if (sdk_max) {
      versionParts.push(`SDK ≤ ${sdk_max}`);
    }
  }

  return (
    <div className="space-y-1">
      {versionParts.length > 0 && (
        <p className="text-[11px] uppercase tracking-wide text-[var(--color-text-soft)]">
          {versionParts.join(" • ")}
        </p>
      )}
      {capabilities && capabilities.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {capabilities.map((capability) => (
            <Badge key={capability} variant="outline" className="text-[10px] font-medium lowercase tracking-wide">
              {capability.replace(/_/g, " ")}
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}

type ProviderConfigField = {
  name: string;
  label: string;
  type: string;
  secret: boolean;
  optional: boolean;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function humanizeFieldLabel(name: string, fallback?: string) {
  if (fallback && fallback.trim().length > 0) {
    return fallback;
  }
  const withSpaces = name
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/[_-]+/g, " ");
  return withSpaces
    .split(" ")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function normalizeFieldType(rawType: unknown): string {
  if (typeof rawType === "string") {
    return rawType;
  }
  if (Array.isArray(rawType)) {
    const primary = rawType.find((value) => typeof value === "string" && value !== "null");
    return typeof primary === "string" ? primary : "string";
  }
  return "string";
}

function deriveFieldsFromSchema(schema?: Record<string, unknown>): ProviderConfigField[] {
  if (!schema) {
    return [];
  }

  const raw = schema as Record<string, unknown>;
  const fieldList = Array.isArray(raw.fields) ? raw.fields : [];
  if (fieldList.length > 0) {
    return fieldList
      .map((item) => {
        if (!isRecord(item)) {
          return null;
        }
        const nameValue = item.name;
        if (typeof nameValue !== "string") {
          return null;
        }
        const requiredFlag = item.required;
        const optionalFlag = item.optional;
        const required = requiredFlag === true
          ? true
          : requiredFlag === false
            ? false
            : optionalFlag === true
              ? false
              : true;
        const optional = !required;
        return {
          name: nameValue,
          label: humanizeFieldLabel(nameValue, typeof item.label === "string" ? item.label : undefined),
          type: normalizeFieldType(item.type),
          secret: Boolean(item.secret || item.type === "secret"),
          optional
        };
      })
      .filter((field): field is ProviderConfigField => field !== null);
  }

  const properties = raw.properties;
  if (isRecord(properties)) {
    const required = new Set(
      Array.isArray(raw.required)
        ? raw.required.filter((value: unknown): value is string => typeof value === "string")
        : []
    );

    return Object.entries(properties)
      .filter((entry): entry is [string, Record<string, unknown>] => {
        const [name, definition] = entry;
        return typeof name === "string" && isRecord(definition);
      })
      .map(([name, definition]) => {
        const secret = Boolean(
          definition.secret === true ||
            definition.writeOnly === true ||
            definition["x-secret"] === true ||
            definition["x_secret"] === true
        );
        const optional = !required.has(name);
        return {
          name,
          label: humanizeFieldLabel(name, typeof definition.title === "string" ? definition.title : undefined),
          type: normalizeFieldType(definition.type),
          secret,
          optional
        };
      });
  }

  return [];
}

function filterProviderFields(fields: ProviderConfigField[], providerTypeId?: string | null): ProviderConfigField[] {
  if (providerTypeId === APPLE_PROVIDER_TYPE_ID) {
    return fields.filter((field) => field.name !== "caldav_url");
  }
  return fields;
}

type EditProviderModalProps = {
  open: boolean;
  provider: Provider;
  providerType?: ProviderTypeDescriptor;
  onClose: () => void;
  onUpdated: () => void;
};

function EditProviderModal({ open, provider, providerType, onClose, onUpdated }: EditProviderModalProps) {
  const { client } = useApi();
  const [name, setName] = useState(provider.name || "");
  const [enabled, setEnabled] = useState(provider.enabled);
  const [error, setError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    setName(provider.name || "");
    setEnabled(provider.enabled);
  }, [provider]);

  const schema = providerType?.config_schema as Record<string, unknown> | undefined;
  const derivedFields = useMemo<ProviderConfigField[]>(() => deriveFieldsFromSchema(schema), [schema]);
  const fields = useMemo<ProviderConfigField[]>(
    () => filterProviderFields(derivedFields, providerType?.id),
    [derivedFields, providerType?.id]
  );

  const isAppleProvider = providerType?.id === APPLE_PROVIDER_TYPE_ID;

  const extractValues = useCallback(
    () => {
      const currentConfig = provider.config as Record<string, unknown>;
      const values: Record<string, string> = {};
      fields.forEach((field) => {
        const value = currentConfig[field.name];
        if (typeof value === "boolean") {
          values[field.name] = value ? "true" : "false";
        } else if (value === null || value === undefined) {
          values[field.name] = "";
        } else {
          values[field.name] = String(value);
        }
      });
      return values;
    },
    [fields, provider.config]
  );

  const [formValues, setFormValues] = useState<Record<string, string>>(extractValues);

  useEffect(() => {
    setFormValues(extractValues);
  }, [extractValues]);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setIsSaving(true);
    setError(null);

    try {
      const fingerprint = provider.config_fingerprint ?? provider.updated_at ?? null;
      const ifMatch = fingerprint ? `W/"${fingerprint}"` : undefined;
      const payload: Record<string, unknown> = {
        name: name.trim(),
        enabled,
      };

      if (fields.length > 0) {
        payload.config = buildConfigPayload(fields, formValues);
      }

      await client.updateProvider(provider.id, payload, { ifMatch });
      onUpdated();
    } catch (err) {
      const message = err instanceof OrbitApiError ? err.message : err instanceof Error ? err.message : "Failed to update provider";
      setError(message);
    } finally {
      setIsSaving(false);
    }
  };

  const onChangeField = (fieldName: string, value: string) => {
    setFormValues((prev) => ({
      ...prev,
      [fieldName]: value,
    }));
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Edit provider"
      footer={
        <div className="flex items-center justify-end gap-3">
          <Button type="button" variant="ghost" onClick={onClose} disabled={isSaving}>
            Cancel
          </Button>
          <Button
            type="submit"
            form="edit-provider-form"
            disabled={isSaving}
            icon={isSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : undefined}
          >
            Save changes
          </Button>
        </div>
      }
    >
      <form id="edit-provider-form" onSubmit={handleSubmit} className="space-y-5 text-sm text-[var(--color-text-soft)]">
        {error && (
          <div className="rounded-[var(--radius-2)] border border-[var(--color-danger)]/60 bg-[var(--color-danger)]/10 px-3 py-2 text-sm text-[var(--color-danger)]">
            {error}
          </div>
        )}

        <div className="space-y-2">
          <label className="text-xs font-semibold uppercase tracking-wide text-[var(--color-text-soft)]">
            Display name
          </label>
          <input
            className="w-full rounded-[var(--radius-2)] border border-border-subtle bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-text-strong)] shadow-sm focus:border-[var(--accent-600)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]/60"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Marketing CalDAV"
          />
        </div>

        <Switch
          checked={enabled}
          onCheckedChange={setEnabled}
          size="sm"
          label="Enabled"
        />

        <div className="space-y-4">
          {fields.length === 0 ? (
            <p className="text-xs text-[var(--color-text-soft)]">
              This provider type does not expose editable configuration fields.
            </p>
          ) : (
            fields.map((field) => {
              const value = formValues[field.name] ?? "";
              const inputType = field.secret
                ? "password"
                : field.type === "integer" || field.type === "number"
                  ? "number"
                  : "text";
              const label = isAppleProvider && field.name === "app_password"
                ? "App specific password"
                : field.label;
              return (
                <div key={field.name} className="space-y-2">
                  <div className="flex items-center justify-between gap-2">
                    <label className="text-xs font-semibold uppercase tracking-wide text-[var(--color-text-soft)]">
                      {label}
                    </label>
                    {!field.optional && (
                      <span className="text-[10px] font-semibold uppercase tracking-wide text-[var(--accent-600)]">
                        Required
                      </span>
                    )}
                  </div>
                  {field.type === "boolean" ? (
                    <select
                      className="w-full rounded-[var(--radius-2)] border border-border-subtle bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-text-strong)] shadow-sm focus:border-[var(--accent-600)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]/60"
                      value={value || "false"}
                      onChange={(event) => onChangeField(field.name, event.target.value)}
                    >
                      <option value="true">True</option>
                      <option value="false">False</option>
                    </select>
                  ) : (
                    <input
                      className="w-full rounded-[var(--radius-2)] border border-border-subtle bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-text-strong)] shadow-sm focus:border-[var(--accent-600)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]/60"
                      type={inputType}
                      value={value}
                      placeholder={field.secret ? "Enter secret" : undefined}
                      onChange={(event) => onChangeField(field.name, event.target.value)}
                    />
                  )}
                  {field.secret && (
                    <p className="text-[11px] text-[var(--color-text-muted)]">
                      Stored securely on the server; not displayed after saving.
                    </p>
                  )}
                  {isAppleProvider && field.name === "app_password" && (
                    <p className="text-[11px] text-[var(--color-text-muted)]">
                      Generate an app-specific password at appleid.apple.com under Sign-In and Security &gt; App-Specific Passwords.
                    </p>
                  )}
                </div>
              );
            })
          )}
        </div>
      </form>
    </Modal>
  );
}

function buildConfigPayload(fields: ProviderConfigField[], values: Record<string, string>) {
  const payload: Record<string, unknown> = {};
  fields.forEach((field) => {
    const rawValue = values[field.name] ?? "";
    if (!rawValue && field.optional) {
      payload[field.name] = "";
      return;
    }
    switch (field.type) {
      case "integer":
        payload[field.name] = rawValue === "" ? "" : Number.parseInt(rawValue, 10);
        break;
      case "number":
        payload[field.name] = rawValue === "" ? "" : Number(rawValue);
        break;
      case "boolean":
        payload[field.name] = rawValue === "true";
        break;
      default:
        payload[field.name] = rawValue;
        break;
    }
  });
  return payload;
}

export default ProvidersPage;
