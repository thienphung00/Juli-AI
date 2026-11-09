import { DASH, fmt, pp, vnd } from "../shopee-analytics/format";
import type { ProductChoice } from "./context";
import type { Breach, CompareResult, DiscountType, N, VariantInput, VariantRow } from "./types";
import { MAX_TITLE_CHARS, breachWarnLines, rangeK, roundK, svk } from "./versions";

/**
 * Tự tạo phương án / So sánh phương án (`TuTaoPhuongAn.dc.html`, mobile `TuTaoPhuongAnMobile.dc.html`).
 *
 * The screen keeps one editor state per variant (up to 4) - the artboard's: change type, up to 3
 * products with quantities, discount as % / số tiền / giá combo cố định, an optional stacked voucher,
 * an optional gift. `toVariant` turns it into the backend's variant (`shopee_reco_manual_common.VariantBody`):
 *
 *   Combo nhiều sản phẩm, Mua kèm, Quà tặng  -> `combo_multi` (2-3 different products; the combo calculator)
 *   Voucher                                  -> `min_spend_voucher` (value, min_spend)
 *   Giảm giá                                 -> `product_discount` (discount_pct)
 *
 * Quảng cáo and Tiêu đề are compared inside their own cards (versions), so they only validate here.
 */

export type BuilderKind = "combo" | "addon" | "gift" | "voucher" | "disc" | "ads" | "title";

export const KINDS: readonly (readonly [BuilderKind, string])[] = [
  ["combo", "Combo nhiều sản phẩm"],
  ["addon", "Mua kèm"],
  ["gift", "Quà tặng"],
  ["voucher", "Voucher"],
  ["disc", "Giảm giá"],
  ["ads", "Quảng cáo"],
  ["title", "Tiêu đề"],
];

export const kindName = (k: BuilderKind): string => KINDS.find(([key]) => key === k)![1];
export const isCalc = (k: BuilderKind): boolean => k !== "ads" && k !== "title";

export type BuilderDiscount = "pct" | "amt" | "price";

export interface BuilderItem {
  readonly id: string;
  readonly qty: number;
}

export interface BuilderVariant {
  readonly kind: BuilderKind;
  readonly items: readonly BuilderItem[];
  readonly dtype: BuilderDiscount;
  readonly dval: number;
  readonly voucher: { readonly v: number; readonly min: number } | null;
  readonly gift: string | null;
  readonly title: string;
}

export const MAX_VARIANTS = 4;
export const MAX_ITEMS = 3;

const empty = (): BuilderItem => ({ id: "", qty: 0 });
const slots = (items: readonly BuilderItem[]): BuilderItem[] => [...items, empty(), empty(), empty()].slice(0, MAX_ITEMS);

/** The starting values of a change type (the artboard's PRESET), on this shop's own products. */
export function presetOf(kind: BuilderKind, products: readonly ProductChoice[], focus?: string | null, current?: BuilderVariant): BuilderVariant {
  const ids = [focus, ...products.map((p) => p.id)].filter((x, i, a): x is string => !!x && a.indexOf(x) === i);
  const [p0 = "", p1 = ""] = ids;
  const base: BuilderVariant = { kind, items: slots([{ id: p0, qty: p0 ? 2 : 0 }, { id: p1, qty: p1 ? 1 : 0 }]), dtype: "pct", dval: 10, voucher: null, gift: null, title: current?.title ?? "" };
  switch (kind) {
    case "addon":
      return { ...base, items: slots([{ id: p0, qty: p0 ? 1 : 0 }, { id: p1, qty: p1 ? 1 : 0 }]), dtype: "amt", dval: 10000 };
    case "gift":
      return { ...base, dval: 5, gift: p1 || null };
    case "voucher":
      return { ...base, items: slots([{ id: p0, qty: p0 ? 2 : 0 }]), dval: 0, voucher: { v: 15000, min: 150000 } };
    case "disc":
      return { ...base, items: slots([{ id: p0, qty: p0 ? 2 : 0 }]), dval: 8 };
    case "ads":
    case "title":
      return { ...base, items: current?.items ?? base.items };
    default:
      return base;
  }
}

