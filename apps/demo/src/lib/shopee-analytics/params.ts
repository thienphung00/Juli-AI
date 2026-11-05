import type { PeriodKind, WindowQuery } from "./client";

/**
 * The URL state of the Shopee shop screens. Link parameters follow the artboards'
 * `VERIFY.md` link table: `kpi`, `src` (all · the_san_pham · trang_shop · live · video ·
 * lien_ket · ads · none · voucher · promo · combo), `sub` (a Thẻ sản phẩm child), `focus`, `from`,
 * `card`, `id`, `tab`, `row`. The window uses its own names (`ky`, `thang`, `tu`, `den`) because
 * `from` already says where a link came from.
 */

export type ShopeeScreen = "tong-quan" | "phan-tich" | "san-pham" | "xep-hang";

export const KPIS: readonly (readonly [string, string])[] = [
  ["gmv", "GMV"],
  ["views", "Lượt xem"],
  ["ctr", "CTR"],
  ["ctor", "CTOR"],
  ["aov", "AOV"],
  ["bien", "Biên cuối"],
  ["disc", "% giảm giá"],
  ["orders", "Số đơn"],
];
export const KPI_NAME: Readonly<Record<string, string>> = Object.fromEntries(KPIS);

/** Source chips: [url key, label, group]. */
export const SOURCES: readonly (readonly [string, string, "g" | "ad" | "p"])[] = [
  ["all", "Tất cả", "g"],
  ["the_san_pham", "Thẻ sản phẩm", "g"],
  ["trang_shop", "Trang shop", "g"],
  ["live", "Live", "g"],
  ["video", "Video", "g"],
  ["lien_ket", "Tiếp thị liên kết", "g"],
  ["ads", "Quảng cáo (trong đó)", "ad"],
  ["none", "Không ưu đãi", "p"],
  ["voucher", "Voucher", "p"],
  ["promo", "Khuyến mãi", "p"],
  ["combo", "Combo", "p"],
];
export const SOURCE_NAME: Readonly<Record<string, string>> = {
  all: "Tất cả",
  the_san_pham: "Thẻ sản phẩm",
  trang_shop: "Trang shop",
  live: "Live",
  video: "Video",
  lien_ket: "Tiếp thị liên kết",
  ads: "Quảng cáo",
  none: "Không ưu đãi",
  voucher: "Voucher",
  promo: "Khuyến mãi",
  combo: "Combo",
};

/** Thẻ sản phẩm children: artboard key ↔ API key. */
export const CHILDREN: readonly (readonly [string, string, string])[] = [
  ["search", "search", "Tìm kiếm"],
  ["de_xuat", "recommend", "Đề xuất"],
  ["gio_hang", "cart", "Giỏ hàng"],
  ["don_mua", "my_orders", "Đơn mua của tôi"],
  ["khuyen_mai", "promo", "Khuyến mãi (gồm Flash Sale)"],
  ["khac", "other", "Khác"],
];
export const CHILD_TO_API: Readonly<Record<string, string>> = Object.fromEntries(
  CHILDREN.map(([url, api]) => [url, api]),
);
export const CHILD_NAME: Readonly<Record<string, string>> = Object.fromEntries(
  CHILDREN.map(([url, , label]) => [url, label]),
);
/** API flow key (`the_san_pham_khac`) ↔ artboard source key (`the_san_pham`). */
export const SRC_TO_API: Readonly<Record<string, string>> = {
  the_san_pham: "the_san_pham_khac",
  none: "none",
};
export function srcOfFlowKey(apiKey: string): string {
  return apiKey === "the_san_pham_khac" ? "the_san_pham" : apiKey;
}
export function childUrlKey(apiKey: string): string {
  return CHILDREN.find(([, api]) => api === apiKey)?.[0] ?? apiKey;
}

/** Xếp theo: artboard key → API `xep_theo`. */
export const XEP: readonly (readonly [string, string, string])[] = [
  ["gmv", "gmv_per_day", "₫ GMV/ngày"],
  ["profit", "profit_per_day", "₫ lợi nhuận/ngày"],
  ["bien", "bien", "Biên cuối"],
  ["orders", "orders", "Số đơn"],
  ["aov", "aov", "AOV"],
  ["disc", "giam_gia", "% giảm giá"],
];

/** What a ranking of this KPI is sorted by when the link says nothing: the KPI itself where the
 *  API ranks by it (biên, AOV, số đơn, % giảm giá), else ₫ GMV/ngày. A "Biên cuối" card must show
 *  the margin, not the day's GMV. */
export function defaultXep(kpi: string): string {
  return kpi === "bien" || kpi === "aov" || kpi === "orders" || kpi === "disc" ? kpi : "gmv";
}

/** The `xep` URL parameter for a choice: omitted when it is the KPI's default. */
export function xepParam(kpi: string, xep: string): string | null {
  return xep === defaultXep(kpi) ? null : xep;
}

export const PRODUCT_TABS: readonly (readonly [string, string])[] = [
  ["hs", "Hiệu suất"],
  ["ng", "Nguồn"],
  ["kw", "Từ khoá"],
  ["cp", "Chi phí & giá sàn"],
  ["ls", "Lịch sử"],
];

const PERIOD_URL: Readonly<Record<string, PeriodKind>> = {
  "7d": "7d",
  "30d": "30d",
  "90d": "90d",
  thang: "month",
  "tuy-chon": "custom",
};
const PERIOD_KEY: Readonly<Record<PeriodKind, string>> = {
  "7d": "7d",
  "30d": "30d",
  "90d": "90d",
  month: "thang",
  custom: "tuy-chon",
};

export const WINDOW_KEYS = ["ky", "thang", "tu", "den", "cmp"] as const;

