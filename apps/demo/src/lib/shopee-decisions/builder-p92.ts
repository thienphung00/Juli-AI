import { DASH, fmt, pp, sv, vnCount, vnd } from "../shopee-analytics/format";
import type { Band, BeforeAfterRow, BuilderOutcome, BuilderVersion, BuilderWarning, CoverOverlay, PickerProduct, VariationRow } from "./builder-api";

/**
 * Tự tạo phương án (P92): the form state of each strategy, and how it becomes a version of
 * `POST /builder/evaluate | compare | choose` (`fasttrack/contracts/p92-api.md` §3).
 * Numbers are kept as the raw text of their input and parsed here, so the cursor never jumps.
 */

export type Kind92 =
  | "voucher"
  | "combo"
  | "listing_combo"
  | "deal_soc"
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
/** Shopee's product-ads edit form (P97 D85.17): the lowest daily budget, the ROAS hint and the presets. */
export const ADS_MIN_BUDGET = 100_000;
export const ADS_BUDGET_MIN_TEXT = "Ngân sách tối thiểu: ₫100.000";
export const ADS_ROAS_HINT = 3.5;
export const ADS_ROAS_PRESETS: readonly number[] = [2.5, 3.5, 4.5];
export const MAX_TARGETS = 100;
export const MAX_COMBO_NAME = 25;
export const MAX_COMBO_TIERS = 5;
export const MAX_COMBO_MEMBERS = 20;
export const MAX_LISTING_IMAGES = 9;
export const MAX_CAMPAIGNS = 30;
/** Shopee's programme forms (P100 wave 2, brief C), mirrored by `specs.py`. */
export const MAX_PROGRAMME_NAME = 150;
export const MAX_DISCOUNT_DAYS = 180;
export const MAX_ADDONS = 5;
export const MAX_ADDON_LIMIT = 100;
/** "Mua ₫[X] để nhận [N] quà tặng": N is below 50. */
export const MAX_GIFT_QTY = 49;

