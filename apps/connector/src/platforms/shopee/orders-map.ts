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
// 0.3.20 (captured 2026-11-15, ORY, field names only): the list page no longer calls the two list
// endpoints (it loads through Shopee's DRM bundle). The reader takes the order ids from the list
// page's links and reads each order with GET /api/v3/order/get_one_order (`{code, data:{order}}`):
// data.order_id / order_sn / status / status_info.status (Vietnamese text) / create_time /
// complete_time, money as whole-dong strings, data.order_items[] with item_id, model_id, amount,
// order_price, item_model{sku, name, model_id}, product{sku}, line_item_id and the combo lists
// (bundle_deal_model / bundle_deal_product / item_list). `trimOrderDetail` is the same allowlist.
//
// TODO(first capture, ORY, one order list page and one order page): the card / income shapes below
// are the recon's field NAMES arranged by the usual Seller Centre conventions, not a captured body.
// Check: (1) the card list key and the per-card item list; (2) `status` as text or number;
// (3) money scale (read from the answer by magnitude, else x100 000 for cards, x1 for income);
// (4) which label strings the income components use. Unknown extra fields never stop a dataset;
// a missing identity field (order id, time, items) is drift.

import { MAX_PLAUSIBLE_AD_VND } from "./config";
import { RAW_ORDER_ID, scaleFromMagnitude } from "./affiliate-map";
import type { Drift, Mapped, Row } from "./map";
import { classify, findList, payloadOf, type ReaderResponse } from "./reader";
import { gmt7Date } from "../../core/time";

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
  // get_one_order (0.3.20): the order-level price before discount (whole dong).
  "price_before_discount",
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
  // get_one_order (0.3.20)
  "line_item_id",
  "add_on_deal_id",
  "bundle_deal_id",
  // batch-1124-a S1 (P-S2, 24/11): the Mua Kèm Deal Sốc add-on line's own flag
  "is_add_on_sub_item",
]);
const ITEM_LISTS = ["order_items", "items", "item_list", "model_list", "order_item_list"] as const;
/** A combo line's own lines (get_one_order): empty for a plain item. */
const SUB_ITEM_LISTS = ["bundle_deal_model", "bundle_deal_product", "item_list"] as const;
const ORDER_NODES = ["order_card", "card", "order", "order_info", "order_ext_info"] as const;

function keep(source: Record<string, unknown>, allowed: ReadonlySet<string>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(source)) {
    if (allowed.has(key) && (value === null || typeof value !== "object")) out[key] = value;
  }
  return out;
}

/**
 * One line with only allowlisted keys. Nested objects never pass whole: `item_model` gives its
 * variation SKU, variation name and model id, `product` only its SKU (its name is dropped); a
 * combo's sub-lines (one level) come along as `sub_items`, trimmed the same way.
 */
function trimItem(item: Record<string, unknown>, depth = 0): Record<string, unknown> {
  const out = keep(item, ITEM_KEEP);
  const model = isRecord(item.item_model) ? item.item_model : undefined;
  if (model) {
    if (typeof model.sku === "string" && out.model_sku === undefined) out.model_sku = model.sku;
    if (typeof model.name === "string" && out.model_name === undefined) out.model_name = model.name;
    if (out.model_id === undefined && (typeof model.model_id === "number" || typeof model.model_id === "string")) out.model_id = model.model_id;
  }
  const product = isRecord(item.product) ? item.product : undefined;
  if (product && typeof product.sku === "string" && out.item_sku === undefined) out.item_sku = product.sku;
  if (depth === 0) {
    // batch-1124-b CONN (P-CONN capture, 24/11): a combo's own lines are `item_list[]` (item id,
    // model id, quantity; no price, no SKU). Their SKUs are on `bundle_deal_model[]` (the variation
    // SKU + Phân loại, like `item_model`) and `bundle_deal_product[]` (the product SKU, like
    // `product`), joined by model id. An answer without `item_list` keeps the first list (0.3.20).
    const key = Array.isArray(item.item_list) && item.item_list.some(isRecord) ? "item_list" : SUB_ITEM_LISTS.find((k) => Array.isArray(item[k]) && (item[k] as unknown[]).some(isRecord));
    if (key) {
      const subs = (item[key] as unknown[]).filter(isRecord).map((sub) => trimItem(sub, depth + 1));
      if (key === "item_list") for (const sub of subs) withComboSkus(sub, item);
      out.sub_items = subs;
    }
  }
  return out;
}

/** A positive id as text (0 is Shopee's "none"), for the model-id join of a combo's lists. */
const joinId = (value: unknown): string | undefined => {
  const id = idOf(value);
  return id !== undefined && id !== "0" ? id : undefined;
};

