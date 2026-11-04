import { DASH, fmt, pc, vnd } from "../shopee-analytics/format";
import type { TableRow } from "../shopee-decisions/versions";
import type { Card, CardVersion } from "../shopee-decisions/types";
import { isRefused, roundK, svk } from "../shopee-decisions/versions";
import type { KolBlock, KolCardKind, KolProductReport, KolReport, KolRow } from "./types";

/** The pair threshold of "Ít dữ liệu" (D-11) when a report does not carry `labels.low_data_threshold`. */
export const FEW_ORDERS = 10;

export const KOL_KIND_LABEL: Readonly<Record<KolCardKind, string>> = { affiliate_sample: "Gửi mẫu", affiliate_invite: "Mời KOL" };

export const isKolKind = (kind: string): kind is KolCardKind => kind === "affiliate_sample" || kind === "affiliate_invite";

/** The `kol` block of a card or one of its versions. */
export function kolOf(v: Pick<CardVersion, "kol"> | Pick<Card, "kol">): KolBlock | null {
  return v.kol ?? null;
}

const num = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n);
const rng = (a: number | null | undefined, b: number | null | undefined, f: (n: number) => string): string => {
  if (!num(a) || !num(b)) return DASH;
  const lo = Math.min(a, b);
  const hi = Math.max(a, b);
  return f(lo) === f(hi) ? f(lo) : `${f(lo)} – ${f(hi)}`;
};
/** A commission in percent points: 8 -> "8%", 7.5 -> "7,5%". */
export const pctText = (n: number): string => `${Number.isInteger(n) ? fmt(n, 0) : fmt(n, 1)}%`;
const ro = (x: number) => String(Math.max(0, Math.round(x)));

/** What the estimate stands on, from the numbers the card has: the pair's orders and whether that is "Ít dữ liệu". */
export function kolBasis(k: KolBlock): string {
  return `${k.handle} có ${fmt(k.pair_orders, 0)} đơn của sản phẩm này trong 30 ngày${k.roi_shopee === null ? "" : `, ROI Shopee (chỉ hoa hồng) ${fmt(k.roi_shopee, 1)}`}`;
}

/** Rows of the versions table of a KOL card (`CardKOL.dc.html`): no "Hôm nay" column. */
export function kolVersionRows(versions: readonly CardVersion[], invite: boolean): TableRow[] {
  const blocks = versions.map((v) => (isRefused(v) ? null : kolOf(v)));
  const cells = (f: (k: KolBlock) => { v: string; d?: string; tone?: "up" | "down" | "plain" | "muted" }) =>
    blocks.map((k) => {
      if (!k) return { v: "Không tính được", d: "", tone: "muted" as const, bad: false };
      const r = f(k);
      return { v: r.v, d: r.d ?? "", tone: r.tone ?? ("plain" as const), bad: false };
    });
  const rows: (TableRow | null)[] = [
    { key: "product", label: "Sản phẩm", sub: "gửi / bán", today: null, cells: cells((k) => ({ v: k.product.name })) },
    invite ? null : { key: "qty", label: "Số lượng mẫu", sub: "", today: null, cells: cells((k) => ({ v: `${k.qty} mẫu` })) },
    {
      key: "sample",
      label: "Chi phí mẫu",
      sub: invite ? "không gửi mẫu" : "số lượng × (giá vốn + đóng gói) + ship",
      today: null,
      cells: cells((k) => ({
        v: k.sample ? vnd(k.sample.cost) : DASH,
        tone: "muted",
        d: k.sample ? `${k.qty} × ${vnd(k.sample.unit_cogs + k.sample.unit_packaging)} + ${vnd(k.sample.ship_fee)}` : "",
      })),
    },
    { key: "rate", label: "Hoa hồng", sub: "theo sản phẩm bán ra", today: null, cells: cells((k) => ({ v: pctText(k.commission_pct), d: num(k.commission_pct_current) ? `hiện tại ${pctText(k.commission_pct_current)}` : "" })) },
    { key: "orders", label: "Đơn dự kiến / tháng", sub: "ít dữ liệu: khoảng rộng", today: null, cells: cells((k) => ({ v: rng(k.expected.orders.p10, k.expected.orders.p90, ro), d: k.low_data ? "ít dữ liệu" : `cặp này ${fmt(k.pair_orders, 0)} đơn` })) },
    { key: "net", label: "Lợi nhuận ròng dự kiến", sub: "sau phí sàn, giá vốn, đóng gói, hoa hồng (giữa khoảng)", today: null, cells: cells((k) => ({ v: vnd(roundK(k.expected.net_profit)) })) },
    {
      key: "after",
      label: "Lợi nhuận sau mẫu",
      sub: "ròng − chi phí mẫu",
      today: null,
      cells: cells((k) => {
        const [lo, hi] = k.expected.profit_after_sample_range;
        return { v: rng(lo, hi, svk), tone: hi <= 0 ? "down" : lo >= 0 ? "up" : "plain" };
      }),
    },
    { key: "roi", label: "ROI gồm mẫu", sub: "(ròng − mẫu) ÷ (hoa hồng + mẫu), giữa khoảng", today: null, cells: cells((k) => ({ v: num(k.expected.roi_incl_samples) ? pc(k.expected.roi_incl_samples, 0) : DASH })) },
    {
      key: "payback",
      label: "Hoàn vốn mẫu",
      sub: "số đơn cần để bù chi phí mẫu",
      today: null,
      cells: cells((k) => ({ v: k.expected.payback_orders ? `≥ ${k.expected.payback_orders} đơn` : "không có chi phí mẫu", d: k.expected.payback_orders ? `ròng mỗi đơn ${vnd(roundK(k.expected.net_per_order))}` : "" })),
    },
  ];
  return rows.filter((r): r is TableRow => r !== null);
}

