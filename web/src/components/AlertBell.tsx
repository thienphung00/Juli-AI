"use client";

import { useCallback, useEffect, useState } from "react";
import { Bell, X } from "lucide-react";
import { MOCK_HEADER_ALERTS } from "@/lib/mock-data/header-alerts";

export function AlertBell() {
  const [open, setOpen] = useState(false);
  const count = MOCK_HEADER_ALERTS.length;

  const close = useCallback(() => setOpen(false), []);

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
        className="relative flex h-9 w-9 items-center justify-center rounded-full transition-opacity hover:opacity-90"
        style={{ background: "var(--muted)", border: "1px solid var(--border)" }}
      >
        <Bell size={18} style={{ color: "var(--foreground)" }} />
        {count > 0 && (
          <span
            className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-[10px] font-bold text-white"
            style={{ background: "var(--primary)" }}
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
            className="fixed inset-x-0 bottom-0 z-[70] mx-auto max-h-[70vh] max-w-lg overflow-y-auto rounded-t-2xl p-4 shadow-xl safe-area-bottom"
            style={{ background: "var(--card)", borderTop: "1px solid var(--border)" }}
          >
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-base font-bold" style={{ color: "var(--foreground)" }}>
                Cảnh báo
              </h2>
              <button
                type="button"
                aria-label="Đóng"
                onClick={close}
                className="flex h-8 w-8 items-center justify-center rounded-full"
                style={{ background: "var(--muted)" }}
              >
                <X size={16} />
              </button>
            </div>
            <ul className="space-y-3">
              {MOCK_HEADER_ALERTS.map((alert) => (
                <li
                  key={alert.id}
                  className="rounded-xl p-3"
                  style={{ background: "var(--muted)", border: "1px solid var(--border)" }}
                >
                  <p className="text-sm font-semibold" style={{ color: "var(--foreground)" }}>
                    {alert.title}
                  </p>
                  <p className="mt-1 text-xs" style={{ color: "var(--muted-foreground)" }}>
                    {alert.message}
                  </p>
                </li>
              ))}
            </ul>
          </div>
        </>
      )}
    </>
  );
}
