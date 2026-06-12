"use client";

import { AuthenticatedShell } from "./AuthenticatedShell";

/** Placeholder shell for Decisions tab — sub-tabs land in follow-up issues (#192+). */
export function DecisionsPage() {
  return (
    <AuthenticatedShell title="Quyết định">
      <div
        className="rounded-2xl border p-6 text-center"
        style={{ borderColor: "var(--border)", background: "var(--card)" }}
        data-testid="decisions-shell-placeholder"
      >
        <p className="text-sm" style={{ color: "var(--muted-foreground)" }}>
          Nội dung quyết định sẽ có trong các bản cập nhật tiếp theo.
        </p>
      </div>
    </AuthenticatedShell>
  );
}
