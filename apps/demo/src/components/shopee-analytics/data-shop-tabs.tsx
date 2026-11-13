"use client";

import Link from "next/link";

import { useSampleShopReviewer } from "../../lib/reviewer/mode";
import { sellerLinks, type DashboardKind, type ShopeeLinks } from "../../lib/shopee-analytics/links";

/**
 * Dữ liệu shop: the one sub-tab strip over Sản phẩm · Từ khóa · Dịch vụ hiển thị · Đơn hàng · Luồng.
 * Each tab is the existing screen on its existing route. On the reviewer's sample shop only Sản phẩm
 * is shown (the other four are not available there).
 */
export type DataShopTab = "san-pham" | DashboardKind;

export const DATA_SHOP_TABS: readonly { readonly key: DataShopTab; readonly label: string }[] = [
  { key: "san-pham", label: "Sản phẩm" },
  { key: "tu-khoa", label: "Từ khóa" },
  { key: "quang-cao", label: "Dịch vụ hiển thị" },
  { key: "don-hang", label: "Đơn hàng" },
  { key: "luong-san-pham", label: "Luồng" },
];

export function DataShopTabs({ active, links }: { readonly active: DataShopTab; readonly links: ShopeeLinks }) {
  const sampleShop = useSampleShopReviewer();
  const tabs = sampleShop ? DATA_SHOP_TABS.filter((t) => t.key === "san-pham") : DATA_SHOP_TABS;
  return (
    <nav aria-label="Dữ liệu shop" className="sa-seg sa-seg--round sa-tabs" data-testid="dashboard-tabs">
      {tabs.map((t) => (
        <Link
          aria-current={active === t.key ? "page" : undefined}
          className={`sa-seg__item ${active === t.key ? "sa-seg__item--on" : ""}`}
          href={t.key === "san-pham" ? links.products() : links.dashboard(t.key)}
          key={t.key}
        >
          {t.label}
        </Link>
      ))}
    </nav>
  );
}

/** The strip for the seller app's own routes (Sản phẩm list). */
export function SellerDataShopTabs({ active }: { readonly active: DataShopTab }) {
  return <DataShopTabs active={active} links={sellerLinks} />;
}
