import type { ShopAnalysisEnvelope } from "../../lib/shop-analysis/types";

/** P64 (D73.3): the line shown when the report's GMV / Đơn / AOV come from orders, not Analytics. */
export const ORDERS_SOURCE_COPY =
  "Tính từ đơn hàng TikTok (Orders API): GMV, số đơn và AOV cộng từ các đơn đã thanh toán; lượt hiển thị, CTR và CTOR để trống vì TikTok Analytics chưa có số liệu.";

/**
 * Says where the numbers come from when the backend built the report from the
 * shop's real synced orders (`report.metrics_source === "orders"`, the sandbox
 * shop whose TikTok Analytics is all zeros). Renders nothing otherwise.
 */
export function MetricsSourceNote({ envelope }: { readonly envelope: ShopAnalysisEnvelope }) {
  if (envelope.report.metrics_source !== "orders") return null;
  return (
    <p className="demo-notice" data-testid="metrics-source-orders" role="note">
      {ORDERS_SOURCE_COPY}
    </p>
  );
}