export function discountRange(t: BuilderDiscount): { readonly min: number; readonly max: number; readonly step: number } {
  return t === "pct" ? { min: 0, max: 30, step: 1 } : t === "amt" ? { min: 0, max: 100_000, step: 1000 } : { min: 10_000, max: 2_000_000, step: 1000 };
}

export const discountLabel = (t: BuilderDiscount, v: number): string => (t === "pct" ? `${fmt(v, 0)}%` : vnd(v));

/** The first value when the person switches the discount type. */
export function defaultDiscount(t: BuilderDiscount, listValue: number | null): number {
  return t === "pct" ? 10 : t === "amt" ? 20_000 : Math.max(10_000, Math.round(((listValue ?? 237_000) * 0.84) / 1000) * 1000);
}

/** Calculator kinds that take their discount as % only. */
export const PCT_ONLY: ReadonlySet<BuilderKind> = new Set<BuilderKind>(["voucher", "disc"]);

const DISCOUNT_TYPE: Readonly<Record<BuilderDiscount, DiscountType>> = { pct: "pct", amt: "amount", price: "fixed_price" };

export interface Built {
  readonly input: VariantInput | null;
  /** Why the variant cannot be priced yet (shown instead of numbers). */
  readonly problem: string | null;
}

export function toVariant(v: BuilderVariant, label?: string): Built {
  const lines = v.items.filter((i) => i.id && i.qty > 0);
  const ids = [...new Set(lines.map((l) => l.id))];
  const name = label ? { label } : {};
  if (v.kind === "ads" || v.kind === "title") return { input: null, problem: null };
  if (v.kind === "voucher") {
    if (!v.voucher) return { input: null, problem: "Chọn giá trị voucher." };
    return {
      input: { ...name, change_kind: "min_spend_voucher", items: ids.slice(0, 1), extra: {}, inputs: { value: v.voucher.v, max_value: v.voucher.v, min_spend: v.voucher.min, quantity: 100, days: 30 } },
      problem: null,
    };
  }
  if (v.kind === "disc") {
    if (ids.length === 0) return { input: null, problem: "Chưa chọn sản phẩm." };
    return { input: { ...name, change_kind: "product_discount", items: ids.slice(0, 1), extra: {}, inputs: { discount_pct: v.dval } }, problem: null };
  }
  if (ids.length < 2) return { input: null, problem: "Combo cần 2 hoặc 3 sản phẩm." };
  if (v.dtype === "price" && v.dval <= 0) return { input: null, problem: "Nhập giá combo." };
  return {
    input: {
      ...name,
      change_kind: "combo_multi",
      items: ids,
      extra: {
        combo_items: lines.map((l) => ({ item_id: l.id, qty: l.qty })),
        discount_type: DISCOUNT_TYPE[v.dtype],
        discount_value: v.dval,
        ...(v.voucher ? { voucher: { value: v.voucher.v, min_spend: v.voucher.min } } : {}),
        ...(v.gift ? { gift_item: v.gift } : {}),
      },
      inputs: {},
    },
    problem: null,
  };
}

/** The variants that can be priced, with their place in the editor (compare takes 2-4; one is sent twice). */
export interface Sendable {
  readonly index: number;
  readonly input: VariantInput;
}

export function sendable(vars: readonly BuilderVariant[]): Sendable[] {
  const out: Sendable[] = [];
  vars.forEach((v, index) => {
    const { input } = toVariant(v, `P${index + 1}`);
    if (input) out.push({ index, input });
  });
  return out;
}

/** What the backend needs to compare: 2-4 variants (a single one is sent twice and read once). */
export function compareBody(s: readonly Sendable[]): VariantInput[] {
  const list = s.map((x) => x.input);
  return list.length === 1 ? [list[0]!, list[0]!] : list;
}

