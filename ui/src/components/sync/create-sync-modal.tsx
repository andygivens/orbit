import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";

import { Modal } from "../ui/modal";
import { Button } from "../ui/button";
import { useApi } from "../../lib/api-context";
import { OrbitApiError } from "../../lib/api";
import type { Provider, SyncConfig, SyncCreatePayload } from "../../types/api";

export type CreateSyncModalProps = {
  open: boolean;
  providers: Provider[];
  isLoadingProviders: boolean;
  providersError: string | null;
  onClose: () => void;
  onCreated: (sync: SyncConfig) => Promise<void> | void;
};

export function CreateSyncModal({
  open,
  providers,
  isLoadingProviders,
  providersError,
  onClose,
  onCreated,
}: CreateSyncModalProps) {
  const { client } = useApi();
  const [name, setName] = useState("");
  const [direction, setDirection] = useState<"bidirectional" | "one_way">("bidirectional");
  const [primaryProviderId, setPrimaryProviderId] = useState("");
  const [secondaryProviderId, setSecondaryProviderId] = useState("");
  const [intervalMinutes, setIntervalMinutes] = useState(5);
  const [windowPastDays, setWindowPastDays] = useState(3);
  const [windowFutureDays, setWindowFutureDays] = useState(7);
  const [enabled, setEnabled] = useState(true);
  const [formError, setFormError] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const providerOptions = useMemo(() => {
    return [...providers].sort((a, b) => a.name.localeCompare(b.name));
  }, [providers]);

  useEffect(() => {
    if (!open) {
      return;
    }

    const enabledProviders = providerOptions.filter((provider) => provider.enabled);
    const first = enabledProviders[0] ?? providerOptions[0];
    const second = enabledProviders.find((provider) => provider.id !== first?.id) ?? providerOptions.find((provider) => provider.id !== first?.id);

    setName("");
    setDirection("bidirectional");
    setIntervalMinutes(5);
    setWindowPastDays(3);
    setWindowFutureDays(7);
    setEnabled(true);
    setFormError(null);
    setSubmitError(null);
    setPrimaryProviderId(first?.id ?? "");
    setSecondaryProviderId(second?.id ?? "");
  }, [open, providerOptions]);

  const hasEnoughProviders = providerOptions.length >= 2;
  const disabled = isSubmitting || isLoadingProviders || !hasEnoughProviders;

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setFormError(null);
    setSubmitError(null);

    const trimmedName = name.trim();
    if (!trimmedName) {
      setFormError("Enter a sync name.");
      return;
    }
    if (!primaryProviderId || !secondaryProviderId) {
      setFormError("Select both source and target providers.");
      return;
    }
    if (primaryProviderId === secondaryProviderId) {
      setFormError("Source and target providers must be different.");
      return;
    }

    const intervalSeconds = Math.max(60, intervalMinutes * 60);
    const pastDays = Math.max(0, windowPastDays);
    const futureDays = Math.max(0, windowFutureDays);

    const payload: SyncCreatePayload = {
      name: trimmedName,
      direction,
      interval_seconds: intervalSeconds,
      enabled,
      endpoints: [
        { provider_id: primaryProviderId, role: "primary" },
        { provider_id: secondaryProviderId, role: "secondary" },
      ],
      window_days_back: pastDays,
      window_days_forward: futureDays,
    };

    setIsSubmitting(true);
    try {
      const sync = await client.createSync(payload);
      await onCreated(sync);
    } catch (error) {
      if (error instanceof OrbitApiError) {
        setSubmitError(error.message);
      } else if (error instanceof Error) {
        setSubmitError(error.message);
      } else {
        setSubmitError("Failed to create sync");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Modal
      open={open}
      title="Create sync"
      onClose={isSubmitting ? () => {} : onClose}
      size="md"
      footer={
        <div className="flex w-full items-center justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button variant="primary" size="sm" type="submit" form="create-sync-form" disabled={disabled}>
            {isSubmitting ? "Creating" : "Create sync"}
          </Button>
        </div>
      }
    >
      <form id="create-sync-form" className="space-y-4" onSubmit={handleSubmit}>
        {providersError && (
          <div className="rounded-lg border border-[var(--color-danger)]/60 bg-[var(--color-danger)]/10 px-3 py-2 text-xs text-[var(--color-danger)]">
            {providersError}
          </div>
        )}
        {!hasEnoughProviders && (
          <div className="rounded-lg border border-[var(--color-warning)]/50 bg-[var(--color-warning)]/12 px-3 py-2 text-xs text-[var(--color-warning)]">
            At least two enabled providers are required before creating a sync.
          </div>
        )}
        <label className="flex flex-col gap-2 text-sm">
          <span className="font-medium text-[var(--color-text-strong)]">Sync name</span>
          <input
            type="text"
            value={name}
            onChange={(event) => setName(event.target.value)}
            className="rounded-lg border border-border-strong bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-text-strong)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-600)]"
            placeholder="Apple ↔ Skylight"
            disabled={isSubmitting}
            required
          />
        </label>
        <div className="grid gap-4 md:grid-cols-2">
          <label className="flex flex-col gap-2 text-sm">
            <span className="font-medium text-[var(--color-text-strong)]">Source provider</span>
            <select
              value={primaryProviderId}
              onChange={(event) => setPrimaryProviderId(event.target.value)}
              className="rounded-lg border border-border-strong bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-text-strong)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-600)]"
              disabled={disabled}
            >
              <option value="">Select provider</option>
              {providerOptions.map((provider) => (
                <option key={provider.id} value={provider.id} disabled={!provider.enabled}>
                  {provider.name}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-2 text-sm">
            <span className="font-medium text-[var(--color-text-strong)]">Target provider</span>
            <select
              value={secondaryProviderId}
              onChange={(event) => setSecondaryProviderId(event.target.value)}
              className="rounded-lg border border-border-strong bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-text-strong)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-600)]"
              disabled={disabled}
            >
              <option value="">Select provider</option>
              {providerOptions.map((provider) => (
                <option key={provider.id} value={provider.id} disabled={!provider.enabled}>
                  {provider.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        <label className="flex flex-col gap-2 text-sm">
          <span className="font-medium text-[var(--color-text-strong)]">Direction</span>
          <select
            value={direction}
            onChange={(event) => setDirection(event.target.value as "bidirectional" | "one_way")}
            className="w-full rounded-lg border border-border-strong bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-text-strong)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-600)]"
            disabled={isSubmitting}
          >
            <option value="bidirectional">Bidirectional — keep both calendars in sync</option>
            <option value="one_way">One-way — source pushes updates to target</option>
          </select>
        </label>
        <div className="grid gap-4 md:grid-cols-3">
          <label className="flex flex-col gap-2 text-sm">
            <span className="font-medium text-[var(--color-text-strong)]">Interval (minutes)</span>
            <input
              type="number"
              min={1}
              value={intervalMinutes}
              onChange={(event) => setIntervalMinutes(event.target.valueAsNumber || 1)}
              className="rounded-lg border border-border-strong bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-text-strong)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-600)]"
              disabled={isSubmitting}
            />
          </label>
          <label className="flex flex-col gap-2 text-sm">
            <span className="font-medium text-[var(--color-text-strong)]">Window - past (days)</span>
            <input
              type="number"
              min={0}
              value={windowPastDays}
              onChange={(event) => setWindowPastDays(event.target.valueAsNumber ?? 0)}
              className="rounded-lg border border-border-strong bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-text-strong)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-600)]"
              disabled={isSubmitting}
            />
          </label>
          <label className="flex flex-col gap-2 text-sm">
            <span className="font-medium text-[var(--color-text-strong)]">Window - future (days)</span>
            <input
              type="number"
              min={0}
              value={windowFutureDays}
              onChange={(event) => setWindowFutureDays(event.target.valueAsNumber ?? 0)}
              className="rounded-lg border border-border-strong bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-text-strong)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-600)]"
              disabled={isSubmitting}
            />
          </label>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(event) => setEnabled(event.target.checked)}
            disabled={isSubmitting}
          />
          <span className="text-[var(--color-text-soft)]">Enable sync immediately</span>
        </label>
        {formError && (
          <div className="rounded-lg border border-[var(--color-danger)]/60 bg-[var(--color-danger)]/10 px-3 py-2 text-xs text-[var(--color-danger)]">
            {formError}
          </div>
        )}
        {submitError && (
          <div className="rounded-lg border border-[var(--color-danger)]/60 bg-[var(--color-danger)]/10 px-3 py-2 text-xs text-[var(--color-danger)]">
            {submitError}
          </div>
        )}
        <p className="text-xs text-[var(--color-text-soft)]">
          Syncs run on the configured interval. You can trigger an immediate run from the Syncs page after creation.
        </p>
      </form>
    </Modal>
  );
}
