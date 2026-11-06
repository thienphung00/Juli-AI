import { DASH, fmt, pp, sv, vnd } from "../shopee-analytics/format";
import type { Band, BuilderOutcome, BuilderVersion, BuilderWarning, CoverOverlay, PickerProduct, VariationRow } from "./builder-api";

/**
 * Tự tạo phương án (P92): the form state of each strategy, and how it becomes a version of
 * `POST /builder/evaluate | compare | choose` (`fasttrack/contracts/p92-api.md` §3).
 * Numbers are kept as the raw text of their input and parsed here, so the cursor never jumps.
 */

export type Kind92 =
  | "voucher"
  | "combo"
  | "add_on"
  | "gift"
  | "product_discount"
  | "price_flash"
  | "variation_set"
  | "ads"
  | "title"
  | "cover_image"
  | "description_first_line"
  | "affiliate"
  | "price_display";

export const MAX_VERSIONS = 4;
export const MAX_TITLE = 100;
/** The server's limits (`services/shopee_builder/specs.py`), checked here so a refusal reads in Vietnamese. */
export const MAX_PCT = 90;
export const MAX_VOUCHER_DAYS = 90;
export const MAX_FIRST_LINE = 300;

/** The 13 strategies, each with the driver metric(s) it is measured by (B-3, artboard `kinds`). */
export const KINDS_92: readonly { readonly key: Kind92; readonly name: string; readonly drivers: string }[] = [
  { key: "voucher", name: "Voucher", drivers: "AOV · CTOR" },
  { key: "combo", name: "Combo nhiều sản phẩm", drivers: "AOV · CTOR" },
  { key: "add_on", name: "Mua kèm", drivers: "AOV" },
  { key: "gift", name: "Quà tặng", drivers: "CTOR · đơn" },
  { key: "product_discount", name: "Giảm giá", drivers: "CTOR · đơn" },
  { key: "price_flash", name: "Giá bán + Flash sale", drivers: "CTOR · đơn" },
  { key: "variation_set", name: "Phân loại / set", drivers: "AOV · CTOR" },
  { key: "ads", name: "Quảng cáo", drivers: "chi · GMV · ROAS" },
  { key: "title", name: "Tiêu đề", drivers: "lượt xem · CTR" },
  { key: "cover_image", name: "Ảnh bìa", drivers: "CTR" },
  { key: "description_first_line", name: "Mô tả", drivers: "CTOR" },
  { key: "affiliate", name: "Affiliate / KOL", drivers: "đơn affiliate" },
  { key: "price_display", name: "Hiển thị giá + listing", drivers: "CTR · CTOR · lượt xem" },
];

export const kindName92 = (k: string): string => KINDS_92.find((x) => x.key === k)?.name ?? k;

/** The kind the server knows for a form kind (some forms hold two). */
export const SERVER_KIND_NAMES: Readonly<Record<string, string>> = {
  voucher: "Voucher",
  combo: "Combo",
  add_on: "Mua kèm",
  gift: "Quà tặng",
  product_discount: "Giảm giá",
  price: "Giá bán",
  flash_sale: "Flash sale",
  variation_set: "Phân loại / set",
  ads: "Quảng cáo",
  title: "Tiêu đề",
  cover_image: "Ảnh bìa",
  description_first_line: "Mô tả",
  affiliate: "Affiliate / KOL",
  price_display: "Hiển thị giá",
  listing_hide: "Ẩn listing",
  listing_relist: "Đưa lại listing",
};

// ── parsing ──────────────────────────────────────────────────────────────

