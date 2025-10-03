import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";
import type {
  CSSProperties,
  KeyboardEvent as ReactKeyboardEvent,
  MouseEvent as ReactMouseEvent,
  TouchEvent as ReactTouchEvent,
} from "react";

import { useUi2Data } from "../../lib/ui2-data";
import { useApi } from "../../lib/api-context";
import type {
  IncidentRow,
  InventoryScope,
  OperationRow,
  ProviderEventDetail,
  ProviderEventRow,
  ScopeKey,
  SyncEventDetail,
  SyncEventRow,
  SyncMappingRow,
  SyncMappingSegment,
  SyncStatus,
  SystemMetric,
  WindowRange,
} from "./types";

const DEFAULT_LAYOUT = { left: 28, right: 30, bottom: 28 } as const;

import "./ui2.css";

type MappingDetailData = {
  id: string;
  orbitEventId: string;
  title: string;
  eventTime?: string;
  startAt?: string;
  endAt?: string;
  syncId?: string;
  lastMergedAt?: string;
  notes: string;
  segments: SyncMappingSegment[];
  selectedSegmentId?: string | null;
  selectedProviderId?: string | null;
};

type DetailSelection =
  | { type: "sync-event"; key: string; data: SyncEventDetail }
  | { type: "calendar-event"; key: string; data: ProviderEventDetail }
  | { type: "mapping-record"; key: string; data: MappingDetailData };

type ActionKind =
  | "confirm-mapping"
  | "recreate-mapping"
  | "confirm-provider-event"
  | "recreate-provider-event"
  | "query-provider";

type ActionState = {
  type: ActionKind;
  target: string;
};

type ActionFeedback = {
  tone: "success" | "error";
  message: string;
};

const classNames = (...values: Array<string | false | null | undefined>) => values.filter(Boolean).join(" ");

type SyncEventsProps = {
  syncEvents: SyncEventRow[];
  providerEvents: ProviderEventRow[];
  syncFilters: Record<SyncStatus, boolean>;
  onToggleFilter: (status: SyncStatus) => void;
  windowRange: WindowRange;
  onWindowChange: (range: WindowRange) => void;
  detailKey: string | undefined;
  onSelectDetail: (selection: DetailSelection) => void;
  isLoading: boolean;
  error: string | null;
  providerName?: string | null;
  hasSyncEvents: boolean;
  onRefresh: () => void;
  isQuerying: boolean;
};

type DetailDrawerProps = {
  selection: DetailSelection | null;
  collapsed: boolean;
  isOpen: boolean;
  onToggle: () => void;
  onClose: () => void;
  onConfirmMapping: (mapping: SyncMappingRow, segment: SyncMappingSegment) => void;
  onRecreateMapping: (mapping: SyncMappingRow, segment: SyncMappingSegment) => void;
  onConfirmProviderEvent: (detail: ProviderEventDetail) => void;
  onRecreateProviderEvent: (detail: ProviderEventDetail) => void;
  actionState: ActionState | null;
  style?: CSSProperties;
};

