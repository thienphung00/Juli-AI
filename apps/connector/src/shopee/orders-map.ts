// Order lines and per-order income (Connector 0.3.11, P97 T1).
//
// Sources (recon 2026-11-09, field names only, no buyer data kept):
//   POST /api/v3/order/search_order_list_index   -> the order ids of a list page
//   POST /api/v3/order/get_order_list_card_list  -> the cards of those orders (batched)
//   GET  /api/v4/accounting/pc/seller_income/income_detail/get_order_income_components
//
// PII: the cards carry the buyer's username and address. `trimOrderBody` runs IN THE PAGE (the hook
// keeps only what it returns) and is an ALLOWLIST: a key it does not know is dropped, so a name
// that is wrong makes the mapper find nothing (drift: dataset stopped) and never leaks a buyer.
// The order id leaves the mapper only as `__order_id__`; the service worker replaces it by
// `order_ref` (the shop's keyed hash) before posting, exactly like the affiliate reader.
//
// TODO(first capture, ORY, one order list page and one order page): the card / income shapes below
// are the recon's field NAMES arranged by the usual Seller Centre conventions, not a captured body.
// Check: (1) the card list key and the per-card item list; (2) `status` as text or number;
// (3) money scale (read from the answer by magnitude, else x100 000 for cards, x1 for income);
// (4) which label strings the income components use. Unknown extra fields never stop a dataset;
// a missing identity field (order id, time, items) is drift.

import { MAX_PLAUSIBLE_AD_VND } from "../config";
import { RAW_ORDER_ID, scaleFromMagnitude } from "./affiliate-map";
import type { Drift, Mapped, Row } from "./map";
import { classify, findList, payloadOf, type ReaderResponse } from "./reader";
import { gmt7Date } from "./time";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function num(value: unknown): number | undefined {
  const n = typeof value === "string" && value.trim() !== "" ? Number(value) : value;
  return typeof n === "number" && Number.isFinite(n) ? n : undefined;
}

function text(value: unknown, max: number): string | undefined {
  if (typeof value !== "string") return undefined;
  const t = value.trim();
  return t ? t.slice(0, max) : undefined;
}

function idOf(value: unknown): string | undefined {
  if (typeof value === "number" && Number.isInteger(value) && value >= 0) return String(value);
  if (typeof value === "string" && /^[A-Za-z0-9]{6,40}$/.test(value)) return value;
  return undefined;
}

/** Unix seconds (or ms) -> a naive GMT+7 wall-clock timestamp, as the other readers post. */
function wallClock(value: unknown): string | undefined {
  const n = num(value);
  if (n === undefined || n <= 0) return undefined;
  const seconds = n > 1e12 ? Math.floor(n / 1000) : n;
  return new Date((seconds + 7 * 3600) * 1000).toISOString().slice(0, 19);
}

// -- in-page allowlist --------------------------------------------------------------------------

/** Order-level keys that may leave the page. No username, name, address, phone, note, tracking. */
const ORDER_KEEP = new Set([
  "order_id",
  "order_sn",
  "status",
  "order_status",
  "create_time",
  "pay_time",
  "paid_time",
  "complete_time",
  "completed_time",
  "order_complete_time",
  "total_price",
  "final_total",
  "buyer_paid_shipping_fee",
  "shipping_fee_paid_by_buyer",
  "shop_voucher_amount",
  "seller_voucher",
  "shopee_voucher_amount",
  "platform_voucher",
  "bundle_deal_discount",
  "combo_discount",
  "bank_promo_amount",
  "promotion_type",
]);
/** Line-level keys. The product name is dropped too (not needed, and not ours to keep). */
const ITEM_KEEP = new Set([
  "item_id",
  "model_id",
  "item_sku",
  "model_sku",
  "sku",
  "variation_sku",
  "model_name",
  "variation_name",
  "amount",
  "quantity",
  "qty",
  "returned_qty",
  "item_price",
  "original_price",
  "order_price",
  "deal_price",
  "price_before_discount",
  "seller_discount",
  "shopee_discount",
]);
const ITEM_LISTS = ["items", "item_list", "order_items", "model_list", "order_item_list"] as const;
const ORDER_NODES = ["order_card", "card", "order", "order_info", "order_ext_info"] as const;

function keep(source: Record<string, unknown>, allowed: ReadonlySet<string>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(source)) {
    if (allowed.has(key) && (value === null || typeof value !== "object")) out[key] = value;
  }
  return out;
}

