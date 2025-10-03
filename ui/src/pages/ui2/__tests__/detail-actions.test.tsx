import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { MappingDetailView, ProviderEventDetailView } from "../index";
import type { ProviderEventDetail, SyncMappingRow, SyncMappingSegment } from "../types";

describe("MappingDetailView", () => {
  const baseSegment: SyncMappingSegment = {
    mappingId: "map-1",
    providerId: "provider-1",
    providerLabel: "Provider 1",
    providerUid: "uid-1",
    role: "source",
    lastSeen: "Just now",
  };

  const baseMapping: SyncMappingRow = {
    id: "orbit-1",
    event: "Launch Review",
    eventTime: "2025-03-18 10:30",
    lastSynced: "2m ago",
    orbitEventId: "orbit-1",
    notes: "",
    segments: [baseSegment],
    startAt: "2025-03-18T10:30:00Z",
    endAt: "2025-03-18T11:00:00Z",
    lastMergedAt: "2025-03-18T11:05:00Z",
    syncId: "sync-1",
  };

  it("invokes confirm handler when action button is clicked", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    const onRecreate = vi.fn();

    render(
      <MappingDetailView
        data={{
          id: baseMapping.id,
          orbitEventId: baseMapping.orbitEventId,
          title: baseMapping.event,
          eventTime: baseMapping.eventTime,
          startAt: baseMapping.startAt ?? undefined,
          endAt: baseMapping.endAt ?? undefined,
          syncId: baseMapping.syncId ?? undefined,
          lastMergedAt: baseMapping.lastMergedAt ?? undefined,
          notes: baseMapping.notes,
          segments: baseMapping.segments,
          selectedSegmentId: baseSegment.mappingId,
        }}
        onConfirm={onConfirm}
        onRecreate={onRecreate}
        actionState={null}
      />
    );

    await user.click(screen.getByRole("button", { name: /confirm provider state/i }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("disables buttons while an action is pending", () => {
    const onConfirm = vi.fn();
    const onRecreate = vi.fn();

    render(
      <MappingDetailView
        data={{
          id: baseMapping.id,
          orbitEventId: baseMapping.orbitEventId,
          title: baseMapping.event,
          notes: baseMapping.notes,
          segments: baseMapping.segments,
          selectedSegmentId: baseSegment.mappingId,
        }}
        onConfirm={onConfirm}
        onRecreate={onRecreate}
        actionState={{ type: "confirm-mapping", target: baseSegment.mappingId! }}
      />
    );

    const confirmButton = screen.getByRole("button", { name: /confirming/i });
    expect(confirmButton).toBeDisabled();
  });
});

describe("ProviderEventDetailView", () => {
  const baseDetail: ProviderEventDetail = {
    providerEventId: "evt-1",
    providerId: "provider-1",
    providerName: "Provider 1",
    status: "Mapped",
    tombstoned: "No",
    providerLastSeen: "2025-03-18T11:00:00Z",
    title: "Launch Review",
    startAt: "2025-03-18T10:30:00Z",
    endAt: "2025-03-18T11:00:00Z",
    updatedAt: "2025-03-18T11:05:00Z",
    orbitEventId: "orbit-1",
    syncId: "sync-1",
    mappingId: "map-1",
  };

  it("calls confirm callback when the button is pressed", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    const onRecreate = vi.fn();

    render(
      <ProviderEventDetailView
        data={baseDetail}
        onConfirm={onConfirm}
        onRecreate={onRecreate}
        actionState={null}
      />
    );

    await user.click(screen.getByRole("button", { name: /confirm presence/i }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("disables confirm button when provider UID is missing", () => {
    const onConfirm = vi.fn();
    const onRecreate = vi.fn();

    render(
      <ProviderEventDetailView
        data={{ ...baseDetail, providerEventId: "" }}
        onConfirm={onConfirm}
        onRecreate={onRecreate}
        actionState={null}
      />
    );

    expect(screen.getByRole("button", { name: /confirm presence/i })).toBeDisabled();
  });
});
