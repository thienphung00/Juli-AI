"use client";

import { AuthenticatedShell } from "./AuthenticatedShell";

export function OperationPage() {
  return (
    <AuthenticatedShell title="Vận hành">
      <p className="text-sm" style={{ color: "var(--muted-foreground)" }}>
        Trung tâm vận hành — sản phẩm, đơn hàng, creator và hoàn trả sẽ được gom tại đây ở issue tiếp theo.
      </p>
    </AuthenticatedShell>
  );
}
