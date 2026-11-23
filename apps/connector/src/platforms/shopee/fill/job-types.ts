// A fill job as Juli serves it (GET /v1/ingest/fill-jobs), validated field by field: the page
// only ever sees plain, bounded values, and a job whose address is not one of the allowed Seller
// Centre pages for its kind is dropped (nothing is opened, nothing is typed).

import { FILL_JOB_ID_PATTERN, FILL_JOB_PAGES } from "../config";
import { DATE_FORMAT } from "./controls";
import { type FillField, type FillKey } from "../../../core/fill/types";
import type { CoreJob, JobReply as CoreJobReply } from "../../../core/fill/form";

export type JobKind =
  | "title"
  | "description_first_line"
  | "voucher"
  | "ads_edit"
  | "affiliate_commission"
  | "combo"
  /** One new price per variation of a product (Giá bán / Flash sale). */
  | "price"
  /** 0.3.27 (F3.1, contract B): undo of an executed voucher / combo: the list row's Kết thúc / Xóa is shown, never pressed. */
  | "voucher_end"
  | "combo_end"
  /** 0.3.27 (F3.2, contract C): read the object again after a save, read-only. */
  | "readback"
  /** batch-1123-a F (0.3.32): Chương Trình Của Shop, Flash Sale Của Shop, Deal Sốc (Mua Kèm / Mua Để Nhận Quà). */
  | "product_discount"
  | "flash_sale"
  | "add_on"
  | "gift"
  /** The product page: a new cover (Ảnh bìa) and new options (Phân loại hàng). */
  | "cover_image"
  | "variation_set"
  /** Their undo: the list row's Kết thúc / Xóa (or its "Thêm" menu) is shown, never pressed. */
  | "discount_end"
  | "flash_sale_end"
  | "deal_end";

/** batch-1123-a F: the end jobs of the programmes (revert only, like voucher_end / combo_end). */
export const PROGRAMME_ENDS = ["discount_end", "flash_sale_end", "deal_end"] as const;
/** The kinds a revert may be: a text, a commission or a price put back, a row's end, the product page's undo. */
const REVERTIBLE: readonly JobKind[] = ["title", "description_first_line", "affiliate_commission", "voucher_end", "combo_end", "price", "cover_image", "variation_set", ...PROGRAMME_ENDS];

/** Forward fill, the undo of an executed card (contract B), or a read-back (contract C). */
export type JobMode = "forward" | "revert" | "readback";
export type JobStatus = "queued" | "opened" | "filled" | "saved" | "captured" | "failed" | "cancelled";

export interface VoucherPayload {
  usecase: 1 | 2;
  name: string;
  codeSuffix: string;
  startsAt: string;
  endsAt: string;
  discount: { type: "amount"; value: number } | { type: "percent"; value: number; max: { mode: "limited"; value: number } | { mode: "unlimited" } };
  minSpend: number;
  usageTotal: number;
  perBuyer: number;
  display: "multi" | "code" | "private";
  productIds: string[];
  /** "Mã giảm giá thông minh" as the card says (off when the card does not say). */
  smart: boolean;
}

export interface AdsPayload {
  campaignId: string;
  variant: "manual" | "manual-mpd";
  budget?: { mode: "daily"; value: number } | { mode: "unlimited" };
  roas?: { mode: "custom"; value: number } | { mode: "preset"; value: number };
}

export interface AffiliatePayload {
  productIds: string[];
  commissionPct: number;
}

export type ComboType = "pct" | "amount" | "special_price";

export interface PriceVariation {
  variationId: string;
  price: number;
  name?: string;
}

export interface PricePayload {
  itemId: string;
  variations: PriceVariation[];
}

/** Per variation Giá sau giảm / Giá đã giảm / Giá Mua Kèm (`finalPrice`) OR %GIẢM (`discountPct`). */
export interface DiscountRow {
  variationId: string;
  name?: string;
  finalPrice?: number;
  discountPct?: number;
  /** Flash Sale: SL sản phẩm khuyến mãi of this variation. */
  stock?: number;
}

export interface ProductDiscountPayload {
  name: string;
  startsAt: string;
  endsAt: string;
  productIds: string[];
  variations: DiscountRow[];
  /** One % for every variation of every product (a many-target card). */
  allPct?: number;
  promoQty?: number;
  perBuyerLimit?: number;
}

