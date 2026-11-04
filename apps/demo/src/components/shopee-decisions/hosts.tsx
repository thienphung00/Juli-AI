"use client";

import { useMemo } from "react";

import { readAuthSession } from "../../lib/supabase-auth";
import { opsTabShopeeLinks, sellerLinks, viewAsShopeeLinks } from "../../lib/shopee-analytics/links";
import { DEMO_SHOPEE_BASE, createShopeeApi, opsShopeeBase } from "../../lib/shopee-analytics/client";
import { DEMO_RECO_BASE, createRecoApi, opsRecoBase } from "../../lib/shopee-decisions/client";
import { RecoHostProvider, decisionsQuery, type ProductChoice, type RecoHost } from "../../lib/shopee-decisions/context";
import { viewAsTabHref } from "../../lib/ops/view-as-routes";
import { DecisionsView } from "./decisions-view";

/** Where the Shopee Quyết định screens run: the seller's /decisions, Juli Ops "Xem như shop", the Ops "Đề xuất" tab. */

function withQuery(path: string, query: URLSearchParams): string {
  const qs = query.toString();
  return qs ? `${path}?${qs}` : path;
}

/** The shop's products by GMV (id, name), for the builder and the Ops list. */
function productsOf(api: ReturnType<typeof createShopeeApi>): () => Promise<readonly ProductChoice[]> {
  return async () => (await api.matrix({ period: "30d", sort: "gmv", limit: 50 })).products.map((p) => ({ id: p.product_id, name: p.name }));
}

// ── Seller ───────────────────────────────────────────────────────────────

export function sellerRecoHost(options: {
  readonly token: string;
  readonly shopId: string;
  readonly shopName?: string;
  readonly navigate?: (href: string) => void;
  readonly fetchImpl?: typeof fetch;
}): RecoHost {
  return {
    reco: createRecoApi({ base: DEMO_RECO_BASE, token: options.token, shopId: options.shopId, fetchImpl: options.fetchImpl }),
    links: sellerLinks,
    shopKey: options.shopId,
    shopName: options.shopName,
    products: productsOf(createShopeeApi({ base: DEMO_SHOPEE_BASE, token: options.token, shopId: options.shopId, fetchImpl: options.fetchImpl })),
    href: (view) => withQuery("/decisions", decisionsQuery(view)),
    navigate: options.navigate,
  };
}

/** `/decisions` of a Shopee shop. */
export function SellerShopeeDecisions({
  token,
  shop,
  params,
  onNavigate,
  fetchImpl,
}: {
  readonly token: string;
  readonly shop: { readonly id: string; readonly name: string };
  readonly params: URLSearchParams;
  readonly onNavigate?: (href: string) => void;
  readonly fetchImpl?: typeof fetch;
}) {
  const host = useMemo(() => sellerRecoHost({ token, shopId: shop.id, shopName: shop.name, navigate: onNavigate, fetchImpl }), [token, shop.id, shop.name, onNavigate, fetchImpl]);
  return (
    <RecoHostProvider host={host}>
      <DecisionsView params={params} />
    </RecoHostProvider>
  );
}

// ── Juli Ops ─────────────────────────────────────────────────────────────

/** The Ops host: bearer from the Ops session, the shop in the path. "Xem như shop" is read-only; the tab has staff actions. */
export function useOpsRecoHost(shopId: string, kind: "view-as" | "tab", shopName?: string, fetchImpl?: typeof fetch): RecoHost | null {
  const token = readAuthSession()?.accessToken ?? null;
  return useMemo(() => {
    if (!token) return null;
    const reco = createRecoApi({ base: opsRecoBase(shopId), token, fetchImpl });
    const products = productsOf(createShopeeApi({ base: opsShopeeBase(shopId), token, fetchImpl }));
    if (kind === "view-as") {
      return {
        reco,
        links: viewAsShopeeLinks(shopId),
        shopKey: `ops:${shopId}`,
        shopName,
        products,
        readOnly: true,
        href: (view) => viewAsTabHref(shopId, "decisions", decisionsQuery(view)),
      };
    }
    return {
      reco,
      links: opsTabShopeeLinks(shopId),
      shopKey: `ops-tab:${shopId}`,
      shopName,
      products,
      staff: true,
      href: (view) => withQuery(`/ops/shops/${encodeURIComponent(shopId)}/shopee/de-xuat`, decisionsQuery(view)),
    };
  }, [token, shopId, kind, shopName, fetchImpl]);
}

/** Ops "Xem như shop" · Quyết định of a Shopee shop. */
export function OpsViewAsShopeeDecisions({ shopId, shopName, params, fetchImpl }: { readonly shopId: string; readonly shopName?: string; readonly params: URLSearchParams; readonly fetchImpl?: typeof fetch }) {
  const host = useOpsRecoHost(shopId, "view-as", shopName, fetchImpl);
  if (!host) return <p role="status">Đăng nhập Ops để xem đề xuất.</p>;
  return (
    <RecoHostProvider host={host}>
      <DecisionsView params={params} />
    </RecoHostProvider>
  );
}

/** The Ops "Đề xuất" tab body. */
export function OpsShopeeRecoBody({ shopId, params, fetchImpl }: { readonly shopId: string; readonly params: URLSearchParams; readonly fetchImpl?: typeof fetch }) {
  const host = useOpsRecoHost(shopId, "tab", undefined, fetchImpl);
  if (!host) return <p role="status">Đăng nhập Ops để xem đề xuất.</p>;
  return (
    <RecoHostProvider host={host}>
      <DecisionsView params={params} />
    </RecoHostProvider>
  );
}