// ── Reading the comparison ──────────────────────────────────────────────────

export interface CompareCell {
  readonly v: string;
  readonly d: string;
  readonly tone: "up" | "down" | "flat";
  /** "phương án gốc" / "so P1: +30.000đ". */
  readonly vs: string;
}

export interface CompareRow {
  readonly key: string;
  readonly label: string;
  readonly sub: string;
  readonly today: string;
  readonly cells: readonly (CompareCell | null)[];
}

const num = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n);
const signedPts = (d: number): string => `${d >= 0 ? "+" : "−"}${fmt(Math.abs(d), 1)} điểm`;
const signedOrders = (d: number): string => `${d >= 0 ? "+" : "−"}${fmt(Math.abs(Math.round(d)), 0)} đơn`;
const arrow = (d: number): string => (Math.abs(d) < 1e-9 ? "" : d > 0 ? "▲ " : "▼ ");

interface MetricDef {
  readonly key: string;
  readonly label: string;
  readonly sub: string;
  /** Key of the delta in `metrics` / `between`. */
  readonly delta: string;
  readonly good: 1 | -1;
  readonly today: (c: CompareResult) => string;
  readonly cell: (c: CompareResult, d: number, row: VariantRow) => string;
  readonly fmtDelta: (d: number) => string;
}

const todayOf = (c: CompareResult) => c.today;

const METRICS: readonly MetricDef[] = [
  {
    key: "profit",
    label: "Lợi nhuận",
    sub: "Δ trong số ngày của thay đổi, khoảng dự kiến",
    delta: "dprofit_p50",
    good: 1,
    today: () => DASH,
    cell: (_c, _d, row) => `${rangeK(row.metrics?.dprofit_p10, row.metrics?.dprofit_p90)}`,
    fmtDelta: (d) => svk(d),
  },
  {
    key: "bien",
    label: "Biên",
    sub: "lợi nhuận ÷ tiền khách trả",
    delta: "margin_points_p50",
    good: 1,
    today: (c) => (num(todayOf(c).margin_pct) ? pp(todayOf(c).margin_pct, 1) : DASH),
    cell: (c, d) => {
      const m = todayOf(c).margin_pct;
      return num(m) ? pp(m + d, 1) : DASH;
    },
    fmtDelta: signedPts,
  },
  {
    key: "aov",
    label: "AOV",
    sub: "GMV ÷ số đơn",
    delta: "aov_p50",
    good: 1,
    today: (c) => (num(todayOf(c).aov) ? vnd(roundK(todayOf(c).aov as number)) : DASH),
    cell: (c, d) => (num(todayOf(c).aov) ? vnd(roundK((todayOf(c).aov as number) + d)) : DASH),
    fmtDelta: (d) => svk(d),
  },
  {
    key: "orders",
    label: "Số đơn",
    sub: "30 ngày",
    delta: "dorders_p50",
    good: 1,
    today: (c) => fmt(todayOf(c).orders_30d, 0),
    cell: (c, d) => fmt(Math.round(todayOf(c).orders_30d + d), 0),
    fmtDelta: signedOrders,
  },
  {
    key: "gmv",
    label: "GMV",
    sub: "30 ngày",
    delta: "dgmv_p50",
    good: 1,
    today: (c) => vnd(roundK(todayOf(c).gmv_30d)),
    cell: (c, d) => vnd(roundK(todayOf(c).gmv_30d + d)),
    fmtDelta: (d) => svk(d),
  },
  {
    key: "chi",
    label: "Chi phí",
    sub: "QC + voucher + khuyến mãi + combo + hoa hồng",
    delta: "cost_month",
    good: -1,
    today: (c) => {
      const s = todayOf(c).spend_per_day;
      return num(s) ? vnd(roundK(s * 30)) : DASH;
    },
    cell: (c, d) => {
      const s = todayOf(c).spend_per_day;
      return num(s) ? vnd(roundK(s * 30 + d)) : DASH;
    },
    fmtDelta: (d) => svk(d),
  },
];