export interface FlashSalePayload {
  itemId: string;
  productIds: string[];
  /** The slot by its day (YYYY-MM-DD) and Shopee's label ("21:00:00 - 00:00:00"), never an id. */
  slot: { day: string; label: string; startsAt: string };
  variations: DiscountRow[];
  units: number;
  purchaseLimit?: number;
}

export interface DealAddon {
  itemId: string;
  price?: number;
  pct?: number;
  limit?: number;
}

export interface DealPayload {
  dealType: "add_on" | "gift";
  name: string;
  startsAt: string;
  endsAt: string;
  mainProductIds: string[];
  addonProductIds: string[];
  addons: DealAddon[];
  addonLimit?: number;
  minSpend?: number;
  giftQty?: number;
  giftProductIds: string[];
}

export interface CoverPayload {
  itemId: string;
  oldCoverUrl: string;
  newCoverUrl?: string;
}

export interface VariationOption {
  name: string;
  price?: number;
  sku?: string;
  stock?: number;
}

export interface VariationSetPayload {
  itemId: string;
  options: VariationOption[];
  /** The undo: the options to delete (the person) and the old prices to put back. */
  removeOptions: string[];
  oldVariations: VariationOption[];
}

export interface ComboPayload {
  name: string;
  startsAt: string;
  endsAt: string;
  discountType: ComboType;
  /** Ascending quantity N; value is a percent, an amount off, or the special price for N. */
  tiers: { qty: number; value: number }[];
  purchaseLimit?: number;
  productIds: string[];
}

/** The row a revert ends: by id first, else by the code (its suffix: the shop's prefix is never assumed), else by name. */
export interface EndTarget {
  id?: string;
  code?: string;
  name?: string;
  /** A Flash Sale Của Shop row: its day and slot label. */
  slot?: { day: string; label: string };
}

export type ReadbackDataset = "item_catalog" | "voucher_list" | "combo_list";

export interface ReadbackPayload {
  target: { itemId?: string; voucherId?: string; comboId?: string; name?: string; productIds?: string[] };
  datasets: ReadbackDataset[];
}

export type JobPayload =
  | { kind: "title" | "description_first_line"; fields: FillField[]; itemId: string }
  | { kind: "voucher_end" | "combo_end" | "discount_end" | "flash_sale_end" | "deal_end"; end: EndTarget }
  | { kind: "product_discount"; discount: ProductDiscountPayload }
  | { kind: "flash_sale"; flash: FlashSalePayload }
  | { kind: "add_on" | "gift"; deal: DealPayload }
  | { kind: "cover_image"; cover: CoverPayload }
  | { kind: "variation_set"; variations: VariationSetPayload }
  | { kind: "readback"; readback: ReadbackPayload }
  | { kind: "voucher"; voucher: VoucherPayload }
  | { kind: "ads_edit"; ads: AdsPayload }
  | { kind: "affiliate_commission"; affiliate: AffiliatePayload }
  | { kind: "combo"; combo: ComboPayload }
  | { kind: "price"; price: PricePayload };

export interface FillJob extends CoreJob {
  id: string;
  cardId: string;
  code: string;
  title: string;
  version: number;
  groupCode: string | null;
  kind: JobKind;
  /** 0.3.27: `payload.mode` (forward when absent). */
  mode: JobMode;
  status: JobStatus;
  /** Path (and query) to open, relative to Seller Centre. */
  openPath: string;
  payload: JobPayload;
}

/** The smallest daily budget Shopee accepts for a product ad (recon 2026-11-09). */
export const MIN_DAILY_BUDGET = 100_000;
export const MAX_PRODUCTS = 100;

const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const str = (v: unknown, max: number): string | undefined => (typeof v === "string" && v.length > 0 && v.length <= max ? v : undefined);
const num = (v: unknown): number | undefined => (typeof v === "number" && Number.isFinite(v) ? v : undefined);
const int = (v: unknown, min: number, max: number): number | undefined => {
  const n = num(v);
  return n !== undefined && Number.isInteger(n) && n >= min && n <= max ? n : undefined;
};
const ids = (v: unknown): string[] | undefined => {
  if (!Array.isArray(v) || v.length > MAX_PRODUCTS) return undefined;
  const out = v.filter((x): x is string => typeof x === "string" && /^\d{1,20}$/.test(x));
  return out.length === v.length ? out : undefined;
};