/** One order record (flattened from its wrappers) with only allowlisted keys. */
function trimOrder(card: Record<string, unknown>): Record<string, unknown> {
  const merged: Record<string, unknown> = { ...card };
  for (const node of ORDER_NODES) if (isRecord(card[node])) Object.assign(merged, card[node]);
  const out = keep(merged, ORDER_KEEP);
  for (const listKey of ITEM_LISTS) {
    const list = merged[listKey];
    if (Array.isArray(list)) {
      out.items = list.filter(isRecord).map((item) => keep(item, ITEM_KEEP));
      break;
    }
  }
  return out;
}

const isOrderRecord = (o: Record<string, unknown>) =>
  ("order_id" in o || "order_sn" in o) ||
  ORDER_NODES.some((node) => isRecord(o[node]) && ("order_id" in o[node] || "order_sn" in o[node]));

/** The list-index answer: only the order ids (the page number / totals are not needed). */
export function trimOrderIndex(body: unknown): unknown {
  const found = findList(payloadOf(body), (o) => "order_id" in o || "order_sn" in o);
  const ids = (found?.list ?? []).map((o) => keep(o, new Set(["order_id", "order_sn"])));
  return { code: isRecord(body) ? body.code : undefined, data: { list: ids } };
}

/** The card-list answer: orders and lines with allowlisted keys only (PII dropped in the page). */
export function trimOrderCards(body: unknown): unknown {
  const found = findList(payloadOf(body), isOrderRecord, 5);
  return { code: isRecord(body) ? body.code : undefined, data: { list: (found?.list ?? []).map(trimOrder) } };
}

// -- order lines --------------------------------------------------------------------------------

const MAX_LINES = 2_000;
const MONEY_FIELDS = ["item_price", "original_price", "order_price", "deal_price", "price_before_discount"] as const;

type OrderStatusName = "delivered" | "cancelled" | "in_transit" | "refunded_accepted" | "refunded_not_received";

/** Seller Centre's status as text or number -> the contract-10 value. Unknown = in_transit (not counted as sold). */
export function orderStatusOf(value: unknown): OrderStatusName {
  const t = typeof value === "string" ? value.toLowerCase() : "";
  if (/cancel|hủy|huy/.test(t)) return "cancelled";
  if (/refund|return|hoàn|hoan|trả/.test(t)) return /accept|done|complete|thành công/.test(t) ? "refunded_accepted" : "refunded_not_received";
  if (/complete|deliver|hoàn thành|đã giao/.test(t)) return "delivered";
  return "in_transit";
}

function dayOf(wall: string | undefined): string | undefined {
  return wall?.slice(0, 10);
}

/**
 * All order records of the answers the page / the replay got, keyed by the id that is HASHED: the
 * order number `order_sn` (what the affiliate report and the order export call the order id, so the
 * three join on one `order_ref`), else `order_id`. `api` is the id the order page / income call uses.
 * TODO(first capture): confirm which of the two ids the cards carry.
 */
function collectOrders(responses: ReaderResponse[]): Map<string, Record<string, unknown> & { __api?: string }> {
  const orders = new Map<string, Record<string, unknown> & { __api?: string }>();
  for (const response of responses) {
    if (response.endpoint !== "order_cards" || classify(response.status, response.body) !== "ok") continue;
    for (const order of findList(payloadOf(response.body), isOrderRecord, 5)?.list ?? []) {
      const sn = idOf(order.order_sn);
      const api = idOf(order.order_id);
      const key = sn ?? api;
      if (key !== undefined && !orders.has(key)) orders.set(key, { ...order, ...(api !== undefined ? { __api: api } : {}) });
    }
  }
  return orders;
}

