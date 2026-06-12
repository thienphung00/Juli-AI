"use client";

import { formatNumber } from "@/lib/format";
import type { ShopProfileType } from "@/lib/mock-data/operations/schemas";

import type { ShopHealthSummary } from "@/lib/operations/health-summary";
import type { HealthCheckResults } from "@/lib/operations/health-check";

export function ShopHealthHero({
  shopName,
  profile,
  health,
  summary,
}: {
  shopName: string;
  profile: ShopProfileType;
  health: HealthCheckResults;
  summary: ShopHealthSummary;
}) {
  const profileLabel =
    profile === "NEW_SHOP" ? "Shop mới (probation)" : "Shop trung/lớn";

  return (
    <section className="card p-4" data-testid="shop-health-hero">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-muted text-xs font-medium uppercase tracking-wide">
            Sức khỏe cửa hàng
          </p>
          <h2 className="mt-1 text-lg font-bold" style={{ color: "var(--foreground)" }}>
            {shopName}
          </h2>
          <p className="text-muted mt-1 text-sm" data-testid="shop-health-profile">
            {profileLabel}
          </p>
        </div>
        <div className="text-right">
          <p className="text-muted text-xs font-medium uppercase tracking-wide">Điểm sức khỏe</p>
          <p
            className="mt-1 text-2xl font-bold tabular-nums"
            data-testid="shop-health-score"
            style={{ color: "var(--brand-primary)" }}
          >
            {summary.score}
          </p>
        </div>
      </div>

      <div
        className="mt-4 h-2 overflow-hidden rounded-full"
        style={{ background: "color-mix(in srgb, var(--brand-primary) 18%, transparent)" }}
        role="progressbar"
        aria-valuenow={summary.score}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Điểm sức khỏe cửa hàng"
      >
        <div
          className="h-full rounded-full transition-all"
          style={{
            width: `${summary.score}%`,
            background: "var(--brand-primary)",
          }}
          data-testid="shop-health-progress"
        />
      </div>

      <dl className="mt-4 grid grid-cols-3 gap-2 text-center text-sm">
        <div data-testid="shop-health-critical">
          <dt className="text-muted text-xs">Nguy cấp</dt>
          <dd className="font-semibold" style={{ color: "var(--loss)" }}>
            {formatNumber(summary.criticalCount)}
          </dd>
        </div>
        <div data-testid="shop-health-warning">
          <dt className="text-muted text-xs">Cảnh báo</dt>
          <dd className="font-semibold" style={{ color: "var(--warning)" }}>
            {formatNumber(summary.warningCount)}
          </dd>
        </div>
        <div data-testid="shop-health-healthy">
          <dt className="text-muted text-xs">Ổn định</dt>
          <dd className="font-semibold" style={{ color: "var(--success)" }}>
            {formatNumber(summary.healthyCount)}
          </dd>
        </div>
      </dl>

      <p className="text-muted sr-only" data-testid="shop-health-computed-at">
        Cập nhật lúc {health.computed_at}
      </p>
    </section>
  );
}