export interface WindowState {
  readonly query: WindowQuery;
  /** "So sánh kỳ trước" on (default). */
  readonly compare: boolean;
}

function validMonth(v: string | null): string | null {
  return v && /^\d{4}-\d{2}$/.test(v) ? v : null;
}
function validDay(v: string | null): string | null {
  return v && /^\d{4}-\d{2}-\d{2}$/.test(v) ? v : null;
}

export function readWindow(params: URLSearchParams): WindowState {
  const kind = PERIOD_URL[params.get("ky") ?? ""] ?? "30d";
  const month = validMonth(params.get("thang"));
  const from = validDay(params.get("tu"));
  const to = validDay(params.get("den"));
  let query: WindowQuery = { period: kind };
  // A month or custom window without its bounds falls back to the default 30 days.
  if (kind === "month") query = month ? { period: "month", month } : { period: "30d" };
  if (kind === "custom") query = from && to ? { period: "custom", from, to } : { period: "30d" };
  return { query, compare: params.get("cmp") !== "0" };
}

/** The window (and compare) parameters to carry to the next screen. */
export function windowParams(state: WindowState): URLSearchParams {
  const p = new URLSearchParams();
  const q = state.query;
  if (q.period !== "30d") p.set("ky", PERIOD_KEY[q.period]);
  if (q.period === "month" && q.month) p.set("thang", q.month);
  if (q.period === "custom") {
    if (q.from) p.set("tu", q.from);
    if (q.to) p.set("den", q.to);
  }
  if (!state.compare) p.set("cmp", "0");
  return p;
}

export function windowParamsOf(params: URLSearchParams): URLSearchParams {
  return windowParams(readWindow(params));
}

export function periodLabel(q: WindowQuery): string {
  switch (q.period) {
    case "7d":
      return "7 ngày";
    case "30d":
      return "30 ngày";
    case "90d":
      return "90 ngày";
    case "month":
      return q.month ? `Tháng ${q.month.slice(5)}/${q.month.slice(0, 4)}` : "Tháng";
    default:
      return "Tuỳ chọn";
  }
}

/** The product page only knows 7 / 30 / 90 days. */
export function productPeriod(params: URLSearchParams): "7d" | "30d" | "90d" {
  const k = params.get("ky");
  return k === "7d" || k === "90d" ? k : "30d";
}

export type RankingKind = "products" | "campaigns" | "kols" | "vouchers" | "keywords";

export interface RankingState {
  readonly kpi: string;
  readonly src: string;
  readonly sub: string | null;
  readonly xep: string;
  readonly focus: string | null;
  readonly from: string | null;
  readonly card: string | null;
  readonly kind: RankingKind;
  /** The user asked for products inside a source whose default rows are another kind. */
  readonly byProduct: boolean;
  readonly dir: "xuong" | "len" | null;
}

const KINDS = new Set<RankingKind>(["products", "campaigns", "kols", "vouchers", "keywords"]);

/** Which rows a (kpi, source) cell shows: the artboards' row kinds follow the source. */
export function defaultKind(kpi: string, src: string, sub: string | null): RankingKind {
  if (src === "ads") return "campaigns";
  if (src === "lien_ket" && kpi === "gmv") return "kols";
  if (src === "voucher") return "vouchers";
  if (src === "the_san_pham" && sub === "search" && kpi === "views") return "keywords";
  return "products";
}

export function readRanking(params: URLSearchParams): RankingState {
  const kpi = KPI_NAME[params.get("kpi") ?? ""] ? (params.get("kpi") as string) : "gmv";
  const rawSrc = params.get("src") ?? "all";
  const src = SOURCE_NAME[rawSrc] ? rawSrc : rawSrc === "the_san_pham_khac" ? "the_san_pham" : "all";
  const rawSub = params.get("sub");
  const sub = src === "the_san_pham" && rawSub && CHILD_TO_API[rawSub] ? rawSub : null;
  const xepRaw = params.get("xep") ?? defaultXep(kpi);
  const xep = XEP.some(([k]) => k === xepRaw) ? xepRaw : defaultXep(kpi);
  const loai = params.get("loai") as RankingKind | null;
  const forced = loai && KINDS.has(loai) ? loai : null;
  const dflt = defaultKind(kpi, src, sub);
  const dir = params.get("huong");
  return {
    kpi,
    src,
    sub,
    xep,
    focus: params.get("focus"),
    from: params.get("from"),
    card: params.get("card"),
    kind: forced ?? dflt,
    byProduct: forced === "products" && dflt !== "products",
    dir: dir === "len" || dir === "xuong" ? dir : null,
  };
}

/** `source` / `sub` / `xep_theo` for the API from a ranking state. */
export function apiRankingArgs(s: RankingState): { kind: RankingKind; source: string; sub: string | null; xepTheo: string } {
  const xepTheo = XEP.find(([k]) => k === s.xep)?.[1] ?? "gmv_per_day";
  // Row kinds other than products answer for a narrower set of sources (`SUPPORTED`).
  if (s.kind === "keywords") return { kind: "keywords", source: "all", sub: null, xepTheo };
  if (s.kind === "campaigns") return { kind: "campaigns", source: s.src === "ads" ? "ads" : "all", sub: null, xepTheo };
  if (s.kind === "kols") return { kind: "kols", source: s.src === "lien_ket" ? "lien_ket" : "all", sub: null, xepTheo };
  if (s.kind === "vouchers") return { kind: "vouchers", source: s.src === "voucher" ? "voucher" : "all", sub: null, xepTheo };
  return {
    kind: "products",
    source: SRC_TO_API[s.src] ?? s.src,
    sub: s.sub ? (CHILD_TO_API[s.sub] ?? null) : null,
    xepTheo,
  };
}
