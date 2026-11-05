"use client";

import Link from "next/link";
import { Suspense, useMemo } from "react";

import { useShopReport } from "../../lib/shop-report/shop-report-context";
import { DASHBOARD_KINDS, DASHBOARD_LABEL, sellerLinks, type DashboardKind, type ShopeeLinks } from "../../lib/shopee-analytics/links";
import { DEMO_DASHBOARDS_BASE, createDashboardsApi, type DashboardsApi } from "../../lib/shopee-analytics/dashboards-client";
import { ShopeeAdsBody } from "../ops/shopee/ops-shopee-ads";
import { ShopeeKeywordsBody } from "../ops/shopee/ops-shopee-keywords";
import { ShopeeProductsBody } from "../ops/shopee/ops-shopee-products";
import { ShopeeOrdersBody } from "../ops/shopee/shopee-orders-board";
import { Notice, PageHead } from "./ui";

/**
 * The four Ops shop pages as read-only pages for the seller (P92 B-8): Từ khóa, Quảng cáo + khuyến mãi,
 * Đơn hàng, Sản phẩm + luồng. One component for the seller's Demo (`/tu-khoa`, `/quang-cao`, `/don-hang`,
 * `/luong-san-pham`) and for Juli Ops "Xem như shop"; the {@link DashboardsApi} decides which backend
 * answers. The Ops-only writes (generate keyword seeds, upload metrics, upload orders) are not here.
 */

export const DASHBOARD_ROUTE: Readonly<Record<DashboardKind, string>> = {
  "tu-khoa": "/tu-khoa",
  "quang-cao": "/quang-cao",
  "don-hang": "/don-hang",
  "luong-san-pham": "/luong-san-pham",
};

const LEDE: Readonly<Record<DashboardKind, string>> = {
  "tu-khoa": "Từ khóa ghép từ tiêu đề sản phẩm của shop, với lượt tìm, CPC và độ khó theo lần tra gần nhất.",
  "quang-cao": "Chi phí, đơn và ROAS theo loại quảng cáo, và các chương trình khuyến mãi của shop.",
  "don-hang": "Từng đơn của shop với đòn bẩy đã dùng, trạng thái và thu nhập mỗi đơn. Mã đơn là khoá băm, không có thông tin người mua.",
  "luong-san-pham": "GMV theo luồng truy cập và phễu của từng sản phẩm trong một kỳ.",
};

function DashboardTabs({ active, links }: { readonly active: DashboardKind; readonly links: ShopeeLinks }) {
  return (
    <nav aria-label="Dashboard Shopee" className="sa-seg sa-seg--round sa-tabs" data-testid="dashboard-tabs">
      {DASHBOARD_KINDS.map((k) => (
        <Link aria-current={active === k ? "page" : undefined} className={`sa-seg__item ${active === k ? "sa-seg__item--on" : ""}`} href={links.dashboard(k)} key={k}>
          {DASHBOARD_LABEL[k]}
        </Link>
      ))}
    </nav>
  );
}

/** The page body for one kind, read through `api` (the shop id is only a request key for Ops). */
export function DashboardPage({
  kind,
  api,
  shopId,
  links,
  shopName,
}: {
  readonly kind: DashboardKind;
  readonly api: DashboardsApi;
  readonly shopId: string;
  readonly links: ShopeeLinks;
  readonly shopName?: string;
}) {
  return (
    <div className="sx-dash" data-testid={`dashboard-${kind}`}>
      <PageHead eyebrow={`SHOPEE · ${DASHBOARD_LABEL[kind].toUpperCase()}`} title={shopName ? `${shopName}: ${DASHBOARD_LABEL[kind].toLowerCase()}` : DASHBOARD_LABEL[kind]} />
      <p className="sa-hint">{LEDE[kind]} Chỉ xem.</p>
      <DashboardTabs active={kind} links={links} />
      <div className="sx-dash__body">
        {kind === "tu-khoa" ? <ShopeeKeywordsBody api={api} canEdit={false} seller shopId={shopId} /> : null}
        {kind === "quang-cao" ? <ShopeeAdsBody api={api} shopId={shopId} /> : null}
        {kind === "don-hang" ? <ShopeeOrdersBody api={api} shopId={shopId} /> : null}
        {kind === "luong-san-pham" ? <ShopeeProductsBody api={api} shopId={shopId} /> : null}
      </div>
    </div>
  );
}

function SellerDashboard({ kind }: { readonly kind: DashboardKind }) {
  const { state } = useShopReport();
  const token = "token" in state ? state.token : null;
  const shop = "shop" in state ? state.shop : null;
  const api = useMemo(
    () => (token && shop ? createDashboardsApi({ base: DEMO_DASHBOARDS_BASE, dashboardPrefix: "/dashboard", token, shopId: shop.id }) : null),
    [token, shop],
  );
  if (state.status === "resolving") return <p className="sa-loading">Đang tải…</p>;
  if (!api || !shop) {
    return (
      <div className="sa-page">
        <Notice tone="info" testId="sa-needs-shop">
          Đăng nhập và chọn shop Shopee của bạn để xem số liệu. Đây là màn hình dành cho shop Shopee.
        </Notice>
      </div>
    );
  }
  return (
    <div className="sa-page">
      <DashboardPage api={api} kind={kind} links={sellerLinks} shopId={shop.id} shopName={shop.name} />
    </div>
  );
}

/** `/tu-khoa`, `/quang-cao`, `/don-hang`, `/luong-san-pham` of the seller app. */
export function SellerDashboardPage({ kind }: { readonly kind: DashboardKind }) {
  return (
    <Suspense fallback={<p className="sa-loading">Đang tải…</p>}>
      <SellerDashboard kind={kind} />
    </Suspense>
  );
}
