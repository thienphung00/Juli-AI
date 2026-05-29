"use client";

import { AuthenticatedShell } from "./AuthenticatedShell";

export function AiChatPage() {
  return (
    <AuthenticatedShell title="Juli">
      <p className="text-sm" style={{ color: "var(--muted-foreground)" }}>
        Trò chuyện với Juli AI — giao diện chat đầy đủ sẽ có ở issue tiếp theo.
      </p>
    </AuthenticatedShell>
  );
}
