import Link from "next/link";

import { CONNECT_SHOP_HREF } from "../../lib/app-navigation";

export const NO_SHOP_SAMPLE_TEXT = "Bạn đang xem dữ liệu mẫu";
export const NO_SHOP_CONNECT_LABEL = "Kết nối TikTok Shop ›";

/**
 * P13 (owner, 2026-10-10): a signed-in seller with no TikTok Shop connected
 * sees the bundled sample on Trang chủ, Phân tích and Quyết định, under this
 * strip — what they are looking at, and the way to their own shop
 * (`/auth/connect-shop`). The sample below it stays local: no request, nothing
 * written for the seller.
 */
export function NoShopSampleStrip() {
  return (
    <p className="no-shop-strip" data-testid="no-shop-sample-strip">
      <span>{NO_SHOP_SAMPLE_TEXT}</span>
      <span aria-hidden="true"> · </span>
      <Link className="no-shop-strip__link" href={CONNECT_SHOP_HREF}>
        {NO_SHOP_CONNECT_LABEL}
      </Link>
    </p>
  );
}