function voucher(raw: Record<string, unknown>): VoucherPayload | null {
  const usecase = raw.usecase === 1 ? 1 : raw.usecase === 2 ? 2 : undefined;
  const name = str(raw.name, 100);
  const codeSuffix = str(raw.code_suffix, 5);
  const startsAt = str(raw.starts_at, 16);
  const endsAt = str(raw.ends_at, 16);
  const minSpend = int(raw.min_spend, 0, 1_000_000_000);
  const usageTotal = int(raw.usage_total, 1, 10_000_000);
  const perBuyer = int(raw.per_buyer, 1, 1_000);
  const productIds = ids(raw.product_ids);
  const display = raw.display === "multi" || raw.display === "code" || raw.display === "private" ? raw.display : undefined;
  const d = raw.discount;
  if (!usecase || !name || !codeSuffix || !startsAt || !endsAt || minSpend === undefined || !usageTotal || !perBuyer || !productIds || !display || !isRecord(d)) return null;
  if (raw.smart !== undefined && typeof raw.smart !== "boolean") return null;
  const smart = raw.smart === true;
  if (!/^[A-Z0-9]{1,5}$/.test(codeSuffix) || !DATE_FORMAT.test(startsAt) || !DATE_FORMAT.test(endsAt)) return null;
  if (usecase === 2 && productIds.length === 0) return null;
  if (usecase === 1 && productIds.length > 0) return null;
  let discount: VoucherPayload["discount"];
  if (d.type === "amount") {
    const value = int(d.value, 1, 1_000_000_000);
    if (!value) return null;
    discount = { type: "amount", value };
  } else if (d.type === "percent") {
    const value = num(d.value);
    if (value === undefined || value <= 1 || value > 100) return null; // Shopee: "lớn hơn 1%"
    const m = d.max;
    if (!isRecord(m)) return null;
    if (m.mode === "unlimited") discount = { type: "percent", value, max: { mode: "unlimited" } };
    else {
      const cap = int(m.value, 1, 1_000_000_000);
      if (m.mode !== "limited" || !cap) return null;
      discount = { type: "percent", value, max: { mode: "limited", value: cap } };
    }
  } else return null;
  return { usecase, name, codeSuffix, startsAt, endsAt, discount, minSpend, usageTotal, perBuyer, display, productIds, smart };
}

function ads(raw: Record<string, unknown>): AdsPayload | null {
  const campaignId = str(raw.campaign_id, 20);
  const variant = raw.variant === "manual" || raw.variant === "manual-mpd" ? raw.variant : undefined;
  if (!campaignId || !/^\d+$/.test(campaignId) || !variant) return null;
  const out: AdsPayload = { campaignId, variant };
  if (raw.budget !== undefined) {
    const b = raw.budget;
    if (!isRecord(b)) return null;
    if (b.mode === "unlimited") out.budget = { mode: "unlimited" };
    else {
      const value = int(b.value, MIN_DAILY_BUDGET, 100_000_000_000);
      if (b.mode !== "daily" || !value) return null; // under Shopee's minimum: refused here too
      out.budget = { mode: "daily", value };
    }
  }
  if (raw.roas !== undefined) {
    const r = raw.roas;
    const value = isRecord(r) ? num(r.value) : undefined;
    if (!isRecord(r) || (r.mode !== "custom" && r.mode !== "preset") || value === undefined || value <= 0 || value > 100) return null;
    out.roas = { mode: r.mode, value };
  }
  return out.budget || out.roas ? out : null;
}

export const MAX_COMBO_TIERS = 5;
export const MAX_COMBO_NAME = 25;
export const MAX_PURCHASE_LIMIT = 999_999_999;

