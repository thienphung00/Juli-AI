"use client";

import type { SellerPersona } from "@/lib/mock-data/seller-personas/schemas";
import { formatNumber, formatVND } from "@/lib/format";
import { computeAdSummary } from "@/lib/workflows/growth/ad-summary";

export function AdPerformanceSummary({ persona }: { persona: SellerPersona }) {
  const summary = computeAdSummary(persona);

  return (
    <div className="card p-4" data-testid="ad-performance-summary">
      <h3 className="text-sm font-semibold">Tổng quan quảng cáo 30 ngày</h3>
      <p className="text-muted mt-1 text-xs">
        {summary.activeCampaignCount} chiến dịch đang chạy · dữ liệu demo
      </p>

      <dl className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div>
          <dt className="text-muted text-xs">Chi tiêu</dt>
          <dd className="mt-1 text-sm font-semibold" data-testid="ad-summary-spend">
            {formatVND(summary.totalSpendVnd)}
          </dd>
        </div>
        <div>
          <dt className="text-muted text-xs">ROAS TB</dt>
          <dd className="mt-1 text-sm font-semibold" data-testid="ad-summary-roas">
            {summary.avgRoas.toFixed(1)}×
          </dd>
        </div>
        <div>
          <dt className="text-muted text-xs">CPC TB</dt>
          <dd className="mt-1 text-sm font-semibold" data-testid="ad-summary-cpc">
            {formatVND(summary.avgCpcVnd)}
          </dd>
        </div>
        <div>
          <dt className="text-muted text-xs">Chuyển đổi</dt>
          <dd className="mt-1 text-sm font-semibold" data-testid="ad-summary-conversions">
            {formatNumber(summary.totalConversions)}
          </dd>
        </div>
      </dl>
    </div>
  );
}
