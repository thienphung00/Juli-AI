import { DASH, fmt, pc, vnd } from "../shopee-analytics/format";
import type { TableRow } from "../shopee-decisions/versions";
import type { Card, CardVersion } from "../shopee-decisions/types";
import { isRefused, roundK, svk } from "../shopee-decisions/versions";
import type { KolCardKind, KolCert, KolRow } from "./types";

/** The pair threshold of "Ít dữ liệu" (D-11). */
export const FEW_ORDERS = 10;

export const KOL_KIND_LABEL: Readonly<Record<KolCardKind, string>> = { affiliate_sample: "Gửi mẫu", affiliate_invite: "Mời KOL" };

export const isKolKind = (kind: string): kind is KolCardKind => kind === "affiliate_sample" || kind === "affiliate_invite";

export function kolCertOf(v: Pick<CardVersion, "certain"> | Pick<Card, "certain">): KolCert | null {
  const k = (v.certain as { kol?: KolCert } | undefined)?.kol;
  return k ?? null;
}

const num = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n);
const rng = (a: number | null | undefined, b: number | null | undefined, f: (n: number) => string): string => {
  if (!num(a) || !num(b)) return DASH;
  const lo = Math.min(a, b);
  const hi = Math.max(a, b);
  return f(lo) === f(hi) ? f(lo) : `${f(lo)} – ${f(hi)}`;
};
const ro = (x: number) => String(Math.max(0, Math.round(x)));

/** Rows of the versions table of a KOL card (`CardKOL.dc.html`): no "Hôm nay" column. */
export function kolVersionRows(versions: readonly CardVersion[], invite: boolean): TableRow[] {
  const certs = versions.map((v) => (isRefused(v) ? null : kolCertOf(v)));
  const cells = (f: (c: KolCert) => { v: string; d?: string; tone?: "up" | "down" | "plain" | "muted" }) =>
    certs.map((c) => {
      if (!c) return { v: "Không tính được", d: "", tone: "muted" as const, bad: false };
      const r = f(c);
      return { v: r.v, d: r.d ?? "", tone: r.tone ?? ("plain" as const), bad: false };
    });
  const rows: (TableRow | null)[] = [
    { key: "product", label: "Sản phẩm", sub: "gửi / bán", today: null, cells: cells((c) => ({ v: c.product_name })) },
    invite ? null : { key: "qty", label: "Số lượng mẫu", sub: "", today: null, cells: cells((c) => ({ v: `${c.qty ?? 0} mẫu` })) },
    {
      key: "sample",
      label: "Chi phí mẫu",
      sub: invite ? "không gửi mẫu" : "số lượng × (giá vốn + đóng gói) + ship",
      today: null,
      cells: cells((c) => ({ v: c.sample.cost ? vnd(c.sample.cost) : DASH, tone: "muted", d: c.sample.cost && c.qty ? `${c.qty} × ${vnd(c.sample.unit_cost)} + ${vnd(c.sample.ship)}` : "" })),
    },
    { key: "rate", label: "Hoa hồng", sub: "theo sản phẩm bán ra", today: null, cells: cells((c) => ({ v: `${fmt(c.commission_pct, 0)}%`, d: `mỗi đơn dự kiến ${vnd(num(c.expected.commission_per_order) ? roundK(c.expected.commission_per_order) : null)}` })) },
    { key: "orders", label: "Đơn dự kiến / tháng", sub: "ít dữ liệu: khoảng rộng", today: null, cells: cells((c) => ({ v: rng(c.expected.orders.p10, c.expected.orders.p90, ro), d: c.few_data ? "ít dữ liệu" : c.basis })) },
    { key: "net", label: "Lợi nhuận ròng dự kiến", sub: "sau phí sàn, giá vốn, đóng gói, hoa hồng", today: null, cells: cells((c) => ({ v: rng(c.expected.net.p10, c.expected.net.p90, (x) => vnd(roundK(x))) })) },
    {
      key: "after",
      label: "Lợi nhuận sau mẫu",
      sub: "ròng − chi phí mẫu",
      today: null,
      cells: cells((c) => {
        const { p10, p90 } = c.expected.profit_after_samples;
        return { v: rng(p10, p90, svk), tone: num(p90) && p90 <= 0 ? "down" : num(p10) && p10 >= 0 ? "up" : "plain" };
      }),
    },
    { key: "roi", label: "ROI gồm mẫu", sub: "(ròng − mẫu) ÷ (hoa hồng + mẫu)", today: null, cells: cells((c) => ({ v: c.expected.roi ? rng(c.expected.roi.p10, c.expected.roi.p90, (x) => pc(x, 0)) : DASH })) },
    {
      key: "payback",
      label: "Hoàn vốn mẫu",
      sub: "số đơn cần để bù chi phí mẫu",
      today: null,
      cells: cells((c) => ({ v: c.expected.payback_orders ? `≥ ${c.expected.payback_orders} đơn` : "không có chi phí mẫu", d: c.expected.payback_orders ? `ròng mỗi đơn ${vnd(num(c.expected.net_per_order) ? roundK(c.expected.net_per_order) : null)}` : "" })),
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

export function tilesOf(rows: readonly KolRow[]): Tile[] {
  const sum = (f: (r: KolRow) => number) => rows.reduce((a, r) => a + f(r), 0);
  const comm = sum((r) => r.commission);
  const net = sum((r) => r.net_profit);
  const sample = sum((r) => r.sample_cost);
  const roi = comm + sample > 0 ? (net - sample) / (comm + sample) : null;
  return [
    { k: "GMV từ KOL", v: vnd(roundK(sum((r) => r.gmv))), sub: `${fmt(sum((r) => r.orders), 0)} đơn` },
    { k: "Hoa hồng", v: vnd(roundK(comm)), sub: "theo mức từng sản phẩm" },
    { k: "Lợi nhuận ròng", v: vnd(roundK(net)), sub: "sau phí sàn, giá vốn, đóng gói, hoa hồng" },
    { k: "Chi phí mẫu", v: vnd(roundK(sample)), sub: "số lượng × (giá vốn + đóng gói) + ship" },
    { k: "ROI gồm mẫu", v: roi === null ? DASH : pc(roi, 0), sub: "ROI Shopee lấy nguyên từ file xuất, xem từng dòng", bad: roi !== null && roi < 0 },
  ];
}

export interface RowText {
  readonly handle: string;
  readonly channel: string;
  readonly few: boolean;
  readonly product: string;
  readonly orders: string;
  readonly units: string;
  readonly gmv: string;
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
    few: r.few_data,
    product: r.product_name,
    orders: fmt(r.orders, 0),
    units: fmt(r.units, 0),
    gmv: vnd(roundK(r.gmv)),
    clicks: fmt(r.clicks, 0),
    conversion: pc(r.conversion, 1),
    commission: vnd(roundK(r.commission)),
    net: vnd(roundK(r.net_profit)),
    sample: r.sample_cost ? vnd(r.sample_cost) : DASH,
    after: svk(r.profit_after_samples).replace("+", ""),
    afterBad: r.profit_after_samples < 0,
    roi: r.roi_with_samples === null ? DASH : pc(r.roi_with_samples, 0),
    roiBad: r.roi_with_samples !== null && r.roi_with_samples < 0,
    roiShopee: r.roi_shopee === null || r.roi_shopee === undefined ? DASH : String(r.roi_shopee),
    payback: r.payback_orders ? `≥ ${r.payback_orders} đơn` : DASH,
  };
}