export function Ui2WorkspacePage() {
  const [activeScope, setActiveScope] = useState<ScopeKey>("system");
  const [syncFilters, setSyncFilters] = useState<Record<SyncStatus, boolean>>({ success: true, error: true, pending: true });
  const [windowRange, setWindowRange] = useState<WindowRange>("24h");
  const [detailSelection, setDetailSelection] = useState<DetailSelection | null>(null);
  const [drawerCollapsed, setDrawerCollapsed] = useState(true);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [leftPaneWidth, setLeftPaneWidth] = useState<number>(DEFAULT_LAYOUT.left);
  const [rightPaneWidth, setRightPaneWidth] = useState<number>(DEFAULT_LAYOUT.right);
  const [bottomSectionHeight, setBottomSectionHeight] = useState<number>(DEFAULT_LAYOUT.bottom);
  const [activeResizer, setActiveResizer] = useState<"left" | "right" | "bottom" | null>(null);

  const { auth, client } = useApi();
  const location = useLocation();

  if (auth.status !== "authenticated") {
    return <Navigate to="/login" state={{ from: location.pathname + location.search }} replace />;
  }

  const rootRef = useRef<HTMLDivElement | null>(null);
  const mainRef = useRef<HTMLElement | null>(null);
  const userMenuRef = useRef<HTMLDivElement | null>(null);

  const {
    syncScopes,
    providerScopes,
    syncMappings,
    syncEvents,
    providerEvents,
    operations,
    alertsLabel,
    alertsCount,
    isInventoryLoading,
    inventoryError,
    isScopeLoading,
    scopeError,
    isOperationsLoading,
    operationsError,
    isAlertsLoading,
    alertsError,
    activeSyncName,
    activeProviderName,
    refreshScope,
    refreshOperations,
    refreshAlerts,
    systemMetrics,
    incidents,
  } = useUi2Data(activeScope, windowRange);

  const [actionState, setActionState] = useState<ActionState | null>(null);
  const [actionFeedback, setActionFeedback] = useState<ActionFeedback | null>(null);

  const currentView: "system" | "syncs" | "providers" = useMemo(() => {
    if (activeScope === "system") return "system";
    if (activeScope.startsWith("sync:")) return "syncs";
    return "providers";
  }, [activeScope]);

  const filteredSyncEvents = useMemo(
    () => syncEvents.filter((row) => syncFilters[row.status]),
    [syncEvents, syncFilters]
  );

  const syncViewLoading = currentView === "syncs" && isScopeLoading;
  const syncViewError = currentView === "syncs" ? scopeError : null;
  const providerViewLoading = currentView === "providers" && isScopeLoading;
  const providerViewError = currentView === "providers" ? scopeError : null;
  const alertsTitle = alertsError ?? "Failed sync runs from /sync-runs/summary";
  const alertsText = isAlertsLoading ? "Alerts • loading" : alertsLabel;
  const layoutRefresh = useCallback(() => {
    refreshAlerts();
    refreshOperations();
  }, [refreshAlerts, refreshOperations]);

  const MIN_LEFT = 18;
  const MIN_RIGHT = 20;
  const MIN_CENTER = 32;
  const MIN_BOTTOM = 16;
  const MAX_BOTTOM = 45;

  const clamp = useCallback((value: number, min: number, max: number) => {
    return Math.min(Math.max(value, min), max);
  }, []);

  const centerPaneWidth = useMemo(() => {
    return Math.max(MIN_CENTER, 100 - leftPaneWidth - rightPaneWidth);
  }, [leftPaneWidth, rightPaneWidth, MIN_CENTER]);

  const workspaceTopStyle = useMemo(
    () => ({ flexGrow: 1, flexShrink: 1, flexBasis: `${100 - bottomSectionHeight}%`, minHeight: 0, display: "flex" }),
    [bottomSectionHeight]
  );

  const leftPaneStyle = useMemo(
    () => ({ flex: `0 0 ${leftPaneWidth}%`, minWidth: 220 }),
    [leftPaneWidth]
  );

  const centerPaneStyle = useMemo(
    () => ({ flex: `1 1 ${centerPaneWidth}%`, minWidth: 260 }),
    [centerPaneWidth]
  );

  const rightPaneStyle = useMemo(
    () => ({ flex: `0 0 ${rightPaneWidth}%`, minWidth: 260 }),
    [rightPaneWidth]
  );

  const operationsStyle = useMemo(
    () => ({ flexGrow: 0, flexShrink: 0, flexBasis: `${bottomSectionHeight}%`, maxHeight: "60vh" }),
    [bottomSectionHeight]
  );

  useEffect(() => {
    if (!userMenuOpen) {
      return;
    }

    const handleOutside = (event: MouseEvent | TouchEvent) => {
      if (userMenuRef.current && !userMenuRef.current.contains(event.target as Node)) {
        setUserMenuOpen(false);
      }
    };

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setUserMenuOpen(false);
      }
    };

    document.addEventListener("mousedown", handleOutside);
    document.addEventListener("touchstart", handleOutside);
    document.addEventListener("keydown", handleEscape);

    return () => {
      document.removeEventListener("mousedown", handleOutside);
      document.removeEventListener("touchstart", handleOutside);
      document.removeEventListener("keydown", handleEscape);
    };
  }, [userMenuOpen]);

  const finishResize = useCallback(() => {
    setActiveResizer(null);
  }, []);

  const handleColumnResizeStart = useCallback(
    (nativeEvent: MouseEvent | TouchEvent, target: "left" | "right") => {
      nativeEvent.preventDefault();
      const container = rootRef.current;
      if (!container) {
        return;
      }
      const { width } = container.getBoundingClientRect();
      if (!width) {
        return;
      }
      const startX = "touches" in nativeEvent ? nativeEvent.touches[0]?.clientX ?? 0 : nativeEvent.clientX;
      const startLeft = leftPaneWidth;
      const startRight = rightPaneWidth;

      const onMove = (event: MouseEvent | TouchEvent) => {
        const clientX = "touches" in event ? event.touches[0]?.clientX ?? 0 : event.clientX;
        const deltaPercent = ((clientX - startX) / width) * 100;
        if (target === "left") {
          const maxLeft = Math.max(MIN_LEFT, 100 - rightPaneWidth - MIN_CENTER);
          const nextLeft = clamp(startLeft + deltaPercent, MIN_LEFT, maxLeft);
          setLeftPaneWidth(nextLeft);
        } else {
          const maxRight = Math.max(MIN_RIGHT, 100 - leftPaneWidth - MIN_CENTER);
          const nextRight = clamp(startRight + deltaPercent, MIN_RIGHT, maxRight);
          setRightPaneWidth(nextRight);
        }
      };

      const onUp = () => {
        window.removeEventListener("mousemove", onMove as EventListener);
        window.removeEventListener("touchmove", onMove as EventListener);
        window.removeEventListener("mouseup", onUp);
        window.removeEventListener("touchend", onUp);
        finishResize();
      };

      window.addEventListener("mousemove", onMove as EventListener, { passive: false });
      window.addEventListener("touchmove", onMove as EventListener, { passive: false });
      window.addEventListener("mouseup", onUp);
      window.addEventListener("touchend", onUp);
      setActiveResizer(target);
    },
    [MIN_CENTER, MIN_LEFT, MIN_RIGHT, clamp, finishResize, leftPaneWidth, rightPaneWidth]
  );

  const handleRowResizeStart = useCallback(
    (nativeEvent: MouseEvent | TouchEvent) => {
      nativeEvent.preventDefault();
      const container = mainRef.current;
      if (!container) {
        return;
      }
      const { height } = container.getBoundingClientRect();
      if (!height) {
        return;
      }
      const startY = "touches" in nativeEvent ? nativeEvent.touches[0]?.clientY ?? 0 : nativeEvent.clientY;
      const startBottom = bottomSectionHeight;

      const onMove = (event: MouseEvent | TouchEvent) => {
        const clientY = "touches" in event ? event.touches[0]?.clientY ?? 0 : event.clientY;
        const deltaPercent = ((clientY - startY) / height) * 100;
        const nextBottom = clamp(startBottom + deltaPercent, MIN_BOTTOM, MAX_BOTTOM);
        setBottomSectionHeight(nextBottom);
      };

      const onUp = () => {
        window.removeEventListener("mousemove", onMove as EventListener);
        window.removeEventListener("touchmove", onMove as EventListener);
        window.removeEventListener("mouseup", onUp);
        window.removeEventListener("touchend", onUp);
        finishResize();
      };

      window.addEventListener("mousemove", onMove as EventListener, { passive: false });
      window.addEventListener("touchmove", onMove as EventListener, { passive: false });
      window.addEventListener("mouseup", onUp);
      window.addEventListener("touchend", onUp);
      setActiveResizer("bottom");
    },
    [MAX_BOTTOM, MIN_BOTTOM, bottomSectionHeight, clamp, finishResize]
  );

  const handleColumnResizeKey = useCallback(
    (event: ReactKeyboardEvent<HTMLDivElement>, target: "left" | "right") => {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") {
        return;
      }
      event.preventDefault();
      const delta = event.key === "ArrowLeft" ? -2 : 2;
      if (target === "left") {
        const maxLeft = Math.max(MIN_LEFT, 100 - rightPaneWidth - MIN_CENTER);
        setLeftPaneWidth((current) => clamp(current + delta, MIN_LEFT, maxLeft));
      } else {
        const maxRight = Math.max(MIN_RIGHT, 100 - leftPaneWidth - MIN_CENTER);
        setRightPaneWidth((current) => clamp(current + delta, MIN_RIGHT, maxRight));
      }
    },
    [MIN_CENTER, MIN_LEFT, MIN_RIGHT, clamp, leftPaneWidth, rightPaneWidth]
  );

  const handleRowResizeKey = useCallback(
    (event: ReactKeyboardEvent<HTMLDivElement>) => {
      if (event.key !== "ArrowUp" && event.key !== "ArrowDown") {
        return;
      }
      event.preventDefault();
      const delta = event.key === "ArrowUp" ? -2 : 2;
      setBottomSectionHeight((current) => clamp(current + delta, MIN_BOTTOM, MAX_BOTTOM));
    },
    [MAX_BOTTOM, MIN_BOTTOM, clamp]
  );

  const resetHorizontalLayout = useCallback(() => {
    setLeftPaneWidth(DEFAULT_LAYOUT.left);
    setRightPaneWidth(DEFAULT_LAYOUT.right);
  }, []);

  const resetVerticalLayout = useCallback(() => {
    setBottomSectionHeight(DEFAULT_LAYOUT.bottom);
  }, []);

  const leftResizerClass = classNames("col-resizer", activeResizer === "left" && "active");
  const rightResizerClass = classNames("col-resizer", activeResizer === "right" && "active");
  const rowResizerClass = classNames("row-resizer", activeResizer === "bottom" && "active");
  const userMenuClass = classNames("user-menu", userMenuOpen && "is-open");

  const handleLeftMouseDown = useCallback(
    (event: ReactMouseEvent<HTMLDivElement>) => {
      handleColumnResizeStart(event.nativeEvent, "left");
    },
    [handleColumnResizeStart]
  );

  const handleLeftTouchStart = useCallback(
    (event: ReactTouchEvent<HTMLDivElement>) => {
      handleColumnResizeStart(event.nativeEvent, "left");
    },
    [handleColumnResizeStart]
  );

  const handleRightMouseDown = useCallback(
    (event: ReactMouseEvent<HTMLDivElement>) => {
      handleColumnResizeStart(event.nativeEvent, "right");
    },
    [handleColumnResizeStart]
  );

  const handleRightTouchStart = useCallback(
    (event: ReactTouchEvent<HTMLDivElement>) => {
      handleColumnResizeStart(event.nativeEvent, "right");
    },
    [handleColumnResizeStart]
  );

  const handleRowMouseDown = useCallback(
    (event: ReactMouseEvent<HTMLDivElement>) => {
      handleRowResizeStart(event.nativeEvent);
    },
    [handleRowResizeStart]
  );

  const handleRowTouchStart = useCallback(
    (event: ReactTouchEvent<HTMLDivElement>) => {
      handleRowResizeStart(event.nativeEvent);
    },
    [handleRowResizeStart]
  );

  const toggleUserMenu = useCallback(() => {
    setUserMenuOpen((open) => !open);
  }, []);

  const handleUserMenuKeyDown = useCallback(
    (event: ReactKeyboardEvent<HTMLButtonElement>) => {
      if ((event.key === "Enter" || event.key === " ") && !userMenuOpen) {
        event.preventDefault();
        setUserMenuOpen(true);
        return;
      }
      if (event.key === "ArrowDown" && !userMenuOpen) {
        event.preventDefault();
        setUserMenuOpen(true);
      }
    },
    [userMenuOpen]
  );

  const handleQueryProvider = useCallback(() => {
    if (!activeScope.startsWith("provider:")) {
      setActionFeedback({ tone: "error", message: "Select a provider scope to query." });
      return;
    }
    const providerId = activeScope.slice("provider:".length);
    setActionState({ type: "query-provider", target: providerId });
    setActionFeedback({ tone: "success", message: "Querying provider…" });
    refreshScope();
    refreshOperations();
    refreshAlerts();
  }, [activeScope, refreshAlerts, refreshOperations, refreshScope]);

  useEffect(() => {
    setActionFeedback(null);
  }, [activeScope]);

  useEffect(() => {
    if (actionState?.type === "query-provider" && !providerViewLoading) {
      setActionState(null);
      setActionFeedback({ tone: "success", message: "Provider query completed." });
    }
  }, [actionState, providerViewLoading]);

  const resolveErrorMessage = useCallback((error: unknown) => {
    if (error instanceof Error) {
      return error.message;
    }
    return "Unexpected error occurred";
  }, []);

  const handleConfirmMapping = useCallback(
    async (mapping: SyncMappingRow, segment: SyncMappingSegment) => {
      const target = segment.mappingId || `${segment.providerId}:${segment.providerUid ?? ""}`;
      if (!segment.providerUid) {
        setActionFeedback({ tone: "error", message: "Missing provider UID for this segment." });
        return;
      }
      setActionState({ type: "confirm-mapping", target });
      setActionFeedback(null);
      try {
        const response = await client.troubleshootConfirmProvider({
          providerId: segment.providerId,
          providerUid: segment.providerUid,
          mappingId: segment.mappingId,
          syncId: mapping.syncId,
        });
        const message = response.operation_id
          ? `Confirmation queued (operation ${response.operation_id}).`
          : `Provider ${segment.providerLabel} confirmed.`;
        setActionFeedback({ tone: "success", message });
        refreshScope();
        refreshOperations();
        refreshAlerts();
      } catch (error) {
        setActionFeedback({ tone: "error", message: resolveErrorMessage(error) });
      } finally {
        setActionState(null);
      }
    },
    [client, refreshAlerts, refreshOperations, refreshScope, resolveErrorMessage]
  );

  const handleRecreateMapping = useCallback(
    async (mapping: SyncMappingRow, segment: SyncMappingSegment) => {
      if (!segment.mappingId) {
        setActionFeedback({ tone: "error", message: "Provider mapping identifier is unavailable." });
        return;
      }
      const target = segment.mappingId;
      setActionState({ type: "recreate-mapping", target });
      setActionFeedback(null);
      try {
        const response = await client.troubleshootRecreate({
          mappingId: segment.mappingId,
          targetProviderId: segment.providerId,
          syncId: mapping.syncId,
        });
        const message = response.operation_id
          ? `Recreate queued (operation ${response.operation_id}).`
          : `Event recreated on ${segment.providerLabel}.`;
        setActionFeedback({ tone: "success", message });
        refreshScope();
        refreshOperations();
        refreshAlerts();
      } catch (error) {
        setActionFeedback({ tone: "error", message: resolveErrorMessage(error) });
      } finally {
        setActionState(null);
      }
    },
    [client, refreshAlerts, refreshOperations, refreshScope, resolveErrorMessage]
  );

  const handleConfirmProviderEvent = useCallback(
    async (detail: ProviderEventDetail) => {
      const target = detail.providerEventId || detail.mappingId || detail.providerId;
      if (!detail.providerEventId) {
        setActionFeedback({ tone: "error", message: "Provider event ID missing; unable to confirm." });
        return;
      }
      setActionState({ type: "confirm-provider-event", target });
      setActionFeedback(null);
      try {
        const response = await client.troubleshootConfirmProvider({
          providerId: detail.providerId,
          providerUid: detail.providerEventId,
          mappingId: detail.mappingId || undefined,
          syncId: detail.syncId || undefined,
        });
        const message = response.operation_id
          ? `Confirmation queued (operation ${response.operation_id}).`
          : `Provider ${detail.providerName} confirmed.`;
        setActionFeedback({ tone: "success", message });
        refreshScope();
        refreshOperations();
        refreshAlerts();
      } catch (error) {
        setActionFeedback({ tone: "error", message: resolveErrorMessage(error) });
      } finally {
        setActionState(null);
      }
    },
    [client, refreshAlerts, refreshOperations, refreshScope, resolveErrorMessage]
  );

  const handleRecreateProviderEvent = useCallback(
    async (detail: ProviderEventDetail) => {
      if (!detail.mappingId) {
        setActionFeedback({ tone: "error", message: "No mapping associated with this provider event." });
        return;
      }
      const target = detail.mappingId;
      setActionState({ type: "recreate-provider-event", target });
      setActionFeedback(null);
      try {
        const response = await client.troubleshootRecreate({
          mappingId: detail.mappingId,
          targetProviderId: detail.providerId,
          syncId: detail.syncId || undefined,
        });
        const message = response.operation_id
          ? `Recreate queued (operation ${response.operation_id}).`
          : `Event recreated for ${detail.providerName}.`;
        setActionFeedback({ tone: "success", message });
        refreshScope();
        refreshOperations();
        refreshAlerts();
      } catch (error) {
        setActionFeedback({ tone: "error", message: resolveErrorMessage(error) });
      } finally {
        setActionState(null);
      }
    },
    [client, refreshAlerts, refreshOperations, refreshScope, resolveErrorMessage]
  );

  useEffect(() => {
    if (activeScope === "system" || isInventoryLoading) {
      return;
    }
    const scopeExists = [...syncScopes, ...providerScopes].some((scope) => scope.key === activeScope);
    if (!scopeExists) {
      setActiveScope("system");
    }
  }, [activeScope, isInventoryLoading, providerScopes, syncScopes]);

  const handleScopeChange = (scope: ScopeKey) => {
    setActiveScope(scope);
    setDetailSelection(null);
    setDrawerCollapsed(true);
  };

  const toggleSyncFilter = (status: SyncStatus) => {
    setSyncFilters((prev) => {
      const next = { ...prev, [status]: !prev[status] };
      if (!next.success && !next.error && !next.pending) {
        return { success: true, error: true, pending: true };
      }
      return next;
    });
  };

  const handleSelectDetail = (selection: DetailSelection) => {
    if (detailSelection?.key === selection.key && !drawerCollapsed) {
      setDrawerCollapsed(true);
      return;
    }
    setDetailSelection(selection);
    setDrawerCollapsed(false);
  };

  const handleToggleDrawer = () => setDrawerCollapsed((prev) => !prev);
  const handleCloseDrawer = () => setDrawerCollapsed(true);

  const detailKey = detailSelection?.key;
  const isDrawerOpen = !drawerCollapsed && detailSelection !== null;

  return (
    <div className="ui2-root" ref={rootRef}>
      <div className="app-shell">
        <header>
          <div className="brand">
            <div className="glyph">O</div>
            <h1>Orbit</h1>
          </div>
          <div className="toolbar" style={{ border: 0, background: "transparent", padding: 0, gap: "12px" }}>
            <div className="search" style={{ maxWidth: 320 }}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path
                  d="M15.5 14h-.79l-.28-.27a6.2 6.2 0 0 0 1.57-4.13 6.1 6.1 0 1 0-6.1 6.1 6.2 6.2 0 0 0 4.13-1.57l.27.28v.79l4.7 4.69 1.4-1.4-4.7-4.7Zm-6.1 0a4.1 4.1 0 1 1 0-8.2 4.1 4.1 0 0 1 0 8.2Z"
                  fill="currentColor"
                />
              </svg>
              <input placeholder="Jump to sync, provider, run ID" disabled title="Global search planned" />
            </div>
            <div
              className={classNames(
                "pill",
                alertsCount > 0 && "pill-critical",
                alertsCount === 0 && !isAlertsLoading && !alertsError && "pill-success"
              )}
              title={alertsTitle}
            >
              {alertsText}
            </div>
          </div>
          <div className="header-actions">
            <div className={userMenuClass} ref={userMenuRef}>
              <button
                type="button"
                className="avatar-button"
                aria-haspopup="menu"
                aria-expanded={userMenuOpen ? "true" : "false"}
                onClick={toggleUserMenu}
                onKeyDown={handleUserMenuKeyDown}
              >
                <span className="sr-only">Open user menu</span>
                <span className="avatar-pill" aria-hidden="true">SM</span>
                <svg className="user-menu-caret" viewBox="0 0 16 16" aria-hidden="true">
                  <path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"></path>
                </svg>
              </button>
              {userMenuOpen && (
                <div className="user-menu-popover" role="menu">
                  <div className="user-popover-header">
                    <div className="user-name">Sophia Miles</div>
                    <div className="user-email">sophia@orbit.dev</div>
                  </div>
                  <button className="user-menu-item" type="button" role="menuitem">
                    Toggle light mode
                  </button>
                  <button className="user-menu-item" type="button" role="menuitem">
                    Profile settings
                  </button>
                  <button className="user-menu-item" type="button" role="menuitem">
                    Log out
                  </button>
                </div>
              )}
            </div>
          </div>
        </header>

        <main ref={mainRef}>
          <div className="workspace-top" style={workspaceTopStyle}>
            <InventoryPanel
              activeScope={activeScope}
              onScopeChange={handleScopeChange}
              syncScopes={syncScopes}
              providerScopes={providerScopes}
              isLoading={isInventoryLoading}
              error={inventoryError}
              style={leftPaneStyle}
            />

            <div
              className={leftResizerClass}
              data-target="left"
              role="separator"
              aria-orientation="vertical"
              tabIndex={0}
              onMouseDown={handleLeftMouseDown}
              onTouchStart={handleLeftTouchStart}
              onKeyDown={(event) => handleColumnResizeKey(event, "left")}
              onDoubleClick={resetHorizontalLayout}
            ></div>

            <section className="panel split-panel" data-pane="center" style={centerPaneStyle}>
              <div className="panel-header">
                <div className="title">
                  <span style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--accent)" }}></span>
                  Detail
                </div>
                <button className="primary compact" id="detail-create" type="button">
                  + New provider
                </button>
              </div>

              <div className="panel-body detail-scroll">
                {actionFeedback && (
                  <div
                    className="helper"
                    role="status"
                    style={{ color: actionFeedback.tone === "error" ? "var(--color-danger)" : "var(--accent)" }}
                  >
                    {actionFeedback.message}
                  </div>
                )}
                {currentView === "system" && (
                  <SystemDashboard
                    metrics={systemMetrics}
                    incidents={incidents}
                    onRefresh={layoutRefresh}
                    isLoading={isAlertsLoading || isOperationsLoading}
                    error={alertsError || operationsError}
                  />
                )}
                {currentView === "syncs" && (
                  <SyncMappingsTable
                    mappings={syncMappings}
                    isLoading={syncViewLoading}
                    error={syncViewError}
                    actionState={actionState}
                    onConfirm={handleConfirmMapping}
                    onRecreate={handleRecreateMapping}
                    syncName={activeSyncName}
                    selectedKey={detailKey}
                    onSelect={(mapping, segment) =>
                      handleSelectDetail({
                        type: "mapping-record",
                        key: `${mapping.id}:${segment.mappingId}:${segment.providerId}`,
                        data: {
                          id: mapping.id,
                          orbitEventId: mapping.orbitEventId,
                          title: mapping.event,
                          eventTime: mapping.eventTime,
                          startAt: mapping.startAt ?? mapping.eventTime,
                          endAt: mapping.endAt ?? mapping.eventTime,
                          syncId: mapping.syncId ?? "",
                          lastMergedAt: mapping.lastMergedAt ?? mapping.lastSynced,
                          notes: mapping.notes,
                          segments: mapping.segments,
                          selectedSegmentId: segment.mappingId ?? null,
                          selectedProviderId: segment.providerId
                        }
                      })
                    }
                  />
                )}
                {currentView === "providers" && (
                  <ProviderWorkspace
                    syncEvents={filteredSyncEvents}
                    providerEvents={providerEvents}
                    syncFilters={syncFilters}
                    onToggleFilter={toggleSyncFilter}
                    windowRange={windowRange}
                    onWindowChange={setWindowRange}
                    detailKey={detailKey}
                    onSelectDetail={handleSelectDetail}
                    isLoading={providerViewLoading}
                    error={providerViewError}
                    providerName={activeProviderName}
                    hasSyncEvents={syncEvents.length > 0}
                    onRefresh={handleQueryProvider}
                    isQuerying={actionState?.type === "query-provider"}
                  />
                )}
              </div>
            </section>

            <div
              className={rightResizerClass}
              data-target="right"
              role="separator"
              aria-orientation="vertical"
              tabIndex={0}
              onMouseDown={handleRightMouseDown}
              onTouchStart={handleRightTouchStart}
              onKeyDown={(event) => handleColumnResizeKey(event, "right")}
              onDoubleClick={resetHorizontalLayout}
            ></div>

            <DetailDrawer
              selection={detailSelection}
              collapsed={drawerCollapsed || !detailSelection}
              onToggle={handleToggleDrawer}
              onClose={handleCloseDrawer}
              isOpen={isDrawerOpen}
              onConfirmMapping={handleConfirmMapping}
              onRecreateMapping={handleRecreateMapping}
              onConfirmProviderEvent={handleConfirmProviderEvent}
              onRecreateProviderEvent={handleRecreateProviderEvent}
              actionState={actionState}
              style={rightPaneStyle}
            />
          </div>

          <div
            className={rowResizerClass}
            data-target="bottom"
            role="separator"
            aria-orientation="horizontal"
            tabIndex={0}
            onMouseDown={handleRowMouseDown}
            onTouchStart={handleRowTouchStart}
            onKeyDown={handleRowResizeKey}
            onDoubleClick={resetVerticalLayout}
          ></div>

          <OperationsStrip operations={operations} isLoading={isOperationsLoading} error={operationsError} style={operationsStyle} />
        </main>
      </div>
    </div>
  );
}