function combo(raw: Record<string, unknown>): ComboPayload | null {
  const name = str(raw.name, MAX_COMBO_NAME);
  const startsAt = str(raw.starts_at, 16);
  const endsAt = str(raw.ends_at, 16);
  const discountType = raw.discount_type === "pct" || raw.discount_type === "amount" || raw.discount_type === "special_price" ? raw.discount_type : undefined;
  const productIds = ids(raw.product_ids);
  if (!name || !startsAt || !endsAt || !discountType || !productIds || productIds.length === 0) return null;
  if (!DATE_FORMAT.test(startsAt) || !DATE_FORMAT.test(endsAt)) return null;
  const rows = raw.tiers;
  if (!Array.isArray(rows) || rows.length < 1 || rows.length > MAX_COMBO_TIERS) return null;
  const tiers: ComboPayload["tiers"] = [];
  for (const row of rows) {
    if (!isRecord(row)) return null;
    const qty = int(row.qty, 2, 9999);
    const value = int(row.value, 1, discountType === "pct" ? 99 : 1_000_000_000);
    if (!qty || !value || (tiers.length > 0 && qty <= (tiers[tiers.length - 1] as { qty: number }).qty)) return null;
    tiers.push({ qty, value });
  }
  const out: ComboPayload = { name, startsAt, endsAt, discountType, tiers, productIds };
  if (raw.purchase_limit !== undefined) {
    const limit = int(raw.purchase_limit, 1, MAX_PURCHASE_LIMIT);
    if (!limit) return null;
    out.purchaseLimit = limit;
  }
  return out;
}

function addressOk(kind: JobKind, openPath: string, payload: JobPayload): boolean {
  let url: URL;
  try {
    url = new URL(openPath, "https://banhang.shopee.vn");
  } catch {
    return false;
  }
  const path = url.pathname;
  if (kind === "title" || kind === "description_first_line") {
    const m = FILL_JOB_PAGES.product_edit.exec(path);
    return !!m && payload.kind === kind && m[1] === payload.itemId;
  }
  if (kind === "voucher" && payload.kind === "voucher") {
    return FILL_JOB_PAGES.voucher_new.test(path) && url.search === `?usecase=${payload.voucher.usecase}`;
  }
  if (kind === "ads_edit" && payload.kind === "ads_edit") {
    const m = FILL_JOB_PAGES.ads_edit.exec(path);
    return !!m && m[1] === payload.ads.variant && m[2] === payload.ads.campaignId;
  }
  if (kind === "combo") return payload.kind === "combo" && FILL_JOB_PAGES.bundle_new.test(path) && url.search === "";
  if (kind === "price" && payload.kind === "price") {
    const m = FILL_JOB_PAGES.product_edit.exec(path);
    return !!m && m[1] === payload.price.itemId && url.search === "";
  }
  if (kind === "affiliate_commission") return FILL_JOB_PAGES.affiliate_open.test(path);
  if (kind === "product_discount") return payload.kind === kind && FILL_JOB_PAGES.discount_new.test(path) && url.search === "";
  if (kind === "flash_sale") return payload.kind === kind && FILL_JOB_PAGES.flash_sale_new.test(path) && url.search === "";
  if (kind === "add_on" || kind === "gift") return payload.kind === kind && FILL_JOB_PAGES.deal_new.test(path) && url.search === "";
  if ((kind === "cover_image" || kind === "variation_set") && (payload.kind === "cover_image" || payload.kind === "variation_set")) {
    const m = FILL_JOB_PAGES.product_edit.exec(path);
    const item = payload.kind === "cover_image" ? payload.cover.itemId : payload.variations.itemId;
    return payload.kind === kind && !!m && m[1] === item && url.search === "";
  }
  if (kind === "discount_end" || kind === "deal_end") return payload.kind === kind && FILL_JOB_PAGES.discount_list.test(path);
  if (kind === "flash_sale_end") return payload.kind === kind && FILL_JOB_PAGES.flash_sale_list.test(path);
  if (kind === "voucher_end") return payload.kind === kind && FILL_JOB_PAGES.voucher_list.test(path);
  if (kind === "combo_end") return payload.kind === kind && FILL_JOB_PAGES.bundle_list.test(path);
  if (kind === "readback" && payload.kind === "readback") {
    const item = FILL_JOB_PAGES.product_edit.exec(path);
    if (item) return payload.readback.target.itemId === item[1];
    if (FILL_JOB_PAGES.affiliate_open.test(path)) return (payload.readback.target.productIds?.length ?? 0) > 0;
    return [FILL_JOB_PAGES.voucher_list, FILL_JOB_PAGES.bundle_list, /^\/portal\/product\/list\/all$/].some((re) => re.test(path));
  }
  return false;
}

const TEXT_KEYS: readonly FillKey[] = ["title", "description_first_line"];

const digitsOf = (v: unknown): string | undefined =>
  typeof v === "string" && /^\d{1,20}$/.test(v) ? v : typeof v === "number" && Number.isSafeInteger(v) && v > 0 ? String(v) : undefined;

