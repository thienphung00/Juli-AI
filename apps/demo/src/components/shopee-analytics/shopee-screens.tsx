"use client";

import Link from "next/link";

import { useShopee } from "../../lib/shopee-analytics/context";
import type { ShopeeScreen } from "../../lib/shopee-analytics/params";
import { PhanTichPageView } from "./phan-tich-view";
import { ProductListView } from "./product-list";
import { ProductPageView } from "./product-page";
import { TongQuanView } from "./tong-quan";

/**
 * The Shopee shop screens behind one switch, for hosts that show several in one page (Juli
 * Ops "Xem như shop" and the Ops analytics tab). The seller app has one Next route per screen and
 * renders the views directly.
 */

export const SCREEN_TABS: readonly (readonly [ShopeeScreen, string])[] = [
  ["tong-quan", "Tổng quan"],
  ["phan-tich", "Phân tích"],
  ["san-pham", "Sản phẩm"],
];

/** P96b: an old Xếp hạng link (`xep-hang`) opens Phân tích, whose product table took its place. */
export function screenOf(raw: string | null | undefined): ShopeeScreen {
  if (raw === "xep-hang") return "phan-tich";
  return raw === "phan-tich" || raw === "san-pham" ? raw : "tong-quan";
}

export function ShopeeScreenSwitch({ screen, params, productId }: { readonly screen: ShopeeScreen; readonly params: URLSearchParams; readonly productId?: string | null }) {
  switch (screen) {
    case "phan-tich":
      return <PhanTichPageView params={params} />;
    case "san-pham":
      return productId ? <ProductPageView id={productId} params={params} /> : <ProductListView params={params} />;
    default:
      return <TongQuanView params={params} />;
  }
}

/** The in-page tab strip (Ops analytics tab; the seller app has the shell's own navigation). */
export function ScreenTabs({ active }: { readonly active: ShopeeScreen }) {
  const { links } = useShopee();
  return (
    <nav aria-label="Màn hình Shopee" className="sa-seg sa-seg--round sa-tabs" data-testid="sa-screen-tabs">
      {SCREEN_TABS.map(([k, label]) => (
        <Link aria-current={active === k ? "page" : undefined} className={`sa-seg__item ${active === k ? "sa-seg__item--on" : ""}`} href={links.screen(k, new URLSearchParams())} key={k}>
          {label}
        </Link>
      ))}
    </nav>
  );
}