const toneOf = (good: 1 | -1, d: number): "up" | "down" | "flat" => (Math.abs(d) < 1e-9 ? "flat" : d * good > 0 ? "up" : "down");

/** Rows of the comparison table; one cell per variant of the editor (null: not priced here). */
export function compareRows(result: CompareResult, sent: readonly Sendable[], variantCount: number): CompareRow[] {
  const byEditor = new Map<number, VariantRow>();
  sent.forEach((s, k) => {
    const row = result.variants[k];
    if (row) byEditor.set(s.index, row);
  });
  const ref = [...byEditor.entries()].find(([, r]) => r.ok);
  const refIndex = ref ? ref[0] : -1;
  const rows: CompareRow[] = METRICS.map((m) => ({
    key: m.key,
    label: m.label,
    sub: m.sub,
    today: m.today(result),
    cells: Array.from({ length: variantCount }, (_, i): CompareCell | null => {
      const row = byEditor.get(i);
      if (!row || !row.ok || !row.metrics) return null;
      const raw = row.metrics[m.delta as keyof typeof row.metrics];
      const d = num(raw) ? raw : 0;
      let vs = "";
      if (i === refIndex) vs = "phương án gốc";
      else if (ref) {
        const refRaw = ref[1].metrics?.[m.delta as keyof typeof row.metrics];
        vs = `so P${refIndex + 1}: ${m.fmtDelta(d - (num(refRaw) ? refRaw : 0))}`;
      }
      return { v: m.cell(result, d, row), d: `${arrow(d)}${m.fmtDelta(d)}`, tone: toneOf(m.good, d), vs };
    }),
  }));
  rows.push({
    key: "floor",
    label: "Giá sàn",
    sub: "từng sản phẩm trong phương án",
    today: DASH,
    cells: Array.from({ length: variantCount }, (_, i): CompareCell | null => {
      const row = byEditor.get(i);
      if (!row || !row.ok) return null;
      const bad = row.card?.floor.breaches ?? [];
      const over = row.metrics?.spend_over_cap === true;
      const names = [...new Set(bad.map((b) => b.sku))].join(", ");
      const v = bad.length > 0 ? `✕ ${names}` : over ? "✕ Vượt trần chi" : "✓ Trên giá sàn vận hành";
      return { v, d: "", tone: bad.length > 0 || over ? "down" : "up", vs: "" };
    }),
  });
  return rows;
}

/** "P3 so với P1: biên giảm 1,2 điểm nhưng AOV tăng …" - one sentence per variant that trades margin for basket size. */
export function tradeoffs(result: CompareResult, sent: readonly Sendable[]): string[] {
  const rows = sent.map((s, k) => ({ editor: s.index, row: result.variants[k] })).filter((x) => x.row?.ok && x.row.metrics);
  const ref = rows[0];
  if (!ref) return [];
  const out: string[] = [];
  for (const x of rows.slice(1)) {
    const between = result.between.find((b) => b.from === ref.row!.index && b.to === x.row!.index);
    if (!between) continue;
    const dBien = between.delta["margin_points_p50"];
    const dAov = between.delta["aov_p50"];
    if (num(dBien) && num(dAov) && dBien < 0 && dAov > 0) {
      out.push(
        `P${x.editor + 1} so với P${ref.editor + 1}: biên giảm ${fmt(Math.abs(dBien), 1)} điểm nhưng AOV tăng ${vnd(roundK(dAov))}, GMV ${svk(between.delta["dgmv_p50"])}, lợi nhuận ${svk(between.delta["dprofit_p50"])} trong kỳ tính. Chọn theo việc bạn cần: lợi nhuận hay doanh thu.`,
      );
    }
  }
  return out;
}