// ── Report ──────────────────────────────────────────────────────────────────

export interface Tile {
  readonly k: string;
  readonly v: string;
  readonly sub: string;
  readonly bad?: boolean;
}

/** The tiles come from `totals` (the rows after the filters, before the limit), as the server summed them. */
export function tilesOf(report: Pick<KolReport, "totals" | "labels">): Tile[] {
  const t = report.totals;
  const roi = t.roi_incl_samples;
  return [
    { k: "GMV từ KOL", v: vnd(roundK(t.gmv)), sub: `${fmt(t.orders, 0)} đơn · ${fmt(t.kols, 0)} KOL` },
    { k: "Hoa hồng", v: vnd(roundK(t.commission)), sub: report.labels.commission },
    { k: "Lợi nhuận ròng", v: vnd(roundK(t.net_profit)), sub: "sau phí sàn, giá vốn, đóng gói, hoa hồng" },
    { k: "Chi phí mẫu", v: num(t.sample_cost) ? vnd(roundK(t.sample_cost)) : DASH, sub: report.labels.sample_cost },
    { k: "ROI gồm mẫu", v: num(roi) ? pc(roi, 0) : DASH, sub: "ROI Shopee lấy nguyên từ file xuất, xem từng dòng", bad: num(roi) && roi < 0 },
  ];
}

export interface RowText {
  readonly handle: string;
  readonly channel: string;
  readonly few: boolean;
  readonly fewLabel: string;
  readonly product: string;
  readonly orders: string;
  readonly units: string;
  readonly gmv: string;
  /** The creator's clicks from the Shopee export (the pair's own clicks are not known). */
  readonly clicks: string;
  readonly conversion: string;
  readonly commission: string;
  readonly net: string;
  readonly sample: string;
  readonly after: string;
  readonly afterBad: boolean;
  readonly roi: string;
  readonly roiBad: boolean;
  readonly roiShopee: string;
  readonly payback: string;
}

export function rowText(r: KolRow): RowText {
  return {
    handle: r.handle,
    channel: r.channel,
    few: r.low_data,
    fewLabel: r.low_data_label ?? "Ít dữ liệu",
    product: r.product_name,
    orders: fmt(r.orders, 0),
    units: fmt(r.units, 0),
    gmv: vnd(roundK(r.gmv)),
    clicks: num(r.kol_clicks) ? fmt(r.kol_clicks, 0) : DASH,
    conversion: num(r.kol_conversion) ? pc(r.kol_conversion, 1) : DASH,
    commission: vnd(roundK(r.commission)),
    net: vnd(roundK(r.net_profit)),
    sample: num(r.sample_cost) ? (r.sample_cost > 0 ? vnd(r.sample_cost) : DASH) : r.sample_qty > 0 ? "chưa tính được" : DASH,
    after: svk(r.profit_after_samples).replace("+", ""),
    afterBad: r.profit_after_samples < 0,
    roi: num(r.roi_incl_samples) ? pc(r.roi_incl_samples, 0) : DASH,
    roiBad: num(r.roi_incl_samples) && r.roi_incl_samples < 0,
    roiShopee: num(r.roi_shopee) ? fmt(r.roi_shopee, 1) : DASH,
    payback: r.payback_orders ? `≥ ${r.payback_orders} đơn` : DASH,
  };
}

/** Commission now of a product, from the product tab body. */
export function productRateText(p: Pick<KolProductReport, "product">): string {
  const rate = p.product.commission_rate;
  return num(rate) ? pc(rate, 0) : DASH;
}