/** A number typed with `.` or `,` as the decimal mark and no grouping; `null` when empty or not a number. */
export function num(text: string | null | undefined): number | null {
  if (text === null || text === undefined) return null;
  const t = text.trim().replace(/\s/g, "").replace(",", ".");
  if (t === "") return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

/** 5000 -> "5k", 100000 -> "100k", 12500 -> "12.500đ". */
export function kmoney(n: number): string {
  return n % 1000 === 0 && n >= 1000 ? `${fmt(n / 1000)}k` : vnd(n);
}

/** Chips of the voucher panel, from the shop's AOV: 5k/100k, 10k/100k, 10k/150k, 15k/200k at AOV 124.143đ. */
export function voucherChips(aov: number | null): readonly { readonly value: number; readonly min: number; readonly label: string }[] {
  const lo = aov && aov > 0 ? Math.max(50_000, Math.round((aov * 0.8) / 50_000) * 50_000) : 100_000;
  const pairs: [number, number][] = [
    [5_000, lo],
    [10_000, lo],
    [10_000, lo + 50_000],
    [15_000, lo + 100_000],
  ];
  return pairs.map(([value, min]) => ({ value, min, label: `${value / 1000}k / ${min / 1000}k` }));
}

/**
 * The variation step 2 starts on: the first one with orders in the last 30 days, else the first in
 * stock, else the first. The list is in variation-id order, so its head is often an old, sold-out one.
 */
export function defaultVariationId(variations: readonly VariationRow[]): string | undefined {
  const withOrders = variations.find((v) => (v.orders_30d ?? 0) > 0);
  const inStock = variations.find((v) => (v.stock ?? 0) > 0);
  return (withOrders ?? inStock ?? variations[0])?.variation_id;
}

// ── form state ───────────────────────────────────────────────────────────

export interface ComboItem {
  readonly itemId: string;
  readonly variationId: string;
  readonly qty: string;
}
export interface AddonRow {
  readonly itemId: string;
  readonly variationId: string;
  readonly mode: "price" | "pct";
  readonly value: string;
  readonly limit: string;
}
export interface VarValue {
  readonly variationId: string;
  readonly value: string;
}
export interface NewVariation {
  readonly name: string;
  readonly price: string;
  readonly sku: string;
  readonly packCount: string;
  readonly stock: string;
}
export interface KeywordBid {
  readonly keyword: string;
  readonly bid: string;
  readonly match: "broad" | "exact";
}

export interface Forms {
  readonly voucher: { scope: "shop" | "product" | "follower" | "livestream"; dtype: "amount" | "pct"; value: string; min: string; max: string; usage: string; perBuyer: string; start: string; end: string };
  readonly combo: { items: readonly ComboItem[]; pricing: "fixed_price" | "pct" | "amount"; value: string; target: "bundle_deal" | "new_listing" };
  readonly add_on: { addons: readonly AddonRow[] };
  readonly gift: { source: "listing" | "unsold"; giftItemId: string; unitCost: string; label: string; packaging: string; qty: string; trigger: "buy_item" | "min_spend"; triggerItemId: string; minSpend: string };
  readonly product_discount: { mode: "pct" | "final_price"; rows: readonly VarValue[]; start: string; end: string; perBuyer: string };
  readonly price_flash: { what: "price" | "flash_sale"; mode: "pct" | "final_price"; rows: readonly VarValue[]; units: string; slotStart: string; slotHours: string };
  readonly variation_set: { rows: readonly NewVariation[] };
  readonly ads: { lever: "budget" | "roas" | "add_product" | "remove_product" | "keywords"; campaignKey: string; dailyBudget: string; roasTarget: string; itemId: string; keywords: readonly KeywordBid[] };
  readonly title: { ticked: readonly string[]; text: string };
  readonly cover_image: { overlay: CoverOverlay | null };
  readonly description_first_line: { text: string };
  readonly affiliate: { commission: string; campaign: string; samples: string; shipFee: string };
  readonly price_display: { what: "price_display" | "listing_hide" | "listing_relist"; text: string; stock: string };
}

export const newItem = (itemId = "", variationId = ""): ComboItem => ({ itemId, variationId, qty: "1" });

export function initialForms(): Forms {
  return {
    voucher: { scope: "product", dtype: "amount", value: "5000", min: "100000", max: "", usage: "", perBuyer: "", start: "", end: "" },
    combo: { items: [newItem(), newItem()], pricing: "pct", value: "10", target: "new_listing" },
    add_on: { addons: [{ itemId: "", variationId: "", mode: "pct", value: "15", limit: "1" }] },
    gift: { source: "listing", giftItemId: "", unitCost: "", label: "", packaging: "", qty: "1", trigger: "min_spend", triggerItemId: "", minSpend: "150000" },
    product_discount: { mode: "pct", rows: [], start: "", end: "", perBuyer: "" },
    price_flash: { what: "price", mode: "pct", rows: [], units: "50", slotStart: "", slotHours: "2" },
    variation_set: { rows: [{ name: "", price: "", sku: "", packCount: "", stock: "" }] },
    ads: { lever: "budget", campaignKey: "", dailyBudget: "", roasTarget: "", itemId: "", keywords: [{ keyword: "", bid: "", match: "broad" }] },
    title: { ticked: [], text: "" },
    cover_image: { overlay: null },
    description_first_line: { text: "" },
    affiliate: { commission: "10", campaign: "", samples: "0", shipFee: "" },
    price_display: { what: "price_display", text: "", stock: "" },
  };
}

/** What the builder knows about the chosen product when it turns a form into a version. */
export interface BuildCtx {
  readonly product: PickerProduct;
  /** The variations chosen in step 2 (all of them for "Tất cả phân loại"). */
  readonly variations: readonly VariationRow[];
}

export interface Built92 {
  readonly version: BuilderVersion | null;
  /** Why it cannot be priced yet (shown instead of numbers). */
  readonly problem: string | null;
}

const no = (problem: string): Built92 => ({ version: null, problem });
const PCT_PROBLEM = `Phần trăm giảm tối đa ${MAX_PCT}%.`;
/** `{variation_id}` only when one is chosen: an empty id is never sent (the server picks the top SKU). */
const vid = (variationId: string): Record<string, string> => (variationId ? { variation_id: variationId } : {});
/** An optional whole number typed in a field: null when empty, the problem text when below `min` / above `max`. */
function intIn(text: string, min: number, max: number, problem: string): { readonly n: number | null; readonly problem: string | null } {
  const n = num(text);
  if (n === null) return { n: null, problem: null };
  if (!Number.isInteger(n) || n < min || n > max) return { n: null, problem };
  return { n, problem: null };
}
function dateProblem(start: string, end: string, maxDays: number | null): string | null {
  if (!start || !end) return null;
  const a = Date.parse(`${start}T00:00:00Z`);
  const b = Date.parse(`${end}T00:00:00Z`);
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null;
  if (b < a) return "Ngày kết thúc phải từ ngày bắt đầu trở đi.";
  if (maxDays !== null && Math.round((b - a) / 86_400_000) + 1 > maxDays) return `Chạy tối đa ${maxDays} ngày.`;
  return null;
}
const clip = (s: string, n = 60): string => (s.length > n ? s.slice(0, n) : s);
const dated = (start: string, end: string): Record<string, string> => ({ ...(start ? { start } : {}), ...(end ? { end } : {}) });
const opt = (key: string, text: string): Record<string, number> => {
  const n = num(text);
  return n !== null ? { [key]: n } : {};
};

function varRows(rows: readonly VarValue[], mode: "pct" | "final_price", pctKey: string): { rows: Record<string, unknown>[]; problem: string | null } {
  const out: Record<string, unknown>[] = [];
  for (const r of rows) {
    const n = num(r.value);
    if (n === null || r.value.trim() === "") continue;
    if (n <= 0) return { rows: [], problem: "Nhập số lớn hơn 0." };
    if (mode === "pct" && n > MAX_PCT) return { rows: [], problem: PCT_PROBLEM };
    out.push({ ...vid(r.variationId), [mode === "pct" ? pctKey : "final_price"]: n });
  }
  return { rows: out, problem: out.length === 0 ? "Nhập mức giảm hoặc giá cho ít nhất một phân loại." : null };
}

export function buildVersion(kind: Kind92, f: Forms, ctx: BuildCtx): Built92 {
  const id = ctx.product.item_id;
  switch (kind) {
    case "voucher": {
      const v = f.voucher;
      const value = num(v.value);
      const min = num(v.min) ?? 0;
      if (value === null || value <= 0) return no("Nhập giá trị voucher.");
      if (v.dtype === "pct" && value > 90) return no("Voucher phần trăm tối đa 90%.");
      if (min < 0) return no("Đơn tối thiểu từ 0đ.");
      if (v.dtype === "amount" && min > 0 && value >= min) return no("Giá trị voucher phải nhỏ hơn đơn tối thiểu.");
      const cap = v.dtype === "pct" ? intIn(v.max, 1, Number.MAX_SAFE_INTEGER, "Giảm tối đa từ 1đ.") : { n: null, problem: null };
      const usage = intIn(v.usage, 1, 10_000_000, "Số lượt dùng tối đa từ 1.");
      const perBuyer = intIn(v.perBuyer, 1, 100, "Giới hạn mỗi người từ 1 đến 100 lượt.");
      const problem = cap.problem ?? usage.problem ?? perBuyer.problem ?? dateProblem(v.start, v.end, MAX_VOUCHER_DAYS);
      if (problem) return no(problem);
      const label = v.dtype === "pct" ? `${fmt(value, 0)}% / ${kmoney(min)}` : `${kmoney(value)} / ${kmoney(min)}`;
      return {
        problem: null,
        version: {
          kind: "voucher",
          label: clip(label),
          scope: v.scope,
          ...(v.scope === "product" ? { item_ids: [id] } : {}),
          discount_type: v.dtype,
          value,
          min_spend: min,
          ...(cap.n !== null ? { max_value: cap.n } : {}),
          ...(usage.n !== null ? { usage_limit: usage.n } : {}),
          ...(perBuyer.n !== null ? { per_buyer_limit: perBuyer.n } : {}),
          ...dated(v.start, v.end),
        },
      };
    }
    case "combo": {
      const c = f.combo;
      const items = c.items.filter((i) => i.itemId);
      if (items.length < 2) return no("Combo cần từ 2 đến 6 sản phẩm khác nhau.");
      if (new Set(items.map((i) => i.itemId)).size !== items.length) return no("Các sản phẩm trong combo phải khác nhau.");
      const value = num(c.value);
      if (value === null || value <= 0) return no(c.pricing === "fixed_price" ? "Nhập giá combo." : "Nhập mức giảm.");
      if (c.pricing === "pct" && value > MAX_PCT) return no(PCT_PROBLEM);
      // P96e: 10đ as a fixed combo price is a percent typed in the wrong mode, not a price.
      if (c.pricing === "fixed_price" && value < MIN_COMBO_PRICE) return no(REFUSAL_TEXT.combo_price_too_low!);
      const lines: Record<string, unknown>[] = [];
      for (const i of items) {
        const q = intIn(i.qty.trim() === "" ? "1" : i.qty, 1, 20, "Số lượng mỗi sản phẩm từ 1 đến 20.");
        if (q.problem) return no(q.problem);
        lines.push({ item_id: i.itemId, ...vid(i.variationId), qty: q.n ?? 1 });
      }
      return { problem: null, version: { kind: "combo", label: clip(`Combo ${lines.length} sản phẩm`), items: lines, pricing: c.pricing, value, target: c.target } };
    }
    case "add_on": {
      const rows = f.add_on.addons.filter((a) => a.itemId);
      if (rows.length === 0) return no("Chọn ít nhất một sản phẩm mua kèm.");
      const addons: Record<string, unknown>[] = [];
      for (const a of rows) {
        const n = num(a.value);
        if (n === null || n <= 0) return no("Nhập giá mua kèm hoặc % giảm.");
        if (a.mode === "pct" && n > MAX_PCT) return no(PCT_PROBLEM);
        const limit = intIn(a.limit.trim() === "" ? "1" : a.limit, 1, 20, "Giới hạn mỗi đơn từ 1 đến 20.");
        if (limit.problem) return no(limit.problem);
        addons.push({ item_id: a.itemId, ...vid(a.variationId), [a.mode === "price" ? "price" : "pct"]: n, limit_per_order: limit.n ?? 1 });
      }
      return { problem: null, version: { kind: "add_on", label: clip(`Mua kèm ${addons.length} sản phẩm`), main_item_id: id, addons } };
    }
    case "gift": {
      const g = f.gift;
      const q = intIn(g.qty.trim() === "" ? "1" : g.qty, 1, 20, "Số lượng quà từ 1 đến 20.");
      if (q.problem) return no(q.problem);
      const qty = q.n ?? 1;
      let gift: Record<string, unknown>;
      if (g.source === "listing") {
        if (!g.giftItemId) return no("Chọn sản phẩm làm quà.");
        gift = { item_id: g.giftItemId, qty, ...opt("packaging", g.packaging) };
      } else {
        const cost = num(g.unitCost);
        if (cost === null || cost < 0) return no("Nhập chi phí mỗi quà.");
        if (!g.label.trim()) return no("Nhập tên quà.");
        gift = { unit_cost: cost, qty, label: clip(g.label.trim()), ...opt("packaging", g.packaging) };
      }
      let trigger: Record<string, unknown>;
      if (g.trigger === "buy_item") trigger = { type: "buy_item", item_id: g.triggerItemId || id };
      else {
        const amount = num(g.minSpend);
        if (amount === null || amount < 0) return no("Nhập đơn tối thiểu để nhận quà.");
        trigger = { type: "min_spend", amount };
      }
      return { problem: null, version: { kind: "gift", label: clip(g.trigger === "min_spend" ? `Quà đơn ≥ ${kmoney(num(g.minSpend) ?? 0)}` : "Quà khi mua sản phẩm"), gift, trigger } };
    }
    case "product_discount": {
      const d = f.product_discount;
      const { rows, problem } = varRows(d.rows, d.mode, "discount_pct");
      if (problem) return no(problem);
      const perBuyer = intIn(d.perBuyer, 1, 100, "Giới hạn mỗi người từ 1 đến 100 lượt.");
      const more = perBuyer.problem ?? dateProblem(d.start, d.end, null);
      if (more) return no(more);
      return {
        problem: null,
        version: { kind: "product_discount", label: clip(d.mode === "pct" ? `Giảm ${d.rows.map((r) => num(r.value)).find((n) => n) ?? ""}%` : "Giảm về giá mới"), item_id: id, variations: rows, ...dated(d.start, d.end), ...(perBuyer.n !== null ? { per_buyer_limit: perBuyer.n } : {}) },
      };
    }
    case "price_flash": {
      const p = f.price_flash;
      if (p.what === "price") {
        const out: Record<string, unknown>[] = [];
        for (const r of p.rows) {
          const n = num(r.value);
          if (n === null) continue;
          if (p.mode === "pct" && (n < -50 || n > 100)) return no("Đổi giá trong khoảng −50% đến +100%.");
          if (p.mode === "final_price" && n <= 0) return no("Nhập giá bán lớn hơn 0.");
          const current = ctx.variations.find((x) => x.variation_id === r.variationId)?.selling_price ?? null;
          if ((p.mode === "pct" && n === 0) || (p.mode === "final_price" && current !== null && n === current)) return no("Giá không đổi.");
          out.push({ ...vid(r.variationId), [p.mode === "pct" ? "change_pct" : "final_price"]: n });
        }
        if (out.length === 0) return no("Nhập giá mới cho ít nhất một phân loại.");
        return { problem: null, version: { kind: "price", label: "Đổi giá niêm yết", item_id: id, variations: out } };
      }
      const { rows, problem } = varRows(p.rows, p.mode, "discount_pct");
      if (problem) return no(problem);
      const units = num(p.units);
      if (units === null || units <= 0) return no("Nhập số lượng suất flash sale.");
      if (!Number.isInteger(units)) return no("Số lượng suất là số nguyên.");
      const hours = intIn(p.slotHours.trim() === "" ? "2" : p.slotHours, 1, 72, "Số giờ của khung từ 1 đến 72.");
      if (hours.problem) return no(hours.problem);
      return { problem: null, version: { kind: "flash_sale", label: "Flash sale", item_id: id, variations: rows, units, ...(p.slotStart ? { slot_start: p.slotStart } : {}), slot_hours: hours.n ?? 2 } };
    }
    case "variation_set": {
      const out: Record<string, unknown>[] = [];
      for (const r of f.variation_set.rows) {
        if (!r.name.trim() && !r.price.trim()) continue;
        const price = num(r.price);
        if (!r.name.trim() || price === null || price <= 0) return no("Mỗi phân loại mới cần tên và giá.");
        const pack = intIn(r.packCount, 1, 100, "Số lượng trong gói từ 1 đến 100.");
        if (pack.problem) return no(pack.problem);
        out.push({ name: r.name.trim(), price, ...(r.sku.trim() ? { sku: r.sku.trim() } : {}), ...(pack.n !== null ? { pack_count: pack.n } : {}), ...opt("stock", r.stock) });
      }
      if (out.length === 0) return no("Thêm ít nhất một phân loại mới.");
      return { problem: null, version: { kind: "variation_set", label: clip(`Thêm ${out.map((o) => String(o["name"])).join(", ")}`), item_id: id, new_variations: out } };
    }
    case "ads": {
      const a = f.ads;
      if (a.lever === "keywords") {
        const kws = a.keywords.filter((k) => k.keyword.trim());
        if (kws.length === 0) return no("Nhập ít nhất một từ khoá.");
        const out = [];
        for (const k of kws) {
          const bid = num(k.bid);
          if (bid === null || bid <= 0) return no("Nhập giá thầu cho từng từ khoá.");
          out.push({ keyword: k.keyword.trim(), bid, match: k.match });
        }
        return { problem: null, version: { kind: "ads", label: "Từ khoá và giá thầu", lever: "keywords", keywords: out } };
      }
      if (!a.campaignKey) return no("Chọn chiến dịch.");
      if (a.lever === "budget") {
        const n = num(a.dailyBudget);
        if (n === null || n <= 0) return no("Nhập ngân sách mỗi ngày.");
        return { problem: null, version: { kind: "ads", label: clip(`Ngân sách ${kmoney(n)}/ngày`), lever: "budget", campaign_key: a.campaignKey, daily_budget: n } };
      }
      if (a.lever === "roas") {
        const n = num(a.roasTarget);
        if (n === null || n <= 0) return no("Nhập ROAS mục tiêu.");
        return { problem: null, version: { kind: "ads", label: clip(`ROAS mục tiêu ${fmt(n, 1)}`), lever: "roas", campaign_key: a.campaignKey, roas_target: n } };
      }
      const item = a.itemId || id;
      return { problem: null, version: { kind: "ads", label: a.lever === "add_product" ? "Thêm sản phẩm vào chiến dịch" : "Gỡ sản phẩm khỏi chiến dịch", lever: a.lever, campaign_key: a.campaignKey, item_id: item } };
    }
    case "title": {
      const t = f.title.text.trim();
      if (!t) return no("Nhập hoặc chọn một tiêu đề.");
      if ([...t].length > MAX_TITLE) return no(`Tiêu đề tối đa ${MAX_TITLE} ký tự.`);
      return { problem: null, version: { kind: "title", label: "Tiêu đề mới", item_id: id, title: t, keywords: [...f.title.ticked] } };
    }
    case "cover_image": {
      const o = f.cover_image.overlay;
      if (!o) return no("Chọn một lớp chữ cho ảnh bìa.");
      return { problem: null, version: { kind: "cover_image", label: clip(o.badge_text || o.hook_text || o.pack_text || "Ảnh bìa"), item_id: id, overlay: o } };
    }
    case "description_first_line": {
      const t = f.description_first_line.text.trim();
      if (!t) return no("Nhập hoặc chọn dòng đầu của mô tả.");
      if (/[\r\n]/.test(t)) return no("Dòng đầu không xuống dòng.");
      if ([...t].length > MAX_FIRST_LINE) return no(`Dòng đầu tối đa ${MAX_FIRST_LINE} ký tự.`);
      return { problem: null, version: { kind: "description_first_line", label: "Dòng đầu mô tả", item_id: id, first_line: t } };
    }
    case "affiliate": {
      const a = f.affiliate;
      const pct = num(a.commission);
      if (pct === null || pct < 0 || pct > 50) return no("Hoa hồng từ 0% đến 50%.");
      const samples = Math.round(num(a.samples) ?? 0);
      if (samples < 0 || samples > 50) return no("Số mẫu gửi từ 0 đến 50.");
      return { problem: null, version: { kind: "affiliate", label: clip(`Hoa hồng ${fmt(pct, 1)}%`), item_id: id, commission_pct: pct, target_campaign: a.campaign === "1", sample_qty: samples, ...opt("sample_ship_fee", a.shipFee) } };
    }
    case "price_display": {
      const p = f.price_display;
      if (p.what === "listing_hide") return { problem: null, version: { kind: "listing_hide", label: "Ẩn listing", item_id: id } };
      if (p.what === "listing_relist" && ctx.product.stock !== null && ctx.product.stock > 0) return no(REFUSAL_TEXT.listing_already_live);
      if (p.what === "listing_relist") return { problem: null, version: { kind: "listing_relist", label: "Đưa lại listing", item_id: id, ...opt("stock", p.stock) } };
      const v = ctx.variations[0];
      return { problem: null, version: { kind: "price_display", label: "Hiển thị giá mỗi đơn vị", item_id: id, ...(v && ctx.variations.length === 1 ? { variation_id: v.variation_id } : {}), ...(p.text.trim() ? { text: p.text.trim() } : {}) } };
    }
  }
}

// ── reading an outcome ───────────────────────────────────────────────────

/** Refusal codes the server sends, in Vietnamese (the server's own `message` wins when it has one). */
export const REFUSAL_TEXT: Readonly<Record<string, string>> = {
  sku_no_orders: "Phân loại này chưa có đơn trong kỳ (có thể hết hàng) — chọn phân loại khác.",
  sku_unknown: "Phân loại này không thuộc sản phẩm đã chọn.",
  voucher_scope_no_data: "Chưa có dữ liệu đơn theo loại voucher này để ước tính.",
  voucher_value_over_min_spend: "Giá trị voucher phải nhỏ hơn đơn tối thiểu.",
  sku_duplicate: "SKU trùng với một phân loại đang có.",
  listing_already_live: "Listing đang bán — chỉ đưa lại listing đã ẩn hoặc hết hàng.",
  no_campaign_report: "Chưa có báo cáo của chiến dịch này để tính.",
  combo_price_too_low: "Giá combo quá thấp (dưới 1.000đ) — bạn muốn nhập % giảm?",
  combo_discount_over_max: "Combo giảm tối đa 90% tổng giá bán hiện tại.",
};

/** P96e: the smallest fixed combo price the builder accepts (mirrors combo.MIN_FIXED_PRICE). */
export const MIN_COMBO_PRICE = 1000;

/** The combo price from a result's details; Ops masks `buyer_*` keys as "•••", so `combo_price` first. */
export function comboPriceOf(d: Readonly<Record<string, unknown>>): number | null {
  for (const k of ["combo_price", "buyer_pays"]) {
    const v = d[k];
    if (typeof v === "number" && Number.isFinite(v)) return v;
  }
  return null;
}

/** "31,6%" / "−12,5%"; below −100 % the item sells under cost and a percent means nothing (P96e). */
export function marginText(pct: number | null | undefined): string {
  if (pct === null || pct === undefined || !Number.isFinite(pct)) return DASH;
  return pct < -100 ? "lỗ (bán dưới giá vốn)" : pp(pct, 1);
}

/** A code -> its sentence; a code with a suffix (`sku_unknown:G600013`) reads by its stem; never the code itself. */
export function codeText(code: string | null | undefined, map: Readonly<Record<string, string>>, fallback: string): string {
  if (!code) return fallback;
  if (map[code]) return map[code];
  const stem = code.split(":")[0] ?? code;
  return map[stem] ?? fallback;
}

const looksLikeCode = (s: string): boolean => /^[a-z0-9_]+(:[\w-]+)?$/.test(s.trim());

export const refusalText = (o: Pick<BuilderOutcome, "refusal">): string => {
  const r = o.refusal;
  const fallback = "Chưa tính được phương án này.";
  if (!r) return fallback;
  if (typeof r === "string") return looksLikeCode(r) ? codeText(r, REFUSAL_TEXT, fallback) : r;
  if (r.message && !looksLikeCode(r.message)) return r.message;
  return codeText(r.code ?? r.message, REFUSAL_TEXT, fallback);
};

/** Break-even / CTOR reason codes (`outcome.py`, `traffic.py`) in Vietnamese. */
export const REASON_TEXT: Readonly<Record<string, string>> = {
  not_applicable: "Không có chi phí trực tiếp; đo sau khi chạy.",
  no_clicks: "chưa có lượt nhấp để tính CTOR",
  no_flow_data: "chưa có số liệu luồng để tính CTOR",
  no_cost: "chưa có chi phí để tính mức hoà vốn",
  no_profit: "chưa tính được lợi nhuận để tính mức hoà vốn",
};

function reasonOf(text: string | null | undefined, code: string | null | undefined, fallback: string): string {
  if (text) return text;
  if (code && !looksLikeCode(code)) return code;
  return codeText(code, REASON_TEXT, fallback);
}

export function bandText(b: Band | null | undefined, unit: "vnd" | "orders" = "vnd"): { readonly main: string; readonly range: string } {
  if (!b || b.p50 === null) return { main: DASH, range: "không đủ dữ liệu" };
  if (unit === "orders") {
    const o = (n: number | null) => (n === null ? DASH : `${n >= 0 ? "+" : "−"}${fmt(Math.abs(Math.round(n)))}`);
    return { main: `${o(b.p50)} đơn`, range: `${o(b.low)} – ${o(b.high)}` };
  }
  return { main: sv(b.p50), range: `${sv(b.low)} – ${sv(b.high)}` };
}

export function metricValue(unit: string, n: number | null): string {
  if (n === null) return DASH;
  if (unit === "vnd") return vnd(n);
  if (unit === "pct") return pp(n, 2);
  if (unit === "ratio") return fmt(n, 1);
  return fmt(Math.round(n));
}

export function breakEvenText(o: BuilderOutcome): string {
  const b = o.break_even;
  if (!b) return DASH;
  if (!b.applies) return reasonOf(b.reason_text, b.reason, "Không có chi phí trực tiếp; đo sau khi chạy.");
  // P96d: a voucher pays back through a bigger basket on the orders that use it, not extra orders
  if (b.basis === "aov") {
    if (b.aov_needed == null) return reasonOf(b.reason_text, b.reason, "Chưa đủ dữ liệu để tính mức hoà vốn.");
    return `cần AOV đơn dùng voucher ≥ ${vnd(b.aov_needed)} (hôm nay ${vnd(b.aov_now ?? null)}), để lợi nhuận không giảm.`;
  }
  if (b.extra_orders === null) return reasonOf(b.reason_text, b.reason, "Chưa đủ dữ liệu để tính mức hoà vốn.");
  const ctorWhy = b.ctor_reason || b.ctor_reason_text ? reasonOf(b.ctor_reason_text, b.ctor_reason, "chưa tính được CTOR cần có") : "";
  const ctor = b.ctor_needed != null ? `, tức CTOR ≥ ${pp(b.ctor_needed, 2)} (hôm nay ${pp(b.ctor_now ?? null, 2)})` : (ctorWhy ? `; ${ctorWhy}` : "");
  return `cần thêm ≥ ${fmt(Math.ceil(b.extra_orders))} đơn${ctor}, để lợi nhuận không giảm.`;
}

export const hasWarning = (o: Pick<BuilderOutcome, "warnings">, type: string): boolean => (o.warnings ?? []).some((w) => w.type === type);

export function floorWarningText(w: BuilderWarning): string {
  if (typeof w.message === "string" && w.message) return w.message;
  if (w.type === "floor") {
    const floor = typeof w.floor === "number" ? w.floor : null;
    const paid = typeof w.min_unit_price === "number" ? w.min_unit_price : null;
    return `${w.sku ?? "SKU"}: khách trả ${vnd(paid)} thấp hơn giá sàn ${vnd(floor)}${floor !== null && paid !== null ? ` (thiếu ${vnd(floor - paid)})` : ""}.`;
  }
  if (w.type === "spend_cap") return "Chi quảng cáo mỗi ngày vượt trần chi của Cài đặt › Mục tiêu.";
  if (w.type === "cost_unknown") return "Có sản phẩm chưa có giá vốn trong Thông số shop: lợi nhuận và biên chưa tính.";
  if (w.type === "floor_unknown") return "Chưa có giá vốn để tính giá sàn.";
  if (w.type === "profit_unknown") return "Chưa tính được lợi nhuận của phương án này.";
  if (w.type === "refused") return "Phương án này chưa tính được.";
  return "Xem chi tiết ở phương án.";
}

/** The breaches of one outcome, in the shape the warning dialog (and `choose`) uses. */
export function breachesOfOutcome(o: BuilderOutcome): readonly BuilderWarning[] {
  return (o.warnings ?? []).filter((w) => w.type === "floor" || w.type === "spend_cap");
}

export const BASIS_LABELS: readonly string[] = ["từ lịch sử sản phẩm", "của shop", "ước tính chung", "không đủ dữ liệu"];


/** "Dự kiến dùng 6 / 20 lượt · chưa chạm giới hạn" of a voucher outcome (null for other kinds). */
export function voucherUsageText(o: BuilderOutcome): string | null {
  const u = o.voucher?.usage;
  if (!u) return null;
  const used = u.used === null ? DASH : fmt(u.used, Number.isInteger(u.used) || u.used >= 10 ? 0 : 1);
  const limit = u.limit === null ? "không giới hạn" : fmt(u.limit, 0);
  const state = u.limit === null ? "" : u.capped ? " · chạm giới hạn" : " · chưa chạm giới hạn";
  return `Dự kiến dùng ${used} / ${limit} lượt${state}`;
}

/** The max-discount line: whether the cap binds and how often (percent vouchers only). */
export function voucherMaxText(o: BuilderOutcome): string | null {
  const m = o.voucher?.max_discount;
  if (!m || !m.applies) return null;
  if (!m.pct_voucher) return "Mức giảm tối đa chỉ có tác dụng với voucher %";
  return m.binding_orders > 0 ? `Mức giảm tối đa chạm ở ${fmt(m.binding_orders, 0)}/${fmt(m.qualifying_orders, 0)} đơn đủ điều kiện` : "Mức giảm tối đa chưa đơn nào chạm";
}

/** Per day / per order / period lines of an outcome, in the units the seller reads. */
export function unitLines(o: BuilderOutcome): readonly string[] {
  const d = o.delta;
  if (!d) return [];
  // No estimate ("không đủ dữ liệu"): no "+0đ lợi nhuận" lines that read like a forecast.
  if (o.basis?.key === "insufficient" || !d.profit || d.profit.p50 === null) return [];
  const out: string[] = [];
  const pd = d.per_day?.profit;
  if (pd && pd.p50 !== null) out.push(`Mỗi ngày: ${sv(pd.p50)} lợi nhuận (${sv(pd.low)} – ${sv(pd.high)})`);
  const po = d.per_order;
  if (po?.profit && po.profit.p50 !== null) out.push(`Mỗi ${po.basis === "voucher_use" ? "đơn dùng voucher" : "đơn"}: ${sv(po.profit.p50)} lợi nhuận${po.cost !== null && po.cost !== 0 ? `, chi phí ${vnd(po.cost)}` : ""}`);
  const pp_ = d.period?.profit;
  if (pp_ && pp_.p50 !== null) out.push(`Trong ${fmt(d.period?.days ?? d.days ?? 0, 0)} ngày: ${sv(pp_.p50)} (${sv(pp_.low)} – ${sv(pp_.high)})`);
  return out;
}

// ── telling versions apart (P96d) ────────────────────────────────────────

/** Names the compare table shows for the ids a version carries. */
export interface VersionNames {
  readonly products?: Readonly<Record<string, string>>;
  readonly variations?: Readonly<Record<string, string>>;
  readonly campaigns?: Readonly<Record<string, string>>;
}

/** One input of a version, under the label its panel uses; `key` lines up the same input across versions. */
export interface VersionFact {
  readonly key: string;
  readonly label: string;
  readonly value: string;
}

const VOUCHER_TYPES: Readonly<Record<string, string>> = {
  shop: "Voucher shop",
  product: "Voucher sản phẩm",
  follower: "Voucher người theo dõi / khách mới",
  livestream: "Voucher livestream / video",
};

const ADS_LEVERS: Readonly<Record<string, string>> = {
  budget: "Ngân sách mỗi ngày",
  roas: "ROAS mục tiêu",
  add_product: "Thêm sản phẩm",
  remove_product: "Bỏ sản phẩm",
  keywords: "Từ khoá và giá thầu",
};

const COMBO_PRICING: Readonly<Record<string, string>> = { fixed_price: "Giá combo", pct: "% giảm trên tổng", amount: "đ giảm trên tổng" };

const n_ = (x: unknown): number | null => (typeof x === "number" && Number.isFinite(x) ? x : null);
const s_ = (x: unknown): string => (typeof x === "string" ? x : "");
const pctText = (x: number): string => `${fmt(x, Number.isInteger(x) ? 0 : 1)}%`;
const signedPct = (x: number): string => `${x > 0 ? "+" : ""}${pctText(x)}`;
const dayText = (iso: string): string => (/^\d{4}-\d{2}-\d{2}/.test(iso) ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}` : iso);

/** The type a compare column names (voucher kind, ads lever, gift source…) and the inputs that make it. */
export function versionFacts(v: BuilderVersion, names: VersionNames = {}): { readonly type: string; readonly facts: readonly VersionFact[] } {
  const product = (id: unknown): string => names.products?.[s_(id)] ?? s_(id);
  const variation = (id: unknown): string => names.variations?.[s_(id)] ?? (s_(id) || "phân loại chính");
  const facts: VersionFact[] = [];
  const add = (key: string, label: string, value: string | null) => {
    if (value !== null && value !== "") facts.push({ key, label, value });
  };
  const dates = () => {
    const start = s_(v["start"]);
    const end = s_(v["end"]);
    if (start || end) add("dates", "Thời gian", `${start ? dayText(start) : "…"}–${end ? dayText(end) : "…"}`);
  };
  const kind = String(v.kind);
  switch (kind) {
    case "voucher": {
      const value = n_(v["value"]);
      add("value", "Giảm", value === null ? null : v["discount_type"] === "pct" ? pctText(value) : vnd(value));
      add("min", "Đơn tối thiểu", vnd(n_(v["min_spend"]) ?? 0));
      const max = n_(v["max_value"]);
      if (max !== null) add("max", "Giảm tối đa", vnd(max));
      const usage = n_(v["usage_limit"]);
      if (usage !== null) add("usage", "Lượt dùng tối đa", fmt(usage));
      const perBuyer = n_(v["per_buyer_limit"]);
      if (perBuyer !== null) add("per_buyer", "Giới hạn mỗi người", fmt(perBuyer));
      dates();
      const items = Array.isArray(v["item_ids"]) ? (v["item_ids"] as unknown[]) : [];
      if (items.length > 0) add("product", "Sản phẩm", items.map(product).join(", "));
      return { type: VOUCHER_TYPES[s_(v["scope"])] ?? "Voucher", facts };
    }
    case "combo": {
      const items = Array.isArray(v["items"]) ? (v["items"] as Record<string, unknown>[]) : [];
      add("items", "Sản phẩm", items.map((i) => `${product(i["item_id"])} × ${fmt(n_(i["qty"]) ?? 1)}`).join(" + "));
      const value = n_(v["value"]);
      const pricing = s_(v["pricing"]);
      add("value", COMBO_PRICING[pricing] ?? "Mức giảm", value === null ? null : pricing === "pct" ? pctText(value) : vnd(value));
      return { type: v["target"] === "new_listing" ? "Combo · Listing combo mới" : "Combo", facts };
    }
    case "add_on": {
      add("main", "Sản phẩm chính", product(v["main_item_id"]));
      for (const a of Array.isArray(v["addons"]) ? (v["addons"] as Record<string, unknown>[]) : []) {
        const price = n_(a["price"]);
        const pct = n_(a["pct"]);
        add(`a:${s_(a["item_id"])}`, `Mua kèm · ${product(a["item_id"])}`, `${price !== null ? vnd(price) : pct !== null ? `−${pctText(pct)}` : DASH} · tối đa ${fmt(n_(a["limit_per_order"]) ?? 1)}/đơn`);
      }
      return { type: "Mua kèm", facts };
    }
    case "gift": {
      const g = (v["gift"] ?? {}) as Record<string, unknown>;
      const t = (v["trigger"] ?? {}) as Record<string, unknown>;
      const listing = g["item_id"] !== undefined;
      add("gift", "Quà", `${listing ? product(g["item_id"]) : s_(g["label"]) || "Quà"} × ${fmt(n_(g["qty"]) ?? 1)}`);
      if (!listing) add("unit_cost", "Chi phí mỗi quà", vnd(n_(g["unit_cost"])));
      const pack = n_(g["packaging"]);
      if (pack !== null) add("packaging", "Đóng gói mỗi quà", vnd(pack));
      if (t["type"] === "min_spend") add("trigger", "Đơn tối thiểu", vnd(n_(t["amount"]) ?? 0));
      else add("trigger", "Mua sản phẩm", product(t["item_id"]));
      return { type: listing ? "Quà tặng · Sản phẩm trong danh sách" : "Quà tặng · Quà không bán", facts };
    }
    case "product_discount":
    case "price":
    case "flash_sale": {
      for (const r of Array.isArray(v["variations"]) ? (v["variations"] as Record<string, unknown>[]) : []) {
        const key = `v:${s_(r["variation_id"])}`;
        const name = variation(r["variation_id"]);
        const final = n_(r["final_price"]);
        const change = n_(r["change_pct"]);
        const off = n_(r["discount_pct"]);
        if (change !== null) add(key, `Thay đổi · ${name}`, signedPct(change));
        else if (final !== null) add(key, `${kind === "flash_sale" ? "Giá flash sale" : kind === "price" ? "Giá mới" : "Giá cuối"} · ${name}`, vnd(final));
        else if (off !== null) add(key, `Giảm · ${name}`, pctText(off));
      }
      if (kind === "flash_sale") {
        add("units", "Số lượng (suất)", fmt(n_(v["units"])));
        add("hours", "Số giờ của khung", fmt(n_(v["slot_hours"])));
        if (s_(v["slot_start"])) add("slot", "Khung giờ bắt đầu", s_(v["slot_start"]).replace("T", " "));
      }
      if (kind === "product_discount") {
        const perBuyer = n_(v["per_buyer_limit"]);
        if (perBuyer !== null) add("per_buyer", "Giới hạn mỗi người", fmt(perBuyer));
        dates();
      }
      return { type: SERVER_KIND_NAMES[kind] ?? kind, facts };
    }
    case "variation_set": {
      for (const r of Array.isArray(v["new_variations"]) ? (v["new_variations"] as Record<string, unknown>[]) : []) {
        const pack = n_(r["pack_count"]);
        add(`n:${s_(r["name"])}`, s_(r["name"]), `${vnd(n_(r["price"]))}${pack !== null ? ` · ${fmt(pack)} cái` : ""}`);
      }
      return { type: "Phân loại / set", facts };
    }
    case "ads": {
      const lever = s_(v["lever"]);
      const key = s_(v["campaign_key"]);
      if (key) add("campaign", "Chiến dịch", names.campaigns?.[key] ?? (key === "daily" ? "Tổng chi quảng cáo (theo ngày)" : key));
      const budget = n_(v["daily_budget"]);
      if (budget !== null) add("budget", "Ngân sách mới mỗi ngày", vnd(budget));
      const roas = n_(v["roas_target"]);
      if (roas !== null) add("roas", "ROAS mục tiêu mới", fmt(roas, 1));
      if (v["item_id"] !== undefined) add("item", "Sản phẩm", product(v["item_id"]));
      for (const k of Array.isArray(v["keywords"]) ? (v["keywords"] as Record<string, unknown>[]) : []) add(`k:${s_(k["keyword"])}`, s_(k["keyword"]), vnd(n_(k["bid"])));
      return { type: `Quảng cáo · ${ADS_LEVERS[lever] ?? lever}`, facts };
    }
    case "title":
      add("text", "Tiêu đề", s_(v["title"]));
      return { type: "Tiêu đề", facts };
    case "description_first_line":
      add("text", "Dòng đầu mô tả", s_(v["first_line"]));
      return { type: "Mô tả", facts };
    case "cover_image": {
      const o = (v["overlay"] ?? {}) as Record<string, unknown>;
      add("text", "Lớp chữ", [o["hook_text"], o["badge_text"], o["pack_text"]].map(s_).filter(Boolean).join(" · "));
      return { type: "Ảnh bìa", facts };
    }
    case "affiliate": {
      const pct = n_(v["commission_pct"]);
      add("commission", "Hoa hồng mới", pct === null ? null : pctText(pct));
      add("samples", "Số mẫu gửi", fmt(n_(v["sample_qty"]) ?? 0));
      const fee = n_(v["sample_ship_fee"]);
      if (fee !== null) add("ship", "Phí ship mỗi mẫu", vnd(fee));
      if (v["target_campaign"] === true) add("target", "Chiến dịch mục tiêu", "có");
      return { type: "Affiliate / KOL", facts };
    }
    case "price_display":
      add("text", "Dòng hiển thị", s_(v["text"]) || "giá mỗi đơn vị");
      return { type: "Hiển thị giá", facts };
    case "listing_relist": {
      const stock = n_(v["stock"]);
      if (stock !== null) add("stock", "Tồn", fmt(stock));
      return { type: "Đưa lại listing", facts };
    }
    default:
      return { type: SERVER_KIND_NAMES[kind] ?? kind, facts };
  }
}

/** "Cả shop · AOV 160.152đ · biên 41,7%": the orders a column's "hôm nay" figures stand on. */
export function baseText(o: BuilderOutcome, names: VersionNames = {}): string | null {
  const b = o.base;
  if (!b) return null;
  const scope = b.scope === "shop" || b.items.length === 0 ? "Cả shop" : b.items.map((i) => names.products?.[i] ?? i).join(", ");
  const parts = [scope];
  if (b.aov !== null) parts.push(`AOV ${vnd(b.aov)}`);
  if (b.margin_pct !== null) parts.push(`biên ${pp(b.margin_pct, 1)}`);
  return parts.join(" · ");
}

/** The best version's chip: it can still lose money, then it is the smallest loss. */
export function bestBadge(o: BuilderOutcome): string {
  const p = o.delta?.profit?.p50 ?? null;
  return p !== null && p < 0 ? "lỗ ít nhất" : "lợi nhuận tốt nhất";
}
