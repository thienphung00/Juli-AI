import { windowParams, type ShopeeScreen, type WindowState } from "./params";

/**
 * Where the Shopee shop screens link to. One set of screens runs in three places (the seller app,
 * Juli Ops "Xem như shop" and the Ops analytics tab), so a screen asks a {@link ShopeeLinks} for
 * an href instead of writing a route. The parameter names are the artboards' (`VERIFY.md` table).
 */

/** P92 B-8: the four read-only pages the seller's Demo has from Ops (slug = the Demo route and the view-as `trang`). */
export type DashboardKind = "tu-khoa" | "quang-cao" | "don-hang" | "luong-san-pham";

export const DASHBOARD_LABEL: Readonly<Record<DashboardKind, string>> = {
  "tu-khoa": "Từ khóa",
  "quang-cao": "Dịch vụ hiển thị + khuyến mãi",
  "don-hang": "Đơn hàng",
  "luong-san-pham": "Sản phẩm + luồng",
};

export const DASHBOARD_KINDS: readonly DashboardKind[] = ["tu-khoa", "quang-cao", "don-hang", "luong-san-pham"];

/** Where each page lives in the Ops shop tabs (`/ops/shops/{id}/shopee/<slug>`). */
const OPS_TAB_SLUG: Readonly<Record<DashboardKind, string>> = {
  "tu-khoa": "tu-khoa",
  "quang-cao": "quang-cao",
  "don-hang": "don-hang",
  "luong-san-pham": "san-pham",
};

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

/** P100: Phân tích for one metric / luồng / sản phẩm, and Quyết định › Đề xuất filtered the same way. */
export interface MetricLink {
  readonly metric?: string | null;
  readonly channel?: string | null;
  readonly product?: string | null;
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
  /** P96b: Phân tích with its product table set to this KPI / source (Xếp hạng is gone). */
  ranking(link?: RankingLink, window?: WindowState): string;
  /** P100: Phân tích with `metric`, `channel`, `product` set (and the window). */
  analysis(link?: MetricLink, window?: WindowState): string;
  /** P100: Quyết định › Đề xuất filtered by `metric`, `product`, `channel`. */
  decisions(link?: MetricLink, window?: WindowState): string;
  /** A Quyết định card (`from` says which screen the person comes from). */
  card(cardId: string, from: string, row?: string | null): string;
  /** Cài đặt › Thông số shop: the cost import for a SKU. */
  costImport(sku: string | null, from: string): string;
  /** P91: Tự tạo phương án / So sánh phương án, opened from a product (`from=product`) or from Quyết định. */
  builder(from: "product" | "quyet-dinh", productId?: string | null): string;
  /** P92 B-1: Cài đặt › Loại trừ sản phẩm (the Tổng quan "trong đó Xđ từ sản phẩm đã loại trừ" line opens it). */
  exclusions(): string;
  /** P92 B-8: one of the four read-only shop pages (Từ khóa, Quảng cáo, Đơn hàng, Sản phẩm + luồng). */
  dashboard(kind: DashboardKind): string;
}

function put(p: URLSearchParams, key: string, value: string | null | undefined): void {
  if (value) p.set(key, value);
}

/** Builds the link set from the three things that differ between hosts. */
export function createLinks(host: {
  readonly screen: (screen: ShopeeScreen, query: URLSearchParams, productId?: string) => string;
  readonly card: (cardId: string, from: string, row?: string | null) => string;
  readonly decisions: (query: URLSearchParams) => string;
  readonly costImport: (sku: string | null, from: string) => string;
  readonly builder: (from: "product" | "quyet-dinh", productId?: string | null) => string;
  readonly exclusions: () => string;
  readonly dashboard: (kind: DashboardKind) => string;
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
      return host.screen("phan-tich", withWindow(p, w));
    },
    analysis: (l = {}, w) => {
      const p = new URLSearchParams();
      put(p, "metric", l.metric);
      put(p, "channel", l.channel);
      put(p, "product", l.product);
      return host.screen("phan-tich", withWindow(p, w));
    },
    decisions: (l = {}, w) => {
      const p = new URLSearchParams({ tab: "de-xuat" });
      put(p, "metric", l.metric);
      put(p, "channel", l.channel);
      put(p, "product", l.product);
      return host.decisions(withWindow(p, w));
    },
    card: host.card,
    costImport: host.costImport,
    builder: host.builder,
    exclusions: host.exclusions,
    dashboard: host.dashboard,
  };
}

/** The seller app: real routes, `/tong-quan`, `/phan-tich`, `/san-pham[/id]` (`/xep-hang` redirects to `/phan-tich`). */
export const SELLER_ROUTE: Readonly<Record<ShopeeScreen, string>> = {
  "tong-quan": "/tong-quan",
  "phan-tich": "/phan-tich",
  "san-pham": "/san-pham",
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
  decisions: (query) => `/decisions?${query.toString()}`,
  // Cài đặt › Thông số shop (Step 4's import, opens on its first step): `tab=thong-so-shop` is the
  // one parameter /settings reads; `from` and `sku` say where the person came from.
  costImport: (sku, from) => {
    const p = new URLSearchParams({ tab: "thong-so-shop", from });
    put(p, "sku", sku);
    return `/settings?${p.toString()}`;
  },
  builder: (from, productId) => {
    const p = new URLSearchParams({ "tu-tao": "1", from });
    put(p, "sp", productId);
    return `/decisions?${p.toString()}`;
  },
  exclusions: () => "/settings?tab=loai-tru-san-pham",
  dashboard: (kind) => `/${kind}`,
});

/** Juli Ops "Xem như shop": one page, `/ops/shops/{id}/xem?trang=<slug>&…`. */
export const VIEW_AS_SLUG: Readonly<Record<ShopeeScreen, string>> = {
  "tong-quan": "tong-quan",
  "phan-tich": "phan-tich",
  "san-pham": "san-pham",
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
    decisions: (query) => {
      const p = new URLSearchParams({ trang: "quyet-dinh" });
      query.forEach((v, k) => p.set(k, v));
      return `${base}?${p.toString()}`;
    },
    costImport: () => `${base}?trang=quy-tac`,
    exclusions: () => `${base}?trang=loai-tru`,
    dashboard: (kind) => `${base}?trang=${kind}`,
    builder: (from, productId) => {
      const p = new URLSearchParams({ trang: "quyet-dinh", "tu-tao": "1", from });
      put(p, "sp", productId);
      return `${base}?${p.toString()}`;
    },
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
    decisions: (query) => `/ops/shops/${encodeURIComponent(shopId)}/shopee/de-xuat?${query.toString()}`,
    costImport: () => `/ops/shops/${encodeURIComponent(shopId)}`,
    exclusions: () => `/ops/shops/${encodeURIComponent(shopId)}#loai-tru-san-pham`,
    dashboard: (kind) => `/ops/shops/${encodeURIComponent(shopId)}/shopee/${OPS_TAB_SLUG[kind]}`,
    builder: (from, productId) => {
      const p = new URLSearchParams({ "tu-tao": "1", from });
      put(p, "sp", productId);
      return `/ops/shops/${encodeURIComponent(shopId)}/shopee/de-xuat?${p.toString()}`;
    },
  });
}
