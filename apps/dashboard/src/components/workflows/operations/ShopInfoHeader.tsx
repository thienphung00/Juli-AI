"use client";

import type { ShopMetadata } from "@/lib/mock-data/operations/schemas";
import { resolveShopStatusLabel } from "@/lib/metrics/shop-health-metrics";

/** Compact shop context for the page header (replaces workflow subtitle). */
export function ShopInfoHeader({ metadata }: { metadata: ShopMetadata }) {
  const statusLabel = resolveShopStatusLabel(metadata);

  return (
    <div
      className="mt-0.5 flex flex-wrap items-center gap-2"
      data-testid="shop-info-card"
    >
      <p className="truncate text-sm font-semibold" style={{ color: "var(--foreground)" }}>
        {metadata.shop_name}
      </p>
      <span
        className="inline-flex shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold"
        style={{
          background: "color-mix(in srgb, var(--brand-primary) 12%, transparent)",
          color: "var(--brand-primary)",
        }}
        data-testid="shop-info-status"
      >
        {statusLabel}
      </span>
    </div>
  );
}