function InventoryPanel({
  activeScope,
  onScopeChange,
  syncScopes,
  providerScopes,
  isLoading,
  error,
  style
}: {
  activeScope: ScopeKey;
  onScopeChange: (scope: ScopeKey) => void;
  syncScopes: InventoryScope[];
  providerScopes: InventoryScope[];
  isLoading: boolean;
  error: string | null;
  style?: CSSProperties;
}) {
  const totalScopes = syncScopes.length + providerScopes.length;
  const renderScopeButton = (scope: InventoryScope) => (
    <button
      key={scope.key}
      type="button"
      className={classNames("scope-node", activeScope === scope.key && "active")}
      onClick={() => onScopeChange(scope.key as ScopeKey)}
    >
      {scope.label}
      {scope.meta && (
        <span
          className={classNames(
            "meta",
            scope.metaTone === "success" && "meta-success",
            scope.metaTone === "critical" && "meta-critical"
          )}
        >
          {scope.meta}
        </span>
      )}
    </button>
  );

  return (
    <section className="panel split-panel" data-pane="left" style={style}>
      <div className="panel-header">
        <div className="title">
          <span style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--accent)" }}></span>
          Inventory
        </div>
      </div>
      <div className="panel-body requests-scroll">
        <div className="scope-tree">
          <button
            type="button"
            className={classNames("scope-node", activeScope === "system" && "active")}
            onClick={() => onScopeChange("system")}
          >
            System
            <span className="meta">{totalScopes} scopes</span>
          </button>

          {isLoading ? (
            <div className="helper">Loading inventory…</div>
          ) : error ? (
            <div className="helper" style={{ color: "var(--color-danger)" }}>{error}</div>
          ) : (
            <>
              <div className="scope-group">
                <div className="scope-group-header">
                  Syncs
                  <span className="pill" style={{ marginLeft: "auto" }}>{syncScopes.length}</span>
                </div>
                {syncScopes.length === 0 ? (
                  <div className="helper">No syncs configured yet.</div>
                ) : (
                  syncScopes.map(renderScopeButton)
                )}
              </div>

              <div className="scope-group">
                <div className="scope-group-header">
                  Providers
                  <span className="pill" style={{ marginLeft: "auto" }}>{providerScopes.length}</span>
                </div>
                {providerScopes.length === 0 ? (
                  <div className="helper">No providers connected yet.</div>
                ) : (
                  providerScopes.map(renderScopeButton)
                )}
              </div>
            </>
          )}
        </div>
      </div>
      <footer>
        <span>Select a scope to load context</span>
        <div className="controls">
          <button className="ghost-button" type="button" style={{ fontSize: 11, padding: "2px 8px" }}>
            Add scope
          </button>
        </div>
      </footer>
    </section>
  );
}

