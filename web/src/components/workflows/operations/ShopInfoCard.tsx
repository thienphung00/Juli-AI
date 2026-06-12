"use client";

import type { ShopMetadata } from "@/lib/mock-data/operations/schemas";
import { resolveShopStatusLabel } from "@/lib/metrics/shop-health-metrics";

export function ShopInfoCard({ metadata }: { metadata: ShopMetadata }) {
  const statusLabel = resolveShopStatusLabel(metadata);

  return (
    <section className="card p-4" data-testid="shop-info-card">
      <p className="text-muted text-xs font-medium uppercase tracking-wide">Thông tin cửa hàng</p>
      <h2 className="mt-1 text-lg font-bold" style={{ color: "var(--foreground)" }}>
        {metadata.shop_name}
      </h2>
      <p
        className="mt-2 inline-flex rounded-full px-2.5 py-0.5 text-xs font-semibold"
        style={{
          background: "color-mix(in srgb, var(--brand-primary) 12%, transparent)",
          color: "var(--brand-primary)",
        }}
        data-testid="shop-info-status"
      >
        {statusLabel}
      </p>
    </section>
  );
}
