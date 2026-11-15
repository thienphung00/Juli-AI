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
    for (const key of SUB_ITEM_LISTS) {
      const list = item[key];
      if (Array.isArray(list) && list.some(isRecord)) {
        out.sub_items = list.filter(isRecord).map((sub) => trimItem(sub, depth + 1));
        break;
      }
    }
  }
  return out;
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
      if (key !== undefined && !orders.has(key)) {
        orders.set(key, { ...order, ...(api !== undefined ? { __api: api } : {}), ...(detail ? { __detail: true } : {}) });
      }
    }
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
      const original =
        money(item.original_price ?? item.price_before_discount ?? item.item_price) ??
        (order.__detail ? (singleUnit !== undefined && deal !== undefined && singleUnit >= deal ? singleUnit : deal) : undefined);
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
      if (Object.keys(extra).length > 0) row.extra = extra;
      if ((num(item.bundle_deal_id) ?? 0) > 0) row.promo_kind = "bundle";
      else if ((num(item.add_on_deal_id) ?? 0) > 0) row.promo_kind = "add_on";
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