function SystemDashboard({
  metrics,
  incidents,
  onRefresh,
  isLoading,
  error
}: {
  metrics: SystemMetric[];
  incidents: IncidentRow[];
  onRefresh: () => void;
  isLoading: boolean;
  error: string | null;
}) {
  return (
    <div className="scope-view is-active" data-view="system">
      <div className="caption">System overview</div>
      <div className="helper">
        Aggregated from operations, syncs, and providers to highlight current health.
        <button
          className="ghost-button"
          type="button"
          style={{ marginLeft: 12, fontSize: 11, padding: "2px 8px" }}
          onClick={onRefresh}
        >
          ↻ Refresh
        </button>
      </div>
      {error && !isLoading && (
        <div className="helper" style={{ color: "var(--color-danger)" }}>{error}</div>
      )}
      <div className="metrics-grid">
        {metrics.map((metric) => (
          <div key={metric.label} className={classNames("metric-card", metric.tone === "critical" && "metric-card-critical") }>
            <div className="label">{metric.label}</div>
            <div className={classNames("value", metric.tone === "critical" && "metric-critical-text")}>{metric.value}</div>
            <div className="trend">{metric.trend}</div>
          </div>
        ))}
      </div>

      <div className="section-title" style={{ padding: "12px 0 6px" }}>Latest incidents</div>
      <table className="table">
        <thead>
          <tr>
            <th>Incident</th>
            <th>Scope</th>
            <th>Status</th>
            <th>Opened</th>
            <th>Owner</th>
          </tr>
        </thead>
        <tbody>
          {incidents.length === 0 ? (
            <tr>
              <td colSpan={5} className="helper">No incidents detected in the recent window.</td>
            </tr>
          ) : (
            incidents.map((incident) => (
              <tr key={incident.id}>
                <td>
                  {incident.id} {incident.title}
                </td>
                <td>{incident.scope}</td>
                <td>
                  <span
                    className={classNames(
                      "pill",
                      incident.status === "investigating" && "pill-critical",
                      incident.status === "in queue" && "pill-pending",
                      incident.status === "resolved" && "pill-success"
                    )}
                  >
                    {incident.status}
                  </span>
                </td>
                <td>{incident.opened}</td>
                <td>{incident.owner}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

function SyncMappingsTable({
  mappings,
  selectedKey,
  onSelect,
  isLoading,
  error,
  syncName,
  onConfirm,
  onRecreate,
  actionState
}: {
  mappings: SyncMappingRow[];
  selectedKey: string | undefined;
  onSelect: (mapping: SyncMappingRow, segment: SyncMappingSegment) => void;
  isLoading: boolean;
  error: string | null;
  syncName?: string | null;
  onConfirm: (mapping: SyncMappingRow, segment: SyncMappingSegment) => void;
  onRecreate: (mapping: SyncMappingRow, segment: SyncMappingSegment) => void;
  actionState: ActionState | null;
}) {
  const hasRows = mappings.some((mapping) => mapping.segments.length > 0);

  return (
    <div className="scope-view is-active" data-view="syncs">
      <div className="caption">Sync mappings {syncName ? `• ${syncName}` : ""}</div>
      <div className="helper">Each mapping aligns multiple providers to a single Orbit event. Rows span providers while keeping event context visible.</div>
      <table className="table">
        <thead>
          <tr>
            <th>Event</th>
            <th>Event time</th>
            <th>Last synced</th>
            <th>Provider</th>
            <th>Last seen @ provider</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {isLoading ? (
            <tr>
              <td colSpan={6} className="helper">Loading mappings…</td>
            </tr>
          ) : error ? (
            <tr>
              <td colSpan={6} className="helper" style={{ color: "var(--color-danger)" }}>{error}</td>
            </tr>
          ) : !hasRows ? (
            <tr>
              <td colSpan={6} className="helper">No mappings found for this sync.</td>
            </tr>
          ) : (
            mappings.flatMap((mapping) =>
              mapping.segments.map((segment, index) => {
                const key = `${mapping.id}:${segment.mappingId}:${segment.providerId}`;
                const isSelected = selectedKey === key;
                const confirmTarget = segment.mappingId || `${segment.providerId}:${segment.providerUid ?? ""}`;
                const recreateTarget = segment.mappingId ?? "";
                const confirmBusy = actionState?.type === "confirm-mapping" && actionState.target === confirmTarget;
                const recreateBusy = actionState?.type === "recreate-mapping" && actionState.target === recreateTarget;
                const confirmDisabled = isLoading || confirmBusy || !segment.providerUid;
                const recreateDisabled = isLoading || recreateBusy || !segment.mappingId;
                return (
                  <tr
                    key={key}
                    className={classNames(isSelected && "is-selected")}
                    onClick={() => onSelect(mapping, segment)}
                  >
                    {index === 0 && <td rowSpan={mapping.segments.length}>{mapping.event}</td>}
                    {index === 0 && <td rowSpan={mapping.segments.length}>{mapping.eventTime}</td>}
                    {index === 0 && <td rowSpan={mapping.segments.length}>{mapping.lastSynced}</td>}
                    <td>{segment.providerLabel}</td>
                    <td>{segment.lastSeen}</td>
                    <td className="cell-actions">
                      <button
                        className="primary compact"
                        type="button"
                        disabled={confirmDisabled}
                        onClick={(event) => {
                          event.stopPropagation();
                          onConfirm(mapping, segment);
                        }}
                      >
                        Confirm
                      </button>
                      <button
                        className="primary compact"
                        type="button"
                        disabled={recreateDisabled}
                        onClick={(event) => {
                          event.stopPropagation();
                          onRecreate(mapping, segment);
                        }}
                      >
                        Create
                      </button>
                    </td>
                  </tr>
                );
              })
            )
          )}
        </tbody>
      </table>
    </div>
  );
}

function ProviderWorkspace({
  syncEvents,
  providerEvents,
  syncFilters,
  onToggleFilter,
  windowRange,
  onWindowChange,
  detailKey,
  onSelectDetail,
  isLoading,
  error,
  providerName,
  hasSyncEvents,
  onRefresh,
  isQuerying
}: SyncEventsProps) {
  const handleWindowClick = (range: WindowRange) => {
    onWindowChange(range);
  };

  const createSyncSelection = (row: SyncEventRow): DetailSelection => ({
    type: "sync-event",
    key: row.id,
    data: row.detail
  });

  const createProviderSelection = (row: ProviderEventRow): DetailSelection => ({
    type: "calendar-event",
    key: row.id,
    data: row.detail
  });

  const providerStatusClass = (label: string) => {
    const normalized = label.toLowerCase();
    if (normalized.includes("orphan") || normalized.includes("error") || normalized.includes("tomb")) {
      return "pill-critical";
    }
    if (normalized.includes("pending") || normalized.includes("tent")) {
      return "pill-pending";
    }
    if (normalized.includes("mapped") || normalized.includes("active") || normalized.includes("synced")) {
      return "pill-success";
    }
    return "pill-info";
  };

  return (
    <div className="scope-view is-active" data-view="providers">
      <div className="caption">
        Sync events {providerName ? `• ${providerName}` : "(local)"}
      </div>
      <div className="helper">Auto-loaded from Orbit to surface the most recent sync runs for this provider.</div>
      {error && !isLoading && (
        <div className="helper" style={{ color: "var(--color-danger)" }}>{error}</div>
      )}

      <div className="controls" style={{ gap: 12, alignItems: "center", margin: "10px 0 14px", flexWrap: "wrap", display: "flex" }}>
        <span className="sync-label">Show</span>
        <div className="control-iconset" role="group" aria-label="Filter sync results">
          {(["error", "pending", "success"] as SyncStatus[]).map((status) => (
            <button
              key={status}
              type="button"
              className={classNames("filter-chip", status, syncFilters[status] && "is-active")}
              data-sync-filter={status}
              aria-pressed={syncFilters[status] ? "true" : "false"}
              onClick={() => onToggleFilter(status)}
            >
              {status === "error" && (
                <svg viewBox="0 0 16 16" aria-hidden="true">
                  <path d="M8 2.2L2.3 13.5h11.4L8 2.2z" fill="none" stroke="currentColor" strokeLinejoin="round" strokeWidth="1.3"></path>
                  <path d="M8 6.2v3.4" stroke="currentColor" strokeLinecap="round" strokeWidth="1.3"></path>
                  <circle cx="8" cy="11.3" r="0.9" fill="currentColor"></circle>
                </svg>
              )}
              {status === "pending" && (
                <svg viewBox="0 0 16 16" aria-hidden="true">
                  <circle cx="8" cy="8" r="5.3" fill="none" stroke="currentColor" strokeWidth="1.3"></circle>
                  <path d="M8 4.7v3.5l2.6 1.5" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.3"></path>
                </svg>
              )}
              {status === "success" && (
                <svg viewBox="0 0 16 16" aria-hidden="true">
                  <circle cx="8" cy="8" r="5.3" fill="none" stroke="currentColor" strokeWidth="1.3"></circle>
                  <path d="M5.2 8.3l1.8 1.8 3.8-3.8" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"></path>
                </svg>
              )}
              <span>{status === "pending" ? "Pending" : status.charAt(0).toUpperCase() + status.slice(1)}</span>
            </button>
          ))}
        </div>
        <button
          className="ghost-button"
          type="button"
          style={{ fontSize: 11, padding: "2px 8px" }}
          onClick={onRefresh}
          disabled={isQuerying}
        >
          {isQuerying ? "⟳ Querying…" : "↻ Refresh"}
        </button>
      </div>

      <table className="table">
        <thead>
          <tr>
            <th>Event</th>
            <th>Sync result</th>
            <th>Last attempt</th>
            <th>Duration</th>
            <th>Notes</th>
          </tr>
        </thead>
        <tbody>
          {isLoading ? (
            <tr>
              <td colSpan={5} className="helper">Loading sync runs…</td>
            </tr>
          ) : syncEvents.length === 0 ? (
            <tr>
              <td colSpan={5} className="helper">
                {hasSyncEvents
                  ? "No sync runs match the selected filters."
                  : "No sync runs recorded for this provider."}
              </td>
            </tr>
          ) : (
            syncEvents.map((row) => (
              <tr
                key={row.id}
                className={classNames(detailKey === row.id && "is-selected")}
                onClick={() => onSelectDetail(createSyncSelection(row))}
              >
                <td>{row.title}</td>
                <td>
                  <span
                    className={classNames(
                      "pill",
                      row.status === "success" && "pill-success",
                      row.status === "error" && "pill-critical",
                      row.status === "pending" && "pill-pending"
                    )}
                  >
                    {row.detail.status}
                  </span>
                </td>
                <td>{row.lastAttempt}</td>
                <td>{row.duration}</td>
                <td>{row.notes}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>

      <div className="caption" style={{ marginTop: 26 }}>Query provider (live)</div>
      <div className="helper">Runs a direct provider lookup outside of Orbit cache. Useful for confirming remote state.</div>

      <div className="controls" style={{ gap: 12, alignItems: "center", margin: "10px 0 14px", flexWrap: "wrap", display: "flex" }}>
        <div className="window-pills" role="group" aria-label="Window around today">
          <span className="window-label">
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <circle cx="8" cy="8" r="2.2" fill="none" stroke="currentColor" strokeWidth="1.3"></circle>
              <path d="M3.2 8h2.4" fill="none" stroke="currentColor" strokeLinecap="round" strokeWidth="1.3"></path>
              <path d="M10.4 8h2.4" fill="none" stroke="currentColor" strokeLinecap="round" strokeWidth="1.3"></path>
              <path d="M11.6 6.8v2.4" fill="none" stroke="currentColor" strokeLinecap="round" strokeWidth="1.3"></path>
            </svg>
            ± Today
          </span>
          {(["24h", "7d", "14d", "30d"] as WindowRange[]).map((range) => (
            <button
              key={range}
              type="button"
              className={classNames("window-pill", windowRange === range && "is-active")}
              aria-pressed={windowRange === range ? "true" : "false"}
              onClick={() => handleWindowClick(range)}
            >
              {range}
            </button>
          ))}
        </div>
        <div className="query-actions">
          <span className="tiny">Last queried via troubleshooting API</span>
          <button
            className="primary compact"
            type="button"
            onClick={onRefresh}
            disabled={isQuerying}
          >
            {isQuerying ? "⟳ Querying…" : "↻ Query provider"}
          </button>
        </div>
      </div>

      <table className="table">
        <thead>
          <tr>
            <th>Event</th>
            <th>When</th>
            <th>Attendees</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {isLoading ? (
            <tr>
              <td colSpan={4} className="helper">Loading provider events…</td>
            </tr>
          ) : providerEvents.length === 0 ? (
            <tr>
              <td colSpan={4} className="helper">No provider events detected within the selected window.</td>
            </tr>
          ) : (
            providerEvents.map((row) => (
              <tr
                key={row.id}
                className={classNames(detailKey === row.id && "is-selected")}
                onClick={() => onSelectDetail(createProviderSelection(row))}
              >
                <td>{row.title}</td>
                <td>{row.when}</td>
                <td>{row.attendees}</td>
                <td>
                  <span className={classNames("pill", providerStatusClass(row.statusLabel))}>{row.statusLabel}</span>
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

function DetailDrawer({ selection, collapsed, isOpen, onToggle, onClose, onConfirmMapping, onRecreateMapping, onConfirmProviderEvent, onRecreateProviderEvent, actionState, style }: DetailDrawerProps) {
  const paneClass = classNames("panel", "split-panel", "detail-pane", collapsed && "is-collapsed");

  return (
    <section className={paneClass} data-pane="right" id="detail-pane" style={style}>
      <button
        type="button"
        className="detail-handle"
        aria-expanded={isOpen ? "true" : "false"}
        aria-controls="detail-content"
        aria-label="Toggle detail drawer"
        onClick={onToggle}
      >
        {collapsed ? "‹" : "›"}
      </button>
      <div className="panel-header">
        <div className="title">
          <span>Item Detail</span>
          <span className="detail-subtitle" id="detail-subtitle">
            {selection ? subtitleForSelection(selection) : "No selection"}
          </span>
        </div>
        <div className="panel-actions">
          <button className="ghost-button" type="button" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
      <div className="panel-body detail-scroll" id="detail-content">
        {!selection && (
          <div className="detail-empty" data-detail-state="empty">
            <div className="empty-glyph">◎</div>
            <div className="empty-title">Nothing selected</div>
            <div className="empty-copy">Choose a row from the detail pane to preview diagnostics and remediation options.</div>
          </div>
        )}
        {selection?.type === "sync-event" && <SyncEventDetailView data={selection.data} />}
        {selection?.type === "calendar-event" && (
          <ProviderEventDetailView
            data={selection.data}
            onConfirm={onConfirmProviderEvent}
            onRecreate={onRecreateProviderEvent}
            actionState={actionState}
          />
        )}
        {selection?.type === "mapping-record" && (
          <MappingDetailView
            data={selection.data}
            onConfirm={onConfirmMapping}
            onRecreate={onRecreateMapping}
            actionState={actionState}
          />
        )}
      </div>
    </section>
  );
}

function subtitleForSelection(selection: DetailSelection): string {
  switch (selection.type) {
    case "sync-event":
      return `${selection.data.status} • Sync run`;
    case "calendar-event":
      return `${selection.data.providerName} • Provider event`;
    case "mapping-record":
      return `${selection.data.syncId ?? "Orbit"} • Orbit mapping`;
    default:
      return "Item detail";
  }
}

function SyncEventDetailView({ data }: { data: SyncEventDetail }) {
  return (
    <article className="detail-view" data-detail-view="sync-event">
      <div className="detail-section">
        <div className="section-heading">Run summary</div>
        <div className="kv-grid">
          <div className="kv-item"><div className="label">Run ID</div><div className="value">{data.runId}</div></div>
          <div className="kv-item"><div className="label">Status</div><div className="value">{data.status}</div></div>
          <div className="kv-item"><div className="label">Direction</div><div className="value">{data.direction}</div></div>
          <div className="kv-item"><div className="label">Duration</div><div className="value">{data.duration}</div></div>
          <div className="kv-item"><div className="label">Started</div><div className="value">{data.startedAt}</div></div>
          <div className="kv-item"><div className="label">Finished</div><div className="value">{data.finishedAt}</div></div>
        </div>
      </div>
      <div className="detail-section">
        <div className="section-heading">Volume metrics</div>
        <div className="kv-grid">
          <div className="kv-item"><div className="label">Processed</div><div className="value">{data.eventsProcessed}</div></div>
          <div className="kv-item"><div className="label">Created</div><div className="value">{data.eventsCreated}</div></div>
          <div className="kv-item"><div className="label">Updated</div><div className="value">{data.eventsUpdated}</div></div>
          <div className="kv-item"><div className="label">Deleted</div><div className="value">{data.eventsDeleted}</div></div>
          <div className="kv-item"><div className="label">Errors</div><div className="value">{data.errors}</div></div>
          <div className="kv-item"><div className="label">Phase</div><div className="value">{data.phase}</div></div>
        </div>
      </div>
      <div className="detail-section">
        <div className="section-heading">Sync context</div>
        <div className="kv-grid">
          <div className="kv-item"><div className="label">Sync ID</div><div className="value">{data.syncId}</div></div>
          <div className="kv-item"><div className="label">Mode</div><div className="value">{data.mode}</div></div>
          <div className="kv-item"><div className="label">Source provider</div><div className="value">{data.sourceProvider}</div></div>
          <div className="kv-item"><div className="label">Target provider</div><div className="value">{data.targetProvider}</div></div>
          <div className="kv-item"><div className="label">Operation</div><div className="value">{data.operationId}</div></div>
          <div className="kv-item"><div className="label">Error message</div><div className="value">{data.errorMessage || "—"}</div></div>
        </div>
        <div className="detail-actions">
          <button className="ghost-button" type="button" onClick={() => console.log("Retry run", data.runId)}>
            Retry run
          </button>
          <button className="ghost-button" type="button" onClick={() => console.log("Inspect metrics", data.runId)}>
            Inspect metrics
          </button>
        </div>
      </div>
    </article>
  );
}

function ProviderEventDetailView({
  data,
  onConfirm,
  onRecreate,
  actionState
}: {
  data: ProviderEventDetail;
  onConfirm: (detail: ProviderEventDetail) => void;
  onRecreate: (detail: ProviderEventDetail) => void;
  actionState: ActionState | null;
}) {
  const actionTarget = data.providerEventId || data.mappingId || data.providerId;
  const confirmBusy = actionState?.type === "confirm-provider-event" && actionState.target === actionTarget;
  const recreateTarget = data.mappingId ?? "";
  const recreateBusy = actionState?.type === "recreate-provider-event" && actionState.target === recreateTarget;

  const confirmDisabled = !data.providerEventId || confirmBusy;
  const recreateDisabled = !data.mappingId || recreateBusy;

  const handleConfirm = () => {
    if (confirmDisabled) {
      return;
    }
    onConfirm(data);
  };

  const handleRecreate = () => {
    if (recreateDisabled) {
      return;
    }
    onRecreate(data);
  };

  return (
    <article className="detail-view" data-detail-view="calendar-event">
      <div className="detail-section">
        <div className="section-heading">Provider event</div>
        <div className="kv-grid">
          <div className="kv-item"><div className="label">Provider event ID</div><div className="value">{data.providerEventId}</div></div>
          <div className="kv-item"><div className="label">Provider</div><div className="value">{data.providerName}</div></div>
          <div className="kv-item"><div className="label">Provider ID</div><div className="value">{data.providerId}</div></div>
          <div className="kv-item"><div className="label">Status</div><div className="value">{data.status}</div></div>
          <div className="kv-item"><div className="label">Tombstoned</div><div className="value">{data.tombstoned}</div></div>
          <div className="kv-item"><div className="label">Last seen</div><div className="value">{data.providerLastSeen}</div></div>
        </div>
      </div>
      <div className="detail-section">
        <div className="section-heading">Timing</div>
        <div className="kv-grid">
          <div className="kv-item"><div className="label">Title</div><div className="value">{data.title}</div></div>
          <div className="kv-item"><div className="label">Starts</div><div className="value">{data.startAt}</div></div>
          <div className="kv-item"><div className="label">Ends</div><div className="value">{data.endAt}</div></div>
          <div className="kv-item"><div className="label">Updated</div><div className="value">{data.updatedAt}</div></div>
        </div>
      </div>
      <div className="detail-section">
        <div className="section-heading">Orbit context</div>
        <div className="kv-grid">
          <div className="kv-item"><div className="label">Orbit event</div><div className="value">{data.orbitEventId}</div></div>
          <div className="kv-item"><div className="label">Sync</div><div className="value">{data.syncId || "—"}</div></div>
          <div className="kv-item"><div className="label">Mapping ID</div><div className="value">{data.mappingId || "—"}</div></div>
        </div>
        <div className="detail-actions">
          <button className="ghost-button" type="button" disabled={confirmDisabled} onClick={handleConfirm}>
            {confirmBusy ? "Confirming…" : "Confirm presence"}
          </button>
          <button className="ghost-button" type="button" disabled={recreateDisabled} onClick={handleRecreate}>
            {recreateBusy ? "Recreating…" : "Recreate from Orbit"}
          </button>
        </div>
      </div>
    </article>
  );
}

function MappingDetailView({
  data,
  onConfirm,
  onRecreate,
  actionState
}: {
  data: MappingDetailData;
  onConfirm: (mapping: SyncMappingRow, segment: SyncMappingSegment) => void;
  onRecreate: (mapping: SyncMappingRow, segment: SyncMappingSegment) => void;
  actionState: ActionState | null;
}) {
  const selectedSegment =
    data.segments.find((segment) => segment.mappingId === data.selectedSegmentId) ??
    data.segments.find((segment) => segment.providerId === data.selectedProviderId) ??
    data.segments[0];

  const mappingRecord: SyncMappingRow = {
    id: data.id,
    event: data.title,
    eventTime: data.eventTime ?? data.startAt ?? data.endAt ?? "—",
    lastSynced: data.lastMergedAt ?? "—",
    orbitEventId: data.orbitEventId,
    notes: data.notes,
    segments: data.segments,
    startAt: data.startAt,
    endAt: data.endAt,
    lastMergedAt: data.lastMergedAt,
    syncId: data.syncId ?? null,
  };

  const confirmTarget = selectedSegment
    ? selectedSegment.mappingId || `${selectedSegment.providerId}:${selectedSegment.providerUid ?? ""}`
    : "";
  const recreateTarget = selectedSegment?.mappingId ?? "";

  const confirmBusy = actionState?.type === "confirm-mapping" && actionState.target === confirmTarget;
  const recreateBusy = actionState?.type === "recreate-mapping" && actionState.target === recreateTarget;

  const confirmDisabled = !selectedSegment || !selectedSegment.providerUid || confirmBusy;
  const recreateDisabled = !selectedSegment || !selectedSegment.mappingId || recreateBusy;

  const handleConfirm = () => {
    if (!selectedSegment || confirmDisabled) {
      return;
    }
    onConfirm(mappingRecord, selectedSegment);
  };

  const handleRecreate = () => {
    if (!selectedSegment || recreateDisabled) {
      return;
    }
    onRecreate(mappingRecord, selectedSegment);
  };

  return (
    <article className="detail-view" data-detail-view="mapping-record">
      <div className="detail-section">
        <div className="section-heading">Orbit event</div>
        <div className="kv-grid">
          <div className="kv-item"><div className="label">Orbit event ID</div><div className="value">{data.orbitEventId}</div></div>
          <div className="kv-item"><div className="label">Title</div><div className="value">{data.title}</div></div>
          <div className="kv-item"><div className="label">Starts</div><div className="value">{data.startAt ?? "—"}</div></div>
          <div className="kv-item"><div className="label">Ends</div><div className="value">{data.endAt ?? "—"}</div></div>
          <div className="kv-item"><div className="label">Sync</div><div className="value">{data.syncId ?? "—"}</div></div>
          <div className="kv-item"><div className="label">Last merged</div><div className="value">{data.lastMergedAt ?? "—"}</div></div>
        </div>
      </div>
      <div className="detail-section">
        <div className="section-heading">Provider segments</div>
        <div className="segment-grid">
          {data.segments.map((segment) => {
            const isActive = selectedSegment && segment.mappingId === selectedSegment.mappingId;
            return (
              <div
                key={`${segment.mappingId}:${segment.providerId}`}
                className={classNames("segment-card", isActive && "is-active")}
                style={isActive ? { borderColor: "var(--accent)", boxShadow: "0 0 0 1px var(--accent)" } : undefined}
              >
                <div className="segment-label">{segment.role}</div>
                <div className="segment-meta">{segment.providerLabel}</div>
                <div className="kv-item">
                  <div className="label">UID</div>
                  <div className="value">{segment.providerUid || "—"}</div>
                </div>
                <div className="kv-item">
                  <div className="label">Last seen</div>
                  <div className="value">{segment.lastSeen}</div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
      <div className="detail-section">
        <div className="section-heading">Notes</div>
        <div className="kv-item">
          <div className="label">Narrative</div>
          <div className="value">{data.notes ? data.notes : "—"}</div>
        </div>
        <div className="detail-actions">
          <button className="ghost-button" type="button" disabled={confirmDisabled} onClick={handleConfirm}>
            {confirmBusy ? "Confirming…" : "Confirm provider state"}
          </button>
          <button className="ghost-button" type="button" disabled={recreateDisabled} onClick={handleRecreate}>
            {recreateBusy ? "Recreating…" : "Replay to provider"}
          </button>
        </div>
      </div>
    </article>
  );
}

function OperationsStrip({ operations, isLoading, error, style }: { operations: OperationRow[]; isLoading: boolean; error: string | null; style?: CSSProperties }) {
  return (
    <section className="operations-strip" style={style}>
      <table>
        <thead>
          <tr>
            <th>Task</th>
            <th>Status</th>
            <th>Resource</th>
            <th>Created</th>
            <th>Started</th>
            <th>Finished</th>
          </tr>
        </thead>
        <tbody>
          {isLoading ? (
            <tr>
              <td colSpan={6} className="helper">Loading operations…</td>
            </tr>
          ) : error ? (
            <tr>
              <td colSpan={6} className="helper" style={{ color: "var(--color-danger)" }}>{error}</td>
            </tr>
          ) : operations.length === 0 ? (
            <tr>
              <td colSpan={6} className="helper">No recent operations to display.</td>
            </tr>
          ) : (
            operations.map((operation) => (
              <tr key={operation.id}>
                <td>{operation.id}</td>
                <td>
                  <span
                    className={classNames(
                      "pill",
                      operation.status === "failed" && "pill-critical",
                      operation.status === "succeeded" && "pill-success",
                      operation.status === "running" && "pill-info"
                    )}
                  >
                    {operation.status}
                  </span>
                </td>
                <td>{operation.resource}</td>
                <td>{operation.created}</td>
                <td>{operation.started}</td>
                <td>{operation.finished}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </section>
  );
}

export { MappingDetailView, ProviderEventDetailView, SyncMappingsTable };
export default Ui2WorkspacePage;