/** The 13 strategies, each with the driver metric(s) it is measured by (B-3, artboard `kinds`). */
export const KINDS_92: readonly { readonly key: Kind92; readonly name: string; readonly drivers: string }[] = [
  { key: "voucher", name: "Voucher", drivers: "AOV · CTOR" },
  { key: "combo", name: "Combo khuyến mãi", drivers: "AOV · CTOR" },
  { key: "listing_combo", name: "Listing combo mới", drivers: "đơn · bán chéo" },
  { key: "deal_soc", name: "Deal Sốc", drivers: "AOV · CTOR · đơn" },
  { key: "product_discount", name: "Chương Trình Của Shop", drivers: "CTOR · đơn" },
  { key: "price_flash", name: "Giá bán + Flash sale", drivers: "CTOR · đơn" },
  { key: "variation_set", name: "Phân loại / set", drivers: "AOV · CTOR" },
  { key: "ads", name: "Dịch vụ hiển thị", drivers: "chi · GMV · ROAS" },
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
  combo: "Combo khuyến mãi",
  listing_combo: "Listing combo mới",
  add_on: "Deal Sốc · Mua Kèm Deal Sốc",
  gift: "Deal Sốc · Mua Để Nhận Quà",
  product_discount: "Chương Trình Của Shop",
  price: "Giá bán",
  flash_sale: "Flash sale",
  variation_set: "Phân loại / set",
  ads: "Dịch vụ hiển thị",
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

/** One row "Mua [N] sản phẩm → [giá trị]" of Shopee's Combo Khuyến Mãi form. */
export interface ComboTierRow {
  readonly qty: string;
  readonly value: string;
}
export interface AddonRow {
  readonly itemId: string;
  readonly variationId: string;
  readonly mode: "price" | "pct";
  readonly value: string;
  readonly limit: string;
}
/** The two Loại Deal Sốc of Shopee's one form; the server keeps them as the kinds `add_on` / `gift`. */
export type DealSocType = "add_on" | "gift";
export const DEAL_SOC_TYPES: readonly (readonly [DealSocType, string])[] = [
  ["add_on", "Mua Kèm Deal Sốc"],
  ["gift", "Mua Để Nhận Quà"],
];
/** Mua Để Nhận Quà: the gift products, the cost of a gift Shopee does not sell, "Mua ₫[X] để nhận [N] quà tặng". */
export interface GiftForm {
  readonly source: "listing" | "unsold";
  readonly giftItemId: string;
  readonly unitCost: string;
  readonly label: string;
  readonly packaging: string;
  readonly qty: string;
  readonly minSpend: string;
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
export interface Forms {
  /** `items`: the products of a product voucher besides the chosen one (P97 D85.13, the picker's selection). */
  readonly voucher: { scope: "shop" | "product" | "follower" | "livestream"; dtype: "amount" | "pct"; value: string; min: string; max: string; usage: string; perBuyer: string; start: string; end: string; items: readonly string[] };
  /** Combo Khuyến Mãi in Shopee's shape (P97 D85.15): a product list, a type, tiers, the order limit, name ≤ 25, dates. */
  readonly combo: { name: string; items: readonly string[]; dtype: "pct" | "amount" | "special_price"; tiers: readonly ComboTierRow[]; limit: string; start: string; end: string; startHour?: string; endHour?: string };
  /** A new listing that sells several existing products together (P97 D85.16). */
  readonly listing_combo: { title: string; images: readonly string[]; price: string; stock: string; sku: string; members: readonly string[] };
  /** Deal Sốc (P100 wave 2): one form, `type` = Loại Deal Sốc; Tên chương trình and Thời gian bắt đầu / kết thúc are shared. */
  readonly deal_soc: { type: DealSocType; name: string; start: string; end: string; startHour: string; endHour: string; addonLimit: string; addons: readonly AddonRow[]; gift: GiftForm };
  /** `multi`: one % for every product in `targets` (Shopee's bulk discount, P97 D85.13). */
  /** Chương Trình Của Shop: Tên chương trình khuyến mãi, Thời gian khuyến mãi (hours), Số lượng sản phẩm khuyến mãi (empty = Không giới hạn), Giới hạn đặt hàng. */
  readonly product_discount: { mode: "pct" | "final_price"; rows: readonly VarValue[]; name: string; start: string; end: string; startHour: string; endHour: string; promoQty: string; perBuyer: string; multi: boolean; targets: readonly string[]; pct: string };
  readonly price_flash: { what: "price" | "flash_sale"; mode: "pct" | "final_price"; rows: readonly VarValue[]; units: string; slotStart: string; slotHours: string };
  readonly variation_set: { rows: readonly NewVariation[] };
  /** Shopee's edit form (P97 D85.17): budget (≥ ₫100.000 or unlimited), ROAS (system / custom), products, dates; `campaignKeys` = many campaigns. */
  readonly ads: { lever: "budget" | "roas" | "add_product" | "remove_product"; campaignKey: string; campaignKeys: readonly string[]; dailyBudget: string; unlimited: boolean; roasMode: "system" | "custom"; roasTarget: string; itemId: string; start: string; end: string };
  readonly title: { ticked: readonly string[]; text: string };
  readonly cover_image: { overlay: CoverOverlay | null };
  readonly description_first_line: { text: string };
  readonly affiliate: { commission: string; campaign: string; samples: string; shipFee: string; multi: boolean; targets: readonly string[] };
  readonly price_display: { what: "price_display" | "listing_hide" | "listing_relist"; text: string; stock: string };
}

export const newTier = (qty = "2", value = ""): ComboTierRow => ({ qty, value });

export function initialForms(): Forms {
  return {
    voucher: { scope: "product", dtype: "amount", value: "5000", min: "100000", max: "", usage: "", perBuyer: "", start: "", end: "", items: [] },
    combo: { name: "", items: [], dtype: "pct", tiers: [newTier("2", "5"), newTier("3", "8")], limit: "", start: "", end: "" },
    listing_combo: { title: "", images: [], price: "", stock: "", sku: "", members: [] },
    deal_soc: {
      type: "add_on",
      name: "",
      start: "",
      end: "",
      startHour: "",
      endHour: "",
      addonLimit: "",
      addons: [{ itemId: "", variationId: "", mode: "pct", value: "15", limit: "1" }],
      gift: { source: "listing", giftItemId: "", unitCost: "", label: "", packaging: "", qty: "1", minSpend: "150000" },
    },
    product_discount: { mode: "pct", rows: [], name: "", start: "", end: "", startHour: "", endHour: "", promoQty: "", perBuyer: "", multi: false, targets: [], pct: "10" },
    price_flash: { what: "price", mode: "pct", rows: [], units: "50", slotStart: "", slotHours: "2" },
    variation_set: { rows: [{ name: "", price: "", sku: "", packCount: "", stock: "" }] },
    ads: { lever: "budget", campaignKey: "", campaignKeys: [], dailyBudget: "", unlimited: false, roasMode: "custom", roasTarget: "", itemId: "", start: "", end: "" },
    title: { ticked: [], text: "" },
    cover_image: { overlay: null },
    description_first_line: { text: "" },
    affiliate: { commission: "10", campaign: "", samples: "0", shipFee: "", multi: false, targets: [] },
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
/** P100-C (B.9): mirrors `specs.COMBO_TIERS_NOT_INCREASING`. */
const COMBO_TIERS_NOT_INCREASING = "Mỗi mức ưu đãi sau (mua nhiều sản phẩm hơn) cần giảm nhiều hơn mức trước.";

/** P100-C (B.9), as `specs._tiers_increase`: the effective % rises with N — % itself; số tiền ÷ N rises; giá đặc biệt ÷ N falls. */
function comboTiersIncrease(dtype: "pct" | "amount" | "special_price", tiers: readonly { readonly qty: number; readonly value: number }[]): boolean {
  const per = [...tiers].sort((a, b) => a.qty - b.qty).map((t) => (dtype === "pct" ? t.value : t.value / t.qty));
  for (let i = 1; i < per.length; i++) {
    if (dtype === "special_price" ? !(per[i]! < per[i - 1]!) : !(per[i]! > per[i - 1]!)) return false;
  }
  return true;
}

/**
 * P100: "Thời gian chạy Combo" / "Thời gian khuyến mãi" / Deal Sốc "Thời gian bắt đầu / kết thúc" have hour
 * precision (0–23) in Seller Centre; "" = the whole day. `maxDays` = the programme's longest run (180 for
 * Chương Trình Của Shop); null = no limit.
 */
function windowHours(c: { start: string; end: string; startHour?: string; endHour?: string }, maxDays: number | null = null): { problem: string | null; fields: Record<string, number> } {
  const fields: Record<string, number> = {};
  for (const [key, text, date] of [["start_hour", c.startHour ?? "", c.start], ["end_hour", c.endHour ?? "", c.end]] as const) {
    if (text.trim() === "") continue;
    const h = num(text);
    if (h === null || !Number.isInteger(h) || h < 0 || h > 23) return { problem: "Giờ là số nguyên từ 0 đến 23.", fields: {} };
    if (!date) return { problem: "Chọn ngày cho giờ bắt đầu / kết thúc.", fields: {} };
    fields[key] = h;
  }
  if (c.start && c.end && c.start === c.end && fields["start_hour"] !== undefined && fields["end_hour"] !== undefined && fields["end_hour"] <= fields["start_hour"]) {
    return { problem: "Giờ kết thúc phải sau giờ bắt đầu (chạy tối thiểu 1 giờ).", fields: {} };
  }
  if (maxDays !== null && c.start && c.end) {
    const a = Date.parse(`${c.start}T00:00:00Z`);
    const b = Date.parse(`${c.end}T00:00:00Z`);
    if (Number.isFinite(a) && Number.isFinite(b) && b >= a) {
      const dayCount = Math.round((b - a) / 86_400_000);
      const hours = fields["start_hour"] !== undefined && fields["end_hour"] !== undefined ? dayCount * 24 + fields["end_hour"] - fields["start_hour"] : null;
      const days = hours !== null ? Math.max(1, Math.ceil(hours / 24)) : dayCount + 1;
      if (days > maxDays) return { problem: `Chương trình chạy tối đa ${maxDays} ngày.`, fields: {} };
    }
  }
  return { problem: null, fields };
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
      if (v.scope === "product" && v.items.length > MAX_TARGETS) return no(`Voucher sản phẩm áp tối đa ${MAX_TARGETS} sản phẩm.`);
      const label = v.dtype === "pct" ? `${fmt(value, 0)}% / ${kmoney(min)}` : `${kmoney(value)} / ${kmoney(min)}`;
      return {
        problem: null,
        version: {
          kind: "voucher",
          label: clip(label),
          scope: v.scope,
          ...(v.scope === "product" ? { item_ids: v.items.length > 0 ? [...v.items] : [id] } : {}),
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
      if (c.items.length === 0) return no("Chọn ít nhất một sản phẩm cho combo.");
      if (c.items.length > MAX_TARGETS) return no(`Combo có tối đa ${MAX_TARGETS} sản phẩm.`);
      if ([...c.name.trim()].length > MAX_COMBO_NAME) return no(`Tên combo tối đa ${MAX_COMBO_NAME} ký tự.`);
      const tiers: { qty: number; value: number }[] = [];
      for (const [i, t] of c.tiers.entries()) {
        const qty = num(t.qty);
        const value = num(t.value);
        if (qty === null || !Number.isInteger(qty) || qty < 2 || qty > 9999) return no(`Mức ${i + 1}: số sản phẩm cần mua là số nguyên từ 2 đến 9999.`);
        if (value === null || value <= 0) return no(`Mức ${i + 1}: nhập ${c.dtype === "special_price" ? "giá" : c.dtype === "pct" ? "% giảm" : "số tiền giảm"}.`);
        if (c.dtype === "pct" && value > MAX_PCT) return no(`Mức ${i + 1}: ${PCT_PROBLEM}`);
        if (c.dtype === "special_price" && value < MIN_COMBO_PRICE) return no(REFUSAL_TEXT.combo_price_too_low!);
        tiers.push({ qty, value });
      }
      if (tiers.length === 0) return no("Thêm ít nhất một mức ưu đãi.");
      if (new Set(tiers.map((t) => t.qty)).size !== tiers.length) return no("Mỗi mức ưu đãi cần một số lượng mua khác nhau.");
      if (tiers.length > MAX_COMBO_TIERS) return no(`Tối đa ${MAX_COMBO_TIERS} mức ưu đãi.`);
      const limit = intIn(c.limit, 1, 999_999_999, "Giới hạn đặt hàng từ 1 đến 999.999.999.");
      if (!comboTiersIncrease(c.dtype, tiers)) return no(COMBO_TIERS_NOT_INCREASING);
      const hours = windowHours(c);
      const issue = limit.problem ?? hours.problem ?? dateProblem(c.start, c.end, null);
      if (issue) return no(issue);
      const name = c.name.trim();
      return {
        problem: null,
        version: { kind: "combo", label: clip(name || `Combo ${c.items.length} sản phẩm`), ...(name ? { name } : {}), item_ids: [...c.items], discount_type: c.dtype, tiers, ...(limit.n !== null ? { purchase_limit: limit.n } : {}), ...dated(c.start, c.end), ...hours.fields },
      };
    }
    case "listing_combo": {
      const l = f.listing_combo;
      const title = l.title.trim();
      if (!title) return no("Nhập tên listing combo.");
      if ([...title].length > MAX_TITLE) return no(`Tên listing tối đa ${MAX_TITLE} ký tự.`);
      if (l.members.length < 2) return no("Chọn từ 2 sản phẩm trở lên làm thành phần của listing combo.");
      if (l.members.length > MAX_COMBO_MEMBERS) return no(`Listing combo có tối đa ${MAX_COMBO_MEMBERS} sản phẩm thành phần.`);
      const price = num(l.price);
      if (price === null || price < MIN_COMBO_PRICE) return no("Nhập giá bán của listing combo (từ 1.000đ).");
      const stock = intIn(l.stock, 0, 10_000_000, "Tồn kho từ 0 đến 10.000.000.");
      if (stock.problem) return no(stock.problem);
      if (stock.n === null) return no("Nhập tồn kho của listing combo.");
      if (l.images.length > MAX_LISTING_IMAGES) return no(`Tối đa ${MAX_LISTING_IMAGES} ảnh.`);
      const sku = l.sku.trim();
      return { problem: null, version: { kind: "listing_combo", label: clip(title), title, image_refs: [...l.images], price, stock: stock.n, ...(sku ? { sku } : {}), member_ids: [...l.members] } };
    }
    case "deal_soc": {
      const d = f.deal_soc;
      const name = d.name.trim();
      if ([...name].length > MAX_PROGRAMME_NAME) return no(`Tên chương trình tối đa ${MAX_PROGRAMME_NAME} ký tự.`);
      const win = windowHours(d);
      const dates = win.problem ?? dateProblem(d.start, d.end, null);
      if (dates) return no(dates);
      const common = { ...(name ? { name } : {}), ...dated(d.start, d.end), ...win.fields };
      if (d.type === "add_on") {
        const rows = d.addons.filter((a) => a.itemId);
        if (rows.length === 0) return no("Chọn ít nhất một sản phẩm mua kèm.");
        if (rows.length > MAX_ADDONS) return no(`Mua kèm có tối đa ${MAX_ADDONS} sản phẩm.`);
        const limit = intIn(d.addonLimit, 1, MAX_ADDON_LIMIT, `Giới hạn sản phẩm mua kèm từ 1 đến ${MAX_ADDON_LIMIT}.`);
        if (limit.problem) return no(limit.problem);
        const addons: Record<string, unknown>[] = [];
        for (const a of rows) {
          const n = num(a.value);
          if (n === null || n <= 0) return no("Nhập giá mua kèm hoặc % giảm.");
          if (a.mode === "pct" && n > MAX_PCT) return no(PCT_PROBLEM);
          const perOrder = intIn(a.limit.trim() === "" ? "1" : a.limit, 1, 20, "Giới hạn mỗi đơn từ 1 đến 20.");
          if (perOrder.problem) return no(perOrder.problem);
          addons.push({ item_id: a.itemId, ...vid(a.variationId), [a.mode === "price" ? "price" : "pct"]: n, limit_per_order: perOrder.n ?? 1 });
        }
        return { problem: null, version: { kind: "add_on", label: clip(name || `Mua kèm ${addons.length} sản phẩm`), main_item_id: id, addons, ...(limit.n !== null ? { addon_limit: limit.n } : {}), ...common } };
      }
      const g = d.gift;
      const q = intIn(g.qty.trim() === "" ? "1" : g.qty, 1, MAX_GIFT_QTY, `Số quà tặng từ 1 đến ${MAX_GIFT_QTY} (Shopee: dưới 50).`);
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
      const amount = num(g.minSpend);
      if (amount === null || amount <= 0) return no("Nhập số tiền mua để nhận quà (điều kiện nhận quà).");
      return { problem: null, version: { kind: "gift", label: clip(name || `Mua ${kmoney(amount)} nhận ${qty} quà`), gift, trigger: { type: "min_spend", amount }, ...common } };
    }
    case "product_discount": {
      const d = f.product_discount;
      const name = d.name.trim();
      if ([...name].length > MAX_PROGRAMME_NAME) return no(`Tên chương trình tối đa ${MAX_PROGRAMME_NAME} ký tự.`);
      const win = windowHours(d, MAX_DISCOUNT_DAYS);
      const promo = intIn(d.promoQty, 1, 10_000_000, "Số lượng sản phẩm khuyến mãi từ 1 trở lên (để trống = Không giới hạn).");
      const buyer = intIn(d.perBuyer, 1, 100, "Giới hạn đặt hàng từ 1 đến 100.");
      const issue = win.problem ?? dateProblem(d.start, d.end, null) ?? promo.problem ?? buyer.problem;
      const common = { ...(name ? { name } : {}), ...dated(d.start, d.end), ...win.fields, ...(promo.n !== null ? { promo_qty: promo.n } : {}), ...(buyer.n !== null ? { per_buyer_limit: buyer.n } : {}) };
      if (d.multi) {
        const pct = num(d.pct);
        if (d.targets.length === 0) return no("Chọn ít nhất một sản phẩm để giảm giá.");
        if (d.targets.length > MAX_TARGETS) return no(`Chọn tối đa ${MAX_TARGETS} sản phẩm.`);
        if (pct === null || pct <= 0) return no("Nhập % GIẢM lớn hơn 0.");
        if (pct > MAX_PCT) return no(PCT_PROBLEM);
        if (issue) return no(issue);
        return {
          problem: null,
          version: { kind: "product_discount", label: clip(name || `Giảm ${fmt(pct, Number.isInteger(pct) ? 0 : 1)}% · ${d.targets.length} sản phẩm`), targets: [...d.targets], discount_pct: pct, ...common },
        };
      }
      const { rows, problem } = varRows(d.rows, d.mode, "discount_pct");
      if (problem) return no(problem);
      if (issue) return no(issue);
      return {
        problem: null,
        version: { kind: "product_discount", label: clip(name || (d.mode === "pct" ? `Giảm ${d.rows.map((r) => num(r.value)).find((n) => n) ?? ""}%` : "Giảm về giá mới")), item_id: id, variations: rows, ...common },
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
      const lever = a.lever === "budget" || a.lever === "roas";
      const keys = lever && a.campaignKeys.length > 0 ? a.campaignKeys : a.campaignKey ? [a.campaignKey] : [];
      if (keys.length === 0) return no("Chọn chiến dịch.");
      if (keys.length > MAX_CAMPAIGNS) return no(`Chọn tối đa ${MAX_CAMPAIGNS} chiến dịch.`);
      const campaign = lever && keys.length > 1 ? { campaign_keys: [...keys] } : { campaign_key: keys[0] };
      const dates = dateProblem(a.start, a.end, null);
      if (dates) return no(dates);
      const when = dated(a.start, a.end);
      if (a.lever === "budget") {
        if (a.unlimited) return { problem: null, version: { kind: "ads", label: "Ngân sách không giới hạn", lever: "budget", ...campaign, unlimited: true, ...when } };
        const n = num(a.dailyBudget);
        if (n === null || n <= 0) return no("Nhập ngân sách mỗi ngày hoặc chọn không giới hạn.");
        if (n < ADS_MIN_BUDGET) return no(ADS_BUDGET_MIN_TEXT);
        return { problem: null, version: { kind: "ads", label: clip(`Ngân sách ${kmoney(n)}/ngày`), lever: "budget", ...campaign, daily_budget: n, ...when } };
      }
      if (a.lever === "roas") {
        if (a.roasMode === "system") return { problem: null, version: { kind: "ads", label: "ROAS do hệ thống tối ưu", lever: "roas", ...campaign, roas_mode: "system", ...when } };
        const n = num(a.roasTarget);
        if (n === null || n <= 0) return no("Nhập ROAS mục tiêu.");
        return { problem: null, version: { kind: "ads", label: clip(`ROAS mục tiêu ${fmt(n, 1)}`), lever: "roas", ...campaign, roas_mode: "custom", roas_target: n, ...when } };
      }
      const item = a.itemId || id;
      return { problem: null, version: { kind: "ads", label: a.lever === "add_product" ? "Thêm sản phẩm vào chiến dịch" : "Gỡ sản phẩm khỏi chiến dịch", lever: a.lever, campaign_key: a.campaignKey, item_id: item, ...when } };
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
      if (a.multi && a.targets.length === 0) return no("Chọn ít nhất một sản phẩm.");
      if (a.multi && a.targets.length > MAX_TARGETS) return no(`Chọn tối đa ${MAX_TARGETS} sản phẩm.`);
      const who = a.multi ? { targets: [...a.targets] } : { item_id: id };
      return { problem: null, version: { kind: "affiliate", label: clip(a.multi ? `Hoa hồng ${fmt(pct, 1)}% · ${a.targets.length} sản phẩm` : `Hoa hồng ${fmt(pct, 1)}%`), ...who, commission_pct: pct, target_campaign: a.campaign === "1", sample_qty: samples, ...opt("sample_ship_fee", a.shipFee) } };
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
  combo_needs_products: "Combo cần ít nhất một sản phẩm.",
  combo_tiers_invalid: "Các mức ưu đãi chưa hợp lệ: mỗi mức một số lượng mua từ 2 trở lên và một giá trị lớn hơn 0.",
  combo_discount_type_invalid: "Kiểu giảm giá phải là %, số tiền hoặc giá đặc biệt.",
  combo_price_not_below_value: "Giá đặc biệt phải thấp hơn tổng giá bán hiện tại của số sản phẩm đó.",
  ads_budget_below_min: ADS_BUDGET_MIN_TEXT,
  listing_combo_members: "Listing combo cần từ 2 sản phẩm thành phần khác nhau.",
  combo_discount_over_max: "Combo giảm tối đa 90% tổng giá bán hiện tại.",
};

/** The smallest special price / listing price the builder accepts (mirrors bundle_tiers.MIN_SPECIAL_PRICE). */
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
    const o = (n: number | null) => (n === null ? DASH : `${n >= 0 ? "+" : "−"}${vnCount(Math.abs(n))}`);
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

/** One before -> after row as a person reads it: "1.200.000đ → 1.350.000đ (1.300.000đ – 1.420.000đ)", or
 * "không đổi" with the reason when the lever has no modelled effect on the metric (D85.9). */
export function beforeAfterText(row: BeforeAfterRow): { readonly main: string; readonly range: string | null; readonly unchanged: boolean } {
  const show = (n: number | null) => metricValue(row.unit, n);
  if (row.unchanged) return { main: `${show(row.before)} · không đổi`, range: row.reason, unchanged: true };
  if (!row.after || row.after.p50 === null) return { main: `${show(row.before)} → ${DASH}`, range: row.reason ?? "không đủ dữ liệu", unchanged: false };
  return { main: `${show(row.before)} → ${show(row.after.p50)}`, range: `${show(row.after.low)} – ${show(row.after.high)}`, unchanged: false };
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
  if (pp_ && pp_.p50 !== null) out.push(`Trong ${fmt(d.period?.days ?? d.days ?? null, 0)} ngày: ${sv(pp_.p50)} (${sv(pp_.low)} – ${sv(pp_.high)})`);
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

const COMBO_TYPES: Readonly<Record<string, string>> = { pct: "Giảm giá theo %", amount: "Giảm giá theo số tiền", special_price: "Giảm giá đặc biệt" };

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
  const dates = (label = "Thời gian") => {
    const start = s_(v["start"]);
    const end = s_(v["end"]);
    const sh = n_(v["start_hour"]);
    const eh = n_(v["end_hour"]);
    const at = (d: string, h: number | null) => (d ? `${h !== null ? `${String(h).padStart(2, "0")}:00 ` : ""}${dayText(d)}` : "…");
    if (start || end) add("dates", label, `${at(start, sh)}–${at(end, eh)}`);
  };
  const kind = String(v.kind);
  switch (kind) {
    case "voucher": {
      const value = n_(v["value"]);
      add("value", "Giảm", value === null ? null : v["discount_type"] === "pct" ? pctText(value) : vnd(value));
      add("min", "Đơn tối thiểu", vnd(n_(v["min_spend"])));
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
      const ids = Array.isArray(v["item_ids"]) ? (v["item_ids"] as unknown[]) : [];
      if (ids.length > 0 || Array.isArray(v["tiers"])) {
        const dtype = s_(v["discount_type"]);
        if (s_(v["name"])) add("name", "Tên combo", s_(v["name"]));
        add("items", `Sản phẩm (${fmt(ids.length)})`, ids.slice(0, 3).map(product).join(", ") + (ids.length > 3 ? `… +${fmt(ids.length - 3)}` : ""));
        add("dtype", "Loại combo", COMBO_TYPES[dtype] ?? dtype);
        for (const t of Array.isArray(v["tiers"]) ? (v["tiers"] as Record<string, unknown>[]) : []) {
          const value = n_(t["value"]);
          add(`tier:${fmt(n_(t["qty"]))}`, `Mua ${fmt(n_(t["qty"]))} sản phẩm`, value === null ? null : dtype === "pct" ? `giảm ${pctText(value)}` : dtype === "amount" ? `giảm ${vnd(value)}` : `chỉ ${vnd(value)}`);
        }
        const limit = n_(v["purchase_limit"]);
        if (limit !== null) add("limit", "Giới hạn đặt hàng", fmt(limit));
        const sh = n_(v["start_hour"]);
        const eh = n_(v["end_hour"]);
        if (sh !== null || eh !== null) {
          const at = (d: string, h: number | null) => (d ? `${h !== null ? `${String(h).padStart(2, "0")}:00 ` : ""}${dayText(d)}` : "…");
          add("dates", "Thời gian chạy Combo", `${at(s_(v["start"]), sh)}–${at(s_(v["end"]), eh)}`);
        } else dates();
        return { type: "Combo khuyến mãi", facts };
      }
      // a combo saved as a fixed basket (before P97): kept readable
      const items = Array.isArray(v["items"]) ? (v["items"] as Record<string, unknown>[]) : [];
      add("items", "Sản phẩm", items.map((i) => `${product(i["item_id"])} × ${fmt(n_(i["qty"]) ?? 1)}`).join(" + "));
      const value = n_(v["value"]);
      const pricing = s_(v["pricing"]);
      add("value", COMBO_PRICING[pricing] ?? "Mức giảm", value === null ? null : pricing === "pct" ? pctText(value) : vnd(value));
      return { type: "Combo kiểu cũ (giỏ cố định)", facts };
    }
    case "listing_combo": {
      add("title", "Tên listing", s_(v["title"]));
      add("price", "Giá bán", vnd(n_(v["price"])));
      add("stock", "Tồn kho", fmt(n_(v["stock"])));
      if (s_(v["sku"])) add("sku", "SKU", s_(v["sku"]));
      const members = Array.isArray(v["member_ids"]) ? (v["member_ids"] as unknown[]) : [];
      add("members", `Sản phẩm thành phần (${fmt(members.length)})`, members.map(product).join(", "));
      return { type: "Listing combo mới", facts };
    }
    case "add_on": {
      if (s_(v["name"])) add("name", "Tên chương trình", s_(v["name"]));
      add("main", "Sản Phẩm Chính", product(v["main_item_id"]));
      const addonLimit = n_(v["addon_limit"]);
      if (addonLimit !== null) add("addon_limit", "Giới hạn sản phẩm mua kèm", fmt(addonLimit));
      dates("Thời gian bắt đầu / kết thúc");
      for (const a of Array.isArray(v["addons"]) ? (v["addons"] as Record<string, unknown>[]) : []) {
        const price = n_(a["price"]);
        const pct = n_(a["pct"]);
        add(`a:${s_(a["item_id"])}`, `Sản Phẩm Mua Kèm · ${product(a["item_id"])}`, `${price !== null ? vnd(price) : pct !== null ? `−${pctText(pct)}` : DASH} · tối đa ${fmt(n_(a["limit_per_order"]) ?? 1)}/đơn`);
      }
      return { type: SERVER_KIND_NAMES["add_on"]!, facts };
    }
    case "gift": {
      const g = (v["gift"] ?? {}) as Record<string, unknown>;
      const t = (v["trigger"] ?? {}) as Record<string, unknown>;
      const listing = g["item_id"] !== undefined;
      if (s_(v["name"])) add("name", "Tên chương trình", s_(v["name"]));
      dates("Thời gian bắt đầu / kết thúc");
      add("gift", "Quà", `${listing ? product(g["item_id"]) : s_(g["label"]) || "Quà"} × ${fmt(n_(g["qty"]) ?? 1)}`);
      if (!listing) add("unit_cost", "Chi phí mỗi quà", vnd(n_(g["unit_cost"])));
      const pack = n_(g["packaging"]);
      if (pack !== null) add("packaging", "Đóng gói mỗi quà", vnd(pack));
      if (t["type"] === "min_spend") add("trigger", "Điều kiện nhận quà", `Mua ${vnd(n_(t["amount"]))} để nhận ${fmt(n_(g["qty"]) ?? 1)} quà tặng`);
      else add("trigger", "Mua sản phẩm", product(t["item_id"])); // a card saved before Deal Sốc
      return { type: SERVER_KIND_NAMES["gift"]!, facts };
    }
    case "product_discount":
    case "price":
    case "flash_sale": {
      const many = Array.isArray(v["targets"]) ? (v["targets"] as unknown[]) : [];
      if (many.length > 0) {
        const off = n_(v["discount_pct"]);
        add("pct", "Giảm", off === null ? null : pctText(off));
        add("targets", `Áp cho ${fmt(many.length)} sản phẩm`, many.slice(0, 3).map(product).join(", ") + (many.length > 3 ? `… +${fmt(many.length - 3)}` : ""));
      }
      for (const r of Array.isArray(v["variations"]) ? (v["variations"] as Record<string, unknown>[]) : []) {
        const key = `v:${s_(r["variation_id"])}`;
        const name = variation(r["variation_id"]);
        const final = n_(r["final_price"]);
        const change = n_(r["change_pct"]);
        const off = n_(r["discount_pct"]);
        if (change !== null) add(key, `Thay đổi · ${name}`, signedPct(change));
        else if (final !== null) add(key, `${kind === "flash_sale" ? "Giá flash sale" : kind === "price" ? "Giá mới" : "Giá sau giảm"} · ${name}`, vnd(final));
        else if (off !== null) add(key, `${kind === "product_discount" ? "% GIẢM" : "Giảm"} · ${name}`, pctText(off));
      }
      if (kind === "flash_sale") {
        add("units", "Số lượng (suất)", fmt(n_(v["units"])));
        add("hours", "Số giờ của khung", fmt(n_(v["slot_hours"])));
        if (s_(v["slot_start"])) add("slot", "Khung giờ bắt đầu", s_(v["slot_start"]).replace("T", " "));
      }
      if (kind === "product_discount") {
        if (s_(v["name"])) add("name", "Tên chương trình khuyến mãi", s_(v["name"]));
        const promo = n_(v["promo_qty"]);
        if (promo !== null) add("promo_qty", "Số lượng sản phẩm khuyến mãi", fmt(promo));
        const perBuyer = n_(v["per_buyer_limit"]);
        if (perBuyer !== null) add("per_buyer", "Giới hạn đặt hàng", fmt(perBuyer));
        dates("Thời gian khuyến mãi");
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
      const keys = Array.isArray(v["campaign_keys"]) ? (v["campaign_keys"] as unknown[]) : [];
      if (keys.length > 0) add("campaigns", `Áp cho ${fmt(keys.length)} chiến dịch`, keys.map((k) => names.campaigns?.[s_(k)] ?? s_(k)).join(", "));
      const budget = n_(v["daily_budget"]);
      if (budget !== null) add("budget", "Ngân sách mới mỗi ngày", vnd(budget));
      if (v["unlimited"] === true) add("budget", "Ngân sách mới mỗi ngày", "Không giới hạn");
      const roas = n_(v["roas_target"]);
      if (roas !== null) add("roas", "ROAS mục tiêu mới", fmt(roas, 1));
      if (v["roas_mode"] === "system") add("roas", "ROAS mục tiêu mới", "Do hệ thống tối ưu");
      dates();
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
      const many = Array.isArray(v["targets"]) ? (v["targets"] as unknown[]) : [];
      if (many.length > 0) add("targets", `Áp cho ${fmt(many.length)} sản phẩm`, many.slice(0, 3).map(product).join(", ") + (many.length > 3 ? `… +${fmt(many.length - 3)}` : ""));
      add("samples", "Số mẫu gửi", fmt(n_(v["sample_qty"])));
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
