"use client";

import { useWorkspaceModeOptional } from "@/lib/mode-context";
import type { WorkspaceMode } from "@/lib/workspace-mode";

const MODE_LABELS: Record<WorkspaceMode, string> = {
  seller: "Người bán",
  affiliate: "Affiliate",
};

export function ModeSwitcher() {
  const ctx = useWorkspaceModeOptional();
  if (!ctx?.mode) return null;

  const { mode, setMode } = ctx;

  const nextMode: WorkspaceMode = mode === "seller" ? "affiliate" : "seller";

  return (
    <button
      type="button"
      aria-label="Chuyển chế độ workspace"
      onClick={() => setMode(nextMode)}
      className="rounded-full px-3 py-1.5 text-xs font-semibold transition-opacity hover:opacity-90"
      style={{
        background: "var(--muted)",
        color: "var(--foreground)",
        border: "1px solid var(--border)",
      }}
    >
      {MODE_LABELS[mode]}
    </button>
  );
}