function endTarget(p: Record<string, unknown>, idKey: "voucher_id" | "combo_id"): EndTarget | null {
  const id = digitsOf(p[idKey]);
  // t2 (2026-11-18): `code_suffix` (the shop's prefix is not Juli's to know, E54); `code` still read
  const code = str(p.code_suffix, 20) ?? str(p.code, 40);
  const name = str(p.name, 100);
  if (p[idKey] !== undefined && p[idKey] !== null && !id) return null;
  if (code !== undefined && !/^[A-Z0-9]{1,20}$/.test(code)) return null;
  if (!id && !code && !name) return null;
  return { ...(id ? { id } : {}), ...(code ? { code } : {}), ...(name ? { name } : {}) };
}

const READBACK_DATASETS: readonly ReadbackDataset[] = ["item_catalog", "voucher_list", "combo_list"];

function readback(p: Record<string, unknown>): ReadbackPayload | null {
  const t = p.target;
  if (!isRecord(t) || !Array.isArray(p.datasets) || p.datasets.length < 1 || p.datasets.length > 3) return null;
  const datasets = p.datasets.filter((d): d is ReadbackDataset => READBACK_DATASETS.includes(d as ReadbackDataset));
  if (datasets.length !== p.datasets.length) return null;
  const target: ReadbackPayload["target"] = {};
  for (const [key, out] of [["item_id", "itemId"], ["voucher_id", "voucherId"], ["combo_id", "comboId"]] as const) {
    if (t[key] === undefined || t[key] === null) continue;
    const id = digitsOf(t[key]);
    if (!id) return null;
    target[out] = id;
  }
  const name = str(t.name, 100);
  if (name) target.name = name;
  if (t.product_ids !== undefined) {
    const products = ids(t.product_ids);
    if (!products || products.length === 0) return null;
    target.productIds = products;
  }
  return Object.keys(target).length > 0 ? { target, datasets } : null;
}

// -- batch-1123-a F: programmes and the product page ---------------------------------------

