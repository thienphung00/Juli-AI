import { windowParams, type ShopeeScreen, type WindowState } from "./params";

/**
 * Where the Shopee shop screens link to. One set of screens runs in three places (the seller app,
 * Juli Ops "Xem như shop" and the Ops analytics tab), so a screen asks a {@link ShopeeLinks} for
 * an href instead of writing a route. The parameter names are the artboards' (`VERIFY.md` table).
 */

export interface RankingLink {
  readonly kpi?: string;
  readonly src?: string;
  readonly sub?: string | null;
  readonly focus?: string | null;
  readonly from?: string | null;
  readonly card?: string | null;
  readonly xep?: string | null;
  readonly loai?: string | null;
  readonly huong?: string | null;
}

export interface ProductLink {
  readonly tab?: string | null;
  readonly kpi?: string | null;
  readonly src?: string | null;
  readonly sub?: string | null;
  readonly row?: string | null;
  readonly from?: string | null;
  readonly card?: string | null;
}

export interface ShopeeLinks {
  /** A screen of the Shopee set with its own query. */
  screen(screen: ShopeeScreen, query: URLSearchParams, productId?: string): string;
  overview(window?: WindowState): string;
  critical(window?: WindowState): string;
  products(window?: WindowState): string;
  product(id: string, link?: ProductLink, window?: WindowState): string;
  ranking(link?: RankingLink, window?: WindowState): string;
  /** A Quyết định card (`from` says which screen the person comes from). */
  card(cardId: string, from: string, row?: string | null): string;
  /** Cài đặt › Thông số shop: the cost import for a SKU. */
  costImport(sku: string | null, from: string): string;
}

function put(p: URLSearchParams, key: string, value: string | null | undefined): void {
  if (value) p.set(key, value);
}

/** Builds the link set from the three things that differ between hosts. */
export function createLinks(host: {
  readonly screen: (screen: ShopeeScreen, query: URLSearchParams, productId?: string) => string;
  readonly card: (cardId: string, from: string, row?: string | null) => string;
  readonly costImport: (sku: string | null, from: string) => string;
}): ShopeeLinks {
  const withWindow = (p: URLSearchParams, w?: WindowState) => {
    if (w) windowParams(w).forEach((v, k) => p.set(k, v));
    return p;
  };
  return {
    screen: host.screen,
    overview: (w) => host.screen("tong-quan", withWindow(new URLSearchParams(), w)),
    critical: (w) => host.screen("phan-tich", withWindow(new URLSearchParams(), w)),
    products: (w) => host.screen("san-pham", withWindow(new URLSearchParams(), w)),
    product: (id, l = {}, w) => {
      const p = new URLSearchParams();
      put(p, "tab", l.tab ?? undefined);
      put(p, "kpi", l.kpi);
      put(p, "src", l.src);
      put(p, "sub", l.sub);
      put(p, "row", l.row);
      put(p, "from", l.from);
      put(p, "card", l.card);
      return host.screen("san-pham", withWindow(p, w), id);
    },
    ranking: (l = {}, w) => {
      const p = new URLSearchParams();
      put(p, "kpi", l.kpi);
      put(p, "src", l.src);
      put(p, "sub", l.sub);
      put(p, "focus", l.focus);
      put(p, "from", l.from);
      put(p, "card", l.card);
      put(p, "xep", l.xep);
      put(p, "loai", l.loai);
      put(p, "huong", l.huong);
      return host.screen("xep-hang", withWindow(p, w));
    },
    card: host.card,
    costImport: host.costImport,
  };
}

/** The seller app: real routes, `/tong-quan`, `/phan-tich`, `/san-pham[/id]`, `/xep-hang`. */
export const SELLER_ROUTE: Readonly<Record<ShopeeScreen, string>> = {
  "tong-quan": "/tong-quan",
  "phan-tich": "/phan-tich",
  "san-pham": "/san-pham",
  "xep-hang": "/xep-hang",
};

function withQuery(path: string, query: URLSearchParams): string {
  const qs = query.toString();
  return qs ? `${path}?${qs}` : path;
}

export const sellerLinks: ShopeeLinks = createLinks({
  screen: (screen, query, productId) =>
    withQuery(
      screen === "san-pham" && productId
        ? `${SELLER_ROUTE["san-pham"]}/${encodeURIComponent(productId)}`
        : SELLER_ROUTE[screen],
      query,
    ),
  // Quyết định reads `?the=<card id>` (focus the card); `from` says where the person came from.
  card: (cardId, from, row) => {
    const p = new URLSearchParams({ the: cardId, from });
    put(p, "row", row);
    return `/decisions?${p.toString()}`;
  },
  // Cài đặt › Thông số shop (Step 4's import, opens on its first step): `tab=thong-so-shop` is the
  // one parameter /settings reads; `from` and `sku` say where the person came from.
  costImport: (sku, from) => {
    const p = new URLSearchParams({ tab: "thong-so-shop", from });
    put(p, "sku", sku);
    return `/settings?${p.toString()}`;
  },
});

/** Juli Ops "Xem như shop": one page, `/ops/shops/{id}/xem?trang=<slug>&…`. */
export const VIEW_AS_SLUG: Readonly<Record<ShopeeScreen, string>> = {
  "tong-quan": "tong-quan",
  "phan-tich": "phan-tich",
  "san-pham": "san-pham",
  "xep-hang": "xep-hang",
};

export function viewAsShopeeLinks(shopId: string, sellerCardHref?: ShopeeLinks["card"]): ShopeeLinks {
  const base = `/ops/shops/${encodeURIComponent(shopId)}/xem`;
  return createLinks({
    screen: (screen, query, productId) => {
      const p = new URLSearchParams({ trang: VIEW_AS_SLUG[screen] });
      if (productId) p.set("id", productId);
      query.forEach((v, k) => p.append(k, v));
      return `${base}?${p.toString()}`;
    },
    card:
      sellerCardHref ??
      ((cardId, from, row) => {
        const p = new URLSearchParams({ trang: "quyet-dinh", the: cardId, from });
        put(p, "row", row);
        return `${base}?${p.toString()}`;
      }),
    costImport: () => `${base}?trang=quy-tac`,
  });
}

/** Ops analytics tab: `/ops/shops/{id}/shopee/phan-tich?man=<screen>&…`. */
export function opsTabShopeeLinks(shopId: string): ShopeeLinks {
  const base = `/ops/shops/${encodeURIComponent(shopId)}/shopee/phan-tich`;
  return createLinks({
    screen: (screen, query, productId) => {
      const p = new URLSearchParams({ man: screen });
      if (productId) p.set("id", productId);
      query.forEach((v, k) => p.append(k, v));
      return `${base}?${p.toString()}`;
    },
    // Cards live in the Ops "Đề xuất" tab of the shop.
    card: (cardId, from, row) => {
      const p = new URLSearchParams({ the: cardId, from });
      put(p, "row", row);
      return `/ops/shops/${encodeURIComponent(shopId)}/shopee/de-xuat?${p.toString()}`;
    },
    costImport: () => `/ops/shops/${encodeURIComponent(shopId)}`,
  });
}