/** One combo sub-line (`item_list` entry, trimmed) with the SKUs its model id has on the combo's lists. */
function withComboSkus(sub: Record<string, unknown>, parent: Record<string, unknown>): void {
  const modelId = joinId(sub.model_id);
  if (modelId === undefined) return;
  const entry = (list: unknown) => (Array.isArray(list) ? list.filter(isRecord).find((m) => joinId(m.model_id) === modelId) : undefined);
  const model = entry(parent.bundle_deal_model);
  if (model) {
    if (typeof model.sku === "string" && model.sku.trim() !== "" && sub.model_sku === undefined) sub.model_sku = model.sku;
    if (typeof model.name === "string" && model.name.trim() !== "" && sub.model_name === undefined) sub.model_name = model.name;
  }
  const product = entry(parent.bundle_deal_product);
  if (product && typeof product.sku === "string" && product.sku.trim() !== "" && sub.item_sku === undefined) sub.item_sku = product.sku;
}

/** One order record (flattened from its wrappers) with only allowlisted keys. */
function trimOrder(card: Record<string, unknown>): Record<string, unknown> {
  const merged: Record<string, unknown> = { ...card };
  for (const node of ORDER_NODES) if (isRecord(card[node])) Object.assign(merged, card[node]);
  const out = keep(merged, ORDER_KEEP);
  // The status as Seller Centre shows it ("Đã giao cho ĐVVC"): text only, never the whole object.
  for (const node of ["status_info", "status_info_v2"]) {
    const info = merged[node];
    if (isRecord(info) && typeof info.status === "string" && out.status_text === undefined) out.status_text = info.status.slice(0, 80);
  }
  for (const listKey of ITEM_LISTS) {
    const list = merged[listKey];
    if (Array.isArray(list)) {
      out.items = list.filter(isRecord).map((item) => trimItem(item));
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

/**
 * One get_one_order answer (0.3.20): the order with allowlisted keys only (PII dropped in the
 * page: no address, buyer, remark, tracking). `data` is null when the answer holds no order.
 */
export function trimOrderDetail(body: unknown): unknown {
  const data = payloadOf(body);
  const order = isRecord(data) && isOrderRecord(data) ? data : null;
  const code = isRecord(body) ? (body.code ?? body.error) : undefined;
  return { code, data: order ? trimOrder(order) : null };
}

// -- order lines --------------------------------------------------------------------------------

/** 0.3.19: the order list catches up by date (up to 40 pages of 40 orders): room for every line. */
const MAX_LINES = 10_000;
const MONEY_FIELDS = ["item_price", "original_price", "order_price", "deal_price", "price_before_discount"] as const;

type OrderStatusName = "delivered" | "cancelled" | "in_transit" | "refunded_accepted" | "refunded_not_received";

/**
 * Seller Centre's status as text or number -> the contract-10 value. Unknown = in_transit (not
 * counted as sold). 0.3.20: the order page's Vietnamese text ("Đã giao cho ĐVVC" is handed to the
 * carrier, not delivered; "Hoàn thành" is complete, not a refund).
 */
export function orderStatusOf(value: unknown): OrderStatusName {
  const t = typeof value === "string" ? value.normalize("NFC").toLowerCase() : "";
  if (/cancel|hủy|huỷ|huy/.test(t)) return "cancelled";
  if (/refund|return|trả hàng|hoàn tiền|tra hang|hoan tien/.test(t)) {
    return /accept|done|complete|thành công|đã hoàn tiền|chấp nhận/.test(t) ? "refunded_accepted" : "refunded_not_received";
  }
  if (/đvvc|dvvc|đang giao|chờ giao|chờ lấy|vận chuyển|shipping|shipped|transit/.test(t)) return "in_transit";
  if (/complete|deliver|hoàn thành|đã giao|đã nhận/.test(t)) return "delivered";
  return "in_transit";
}

/** An order's status: the shown text first, then the code; a completion time means delivered. */
function statusOfOrder(order: Record<string, unknown>): OrderStatusName {
  const text = order.status_text ?? (typeof order.status === "string" ? order.status : order.order_status);
  if (typeof text === "string" && text.trim() !== "") return orderStatusOf(text);
  const completed = num(order.complete_time ?? order.completed_time ?? order.order_complete_time);
  if (completed !== undefined && completed > 0) return "delivered";
  return orderStatusOf(order.status ?? order.order_status);
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
type CollectedOrder = Record<string, unknown> & { __api?: string; __detail?: boolean };

const ORDER_ENDPOINTS = new Set(["order_cards", "order_detail"]);

function collectOrders(responses: ReaderResponse[]): Map<string, CollectedOrder> {
  const orders = new Map<string, CollectedOrder>();
  for (const response of responses) {
    if (!ORDER_ENDPOINTS.has(response.endpoint) || classify(response.status, response.body) !== "ok") continue;
    const payload = payloadOf(response.body);
    const detail = response.endpoint === "order_detail";
    const list = detail
      ? isRecord(payload) && isOrderRecord(payload)
        ? [payload]
        : []
      : (findList(payload, isOrderRecord, 5)?.list ?? []);
    for (const order of list) {
      const sn = idOf(order.order_sn);
      const api = idOf(order.order_id);
      const key = sn ?? api;
      // a2 C-A2: an order's get_one_order answer replaces its card (it names the combo's lines)
      if (key !== undefined && (!orders.has(key) || (detail && !orders.get(key)!.__detail))) {
        orders.set(key, { ...order, ...(api !== undefined ? { __api: api } : {}), ...(detail ? { __detail: true } : {}) });
      }
    }
  }
  // a card keyed by order_id only and its detail keyed by order_sn are one order. 0.3.34 (C-H3): the
  // detail's lines REPLACE the card's under the card's key, so the order keeps the order_ref its
  // card lines were (or will be) posted with: one set of lines, never the card's beside the detail's.
  const detailKeyOf = new Map<string, string>();
  for (const [key, order] of orders) if (order.__detail && order.__api !== undefined) detailKeyOf.set(order.__api, key);
  for (const [key, order] of [...orders]) {
    if (order.__detail || order.__api === undefined) continue;
    const detailKey = detailKeyOf.get(order.__api);
    if (detailKey === undefined || detailKey === key) continue;
    orders.set(key, orders.get(detailKey) as CollectedOrder);
    orders.delete(detailKey);
  }
  return orders;
}

/** The lines an order is posted as: a combo line with priced sub-lines is posted as those (0.3.20). */
function linesOf(order: Record<string, unknown>): Record<string, unknown>[] {
  const items = Array.isArray(order.items) ? order.items.filter(isRecord) : [];
  return items.flatMap((item) => {
    const subs = Array.isArray(item.sub_items) ? item.sub_items.filter(isRecord) : [];
    const priced = (sub: Record<string, unknown>) =>
      (sub.item_id !== undefined || sub.model_id !== undefined) &&
      num(sub.order_price ?? sub.deal_price ?? sub.item_price) !== undefined &&
      num(sub.amount ?? sub.quantity ?? sub.qty) !== undefined;
    return subs.length > 0 && subs.every(priced) ? subs.map((sub) => ({ ...sub, ...(item.bundle_deal_id !== undefined ? { bundle_deal_id: item.bundle_deal_id } : {}) })) : [item];
  });
}

/** The order is still waiting for the buyer's payment (not yet a confirmed order). */
export function awaitingPayment(order: Record<string, unknown>): boolean {
  const t = String(order.status_text ?? (typeof order.status === "string" ? order.status : "") ?? "").toLowerCase();
  return /chờ thanh toán|cho thanh toan|unpaid|to_pay|waiting.?payment/.test(t);
}

export function mapOrderLines(responses: ReaderResponse[], capturedAt: number): Mapped {
  const today = gmt7Date(Math.floor(capturedAt / 1000));
  const orders = collectOrders(responses);
  const answered = responses.some((r) => ORDER_ENDPOINTS.has(r.endpoint) && classify(r.status, r.body) === "ok");
  const viaDetail = responses.some((r) => r.endpoint === "order_detail");
  const base = {
    dataset: "order_lines" as const,
    endpoint: viaDetail ? "order/get_one_order" : "order/get_order_list_card_list",
    orderType: null,
    granularity: "period" as const,
  };
  if (!answered) return { ...base, date: today, rows: [], drift: null };
  const drift: Drift = { unexpected: [], missing: [] };
  const miss = (name: string) => {
    if (!drift.missing.includes(name)) drift.missing.push(name);
  };
  // Money scale: from the size of the amounts; the card service is read as x100 000 when undecided.
  // get_one_order answers are whole dong (scale 1, captured 2026-11-15).
  const priced: Record<string, unknown>[] = [];
  for (const order of orders.values()) {
    if (order.__detail) continue;
    for (const item of Array.isArray(order.items) ? order.items.filter(isRecord) : []) priced.push(item);
  }
  const cardDivisor = scaleFromMagnitude(priced, MONEY_FIELDS) ?? 100_000;
  let divisor = cardDivisor;
  const money = (value: unknown): number | undefined => {
    const n = num(value);
    if (n === undefined || n < 0) return undefined;
    const vnd = Math.round((n / divisor) * 100) / 100;
    return vnd > MAX_PLAUSIBLE_AD_VND ? undefined : vnd;
  };

  const rows: Row[] = [];
  const days: string[] = [];
  for (const [id, order] of orders) {
    divisor = order.__detail ? 1 : cardDivisor;
    const orderedAt = wallClock(order.create_time);
    const items = linesOf(order);
    if (orderedAt === undefined) {
      miss("orders[].create_time");
      continue;
    }
    if (items.length === 0) {
      miss("orders[].items");
      continue;
    }
    const status = statusOfOrder(order);
    const lineValue = (item: Record<string, unknown>) =>
      (money(item.order_price ?? item.deal_price ?? item.item_price) ?? 0) * (num(item.amount ?? item.quantity ?? item.qty) ?? 1);
    const total = items.reduce((sum, item) => sum + lineValue(item), 0);
    const split = (value: unknown, item: Record<string, unknown>): number | undefined => {
      const amount = money(value);
      if (amount === undefined) return undefined;
      return total > 0 ? Math.round(((amount * lineValue(item)) / total) * 100) / 100 : amount / items.length;
    };
    const completedAt = wallClock(order.complete_time ?? order.completed_time ?? order.order_complete_time);
    // get_one_order has no pay time (only `payby_date`, the deadline). Juli counts a line as
    // confirmed by `paid_at`, so an order past payment (COD included) is confirmed at its
    // creation; one still "Chờ thanh toán" (unpaid) carries none (verified on ORY 2026-11-15).
    const paidAt = wallClock(order.pay_time ?? order.paid_time) ?? (awaitingPayment(order) ? undefined : orderedAt);
    items.forEach((item, index) => {
      const qty = num(item.amount ?? item.quantity ?? item.qty);
      const deal = money(item.order_price ?? item.deal_price ?? item.item_price);
      // get_one_order: no per-line original price; a one-line order's own price before discount
      // gives it, else the line's paid price (no seller subsidy claimed).
      const single = items.length === 1 && qty !== undefined && qty > 0 ? money(order.price_before_discount) : undefined;
      const singleUnit = single !== undefined && qty ? Math.round((single / qty) * 100) / 100 : undefined;
      const isCombo = (num(item.bundle_deal_id) ?? 0) > 0;
      // batch-1124-b CONN (owner Q4): a combo line's price is its share of the combo price, and
      // its original price the same (the combo discount is bundle_discount, never seller_subsidy)
      const original =
        order.__detail && isCombo
          ? deal
          : (money(item.original_price ?? item.price_before_discount ?? item.item_price) ??
            (order.__detail ? (singleUnit !== undefined && deal !== undefined && singleUnit >= deal ? singleUnit : deal) : undefined));
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
      const extra: Row = {};
      const itemId = idOf(item.item_id);
      const modelId = idOf(item.model_id);
      if (itemId) extra.item_id = itemId;
      if (modelId) extra.model_id = modelId;
      if (isCombo) {
        row.promo_kind = "bundle";
        const bundleId = num(item.bundle_deal_id);
        if (bundleId !== undefined && Number.isSafeInteger(bundleId)) extra.bundle_deal_id = bundleId;
      }
      else if ((num(item.add_on_deal_id) ?? 0) > 0 || item.is_add_on_sub_item === true) row.promo_kind = "add_on";
      // owner Q4: the combo discount of a line = (the page's list price − its combo price) x qty;
      // unknown (not posted) until the order page has been read
      const listUnit = isCombo ? num(item[PAGE_LIST_PRICE]) : undefined;
      if (listUnit !== undefined && listUnit > 0) extra.list_price = listUnit;
      if (Object.keys(extra).length > 0) row.extra = extra;
      const returned = num(item.returned_qty);
      if (returned !== undefined && returned >= 0) row.returned_qty = returned;
      const shopVoucher = split(order.shop_voucher_amount ?? order.seller_voucher, item);
      const platformVoucher = split(order.shopee_voucher_amount ?? order.platform_voucher, item);
      const bundle = split(order.bundle_deal_discount ?? order.combo_discount, item);
      const shipping = split(order.buyer_paid_shipping_fee ?? order.shipping_fee_paid_by_buyer, item);
      const bank = split(order.bank_promo_amount, item);
      if (shopVoucher !== undefined) row.shop_voucher_share = shopVoucher;
      if (platformVoucher !== undefined) row.platform_voucher_share = platformVoucher;
      if (listUnit !== undefined && listUnit > 0) row.bundle_discount = Math.round(Math.max(0, listUnit - deal) * qty * 100) / 100;
      else if (bundle !== undefined) row.bundle_discount = bundle;
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
    const status = statusOfOrder(order);
    // A read order page (0.3.20): any order with a completion time that was not cancelled.
    if (order.__detail ? status === "cancelled" : status !== "delivered") continue;
    const t = num(order.complete_time ?? order.completed_time ?? order.order_complete_time);
    if (t === undefined || t <= 0) continue;
    const id = order.__api ?? key;
    out.push({ id, ...(key !== id ? { sn: key } : {}), completedAt: (t > 1e12 ? Math.floor(t / 1000) : t) * 1000 });
  }
  return out;
}

// -- why a run mapped 0 rows (0.3.26) -----------------------------------------------------------

/** The order-list / order-detail endpoints and the income endpoint, per job. */
const ZERO_ROW_ENDPOINTS = {
  orders: new Set(["order_search", "order_cards", "order_detail"]),
  order_income: new Set(["order_income_components"]),
} as const;

/** `http_<status>` plus `_code_<code>` when Shopee gave one: metadata only, never a message or an id. */
function failureKey(response: ReaderResponse): string {
  const body = response.body;
  const raw = isRecord(body) ? (body.code ?? body.error) : undefined;
  const code = raw === undefined || raw === null || raw === 0 || raw === "0" ? "" : String(raw).replace(/[^A-Za-z0-9_-]/g, "").slice(0, 16);
  return `http_${response.status}${code ? `_code_${code}` : ""}`;
}

/**
 * The step at which a run that mapped 0 rows came up empty, from the job's own answers (status
 * and Shopee code only): "no_list_answer" / "no_income_answer" (nothing was read),
 * "detail_failed:<http|code>x<N>" (every answer was refused; the commonest refusal and how many
 * answers were refused), else "no_mappable_order" (answers came back but held no usable order).
 */
export function zeroRowsStep(job: keyof typeof ZERO_ROW_ENDPOINTS, responses: ReaderResponse[]): string {
  const answers = responses.filter((r) => ZERO_ROW_ENDPOINTS[job].has(r.endpoint));
  if (answers.length === 0) return job === "orders" ? "no_list_answer" : "no_income_answer";
  const failed = answers.filter((r) => classify(r.status, r.body) !== "ok");
  if (failed.length < answers.length) return "no_mappable_order";
  const counts = new Map<string, number>();
  for (const r of failed) counts.set(failureKey(r), (counts.get(failureKey(r)) ?? 0) + 1);
  const [top] = [...counts.entries()].sort((a, b) => b[1] - a[1]);
  return `detail_failed:${top![0]}x${failed.length}`;
}

// -- per-order income ---------------------------------------------------------------------------

/** Vietnamese labels (diacritics stripped, lower case) -> the order_income field they fill. */
const INCOME_LABELS: [RegExp, string][] = [
  [/^gia san pham$/, "product_price"],
  [/^phi co dinh/, "fee_fixed"],
  [/^phi dich vu piship/, "fee_piship"],
  [/^phi dich vu$/, "fee_service"],
  // 0.3.29 (F4.9): the two fee columns inside Phí Dịch Vụ (the backend never adds them to fee_service)
  [/^phi ha tang/, "fee_infra"],
  [/^phi (chuong trinh )?voucher xtra/, "fee_voucher_xtra"],
  // batch-1124-a S1 (P-S3 capture 24/11): the order page names the row "Voucher Xtra" (under Phụ phí)
  [/^voucher xtra$/, "fee_voucher_xtra"],
  [/^phi (xu ly giao dich|thanh toan)/, "fee_payment"],
  [/^phi van chuyen.*(nguoi mua tra|nguoi mua)/, "ship_buyer_paid"],
  [/^phi van chuyen.*(tro gia|shopee tro)/, "ship_shopee_subsidy"],
  [/^phi van chuyen.*(thuc te|uoc tinh)/, "ship_actual_cost"],
  [/^phi hoa hong lien ket|^hoa hong tiep thi|^phi hoa hong tiep thi/, "affiliate_commission"],
  [/^ma giam gia cua shop/, "seller_voucher_borne"],
  [/^so tien cuoi cung/, "payout"],
  // 0.3.32 (C3, the order page's own "Doanh thu" block, captured 2026-11-23): its final amount
  [/^doanh thu don hang$/, "payout"],
];
/** The income answer's final amount, under the income call's label or the order page's (0.3.32). */
const FINAL_AMOUNT = /^(so tien cuoi cung|doanh thu don hang)$/;
/** a2 C-A10: an income answer (call or page) with its income lines but no final amount yet: the order is not final. */
export function incomeNotFinal(responses: ReaderResponse[]): boolean {
  return responses.some((r) => {
    if (r.endpoint !== "order_income_components" || classify(r.status, r.body) !== "ok") return false;
    const found = pairs(incomePayload(r.body));
    return found.length > 0 && !found.some((p) => FINAL_AMOUNT.test(plain(p.label)));
  });
}

/** a2 C-A10: the order page's income rows hold the final amount ("Doanh Thu Đơn Hàng"). */
export function pageIncomeFinal(items: readonly { name: string }[]): boolean {
  return items.some((i) => FINAL_AMOUNT.test(plain(i.name)));
}
/** A cost is stored as a positive amount the seller bore; these are signed as sent. */
const SIGNED = new Set(["payout", "product_price"]);

/** A label without diacritics, lower case, single-spaced (what the income labels are matched on). */
export function plainLabel(label: string): string {
  return plain(label);
}

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

/**
 * batch-1124-a S1 (P-S3): the order page's buyer-payment rows travel as `data.buyer_items`, apart
 * from the income rows: its "Mã giảm giá của Shop" is what the buyer saved, NOT the seller's cost,
 * so it must never meet INCOME_LABELS (where that label is the seller-borne voucher).
 */
const BUYER_ITEMS = "buyer_items";
/** Buyer-payment labels -> the order_income wire field (split onto the order's lines by Juli). */
const BUYER_LABELS: [RegExp, string][] = [
  [/^ma giam gia cua shop$/, "order_shop_voucher"],
  [/^shopee voucher$/, "order_platform_voucher"],
];

function incomePayload(body: unknown): unknown {
  const data = payloadOf(body);
  if (!isRecord(data) || !(BUYER_ITEMS in data)) return data;
  const { [BUYER_ITEMS]: _buyer, ...rest } = data;
  return rest;
}

function buyerPayload(body: unknown): unknown {
  const data = payloadOf(body);
  return isRecord(data) ? data[BUYER_ITEMS] : undefined;
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

/**
 * 0.3.26: the order ids (the id the income call takes) whose income answer was read: an ok answer
 * with the final amount ("Số tiền cuối cùng"). Any other sent order is retried by the scheduler.
 */
export function incomeReadIds(responses: ReaderResponse[]): Set<string> {
  const out = new Set<string>();
  for (const r of responses) {
    if (r.endpoint !== "order_income_components" || !r.orderId || classify(r.status, r.body) !== "ok") continue;
    if (pairs(incomePayload(r.body)).some((p) => FINAL_AMOUNT.test(plain(p.label)))) out.add(r.orderId);
  }
  return out;
}

export function mapOrderIncome(responses: ReaderResponse[], capturedAt: number): Mapped {
  const today = gmt7Date(Math.floor(capturedAt / 1000));
  const base = { dataset: "order_income" as const, endpoint: "seller_income/get_order_income_components", orderType: null, granularity: "period" as const };
  const answers = responses.filter((r) => r.endpoint === "order_income_components" && classify(r.status, r.body) === "ok" && r.orderId);
  if (answers.length === 0) return { ...base, date: today, rows: [], drift: null };
  // One scale for the whole job, read from the sizes of the product prices and payouts.
  const sample = answers.flatMap((r) =>
    pairs(incomePayload(r.body))
      .filter((p) => /^(gia san pham|so tien cuoi cung|doanh thu don hang)$/.test(plain(p.label)))
      .map((p) => ({ v: Math.abs(p.amount) })),
  );
  const divisor = scaleFromMagnitude(sample, ["v"]) ?? 1;
  const rows: Row[] = [];
  const drift: Drift = { unexpected: [], missing: [] };
  for (const response of answers) {
    // The hashed id is the order number when the queue knew it (joins the export and the affiliate lines).
    const row: Row = { [RAW_ORDER_ID]: response.orderSn ?? response.orderId };
    for (const { label, amount } of pairs(incomePayload(response.body))) {
      const key = plain(label);
      const field = INCOME_LABELS.find(([re]) => re.test(key))?.[1];
      if (field === undefined || field in row) continue;
      const vnd = Math.round((amount / divisor) * 100) / 100;
      row[field] = SIGNED.has(field) ? vnd : Math.abs(vnd);
    }
    for (const { label, amount } of pairs(buyerPayload(response.body))) {
      const field = BUYER_LABELS.find(([re]) => re.test(plain(label)))?.[1];
      if (field === undefined || field in row) continue;
      row[field] = Math.abs(Math.round((amount / divisor) * 100) / 100);
    }
    if (!("payout" in row)) {
      // a2 C-A10 (prod 23/11: drift "components.final_amount" from 0.3.32's income CALL): an answer
      // that has its income lines but no final amount is an order not final yet (in transit, not
      // settled): skipped, the reader says `income_not_final`. Drift stops order_income for the
      // whole version, so it is kept for an answer of another shape: no income line at all.
      const structural = response.source !== "page" && pairs(incomePayload(response.body)).length === 0;
      if (structural && !drift.missing.includes("components")) drift.missing.push("components");
      continue;
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


// -- the order page (0.3.32, C1 + C3, captured 2026-11-23) ----------------------------------------

/** One product line as the order page shows it: "Phân loại", "SKU phân loại" and the line total. */
export interface PageItem {
  variationName?: string;
  sku?: string;
  lineTotal?: number;
  /** The line's quantity as the page shows it. */
  qty?: number;
  /** batch-1124-b CONN: a combo sub-line's unit list price (before the combo discount). */
  listPrice?: number;
}

/** The line key a combo line carries its page list price under (never sent: the mapper reads it). */
export const PAGE_LIST_PRICE = "page_list_price";

const hasSku = (item: Record<string, unknown>): boolean =>
  [item.item_sku, item.sku, item.model_sku, item.variation_sku].some((v) => typeof v === "string" && v.trim() !== "");

/**
 * batch-1123-a2 C-A2: the order ids (what get_one_order takes) of card-list orders with a line that
 * names no SKU (a combo's parent row: posted as `sku:unknown`, 23/11) and no get_one_order answer
 * yet. The reader reads each with get_one_order, which names the combo's own lines.
 */
export function cardOrdersWithoutSku(responses: ReaderResponse[]): string[] {
  const detailed = new Set<string>();
  for (const response of responses) {
    if (response.endpoint !== "order_detail") continue;
    const order = payloadOf(response.body);
    const id = isRecord(order) ? idOf(order.order_id) : undefined;
    if (id) detailed.add(id);
    if (response.orderId) detailed.add(response.orderId);
  }
  const out: string[] = [];
  for (const response of responses) {
    if (response.endpoint !== "order_cards" || classify(response.status, response.body) !== "ok") continue;
    for (const order of findList(payloadOf(response.body), isOrderRecord, 5)?.list ?? []) {
      const flat = trimOrder(order);
      const items = Array.isArray(flat.items) ? flat.items.filter(isRecord) : [];
      const id = idOf(flat.order_id);
      if (!id || items.length === 0 || linesOf(flat).every(hasSku) || detailed.has(id) || out.includes(id)) continue;
      out.push(id);
    }
  }
  return out;
}

/**
 * Orders whose get_one_order answer has a line that names no SKU (a combo's parent line: posted as
 * `sku:unknown`): the order page shows each line's "SKU phân loại", so these are read there. `body`
 * is the trimmed answer (no buyer data), kept to re-post the lines with the page's SKUs.
 */
export function skuLessOrders(responses: ReaderResponse[]): { id: string; sn?: string; body: unknown }[] {
  const out: { id: string; sn?: string; body: unknown }[] = [];
  for (const response of responses) {
    if (response.endpoint !== "order_detail" || classify(response.status, response.body) !== "ok") continue;
    const order = payloadOf(response.body);
    if (!isRecord(order)) continue;
    const items = Array.isArray(order.items) ? order.items.filter(isRecord) : [];
    if (items.length === 0 || linesOf(order).every(hasSku)) continue;
    const sn = idOf(order.order_sn);
    const id = idOf(order.order_id);
    if (!id) continue;
    out.push({ id, ...(sn && sn !== id ? { sn } : {}), body: response.body });
  }
  return out;
}

/**
 * Whole cents per line for one money field: the parent's total (unit x quantity) split by `shares`,
 * each line's total a multiple of its own quantity (so its unit price stays whole cents), the cents
 * left over placed on lines whose quantity divides them. Null when the totals cannot add up exactly.
 */
function splitCents(totalCents: number, shares: number[], qtys: number[]): number[] | null {
  const out = shares.map((share, i) => Math.floor((totalCents * share) / (qtys[i] as number)) * (qtys[i] as number));
  let left = totalCents - out.reduce((a, b) => a + b, 0);
  const order = qtys.map((q, i) => i).sort((a, b) => (qtys[a] as number) - (qtys[b] as number));
  for (const i of order) {
    const q = qtys[i] as number;
    const chunks = Math.floor(left / q);
    out[i] = (out[i] as number) + chunks * q;
    left -= chunks * q;
  }
  return left === 0 ? out : null;
}

/**
 * A combo parent split into the page's lines: each line takes the page line's quantity, and every
 * money field (a unit price) is split so that Σ(unit x qty) over the lines equals the parent's
 * unit x qty exactly; the shares follow the page line totals (equal when one is missing). Null
 * when a page line shows no quantity or the money cannot add up exactly.
 */
function splitCombo(parent: Record<string, unknown>, page: readonly PageItem[]): Record<string, unknown>[] | null {
  const qtys = page.map((p) => p.qty);
  if (!qtys.every((q): q is number => q !== undefined && Number.isInteger(q) && q > 0)) return null;
  const parentQty = num(parent.amount ?? parent.quantity ?? parent.qty) ?? 1;
  const totals = page.map((p) => p.lineTotal);
  const sum = totals.reduce<number>((a, t) => a + (t ?? 0), 0);
  const byTotal = totals.every((t) => t !== undefined && t > 0) && sum > 0;
  const shares = page.map((p) => (byTotal ? (p.lineTotal as number) / sum : 1 / page.length));
  const lines: Record<string, unknown>[] = page.map((_, i) => {
    const line: Record<string, unknown> = { ...parent, amount: qtys[i] };
    delete line.quantity;
    delete line.qty;
    delete line.sub_items;
    return line;
  });
  for (const field of MONEY_FIELDS) {
    const unit = num(parent[field]);
    if (unit === undefined) continue;
    const cents = splitCents(Math.round(unit * parentQty * 100), shares, qtys);
    if (!cents) return null;
    cents.forEach((c, i) => {
      (lines[i] as Record<string, unknown>)[field] = c / 100 / (qtys[i] as number);
    });
  }
  return lines;
}

/**
 * The trimmed get_one_order answer with the order page's SKUs on the lines that had none, or null
 * when the page's lines cannot be matched:
 * - as many page lines as order lines: each SKU-less line takes the page line at its place;
 * - one order line (a combo's parent) and several page lines: the parent becomes one line per page
 *   line with the page line's quantity, its money split exactly (`splitCombo`).
 */
export function withPageSkus(body: unknown, page: readonly PageItem[]): unknown | null {
  if (!isRecord(body)) return null;
  const order = payloadOf(body);
  if (!isRecord(order) || page.length === 0) return null;
  const items = Array.isArray(order.items) ? order.items.filter(isRecord) : [];
  const named = (item: Record<string, unknown>, at: PageItem): Record<string, unknown> => {
    const out: Record<string, unknown> = { ...item };
    delete out.sub_items;
    if (at.sku) out.model_sku = at.sku;
    if (at.variationName) out.model_name = at.variationName;
    if (at.listPrice !== undefined) out[PAGE_LIST_PRICE] = at.listPrice;
    return out;
  };
  let fixed: Record<string, unknown>[] | null = null;
  const subsOf = (item: Record<string, unknown>) => (Array.isArray(item.sub_items) ? item.sub_items.filter(isRecord) : []);
  // batch-1124-b CONN: the page shows a combo as one line per sub-line (`.bundle-deal-item`), so a
  // SKU-less combo parent with N sub-lines takes the next N page lines (split exactly, each with its
  // page quantity); every other line takes one.
  const combo = (item: Record<string, unknown>) => (num(item.bundle_deal_id) ?? 0) > 0 && !hasSku(item) && subsOf(item).length > 0;
  const width = (item: Record<string, unknown>) => (combo(item) ? subsOf(item).length : 1);
  if (items.some(combo) && items.reduce((n, item) => n + width(item), 0) === page.length) {
    fixed = [];
    let at = 0;
    for (const item of items) {
      const n = width(item);
      const slice = page.slice(at, at + n);
      at += n;
      if (!combo(item)) {
        fixed.push(hasSku(item) ? item : named(item, slice[0] as PageItem));
        continue;
      }
      const lines = splitCombo(item, slice);
      if (!lines) return null;
      fixed.push(...lines.map((line, i) => fromSub(named(line, slice[i] as PageItem), subsOf(item)[i])));
    }
  } else if (items.length === page.length) {
    fixed = items.map((item, i) => (hasSku(item) ? item : named(item, page[i] as PageItem)));
  } else if (items.length === 1 && page.length > 1 && !hasSku(items[0] as Record<string, unknown>)) {
    const parent = items[0] as Record<string, unknown>;
    const lines = splitCombo(parent, page);
    const subs = subsOf(parent);
    fixed = lines ? lines.map((line, i) => (subs.length === page.length ? fromSub(named(line, page[i] as PageItem), subs[i] as Record<string, unknown>) : named(line, page[i] as PageItem))) : null;
  }
  if (!fixed || !fixed.every(hasSku)) return null;
  return { ...body, data: { ...order, items: fixed } };
}

/**
 * A combo line split from its parent, with its own sub-line's ids and the SKUs the answer gives it
 * (`bundle_deal_model` / `bundle_deal_product`, joined in the page by model id): the same fields a
 * plain line takes from `item_model` / `product`. The page's "SKU phân loại" stays only where the
 * answer names none.
 */
function fromSub(line: Record<string, unknown>, sub: Record<string, unknown> | undefined): Record<string, unknown> {
  if (!sub) return line;
  const out: Record<string, unknown> = { ...line };
  for (const key of ["item_id", "model_id", "line_item_id"] as const) if (sub[key] !== undefined) out[key] = sub[key];
  for (const key of ["model_sku", "item_sku", "model_name"] as const) {
    if (typeof sub[key] === "string" && (sub[key] as string).trim() !== "") out[key] = sub[key];
  }
  return out;
}


/** 0.3.32: the SKU a line is posted with when its order page could not name it after 3 reads. */
export const UNRESOLVED_SKU = "unresolved_item";
/** Order page reads after which a SKU-less line is posted as UNRESOLVED_SKU and no longer read. */
export const PAGE_FIX_MAX_FAILS = 3;

/** The stored answer with UNRESOLVED_SKU on every line that names no SKU (null when none lacks one). */
export function withUnresolvedSkus(body: unknown): unknown | null {
  if (!isRecord(body)) return null;
  const order = payloadOf(body);
  if (!isRecord(order)) return null;
  const items = Array.isArray(order.items) ? order.items.filter(isRecord) : [];
  if (items.every(hasSku)) return null;
  const marked = items.map((item) => {
    if (hasSku(item)) return item;
    const out: Record<string, unknown> = { ...item, model_sku: UNRESOLVED_SKU };
    delete out.sub_items;
    return out;
  });
  return { ...body, data: { ...order, items: marked } };
}
