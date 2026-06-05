"use client";

import type { SellerProfile } from "@/lib/mock-data/seller-personas/schemas";
import { formatVND } from "@/lib/format";
import { computeFirstSaleMilestone } from "@/lib/workflows/new-seller/milestone";

export function MilestoneProgress({ profile }: { profile: SellerProfile }) {
  const milestone = computeFirstSaleMilestone(profile);

  return (
    <div
      className="rounded-xl border p-4"
      style={{ borderColor: "var(--border)" }}
      data-testid="first-sale-milestone"
    >
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold" style={{ color: "var(--foreground)" }}>
          Tiến độ đơn hàng đầu tiên
        </h3>
        <span
          className="text-sm font-bold"
          style={{ color: "#10b981" }}
          data-testid="milestone-percent"
        >
          {milestone.percent}%
        </span>
      </div>

      <div
        className="mt-3 h-2 w-full overflow-hidden rounded-full"
        style={{ background: "var(--border)" }}
        role="progressbar"
        aria-valuenow={milestone.percent}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Tiến độ đơn hàng đầu tiên"
        data-testid="milestone-progress-bar"
      >
        <div
          className="h-full rounded-full transition-all"
          style={{
            width: `${milestone.percent}%`,
            background: "linear-gradient(135deg, #10b981 0%, #34d399 100%)",
          }}
        />
      </div>

      <p className="text-muted mt-2 text-xs">
        {milestone.hasFirstSale
          ? "Bạn đã đạt đơn hàng có lãi đầu tiên — tiếp tục hoàn thành checklist để tăng trưởng bền vững."
          : `${milestone.orderCount} đơn · GMV ${formatVND(milestone.gmvVnd)} — hoàn thành checklist để đẩy nhanh đơn đầu tiên.`}
      </p>
    </div>
  );
}
