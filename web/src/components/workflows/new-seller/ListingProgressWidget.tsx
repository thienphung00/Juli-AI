"use client";

import type { ListingWidgetState } from "@/lib/workflows/new-seller/shop-progress";

const WIDGET_STATE_LABELS: Record<ListingWidgetState, string> = {
  no_distributor: "Chưa chọn nhà phân phối",
  distributor_known: "Đã chọn nhà phân phối",
  draft_generated: "Bản nháp đã tạo",
  published_stub: "Đã xuất bản nháp (mock)",
};

const WIDGET_STATE_DESCRIPTIONS: Record<ListingWidgetState, string> = {
  no_distributor:
    "Bắt đầu quy trình đăng sản phẩm và chọn nhà phân phối để tiến tới trạng thái Standard.",
  distributor_known:
    "Nhà phân phối đã xác nhận — tiếp tục tạo bản nháp sản phẩm.",
  draft_generated:
    "Bản nháp sẵn sàng — xuất CSV/JSON và đăng thủ công trên Seller Center.",
  published_stub:
    "Bản nháp đã xuất (mock) — không gọi TikTok API. Tiếp tục thêm SKU để đạt 10 listing.",
};

export function ListingProgressWidget({
  widgetState,
  activeListingCount,
  listingTarget,
}: {
  widgetState: ListingWidgetState;
  activeListingCount: number;
  listingTarget: number;
}) {
  return (
    <article
      className="card p-4"
      data-testid="listing-progress-widget"
      data-widget-state={widgetState}
    >
      <div className="flex items-start justify-between gap-2">
        <span
          className="badge text-xs font-semibold"
          style={{ background: "rgba(99, 102, 241, 0.15)", color: "#6366f1" }}
          data-testid="listing-widget-badge"
        >
          Tiến độ đăng sản phẩm
        </span>
        <span
          className="text-xs font-semibold"
          style={{ color: "#10b981" }}
          data-testid="listing-widget-count"
        >
          {activeListingCount}/{listingTarget} SKU
        </span>
      </div>

      <h3
        className="mt-2 text-sm font-semibold"
        data-testid="listing-widget-state-label"
      >
        {WIDGET_STATE_LABELS[widgetState]}
      </h3>

      <p
        className="mt-2 text-sm"
        style={{ color: "var(--muted-foreground)" }}
        data-testid="listing-widget-description"
      >
        {WIDGET_STATE_DESCRIPTIONS[widgetState]}
      </p>
    </article>
  );
}
