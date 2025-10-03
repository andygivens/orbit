import { useEffect, useMemo, useState } from "react";
import { Modal } from "../ui/modal";
import { Button } from "../ui/button";
import { useApi } from "../../lib/api-context";
import type { Provider, SyncConfig, SyncUpdatePayload } from "../../types/api";
import type { FormEvent } from "react";

export type EditSyncModalProps = {
  open: boolean;
  sync: SyncConfig;
  providers: Provider[];
  isLoadingProviders: boolean;
  providersError: string | null;
  onClose: () => void;
  onSaved: () => Promise<void>;
};

export function EditSyncModal({ open, sync, providers, isLoadingProviders, providersError, onClose, onSaved }: EditSyncModalProps) {
  const { client } = useApi();
  const primaryEndpoint = sync.endpoints.find((endpoint) => endpoint.role.toLowerCase() === "primary") ?? sync.endpoints[0];
  const secondaryEndpoint = sync.endpoints.find((endpoint) => endpoint.role.toLowerCase() === "secondary") ?? sync.endpoints[1];

  const [primaryProviderId, setPrimaryProviderId] = useState<string>(primaryEndpoint?.provider_id ?? "");
  const [secondaryProviderId, setSecondaryProviderId] = useState<string>(secondaryEndpoint?.provider_id ?? "");
  const [intervalMinutes, setIntervalMinutes] = useState<number>(Math.max(1, Math.round((sync.interval_seconds ?? 60) / 60)));
  const [windowPastDays, setWindowPastDays] = useState<number>(sync.window_days_back ?? sync.window_days_past ?? 3);
  const [windowFutureDays, setWindowFutureDays] = useState<number>(sync.window_days_forward ?? sync.window_days_future ?? 7);
  const [formError, setFormError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [enabled, setEnabled] = useState<boolean>(sync.enabled);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState("");
  const [isDeleting, setIsDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const providerOptions = useMemo(() => {
    return [...providers].sort((a, b) => a.name.localeCompare(b.name));
  }, [providers]);

  useEffect(() => {
    if (!open) {
      return;
    }
    const nextPrimary = sync.endpoints.find((endpoint) => endpoint.role.toLowerCase() === "primary") ?? sync.endpoints[0];
    const nextSecondary = sync.endpoints.find((endpoint) => endpoint.role.toLowerCase() === "secondary") ?? sync.endpoints[1];
    setPrimaryProviderId(nextPrimary?.provider_id ?? "");
    setSecondaryProviderId(nextSecondary?.provider_id ?? "");
    setIntervalMinutes(Math.max(1, Math.round((sync.interval_seconds ?? 60) / 60)));
  setWindowPastDays(sync.window_days_back ?? sync.window_days_past ?? 3);
  setWindowFutureDays(sync.window_days_forward ?? sync.window_days_future ?? 7);
    setFormError(null);
    setEnabled(sync.enabled);
    setShowDeleteConfirm(false);
    setDeleteConfirm("");
    setDeleteError(null);
  }, [open, sync]);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setFormError(null);

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

    const payload: SyncUpdatePayload = {
      interval_seconds: intervalSeconds,
  window_days_back: pastDays,
  window_days_forward: futureDays,
      endpoints: [
        { provider_id: primaryProviderId, role: "primary" },
        { provider_id: secondaryProviderId, role: "secondary" }
      ]
    };

    payload.enabled = enabled;

    setIsSubmitting(true);
    try {
      await client.updateSync(sync.id, payload);
      await onSaved();
      onClose();
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "Failed to update sync");
    } finally {
      setIsSubmitting(false);
    }
  };

  const isDisabled = isSubmitting || isLoadingProviders || isDeleting;

  const handleDelete = async () => {
    if (deleteConfirm.trim().toUpperCase() !== "DELETE") {
      setDeleteError("Type DELETE to confirm the removal.");
      return;
    }
    setDeleteError(null);
    setIsDeleting(true);
    try {
      await client.deleteSync(sync.id);
      await onSaved();
      onClose();
    } catch (error) {
      setDeleteError(error instanceof Error ? error.message : "Failed to delete sync");
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={isSubmitting || isDeleting ? () => {} : onClose}
      title={`Edit ${sync.name}`}
      size="md"
      footer={
        <div className="flex w-full items-center justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose} disabled={isSubmitting || isDeleting}>
            Cancel
          </Button>
          <Button variant="primary" size="sm" type="submit" form="edit-sync-form" disabled={isDisabled}>
            {isSubmitting ? "Saving" : "Save changes"}
          </Button>
        </div>
      }
    >
      <form id="edit-sync-form" className="space-y-4" onSubmit={handleSubmit}>
        {providersError && (
          <div className="rounded-lg border border-[var(--color-danger)]/60 bg-[var(--color-danger)]/10 px-3 py-2 text-xs text-[var(--color-danger)]">
            {providersError}
          </div>
        )}
        <div className="grid gap-4 md:grid-cols-2">
          <label className="flex flex-col gap-2 text-sm">
            <span className="font-medium text-[var(--color-text-strong)]">Source provider</span>
            <select
              value={primaryProviderId}
              onChange={(event) => setPrimaryProviderId(event.target.value)}
              className="rounded-lg border border-border-strong bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-text-strong)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-600)]"
              disabled={isDisabled}
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
              disabled={isDisabled}
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
        <div className="grid gap-4 md:grid-cols-3">
          <label className="flex flex-col gap-2 text-sm">
            <span className="font-medium text-[var(--color-text-strong)]">Interval (minutes)</span>
            <input
              type="number"
              min={1}
              value={intervalMinutes}
              onChange={(event) => setIntervalMinutes(event.target.valueAsNumber || 1)}
              className="rounded-lg border border-border-strong bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-text-strong)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-600)]"
              disabled={isDisabled}
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
              disabled={isDisabled}
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
              disabled={isDisabled}
            />
          </label>
        </div>
        <div className="rounded-lg border border-border-subtle bg-[var(--color-surface-muted)] px-3 py-3">
          <label className="flex items-center gap-3 text-sm font-medium text-[var(--color-text-strong)]">
            <input
              type="checkbox"
              className="h-4 w-4 rounded border border-border-strong bg-[var(--color-surface)]"
              checked={enabled}
              onChange={(event) => setEnabled(event.target.checked)}
              disabled={isDisabled}
            />
            <span>Sync is enabled</span>
          </label>
          <p className="mt-1 text-xs text-[var(--color-text-soft)]">
            Disable the sync to pause scheduled runs without removing its configuration.
          </p>
        </div>
        {formError && (
          <div className="rounded-lg border border-[var(--color-danger)]/60 bg-[var(--color-danger)]/10 px-3 py-2 text-xs text-[var(--color-danger)]">
            {formError}
          </div>
        )}
        <div className="space-y-3 rounded-lg border border-[var(--color-danger)]/50 bg-[var(--color-danger)]/5 px-3 py-3">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-sm font-medium text-[var(--color-danger)]">Delete sync</p>
              <p className="text-xs text-[var(--color-danger)]/80">
                Permanently delete this sync, its run history, and any scheduled jobs. This action cannot be undone.
              </p>
            </div>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="text-[var(--color-danger)] hover:text-[var(--color-danger)]"
              onClick={() => {
                setShowDeleteConfirm((current) => !current);
                setDeleteError(null);
                setDeleteConfirm("");
              }}
              disabled={isDeleting}
            >
              {showDeleteConfirm ? "Hide confirmation" : "Delete sync"}
            </Button>
          </div>
          {showDeleteConfirm && (
            <div className="space-y-3">
              <p className="text-xs text-[var(--color-danger)]">
                Type DELETE to confirm. The sync will be removed immediately and cannot be recovered.
              </p>
              <input
                type="text"
                value={deleteConfirm}
                onChange={(event) => setDeleteConfirm(event.target.value)}
                placeholder="DELETE"
                className="w-full rounded-lg border border-[var(--color-danger)]/60 bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-danger)] focus:outline-none focus:ring-2 focus:ring-[var(--color-danger)]/60"
                disabled={isDeleting}
              />
              {deleteError && (
                <p className="text-xs text-[var(--color-danger)]">{deleteError}</p>
              )}
              <div className="flex items-center justify-end gap-2">
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setShowDeleteConfirm(false);
                    setDeleteConfirm("");
                    setDeleteError(null);
                  }}
                  disabled={isDeleting}
                >
                  Cancel
                </Button>
                <Button
                  type="button"
                  variant="danger"
                  size="sm"
                  onClick={handleDelete}
                  disabled={deleteConfirm.trim().toUpperCase() !== "DELETE" || isDeleting}
                >
                  {isDeleting ? "Deleting" : "Delete"}
                </Button>
              </div>
            </div>
          )}
        </div>
        <p className="text-xs text-[var(--color-text-soft)]">
          Changes will apply to the next scheduled run. Manual syncs can be triggered from the Syncs page.
        </p>
      </form>
    </Modal>
  );
}
