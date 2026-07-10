"use client";

import { useCallback, useEffect, useState } from "react";
import { Bell, X } from "lucide-react";
import { useWorkspaceModeOptional } from "@/lib/mode-context";
import type { WorkspaceAlert } from "@/lib/services/alerts";
import { getWorkspaceAlerts } from "@/lib/services/alerts";

export function AlertBell() {
  const ctx = useWorkspaceModeOptional();
  const mode = ctx?.mode ?? null;
  const [open, setOpen] = useState(false);
  const [alerts, setAlerts] = useState<WorkspaceAlert[]>([]);

  const close = useCallback(() => setOpen(false), []);

  useEffect(() => {
    if (!mode) {
      setAlerts([]);
      return;
    }

    const workspaceMode = mode;
    let cancelled = false;

    async function load() {
      try {
        const next = await getWorkspaceAlerts(workspaceMode);
        if (!cancelled) setAlerts(next);
      } catch (error) {
        console.error("alerts_load_failed", { error });
        if (!cancelled) setAlerts([]);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [mode]);

  const count = alerts.length;

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, close]);

  return (
    <>
      <button
        type="button"
        aria-label="Cảnh báo"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="relative flex h-11 w-11 items-center justify-center rounded-full transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]"
        style={{ background: "var(--muted)", border: "1px solid var(--border)" }}
        data-testid="alert-bell-button"
      >
        <Bell size={18} style={{ color: "var(--foreground)" }} />
        {count > 0 && (
          <span
            className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-[10px] font-bold text-white"
            style={{ background: "var(--primary)" }}
            data-testid="alert-bell-badge"
          >
            {count}
          </span>
        )}
      </button>

      {open && (
        <>
          <button
            type="button"
            aria-label="Đóng danh sách cảnh báo"
            className="fixed inset-0 z-[60] bg-black/40"
            onClick={close}
          />
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Danh sách cảnh báo"
            className="fixed inset-x-0 bottom-0 z-[70] mx-auto max-h-[70vh] max-w-lg overflow-y-auto rounded-t-2xl p-4 shadow-xl safe-area-bottom md:inset-x-auto md:bottom-4 md:right-4 md:top-20 md:max-h-[calc(100vh-6rem)] md:w-96 md:rounded-2xl"
            style={{ background: "var(--card)", borderTop: "1px solid var(--border)" }}
            data-testid="alert-bell-drawer"
          >
            <div
              className="mx-auto mb-3 h-1 w-10 rounded-full md:hidden"
              style={{ background: "var(--border)" }}
              aria-hidden
            />
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-base font-bold" style={{ color: "var(--foreground)" }}>
                Cảnh báo
              </h2>
              <button
                type="button"
                aria-label="Đóng"
                onClick={close}
                className="flex h-8 w-8 items-center justify-center rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]"
                style={{ background: "var(--muted)" }}
              >
                <X size={16} />
              </button>
            </div>
            {alerts.length === 0 ? (
              <p className="py-6 text-center text-sm text-muted">Không có cảnh báo mới.</p>
            ) : (
              <ul className="space-y-3">
                {alerts.map((alert) => (
                  <li
                    key={alert.id}
                    className="rounded-xl border-l-4 p-3"
                    style={{
                      background: "var(--muted)",
                      borderColor: "var(--primary)",
                      borderLeftWidth: "4px",
                      borderTop: "1px solid var(--border)",
                      borderRight: "1px solid var(--border)",
                      borderBottom: "1px solid var(--border)",
                    }}
                    data-testid={`alert-bell-item-${alert.id}`}
                  >
                    <p className="text-sm font-semibold" style={{ color: "var(--foreground)" }}>
                      {alert.title}
                    </p>
                    <p
                      className="mt-1 text-xs"
                      style={{ color: "var(--muted-foreground)" }}
                      data-testid={`alert-bell-message-${alert.id}`}
                    >
                      {alert.message}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </>
  );
}
