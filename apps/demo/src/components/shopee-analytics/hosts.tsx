"use client";

import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useMemo } from "react";

import { readAuthSession } from "../../lib/supabase-auth";
import { useShopReport } from "../../lib/shop-report/shop-report-context";
import { DEMO_SHOPEE_BASE, createShopeeApi, opsShopeeBase } from "../../lib/shopee-analytics/client";
import { ShopeeHostProvider, type ShopeeHost } from "../../lib/shopee-analytics/context";
import { DEMO_BUILDER_BASE, createBuilderApi, opsBuilderBase, p92BuilderEnabled } from "../../lib/shopee-decisions/builder-api";
import { createKolApi } from "../../lib/shopee-kol/client";
import { kolEnabled } from "../../lib/shopee-decisions/plan-client";
import { DEMO_RECO_BASE, createRecoApi, opsRecoBase } from "../../lib/shopee-decisions/client";
import { opsTabShopeeLinks, sellerLinks, viewAsShopeeLinks } from "../../lib/shopee-analytics/links";
import type { ShopeeScreen } from "../../lib/shopee-analytics/params";
import { PhanTichPageView } from "./phan-tich-view";
import { ProductListView } from "./product-list";
import { ProductPageView } from "./product-page";
import { RankingPageView } from "./ranking-view";
import { ScreenTabs, ShopeeScreenSwitch, screenOf } from "./shopee-screens";
import { TongQuanView } from "./tong-quan";
import { Notice } from "./ui";

/** Where the Shopee shop screens run: the seller app, Juli Ops "Xem như shop", the Ops tab. */

/** The query string as a stable URLSearchParams (a new object only when the string changes). */
export function useQueryParams(): URLSearchParams {
  const search = useSearchParams();
  const text = search?.toString() ?? "";
  return useMemo(() => new URLSearchParams(text), [text]);
}

// ── Seller ───────────────────────────────────────────────────────────────

function SellerHost({ children }: { readonly children: (host: ShopeeHost) => React.ReactNode }) {
  const { state } = useShopReport();
  const token = "token" in state ? state.token : null;
  const shop = "shop" in state ? state.shop : null;
  const host = useMemo<ShopeeHost | null>(
    () =>
      token && shop
        ? {
            api: createShopeeApi({ base: DEMO_SHOPEE_BASE, token, shopId: shop.id }),
            reco: createRecoApi({ base: DEMO_RECO_BASE, token, shopId: shop.id }),
            builder: p92BuilderEnabled() ? createBuilderApi({ base: DEMO_BUILDER_BASE, token, shopId: shop.id }) : undefined,
            kol: kolEnabled() ? createKolApi({ base: DEMO_SHOPEE_BASE, token, shopId: shop.id }) : undefined,
            links: sellerLinks,
            shopKey: shop.id,
            shopName: shop.name,
          }
        : null,
    [token, shop],
  );
  if (state.status === "resolving") return <p className="sa-loading">Đang tải…</p>;
  if (!host) {
    return (
      <div className="sa-page">
        <Notice tone="info" testId="sa-needs-shop">
          Đăng nhập và chọn shop Shopee của bạn để xem số liệu. Đây là màn hình dành cho shop Shopee.
        </Notice>
      </div>
    );
  }
  return <ShopeeHostProvider host={host}>{children(host)}</ShopeeHostProvider>;
}

function SellerScreen({ screen }: { readonly screen: ShopeeScreen }) {
  const params = useQueryParams();
  return <SellerHost>{() => <ShopeeScreenSwitch params={params} screen={screen} />}</SellerHost>;
}

function SellerProduct() {
  const params = useQueryParams();
  const { itemId } = useParams<{ itemId: string }>();
  const id = decodeURIComponent(itemId ?? "");
  return <SellerHost>{() => <ProductPageView id={id} params={params} />}</SellerHost>;
}

/** `/tong-quan`, `/phan-tich`, `/san-pham`, `/xep-hang` of the seller app. */
export function SellerShopeePage({ screen }: { readonly screen: ShopeeScreen }) {
  return (
    <Suspense fallback={<p className="sa-loading">Đang tải…</p>}>
      <SellerScreen screen={screen} />
    </Suspense>
  );
}

/** `/san-pham/[itemId]`. */
export function SellerShopeeProductPage() {
  return (
    <Suspense fallback={<p className="sa-loading">Đang tải…</p>}>
      <SellerProduct />
    </Suspense>
  );
}

// ── Juli Ops ─────────────────────────────────────────────────────────────

/** The Ops host: bearer from the Ops session, the shop in the path, read-only. */
export function useOpsShopeeHost(shopId: string, kind: "view-as" | "tab", shopName?: string, fetchImpl?: typeof fetch): ShopeeHost | null {
  const token = readAuthSession()?.accessToken ?? null;
  return useMemo(
    () =>
      token
        ? {
            api: createShopeeApi({ base: opsShopeeBase(shopId), token, fetchImpl }),
            reco: createRecoApi({ base: opsRecoBase(shopId), token, fetchImpl, asSeller: kind === "view-as" }),
            builder: p92BuilderEnabled() ? createBuilderApi({ base: opsBuilderBase(shopId), token, fetchImpl }) : undefined,
            kol: kolEnabled() ? createKolApi({ base: opsShopeeBase(shopId), token, fetchImpl }) : undefined,
            links: kind === "view-as" ? viewAsShopeeLinks(shopId) : opsTabShopeeLinks(shopId),
            shopKey: `ops:${shopId}`,
            shopName,
            readOnly: true,
          }
        : null,
    [token, shopId, kind, shopName, fetchImpl],
  );
}

/**
 * The Ops analytics tab (`/ops/shops/{id}/shopee/phan-tich?man=<screen>&id=<item>&…`): the same
 * four screens with an in-page tab strip.
 */
export function OpsShopeeAnalyticsBody({ shopId, fetchImpl }: { readonly shopId: string; readonly fetchImpl?: typeof fetch }) {
  const params = useQueryParams();
  const host = useOpsShopeeHost(shopId, "tab", undefined, fetchImpl);
  const screen = screenOf(params.get("man"));
  const productId = params.get("id");
  if (!host) return <Notice tone="info">Đăng nhập Ops để xem số liệu.</Notice>;
  return (
    <ShopeeHostProvider host={host}>
      <ScreenTabs active={screen} />
      <ShopeeScreenSwitch params={params} productId={productId} screen={screen} />
    </ShopeeHostProvider>
  );
}

export { PhanTichPageView, ProductListView, RankingPageView, TongQuanView };