export const MAX_PROGRAMME_NAME = 150;
/** Shopee's Deal Sốc name box: maxlength 25 (capture 03). */
export const MAX_DEAL_NAME = 25;
export const MAX_VARIATION_ROWS = 40;
const SLOT_LABEL = /^([01]\d|2[0-3]):00:00 - ([01]\d|2[0-3]):00:00$/;
const ISO_DAY = /^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$/;
const HTTPS = /^https:\/\/[^\s"'<>]{1,2000}$/;

function discountRows(raw: unknown, stock: boolean): DiscountRow[] | null {
  if (!Array.isArray(raw) || raw.length > MAX_VARIATION_ROWS) return null;
  const out: DiscountRow[] = [];
  const seen = new Set<string>();
  for (const r of raw) {
    if (!isRecord(r)) return null;
    const variationId = str(r.variation_id, 64);
    const name = r.name === undefined ? undefined : str(r.name, 255);
    const finalPrice = r.final_price === undefined ? undefined : int(r.final_price, 1, 1_000_000_000);
    const discountPct = r.discount_pct === undefined ? undefined : num(r.discount_pct);
    if (!variationId || seen.has(variationId) || (r.name !== undefined && !name)) return null;
    if ((finalPrice === undefined) === (discountPct === undefined)) return null;
    if (r.final_price !== undefined && finalPrice === undefined) return null;
    if (discountPct !== undefined && !(discountPct > 0 && discountPct <= 90)) return null;
    const row: DiscountRow = { variationId, ...(name ? { name } : {}), ...(finalPrice !== undefined ? { finalPrice } : { discountPct: discountPct! }) };
    if (stock && r.stock !== undefined) {
      const s = int(r.stock, 1, 1000);
      if (!s) return null;
      row.stock = s;
    }
    seen.add(variationId);
    out.push(row);
  }
  return out;
}

function period(raw: Record<string, unknown>): { startsAt: string; endsAt: string } | null {
  const startsAt = str(raw.starts_at, 16);
  const endsAt = str(raw.ends_at, 16);
  return startsAt && endsAt && DATE_FORMAT.test(startsAt) && DATE_FORMAT.test(endsAt) ? { startsAt, endsAt } : null;
}

function productDiscount(raw: Record<string, unknown>): ProductDiscountPayload | null {
  const name = str(raw.name, MAX_PROGRAMME_NAME);
  const when = period(raw);
  const productIds = ids(raw.product_ids);
  const variations = discountRows(raw.variations ?? [], false);
  if (!name || !when || !productIds || productIds.length === 0 || !variations) return null;
  const out: ProductDiscountPayload = { name, ...when, productIds, variations };
  if (raw.all_pct !== undefined) {
    const pct = num(raw.all_pct);
    if (pct === undefined || !(pct > 0 && pct <= 90)) return null;
    out.allPct = pct;
  }
  // one % for all, or a value per variation: never both, never neither
  if ((out.allPct !== undefined) === (variations.length > 0)) return null;
  for (const [key, field, max] of [["promo_qty", "promoQty", 10_000_000], ["per_buyer_limit", "perBuyerLimit", 100]] as const) {
    if (raw[key] === undefined) continue;
    const v = int(raw[key], 1, max);
    if (!v) return null;
    out[field] = v;
  }
  return out;
}

function flashSale(raw: Record<string, unknown>): FlashSalePayload | null {
  const itemId = digitsOf(raw.item_id);
  const productIds = ids(raw.product_ids);
  const s = raw.slot;
  const variations = discountRows(raw.variations, true);
  const units = int(raw.units, 1, 1_000_000);
  if (!itemId || !productIds || productIds.length !== 1 || productIds[0] !== itemId || !isRecord(s) || !variations || variations.length === 0 || !units) return null;
  const day = str(s.day, 10);
  const label = str(s.label, 19);
  const startsAt = str(s.starts_at, 16);
  if (!day || !ISO_DAY.test(day) || !label || !SLOT_LABEL.test(label) || !startsAt || !DATE_FORMAT.test(startsAt)) return null;
  if (variations.some((v) => v.discountPct !== undefined && (v.discountPct < 5 || v.discountPct > 90))) return null;
  const out: FlashSalePayload = { itemId, productIds, slot: { day, label, startsAt }, variations, units };
  if (raw.purchase_limit !== undefined) {
    const limit = int(raw.purchase_limit, 1, 1000);
    if (!limit) return null;
    out.purchaseLimit = limit;
  }
  return out;
}

function deal(raw: Record<string, unknown>, kind: "add_on" | "gift"): DealPayload | null {
  const name = str(raw.name, MAX_DEAL_NAME);
  const when = period(raw);
  if (raw.deal_type !== kind || !name || !when) return null;
  const mainProductIds = ids(raw.main_product_ids ?? []);
  const addonProductIds = ids(raw.addon_product_ids ?? []);
  const giftProductIds = ids(raw.gift_product_ids ?? []);
  if (!mainProductIds || !addonProductIds || !giftProductIds) return null;
  const out: DealPayload = { dealType: kind, name, ...when, mainProductIds, addonProductIds, addons: [], giftProductIds };
  if (kind === "add_on") {
    if (mainProductIds.length !== 1 || addonProductIds.length === 0) return null;
    const rows = raw.addons ?? [];
    if (!Array.isArray(rows) || rows.length > MAX_PRODUCTS) return null;
    for (const r of rows) {
      if (!isRecord(r)) return null;
      const itemId = digitsOf(r.item_id);
      const price = r.price === undefined ? undefined : int(r.price, 1, 1_000_000_000);
      const pct = r.pct === undefined ? undefined : num(r.pct);
      const limit = r.limit === undefined ? undefined : int(r.limit, 1, 100);
      if (!itemId || (price === undefined) === (pct === undefined) || (r.price !== undefined && !price) || (pct !== undefined && (pct < 0 || pct > 90)) || (r.limit !== undefined && !limit)) return null;
      out.addons.push({ itemId, ...(price !== undefined ? { price } : { pct: pct! }), ...(limit ? { limit } : {}) });
    }
    if (raw.addon_limit !== undefined) {
      const limit = int(raw.addon_limit, 1, 100);
      if (!limit) return null;
      out.addonLimit = limit;
    }
    return out;
  }
  const minSpend = int(raw.min_spend, 1, 9_999_999_999_999);
  const giftQty = int(raw.gift_qty, 1, 49);
  if (!minSpend || !giftQty || giftProductIds.length === 0) return null;
  return { ...out, minSpend, giftQty };
}

function cover(raw: Record<string, unknown>, mode: JobMode): CoverPayload | null {
  const itemId = digitsOf(raw.item_id);
  const oldCoverUrl = typeof raw.old_cover_url === "string" && HTTPS.test(raw.old_cover_url) ? raw.old_cover_url : undefined;
  if (!itemId || !oldCoverUrl) return null;
  const out: CoverPayload = { itemId, oldCoverUrl };
  if (raw.new_cover_url !== undefined) {
    if (mode === "revert" || typeof raw.new_cover_url !== "string" || !HTTPS.test(raw.new_cover_url)) return null;
    out.newCoverUrl = raw.new_cover_url;
  }
  return out;
}

function option(r: unknown): VariationOption | null {
  if (!isRecord(r)) return null;
  const name = str(r.name, 100);
  if (!name || /[\r\n]/.test(name)) return null;
  const out: VariationOption = { name };
  for (const [key, max] of [["price", 2_000_000_000], ["stock", 10_000_000]] as const) {
    if (r[key] === undefined || r[key] === null) continue;
    const v = int(r[key], key === "price" ? 1 : 0, max);
    if (v === undefined) return null;
    out[key] = v;
  }
  if (r.sku !== undefined && r.sku !== null) {
    const sku = str(r.sku, 100);
    if (!sku) return null;
    out.sku = sku;
  }
  return out;
}

function variationSet(raw: Record<string, unknown>, mode: JobMode): VariationSetPayload | null {
  const itemId = digitsOf(raw.item_id);
  if (!itemId) return null;
  const list = (v: unknown, max: number) => (Array.isArray(v) && v.length <= max ? v.map(option) : null);
  const options = list(raw.options ?? [], 12);
  const old = list(raw.old_variations ?? [], MAX_VARIATION_ROWS);
  const names = raw.remove_options ?? [];
  const remove = Array.isArray(names) && names.length <= 12 ? names.map((n) => str(n, 100)) : null;
  if (!options || !old || !remove || options.some((o) => !o) || old.some((o) => !o) || remove.some((n) => !n)) return null;
  const out: VariationSetPayload = { itemId, options: options as VariationOption[], removeOptions: remove as string[], oldVariations: old as VariationOption[] };
  if (mode === "revert" ? out.removeOptions.length === 0 : out.options.length === 0 || out.options.some((o) => o.price === undefined)) return null;
  return out;
}

function programmeEnd(p: Record<string, unknown>): EndTarget | null {
  const id = digitsOf(p.id);
  const name = str(p.name, MAX_PROGRAMME_NAME);
  if (p.id !== undefined && p.id !== null && !id) return null;
  let slot: EndTarget["slot"];
  if (p.slot !== undefined) {
    const s = p.slot;
    const day = isRecord(s) ? str(s.day, 10) : undefined;
    const label = isRecord(s) ? str(s.label, 19) : undefined;
    if (!day || !ISO_DAY.test(day) || !label || !SLOT_LABEL.test(label)) return null;
    slot = { day, label };
  }
  if (!id && !name && !slot) return null;
  return { ...(id ? { id } : {}), ...(name ? { name } : {}), ...(slot ? { slot } : {}) };
}

/** One job of the server's answer, or null when anything is off. */
export function parseFillJob(raw: unknown): FillJob | null {
  if (!isRecord(raw)) return null;
  const id = str(raw.id, 36);
  const kind = raw.kind as JobKind;
  const status = str(raw.status, 12) as JobStatus | undefined;
  const openPath = str(raw.open_path, 200);
  const p = raw.payload;
  if (!id || !FILL_JOB_ID_PATTERN.test(id) || !status || !openPath || !isRecord(p)) return null;
  if (!openPath.startsWith("/") || openPath.startsWith("//")) return null;
  const mode: JobMode = p.mode === undefined || p.mode === "forward" ? "forward" : p.mode === "revert" ? "revert" : p.mode === "readback" ? "readback" : ("bad" as JobMode);
  if (!["forward", "revert", "readback"].includes(mode)) return null;
  // a read-back job is only ever a read-back; an end job only ever a revert
  if ((kind === "readback") !== (mode === "readback")) return null;
  if ((kind === "voucher_end" || kind === "combo_end" || (PROGRAMME_ENDS as readonly string[]).includes(kind)) && mode !== "revert") return null;
  // what a revert may be (contract B): a text, a commission or a price put back, a row's end, a product page undo
  if (mode === "revert" && !REVERTIBLE.includes(kind)) return null;
  let payload: JobPayload | null = null;
  if (kind === "title" || kind === "description_first_line") {
    const itemId = /\/portal\/product\/(\d{1,20})$/.exec(openPath.split("?")[0] ?? "")?.[1];
    const fields: FillField[] = [];
    for (const f of Array.isArray(p.fields) ? p.fields : []) {
      if (!isRecord(f)) return null;
      const key = f.key as FillKey;
      const value = str(f.value, 600);
      const label = str(f.label, 80);
      const mode = f.mode === "replace" || f.mode === "first_line" ? f.mode : undefined;
      const maxChars = num(f.max_chars) ?? 0;
      if (!TEXT_KEYS.includes(key) || key !== kind || !value || !label || !mode || maxChars < 1 || value.length > maxChars || /[\r\n]/.test(value)) return null;
      fields.push({ key, label, value, mode, maxChars });
    }
    if (!itemId || fields.length !== 1) return null;
    payload = { kind, fields, itemId };
  } else if (kind === "voucher") {
    const v = voucher(p);
    payload = v ? { kind, voucher: v } : null;
  } else if (kind === "ads_edit") {
    const a = ads(p);
    payload = a ? { kind, ads: a } : null;
  } else if (kind === "affiliate_commission") {
    const productIds = ids(p.product_ids);
    const pct = num(p.commission_pct);
    payload = productIds && productIds.length > 0 && pct !== undefined && pct > 0 && pct <= 50 ? { kind, affiliate: { productIds, commissionPct: pct } } : null;
  } else if (kind === "combo") {
    const c = combo(p);
    payload = c ? { kind, combo: c } : null;
  } else if (kind === "price") {
    const itemId = /\/portal\/product\/(\d{1,20})$/.exec(openPath.split("?")[0] ?? "")?.[1];
    const rows = p.variations;
    if (!itemId || !Array.isArray(rows) || rows.length < 1 || rows.length > 40) payload = null;
    else {
      const variations: PricePayload["variations"] = [];
      const seen = new Set<string>();
      let ok = true;
      for (const row of rows) {
        if (!isRecord(row)) {
          ok = false;
          break;
        }
        const variationId = str(row.variation_id, 64);
        const price = int(row.price, 1, 1_000_000_000);
        const name = row.name === undefined ? undefined : str(row.name, 255);
        if (!variationId || price === undefined || seen.has(variationId) || (row.name !== undefined && !name)) {
          ok = false;
          break;
        }
        seen.add(variationId);
        variations.push({ variationId, price, ...(name ? { name } : {}) });
      }
      payload = ok ? { kind, price: { itemId, variations } } : null;
    }
  } else if (kind === "voucher_end" || kind === "combo_end") {
    const end = endTarget(p, kind === "voucher_end" ? "voucher_id" : "combo_id");
    payload = end ? { kind, end } : null;
  } else if (kind === "discount_end" || kind === "flash_sale_end" || kind === "deal_end") {
    const end = programmeEnd(p);
    payload = end ? { kind, end } : null;
  } else if (kind === "product_discount") {
    const d = productDiscount(p);
    payload = d ? { kind, discount: d } : null;
  } else if (kind === "flash_sale") {
    const f = flashSale(p);
    payload = f ? { kind, flash: f } : null;
  } else if (kind === "add_on" || kind === "gift") {
    const d = deal(p, kind);
    payload = d ? { kind, deal: d } : null;
  } else if (kind === "cover_image") {
    const c = cover(p, mode);
    payload = c ? { kind, cover: c } : null;
  } else if (kind === "variation_set") {
    const v = variationSet(p, mode);
    payload = v ? { kind, variations: v } : null;
  } else if (kind === "readback") {
    const r = readback(p);
    payload = r ? { kind, readback: r } : null;
  }
  if (!payload || !addressOk(kind, openPath, payload)) return null;
  const version = int(raw.version, 1, 9) ?? 1;
  return {
    id,
    cardId: str(raw.card_id, 36) ?? "",
    code: str(raw.code, 40) ?? "",
    title: str(raw.title, 300) ?? str(raw.code, 40) ?? "",
    version,
    groupCode: str(raw.group_code, 16) ?? null,
    kind,
    mode,
    status,
    openPath,
    payload,
  };
}

/** The reply of the service worker to the content script's job request. */
export type JobReply = CoreJobReply<FillJob>;