export function mapOrderLines(responses: ReaderResponse[], capturedAt: number): Mapped {
  const today = gmt7Date(Math.floor(capturedAt / 1000));
  const orders = collectOrders(responses);
  const answered = responses.some((r) => r.endpoint === "order_cards" && classify(r.status, r.body) === "ok");
  const base = { dataset: "order_lines" as const, endpoint: "order/get_order_list_card_list", orderType: null, granularity: "period" as const };
  if (!answered) return { ...base, date: today, rows: [], drift: null };
  const drift: Drift = { unexpected: [], missing: [] };
  const miss = (name: string) => {
    if (!drift.missing.includes(name)) drift.missing.push(name);
  };
  // Money scale: from the size of the amounts; the card service is read as x100 000 when undecided.
  const priced: Record<string, unknown>[] = [];
  for (const order of orders.values()) {
    for (const item of Array.isArray(order.items) ? order.items.filter(isRecord) : []) priced.push(item);
  }
  const divisor = scaleFromMagnitude(priced, MONEY_FIELDS) ?? 100_000;
  const money = (value: unknown): number | undefined => {
    const n = num(value);
    if (n === undefined || n < 0) return undefined;
    const vnd = Math.round((n / divisor) * 100) / 100;
    return vnd > MAX_PLAUSIBLE_AD_VND ? undefined : vnd;
  };

  const rows: Row[] = [];
  const days: string[] = [];
  for (const [id, order] of orders) {
    const orderedAt = wallClock(order.create_time);
    const items = Array.isArray(order.items) ? order.items.filter(isRecord) : [];
    if (orderedAt === undefined) {
      miss("orders[].create_time");
      continue;
    }
    if (items.length === 0) {
      miss("orders[].items");
      continue;
    }
    const status = orderStatusOf(order.status ?? order.order_status);
    const lineValue = (item: Record<string, unknown>) =>
      (money(item.order_price ?? item.deal_price ?? item.item_price) ?? 0) * (num(item.amount ?? item.quantity ?? item.qty) ?? 1);
    const total = items.reduce((sum, item) => sum + lineValue(item), 0);
    const split = (value: unknown, item: Record<string, unknown>): number | undefined => {
      const amount = money(value);
      if (amount === undefined) return undefined;
      return total > 0 ? Math.round(((amount * lineValue(item)) / total) * 100) / 100 : amount / items.length;
    };
    const completedAt = wallClock(order.complete_time ?? order.completed_time ?? order.order_complete_time);
    const paidAt = wallClock(order.pay_time ?? order.paid_time);
    items.forEach((item, index) => {
      const qty = num(item.amount ?? item.quantity ?? item.qty);
      const original = money(item.original_price ?? item.price_before_discount ?? item.item_price);
      const deal = money(item.order_price ?? item.deal_price ?? item.item_price);
      if (qty === undefined || qty < 0 || original === undefined || deal === undefined) {
        miss("orders[].items[].price_or_qty");
        return;
      }
      const row: Row = {
        [RAW_ORDER_ID]: id,
        line_no: Math.min(index, 999),
        ordered_at: orderedAt,
        status,
        qty,
        original_price: original,
        deal_price: deal,
        seller_subsidy: Math.max(0, Math.round((original - deal) * qty * 100) / 100),
      };
      const sku = text(item.item_sku ?? item.sku, 120);
      const variationSku = text(item.model_sku ?? item.variation_sku, 120);
      const variationName = text(item.model_name ?? item.variation_name, 120);
      if (sku) row.sku = sku;
      if (variationSku) row.variation_sku = variationSku;
      if (variationName) row.variation_name = variationName;
      const returned = num(item.returned_qty);
      if (returned !== undefined && returned >= 0) row.returned_qty = returned;
      const shopVoucher = split(order.shop_voucher_amount ?? order.seller_voucher, item);
      const platformVoucher = split(order.shopee_voucher_amount ?? order.platform_voucher, item);
      const bundle = split(order.bundle_deal_discount ?? order.combo_discount, item);
      const shipping = split(order.buyer_paid_shipping_fee ?? order.shipping_fee_paid_by_buyer, item);
      const bank = split(order.bank_promo_amount, item);
      if (shopVoucher !== undefined) row.shop_voucher_share = shopVoucher;
      if (platformVoucher !== undefined) row.platform_voucher_share = platformVoucher;
      if (bundle !== undefined) row.bundle_discount = bundle;
      if (shipping !== undefined) row.buyer_shipping_fee = shipping;
      if (bank !== undefined) row.bank_promo = bank;
      if (completedAt) row.completed_at = completedAt;
      if (paidAt) row.paid_at = paidAt;
      rows.push(row);
      days.push(dayOf(orderedAt) as string);
    });
  }
  if (orders.size === 0) return { ...base, date: today, rows: [], drift: null };
  if (rows.length > MAX_LINES) rows.length = MAX_LINES;
  days.sort();
  const start = days[0] ?? today;
  const end = days[days.length - 1] ?? today;
  const failed = rows.length === 0 || drift.missing.length > 0 || drift.unexpected.length > 0;
  // One order missing a field must not hide the others: drift only when NOTHING mapped.
  return {
    ...base,
    date: end,
    periodStart: start,
    rows,
    drift: rows.length === 0 && failed ? drift : null,
  };
}

/**
 * Completed orders of a card answer for the income queue: `id` is the id the order page / income
 * call takes, `sn` the order number that is hashed (absent when the cards carry one id only).
 */
