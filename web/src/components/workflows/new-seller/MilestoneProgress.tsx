"use client";

import type { SellerProfile } from "@/lib/mock-data/seller-personas/schemas";
import { formatVND } from "@/lib/format";
import { computeFirstSaleMilestone } from "@/lib/workflows/new-seller/milestone";
import {
  computeListingMilestone,
  STANDARD_STATUS_LISTING_TARGET,
} from "@/lib/workflows/new-seller/shop-progress";

export function MilestoneProgress({
  profile,
  activeListingCount,
}: {
  profile: SellerProfile;
  activeListingCount?: number;
}) {
  const milestone = computeFirstSaleMilestone(profile);
  const listingMilestone = computeListingMilestone(activeListingCount);

  return (
    <div className="space-y-4">
    <div
      className="rounded-xl border p-4"
      style={{ borderColor: "var(--border)" }}
      data-testid="listing-milestone"
    >
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold" style={{ color: "var(--foreground)" }}>
          Tiến độ trạng thái Standard (10 listing)
        </h3>
        <span
          className="text-sm font-bold"
          style={{ color: "var(--primary)" }}
          data-testid="listing-milestone-percent"
        >
          {listingMilestone.percent}%
        </span>
      </div>

      <div
        className="mt-3 h-2 w-full overflow-hidden rounded-full"
        style={{ background: "var(--border)" }}
        role="progressbar"
        aria-valuenow={listingMilestone.percent}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Tiến độ listing trạng thái Standard"
        data-testid="listing-milestone-progress-bar"
      >
        <div
          className="gradient-primary h-full rounded-full transition-all"
          style={{ width: `${listingMilestone.percent}%` }}
        />
      </div>

      <p className="text-muted mt-2 text-xs" data-testid="listing-milestone-copy">
        {listingMilestone.count}/{STANDARD_STATUS_LISTING_TARGET} SKU đang hoạt động
        {listingMilestone.remaining > 0
          ? ` — còn ${listingMilestone.remaining} listing để đạt Standard.`
          : " — đã đạt mốc Standard (mock)."}
      </p>
    </div>

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
          style={{ color: "var(--success)" }}
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
            background: "var(--success)",
          }}
        />
      </div>

      <p className="text-muted mt-2 text-xs">
        {milestone.hasFirstSale
          ? "Bạn đã đạt đơn hàng có lãi đầu tiên — tiếp tục hoàn thành checklist để tăng trưởng bền vững."
          : `${milestone.orderCount} đơn · GMV ${formatVND(milestone.gmvVnd)} — hoàn thành checklist để đẩy nhanh đơn đầu tiên.`}
      </p>
    </div>
    </div>
  );
}
