"use client";

import { AuthenticatedShell } from "./AuthenticatedShell";

export function TrendsPage() {
  return (
    <AuthenticatedShell title="Xu hướng">
      <p className="text-sm" style={{ color: "var(--muted-foreground)" }}>
        Khám phá sản phẩm, creator và shop đang trending — nội dung chi tiết sẽ có ở issue tiếp theo.
      </p>
    </AuthenticatedShell>
  );
}
