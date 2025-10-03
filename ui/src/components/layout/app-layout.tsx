import { useEffect, useMemo, useRef, useState } from "react";
import { Navigate, NavLink, Outlet, useLocation } from "react-router-dom";
import { Activity, ArrowLeftRight, ChevronDown, Menu, Moon, Sparkles, Sun, LogOut, User } from "lucide-react";

import { Button } from "../ui/button";
import { Badge } from "../ui/badge";
import { OrbitApiError } from "../../lib/api";
import { statusBadgeVariant, statusLabel } from "../../lib/providers";
import type { ReadyResponse, HealthResponse } from "../../types/api";
import { cn } from "../../lib/utils";
import { useApi } from "../../lib/api-context";

type SystemStatus = {
  label: string;
  status: string;
  detail?: string | null;
};

const NAV_ITEMS = [
  { label: "Dashboard", to: "/" },
  { label: "Syncs", to: "/syncs" },
  { label: "Providers", to: "/providers" },
  { label: "Admin", to: "/admin" }
];

function Sidebar({
  open,
  onClose,
  systemStatus,
}: {
  open: boolean;
  onClose: () => void;
  systemStatus: SystemStatus[] | null;
}) {
  return (
    <>
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-30 w-72 shrink-0 border-r border-border-subtle bg-[var(--color-surface)] px-6 py-8 transition-transform duration-200 ease-in-out md:static md:z-auto md:flex md:translate-x-0",
          open ? "translate-x-0" : "-translate-x-full md:translate-x-0"
        )}
      >
        <div className="flex h-full flex-col">
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2 text-xl font-semibold text-[var(--color-text-strong)]">
              <Sparkles className="h-6 w-6 text-[var(--accent-600)]" />
              Orbit
            </div>
            <p className="text-xs text-[var(--color-text-soft)]">Orbit service console</p>
          </div>

          <nav className="mt-8 flex flex-1 flex-col gap-1">
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                onClick={onClose}
                className={({ isActive }) =>
                  cn(
                    "rounded-md px-3 py-2 text-sm font-medium transition-colors",
                    isActive
                      ? "bg-[var(--color-hover)] text-[var(--color-text-strong)] shadow-elev-1"
                      : "text-[var(--color-text-soft)] hover:bg-[var(--color-hover)] hover:text-[var(--color-text-strong)]"
                  )
                }
                end={item.to === "/"}
              >
                <span>{item.label}</span>
              </NavLink>
            ))}
          </nav>

          <div className="space-y-4 border-t border-border-subtle pt-6 text-xs text-[var(--color-text-soft)]">
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-[var(--color-text-strong)]">
                <Activity className="h-3.5 w-3.5 text-[var(--accent-600)]" />
                System health
              </div>
              <div className="space-y-1">
                {systemStatus === null ? (
                  <span className="text-[var(--color-text-muted)]">Checking…</span>
                ) : systemStatus.length === 0 ? (
                  <span className="text-[var(--color-text-muted)]">No telemetry available</span>
                ) : (
                  systemStatus.map((item) => (
                    <div key={item.label} className="flex items-center justify-between text-[11px]">
                      <span>{item.label}</span>
                      <Badge
                        variant={statusBadgeVariant(item.status)}
                        title={item.detail ?? undefined}
                      >
                        {statusLabel(item.status)}
                      </Badge>
                    </div>
                  ))
                )}
              </div>
            </div>
            <div className="flex items-center justify-between">
              <span>Environment</span>
              <Badge variant="outline">Dev</Badge>
            </div>
          </div>
        </div>
      </aside>
      {open && (
        <div
          className="fixed inset-0 z-20 bg-[var(--color-text)]/40 backdrop-blur-sm md:hidden"
          onClick={onClose}
        />
      )}
    </>
  );
}
export function AppLayout() {
  const { auth, logout, client } = useApi();
  const location = useLocation();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [systemStatus, setSystemStatus] = useState<SystemStatus[] | null>(null);
  const [darkMode, setDarkMode] = useState<boolean>(() => {
    if (typeof window === "undefined") {
      return false;
    }
    const stored = window.sessionStorage.getItem("orbit-ui-theme");
    if (stored === "dark") {
      return true;
    }
    if (stored === "light") {
      return false;
    }
    const media = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
    return media?.matches ?? false;
  });
  const [profileMenuOpen, setProfileMenuOpen] = useState(false);
  const profileMenuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const root = document.documentElement;
    if (darkMode) {
      root.classList.add("dark");
    } else {
      root.classList.remove("dark");
    }
    if (typeof window !== "undefined") {
      window.sessionStorage.setItem("orbit-ui-theme", darkMode ? "dark" : "light");
    }
  }, [darkMode]);

  useEffect(() => {
    setMobileNavOpen(false);
    setProfileMenuOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    function handleDocumentMouseDown(event: MouseEvent) {
      if (!profileMenuRef.current || !(event.target instanceof Node)) {
        return;
      }
      if (!profileMenuRef.current.contains(event.target)) {
        setProfileMenuOpen(false);
      }
    }

    function handleDocumentKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setProfileMenuOpen(false);
      }
    }

    document.addEventListener("mousedown", handleDocumentMouseDown);
    document.addEventListener("keydown", handleDocumentKeyDown);
    return () => {
      document.removeEventListener("mousedown", handleDocumentMouseDown);
      document.removeEventListener("keydown", handleDocumentKeyDown);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function loadStatus() {
      setSystemStatus(null);

      let readiness: ReadyResponse | null = null;
      let readinessError: unknown = null;
      try {
        readiness = await client.ready();
      } catch (error) {
        readinessError = error;
        if (error instanceof OrbitApiError && error.status === 503) {
          const detail = (error.body as { detail?: ReadyResponse })?.detail;
          if (detail && typeof detail === "object") {
            readiness = detail as ReadyResponse;
          }
        }
      }

  let health: HealthResponse | null = null;
      let healthError: unknown = null;
      try {
        health = await client.health();
      } catch (error) {
        healthError = error;
      }

      if (cancelled) {
        return;
      }

      const statuses: SystemStatus[] = [];

      if (health) {
        const isHealthy = (health.status ?? "").toLowerCase() === "ok";
        statuses.push({
          label: "API service",
          status: isHealthy ? "active" : health.status ?? "unknown",
          detail: health.service ? `Service ${health.service}` : undefined,
        });
      } else if (healthError) {
        statuses.push({
          label: "API service",
          status: "error",
          detail: healthError instanceof Error ? healthError.message : "Health check failed",
        });
      }

      if (readiness) {
        statuses.push({
          label: "Overall readiness",
          status: readiness.status,
          detail: readiness.reason ?? null,
        });

        const providerStatuses = Array.isArray(readiness.providers) ? readiness.providers : [];
        if (providerStatuses.length > 0) {
          const normalize = (status?: string | null) => (status ?? "").toLowerCase();
          const healthyCount = providerStatuses.filter((provider) => {
            const normalized = normalize(provider.status);
            return normalized === "connected" || normalized === "active" || normalized === "ready" || normalized === "ok";
          }).length;
          const degradedCount = providerStatuses.filter((provider) => {
            const normalized = normalize(provider.status);
            return normalized === "degraded" || normalized === "warning" || normalized === "unstable";
          }).length;
          const errorCount = providerStatuses.length - healthyCount - degradedCount;

          let providerStatus: string = "active";
          if (errorCount > 0) {
            providerStatus = "error";
          } else if (degradedCount > 0) {
            providerStatus = "degraded";
          } else if (healthyCount === 0) {
            providerStatus = "unknown";
          }

          const detailParts: string[] = [];
          detailParts.push(`${healthyCount}/${providerStatuses.length} healthy`);
          if (degradedCount > 0) {
            detailParts.push(`${degradedCount} degraded`);
          }
          if (errorCount > 0) {
            detailParts.push(`${errorCount} error`);
          }

          statuses.push({
            label: "Providers",
            status: providerStatus,
            detail: detailParts.join(", "),
          });
        }
      } else if (readinessError) {
        statuses.push({
          label: "Overall readiness",
          status: "error",
          detail: readinessError instanceof Error ? readinessError.message : "Readiness check failed",
        });
      }

      setSystemStatus(statuses);
    }
    loadStatus();
    return () => {
      cancelled = true;
    };
  }, [client]);

  const activeNav = useMemo(() => {
    return NAV_ITEMS.find((item) => (item.to === "/" ? location.pathname === "/" : location.pathname.startsWith(item.to))) ?? NAV_ITEMS[0];
  }, [location.pathname]);

  if (auth.status !== "authenticated") {
    return <Navigate to="/login" state={{ from: location.pathname + location.search }} replace />;
  }

  const username = auth.status === "authenticated" ? auth.tokens.username ?? "admin" : "";

  return (
    <div className="flex min-h-screen bg-[var(--color-bg)]">
      <Sidebar open={mobileNavOpen} onClose={() => setMobileNavOpen(false)} systemStatus={systemStatus} />
      <div className="flex flex-1 flex-col">
        <header className="flex items-center justify-between gap-3 border-b border-border-subtle bg-[var(--color-surface)]/90 px-4 py-3 backdrop-blur md:px-6">
          <div className="flex items-center gap-3 md:hidden">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setMobileNavOpen((value) => !value)}
              className="px-2"
            >
              <Menu className="h-5 w-5 text-[var(--color-text-soft)]" />
            </Button>
            <span className="font-semibold text-[var(--color-text-strong)]">{activeNav.label}</span>
          </div>
          <div className="hidden md:flex items-center gap-2 text-sm text-[var(--color-text-soft)]">
            <ArrowLeftRight className="h-4 w-4" />
            <span className="text-[var(--color-text-strong)]">{activeNav.label}</span>
          </div>
          <div className="ml-auto relative" ref={profileMenuRef}>
            <Button
              variant="outline"
              size="sm"
              className="inline-flex items-center gap-2"
              onClick={() => setProfileMenuOpen((value) => !value)}
              aria-haspopup="menu"
              aria-expanded={profileMenuOpen}
            >
              <User className="h-4 w-4" />
              <span className="hidden text-xs font-medium text-[var(--color-text-strong)] sm:inline">{username}</span>
              <ChevronDown className="h-4 w-4 text-[var(--color-text-soft)]" />
            </Button>
            {profileMenuOpen && (
              <div className="absolute right-0 mt-2 w-64 rounded-[var(--radius-2)] border border-border-subtle bg-[var(--color-surface)] shadow-elev-3">
                <div className="space-y-1 border-b border-border-subtle px-3 py-2">
                  <p className="text-[11px] uppercase tracking-wide text-[var(--color-text-muted)]">Signed in as</p>
                  <p className="text-sm font-medium text-[var(--color-text-strong)]">{username}</p>
                </div>
                <div className="flex flex-col gap-1 p-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="justify-start gap-2 text-sm"
                    onClick={() => {
                      setDarkMode((value) => !value);
                      setProfileMenuOpen(false);
                    }}
                  >
                    {darkMode ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
                    <span>{darkMode ? "Switch to light mode" : "Switch to dark mode"}</span>
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="justify-start gap-2 text-sm text-[var(--color-danger)] hover:text-[var(--color-danger)]"
                    onClick={() => {
                      setProfileMenuOpen(false);
                      logout();
                    }}
                  >
                    <LogOut className="h-4 w-4" />
                    <span>Sign out</span>
                  </Button>
                </div>
              </div>
            )}
          </div>
        </header>
        <div className="h-1 bg-[linear-gradient(90deg,var(--accent-700),var(--accent-500))]" />
        <main className="flex flex-1 flex-col gap-6 bg-[var(--color-bg)] px-4 py-6 md:px-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