/** One alert per variant that breaks a floor (the others can still be saved). */
export function floorAlerts(result: CompareResult, sent: readonly Sendable[], nameOf: (itemId: string) => string): { readonly title: string; readonly text: string }[] {
  const out: { title: string; text: string }[] = [];
  sent.forEach((s, k) => {
    const row = result.variants[k];
    const bad = row?.card?.floor.breaches ?? [];
    if (!row?.ok || bad.length === 0) return;
    out.push({
      title: `P${s.index + 1} chạm giá sàn.`,
      text: `${bad.map((b) => `${nameOf(String((b as Breach)["item_id"] ?? b.sku ?? ""))}${b.sku ? "" : ""}: ${vnd(b.min_unit_price)} < sàn vận hành ${vnd(b.floor)}`).join("; ")}. Vẫn lưu được sau khi bạn xác nhận cảnh báo.`,
    });
  });
  return out;
}

export interface OrderLine {
  readonly k: string;
  readonly v: string;
  readonly tone?: "up" | "down";
}

/** "Một đơn của P1": the combo calculator's per-order arithmetic (`combo.price_combo`), or nothing for the other kinds. */
export function orderLines(row: VariantRow | undefined, todayMargin: N): OrderLine[] | null {
  const c = row?.card?.certain as Record<string, unknown> | undefined;
  if (!c || c["combo_multi"] !== true) return null;
  const n = (k: string): number | null => (num(c[k]) ? (c[k] as number) : null);
  const gift = n("gift_cost");
  const vDisc = n("voucher_discount");
  const contrib = n("contribution");
  const base = n("contribution_without_offer");
  const be = c["break_even_extra_orders"];
  const margin = n("margin_pct");
  const cogs = (n("cogs") ?? 0) + (n("packaging") ?? 0);
  return [
    { k: "Giá niêm yết cả giỏ", v: vnd(n("list_value")) },
    { k: "Giảm giá", v: `−${vnd(n("combo_discount"))}` },
    { k: "Voucher cộng thêm", v: vDisc && vDisc > 0 ? `−${vnd(vDisc)}` : DASH },
    { k: "Khách trả", v: vnd(n("buyer_pays")) },
    { k: "Giá vốn + đóng gói", v: `−${vnd(cogs)}` },
    { k: "Quà tặng (giá vốn + đóng gói)", v: gift !== null ? `−${vnd(gift)}` : DASH },
    { k: "Phí sàn (một lần cho đơn)", v: `−${vnd(n("platform_fees"))}` },
    { k: "Đóng góp mỗi đơn", v: vnd(contrib), tone: contrib !== null && base !== null ? (contrib >= base ? "up" : "down") : undefined },
    { k: "Biên của đơn combo", v: `${pp(margin, 1)}${num(todayMargin) ? ` (hôm nay ${pp(todayMargin, 1)})` : ""}` },
    { k: "Chi phí ưu đãi mỗi đơn", v: vnd(n("cost_per_combo_order")) },
    { k: "Hoà vốn", v: be === 0 ? "Không cần đơn thêm" : typeof be === "number" ? `Cần ≥ ${fmt(be, 0)} đơn combo thêm trong kỳ tính` : "Không hoà vốn" },
  ];
}

/** Floor per SKU of the selected combo: ✓ / ✕, what the buyer pays per unit and the operating floor. */
export function floorLines(row: VariantRow | undefined, nameOf: (itemId: string) => string): { readonly name: string; readonly text: string; readonly bad: boolean }[] {
  const lines = (row?.card?.certain as { lines?: readonly Record<string, unknown>[] } | undefined)?.lines ?? [];
  return lines.map((l) => {
    const bad = l["below_floor"] === true;
    const floor = num(l["floor"]) ? (l["floor"] as number) : null;
    return { name: nameOf(String(l["item_id"] ?? "")), bad, text: `${bad ? "✕" : "✓"} ${vnd(l["unit_paid"] as number)} / sản phẩm, sàn vận hành ${floor === null ? "chưa biết" : vnd(floor)}` };
  });
}

export { MAX_TITLE_CHARS, breachWarnLines };