export function completedOrders(responses: ReaderResponse[]): { id: string; sn?: string; completedAt: number }[] {
  const out: { id: string; sn?: string; completedAt: number }[] = [];
  for (const [key, order] of collectOrders(responses)) {
    if (orderStatusOf(order.status ?? order.order_status) !== "delivered") continue;
    const t = num(order.complete_time ?? order.completed_time ?? order.order_complete_time);
    if (t === undefined || t <= 0) continue;
    const id = order.__api ?? key;
    out.push({ id, ...(key !== id ? { sn: key } : {}), completedAt: (t > 1e12 ? Math.floor(t / 1000) : t) * 1000 });
  }
  return out;
}

// -- per-order income ---------------------------------------------------------------------------

/** Vietnamese labels (diacritics stripped, lower case) -> the order_income field they fill. */
const INCOME_LABELS: [RegExp, string][] = [
  [/^gia san pham$/, "product_price"],
  [/^phi co dinh/, "fee_fixed"],
  [/^phi dich vu piship/, "fee_piship"],
  [/^phi dich vu$/, "fee_service"],
  [/^phi (xu ly giao dich|thanh toan)/, "fee_payment"],
  [/^phi van chuyen.*(nguoi mua tra|nguoi mua)/, "ship_buyer_paid"],
  [/^phi van chuyen.*(tro gia|shopee tro)/, "ship_shopee_subsidy"],
  [/^phi van chuyen.*(thuc te|uoc tinh)/, "ship_actual_cost"],
  [/^phi hoa hong lien ket|^hoa hong tiep thi/, "affiliate_commission"],
  [/^ma giam gia cua shop/, "seller_voucher_borne"],
  [/^so tien cuoi cung/, "payout"],
];
/** A cost is stored as a positive amount the seller bore; these are signed as sent. */
const SIGNED = new Set(["payout", "product_price"]);

function plain(label: string): string {
  return label
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/đ/gi, "d")
    .toLowerCase()
    .replace(/[:*]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

/** Every {label, amount} pair in an income answer, whatever the nesting (a few levels deep). */
function pairs(root: unknown, depth = 8): { label: string; amount: number }[] {
  const out: { label: string; amount: number }[] = [];
  const walk = (node: unknown, level: number): void => {
    if (Array.isArray(node)) {
      for (const item of node) walk(item, level);
      return;
    }
    if (!isRecord(node) || level > depth) return;
    const label = ["name", "title", "label", "description", "text"].map((k) => node[k]).find((v) => typeof v === "string");
    const amount = ["amount", "value", "money", "fee"].map((k) => num(node[k])).find((v) => v !== undefined);
    if (typeof label === "string" && amount !== undefined) out.push({ label, amount });
    for (const value of Object.values(node)) if (typeof value === "object" && value !== null) walk(value, level + 1);
  };
  walk(root, 0);
  return out;
}

export function mapOrderIncome(responses: ReaderResponse[], capturedAt: number): Mapped {
  const today = gmt7Date(Math.floor(capturedAt / 1000));
  const base = { dataset: "order_income" as const, endpoint: "seller_income/get_order_income_components", orderType: null, granularity: "period" as const };
  const answers = responses.filter((r) => r.endpoint === "order_income_components" && classify(r.status, r.body) === "ok" && r.orderId);
  if (answers.length === 0) return { ...base, date: today, rows: [], drift: null };
  // One scale for the whole job, read from the sizes of the product prices and payouts.
  const sample = answers.flatMap((r) =>
    pairs(payloadOf(r.body))
      .filter((p) => /^(gia san pham|so tien cuoi cung)$/.test(plain(p.label)))
      .map((p) => ({ v: Math.abs(p.amount) })),
  );
  const divisor = scaleFromMagnitude(sample, ["v"]) ?? 1;
  const rows: Row[] = [];
  const drift: Drift = { unexpected: [], missing: [] };
  for (const response of answers) {
    // The hashed id is the order number when the queue knew it (joins the export and the affiliate lines).
    const row: Row = { [RAW_ORDER_ID]: response.orderSn ?? response.orderId };
    for (const { label, amount } of pairs(payloadOf(response.body))) {
      const key = plain(label);
      const field = INCOME_LABELS.find(([re]) => re.test(key))?.[1];
      if (field === undefined || field in row) continue;
      const vnd = Math.round((amount / divisor) * 100) / 100;
      row[field] = SIGNED.has(field) ? vnd : Math.abs(vnd);
    }
    if (!("payout" in row)) {
      if (!drift.missing.includes("components.final_amount")) drift.missing.push("components.final_amount");
      continue; // "Ước tính" until the order completes: no final amount, nothing to post yet
    }
    rows.push(row);
  }
  const end = today;
  return {
    ...base,
    date: end,
    periodStart: end,
    rows,
    // One order without a final amount is skipped; drift only when none of the answers had one.
    drift: rows.length === 0 && drift.missing.length > 0 ? drift : null,
  };
}
