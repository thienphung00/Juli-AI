"use client";

import { useCallback, useEffect, useState } from "react";
import { FlaskConical, X } from "lucide-react";
import { PersonaSwitcher } from "./seller-home";
import { useDemoPersonaOptional } from "@/lib/demo-persona-context";
import { useWorkspaceModeOptional } from "@/lib/mode-context";

export function DemoControlsDrawer() {
  const modeContext = useWorkspaceModeOptional();
  const personaContext = useDemoPersonaOptional();
  const [open, setOpen] = useState(false);

  const close = useCallback(() => setOpen(false), []);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, close]);

  if (modeContext?.mode !== "seller" || !personaContext) {
    return null;
  }

  return (
    <>
      <button
        type="button"
        aria-label="Mở cài đặt demo"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex h-11 w-11 items-center justify-center rounded-full transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]"
        style={{ background: "var(--muted)", border: "1px solid var(--border)" }}
        data-testid="demo-controls-button"
      >
        <FlaskConical size={18} style={{ color: "var(--muted-foreground)" }} aria-hidden />
      </button>

      {open && (
        <button
          type="button"
          aria-label="Đóng cài đặt demo"
          className="fixed inset-0 z-[60] bg-black/40"
          onClick={close}
        />
      )}
      <div
        role="dialog"
        aria-modal={open}
        aria-label="Cài đặt demo"
        className={
          open
            ? "fixed inset-x-0 bottom-0 z-[70] mx-auto max-h-[50vh] max-w-lg overflow-y-auto rounded-t-2xl p-4 shadow-xl safe-area-bottom md:inset-x-auto md:bottom-auto md:right-4 md:top-20 md:max-h-[calc(100vh-6rem)] md:w-80 md:rounded-2xl"
            : "sr-only"
        }
        style={{ background: "var(--card)", borderTop: "1px solid var(--border)" }}
        data-testid="demo-controls-drawer"
      >
            <div
              className="mx-auto mb-3 h-1 w-10 rounded-full md:hidden"
              style={{ background: "var(--border)" }}
              aria-hidden
            />
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-base font-bold" style={{ color: "var(--foreground)" }}>
                Demo persona
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
            <p className="mb-3 text-xs" style={{ color: "var(--muted-foreground)" }}>
              Chọn persona để xem luồng công việc khác nhau trong bản demo.
            </p>
        <PersonaSwitcher />
      </div>
    </>
  );
}
