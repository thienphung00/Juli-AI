// Pure mapping of the affiliate ("Tăng Đơn Cùng KOL") reader answers → ingest posts (Connector
// 0.3.6; recon 2026-11-06, field names only). Same policy as reader-map.ts: an unexpected field
// is not drift; a missing identity field, an unknown period or an implausible money scale is
// drift (dataset stopped, nothing posted). Buyer data never leaves the page (reader.ts trims it);
// the order id leaves the mapper only as `__order_id__`, which the service worker replaces by
// `order_ref` (the shop's keyed hash) before posting — a row still carrying it is never sent.

import { AFFILIATE_MIN_PLAUSIBLE_VND, AFFILIATE_MONEY_DIVISOR_FALLBACK, MAX_PLAUSIBLE_AD_VND } from "../config";
import type { Drift, Mapped, Row } from "./map";
import { classify, findList, isConversionOrder, payloadOf, type ReaderResponse } from "./reader";
import { gmt7Date } from "./time";

/** The raw order id's key on a mapped row, until the service worker hashes it. */
export const RAW_ORDER_ID = "__order_id__";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function num(value: unknown): number | undefined {
  if (typeof value === "number") return Number.isFinite(value) ? value : undefined;
  if (typeof value === "string" && value.trim() !== "" && value.trim() !== "-") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : undefined;
  }
  return undefined;
}

function nonNeg(value: unknown): number | undefined {
  const n = num(value);
  return n !== undefined && n >= 0 ? n : undefined;
}

function text(value: unknown, max: number): string | undefined {
  if (typeof value !== "string") return undefined;
  const trimmed = value.trim();
  return trimmed ? trimmed.slice(0, max) : undefined;
}

function digits(value: unknown): string | undefined {
  if (typeof value === "number" && Number.isInteger(value) && value >= 0) return String(value);
  if (typeof value === "string" && /^\d{1,32}$/.test(value)) return value;
  return undefined;
}

/** A platform enum (number or short label) as text. */
function label(value: unknown): string | undefined {
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return text(value, 64);
}

/** Unix seconds (or ms) → Seller Centre's wall clock (GMT+7), no zone suffix. */
function wallClock(value: unknown): string | undefined {
  const n = num(value);
  if (n === undefined || n <= 0) return undefined;
  const seconds = n > 1e12 ? Math.floor(n / 1000) : n;
  return new Date((seconds + 7 * 3600) * 1000).toISOString().slice(0, 19);
}

function dayOfUnix(value: unknown): string | undefined {
  return wallClock(value)?.slice(0, 10);
}

function put(row: Row, key: string, value: unknown): void {
  if (value !== undefined) row[key] = value;
}

function driftOf(unexpected: string[], missing: string[]): Drift | null {
  return unexpected.length || missing.length ? { unexpected, missing } : null;
}

function note(list: string[], value: string): void {
  if (!list.includes(value)) list.push(value);
}

function dataResponses(responses: ReaderResponse[], endpoint: string): ReaderResponse[] {
  return responses.filter((r) => r.endpoint === endpoint && classify(r.status, r.body) === "ok");
}

// -- money scale -----------------------------------------------------------------------------

/** "₫126.360" / "126.360" / "1.234,5" (Vietnamese grouping) → a number; undefined otherwise. */
export function displayNumber(value: unknown): number | undefined {
  if (typeof value !== "string") return undefined;
  let s = value.replace(/[^\d.,]/g, "");
  if (!/\d/.test(s)) return undefined;
  if (s.includes(",")) s = s.replace(/\./g, "").replace(",", ".");
  else s = s.replace(/\./g, "");
  const n = Number(s);
  return Number.isFinite(n) ? n : undefined;
}

/**
 * The divisor that turns the service's numbers into VND, read from `field` / `dis_field` pairs
 * in `rows`: 1 when they agree, 100 000 when the number is the display x 100 000. `null` when
 * the pairs disagree (drift); `undefined` when no pair says anything.
 */
export function scaleFromPairs(rows: Record<string, unknown>[], fields: readonly string[]): number | null | undefined {
  const seen = new Set<number>();
  for (const row of rows) {
    for (const field of fields) {
      const raw = nonNeg(row[field]);
      const shown = displayNumber(row[`dis_${field}`]);
      if (raw === undefined || shown === undefined || raw === 0 || shown === 0) continue;
      const ratio = raw / shown;
      if (Math.abs(ratio - 1) < 0.02) seen.add(1);
      else if (Math.abs(ratio / 100_000 - 1) < 0.02) seen.add(100_000);
      else return null;
    }
  }
  if (seen.size > 1) return null;
  return seen.size === 1 ? [...seen][0] : undefined;
}

class Money {
  constructor(
    readonly divisor: number,
    private readonly issues: { unexpected: string[] },
  ) {}

  of(value: unknown): number | undefined {
    const n = nonNeg(value);
    if (n === undefined) return undefined;
    const vnd = Math.round((n / this.divisor) * 100) / 100;
    if (vnd !== 0 && (vnd < AFFILIATE_MIN_PLAUSIBLE_VND || vnd > MAX_PLAUSIBLE_AD_VND)) {
      note(this.issues.unexpected, "affiliate:money_scale");
    }
    return vnd;
  }
}

function moneyFor(
  rows: Record<string, unknown>[],
  pairs: readonly string[],
  issues: { unexpected: string[] },
): Money {
  const scale = scaleFromPairs(rows, pairs);
  if (scale === null) note(issues.unexpected, "affiliate:money_scale");
  return new Money(scale ?? AFFILIATE_MONEY_DIVISOR_FALLBACK, issues);
}

/** A ratio sent as 0..1, as a percent (0..100) or in basis points (0..10 000) → 0..1. */
function rate(value: unknown): number | undefined {
  const n = nonNeg(value);
  if (n === undefined) return undefined;
  if (n <= 1) return n;
  if (n <= 100) return Math.round((n / 100) * 1e6) / 1e6;
  if (n <= 10_000) return Math.round((n / 10_000) * 1e6) / 1e6;
  return undefined;
}

function empty(dataset: Mapped["dataset"], endpoint: string, date: string, drift: Drift | null): Mapped {
  return { dataset, endpoint, date, orderType: null, granularity: "period", rows: [], drift };
}

function post(
  dataset: Mapped["dataset"],
  endpoint: string,
  period: { start: string; end: string },
  rows: Row[],
  drift: Drift | null,
): Mapped {
  return {
    dataset,
    endpoint,
    date: period.end,
    periodStart: period.start,
    orderType: null,
    granularity: "period",
    rows: drift ? [] : rows,
    drift,
  };
}

const todayOf = (capturedAt: number) => gmt7Date(Math.floor(capturedAt / 1000));

// -- 1. conversion report → affiliate_order_lines ----------------------------------------------

export function mapAffiliateConversions(responses: ReaderResponse[], capturedAt: number): Mapped {
  const answers = dataResponses(responses, "affiliate_conversion");
  const period = answers.find((r) => r.period)?.period ?? { start: todayOf(capturedAt), end: todayOf(capturedAt) };
  const issues = { unexpected: [] as string[], missing: [] as string[] };
  const orders: Record<string, unknown>[] = [];
  for (const response of answers) orders.push(...(findList(payloadOf(response.body), isConversionOrder)?.list ?? []));
  const items = orders.flatMap((order) => (Array.isArray(order.items) ? order.items.filter(isRecord) : []));
  const money = moneyFor(items, ["item_price", "actual_amount", "refunded_amount"], issues);
  const rows: Row[] = [];
  const seen = new Map<string, number>();
  const orderSeen = new Set<string>();
  for (const order of orders) {
    const orderId = text(order.order_id, 64);
    const orderedAt = wallClock(order.purchase_time);
    if (orderId === undefined || orderedAt === undefined) {
      note(issues.missing, orderId === undefined ? "orders[].order_id" : "orders[].purchase_time");
      continue;
    }
    if (orderSeen.has(orderId)) continue; // the same order on two pages
    orderSeen.add(orderId);
    for (const item of Array.isArray(order.items) ? order.items.filter(isRecord) : []) {
      const itemId = digits(item.item_id);
      if (itemId === undefined) {
        note(issues.missing, "orders[].items[].item_id");
        continue;
      }
      const modelId = digits(item.model_id) ?? "";
      const twin = `${orderId}|${itemId}|${modelId}`;
      const lineNo = seen.get(twin) ?? 0;
      seen.set(twin, lineNo + 1);
      const row: Row = { [RAW_ORDER_ID]: orderId, line_no: lineNo, affiliate: true, item_id: itemId, ordered_at: orderedAt };
      if (modelId) row.model_id = modelId;
      put(row, "price", money.of(item.item_price));
      put(row, "qty", nonNeg(item.qty));
      put(row, "order_value", money.of(item.actual_amount));
      put(row, "refund_amount", money.of(item.refunded_amount));
      put(row, "cost", money.of(item.expense));
      put(row, "order_status", text(order.order_status, 64));
      put(row, "completed_at", wallClock(order.order_complete_time));
      put(row, "conversion_at", wallClock(order.conversion_complete_time));
      // The creator's public login handle (not the display name, not a buyer).
      put(row, "affiliate_account", text(order.shopee_username, 120));
      put(row, "mcn", text(order.linked_mcn_name, 120));
      put(row, "campaign_type", label(item.campaign_type));
      put(row, "channel", label(order.traffic_type));
      put(row, "deduction_status", label(item.ams_deduction_status));
      put(row, "deduction_method", label(item.ams_deduction_method));
      put(row, "deducted_at", wallClock(item.ams_deduction_time));
      rows.push(row);
    }
  }
  if (answers.length === 0) return empty("affiliate_order_lines", "affiliateplatform/conversion", period.end, null);
  return post("affiliate_order_lines", "affiliateplatform/conversion", period, rows, driftOf(issues.unexpected, issues.missing));
}

// -- 2. Phân tích Tăng đơn cùng KOL → affiliate_partner_period ---------------------------------

function captured(
  responses: ReaderResponse[],
  endpoint: string,
  dataset: Mapped["dataset"],
  capturedAt: number,
): { response: ReaderResponse; period: { start: string; end: string } } | Mapped {
  const response = dataResponses(responses, endpoint)[0];
  if (!response) return empty(dataset, endpoint, todayOf(capturedAt), null);
  if (!response.period) return empty(dataset, endpoint, todayOf(capturedAt), { unexpected: [], missing: ["period"] });
  return { response, period: response.period };
}

const isKol = (o: Record<string, unknown>) => "affiliate_id" in o && ("gmv" in o || "orders" in o);

export function mapAffiliatePartners(responses: ReaderResponse[], capturedAt: number): Mapped {
  const got = captured(responses, "affiliate_performance", "affiliate_partner_period", capturedAt);
  if ("dataset" in got) return got;
  const issues = { unexpected: [] as string[], missing: [] as string[] };
  const list = findList(payloadOf(got.response.body), isKol)?.list ?? [];
  const money = moneyFor(list, ["gmv", "est_commission"], issues);
  const rows: Row[] = [];
  for (const kol of list) {
    const id = digits(kol.affiliate_id);
    if (id === undefined) {
      note(issues.missing, "list[].affiliate_id");
      continue;
    }
    const row: Row = { affiliate_id: id };
    put(row, "account", text(kol.shopee_username, 120));
    put(row, "sales", money.of(kol.gmv));
    put(row, "orders", nonNeg(kol.orders));
    put(row, "units", nonNeg(kol.item_sold));
    put(row, "clicks", nonNeg(kol.clicks));
    put(row, "buyers", nonNeg(kol.total_buyers));
    put(row, "new_buyers", nonNeg(kol.new_buyers));
    put(row, "est_commission", money.of(kol.est_commission));
    const roi = nonNeg(kol.roi);
    put(row, "roi", roi !== undefined && roi <= 100_000 ? roi : undefined);
    const extra: Record<string, number> = {};
    const actual = money.of(kol.actual_commission);
    if (actual !== undefined) extra.actual_commission = actual;
    const conversion = rate(kol.conversion_rate);
    if (conversion !== undefined) extra.conversion_rate = conversion;
    if (Object.keys(extra).length) row.extra = extra;
    rows.push(row);
  }
  return post("affiliate_partner_period", "affiliateplatform/affiliate_performance", got.period, rows, driftOf(issues.unexpected, issues.missing));
}

// -- 3. Dữ liệu phân tích chính → affiliate_shop_period (one post per day, plus the split) -------

export function mapAffiliateShop(responses: ReaderResponse[], capturedAt: number): Mapped[] {
  const response = dataResponses(responses, "affiliate_seller_daily")[0];
  if (!response) return [empty("affiliate_shop_period", "affiliateplatform/seller_daily", todayOf(capturedAt), null)];
  const issues = { unexpected: [] as string[], missing: [] as string[] };
  const payload = payloadOf(response.body);
  const days = findList(payload, (o) => "ymd" in o)?.list ?? [];
  const money = moneyFor(days, ["actual_amount", "seller_gross_commission", "actual_commission"], issues);
  const out: Mapped[] = [];
  const dayRow = (source: Record<string, unknown>): Row => {
    const row: Row = {};
    put(row, "sales", money.of(source.actual_amount));
    put(row, "orders", nonNeg(source.order_count));
    put(row, "units", nonNeg(source.gross_item_sold));
    put(row, "clicks", nonNeg(source.clicks));
    put(row, "buyers", nonNeg(source.total_buyers));
    put(row, "new_buyers", nonNeg(source.new_buyers));
    put(row, "est_commission", money.of(source.seller_gross_commission));
    put(row, "actual_commission", money.of(source.actual_commission));
    const roi = nonNeg(source.roi);
    put(row, "roi", roi !== undefined && roi <= 100_000 ? roi : undefined);
    return row;
  };
  for (const day of days) {
    const ymd = String(day.ymd ?? "");
    const date = /^\d{8}$/.test(ymd) ? `${ymd.slice(0, 4)}-${ymd.slice(4, 6)}-${ymd.slice(6, 8)}` : /^\d{4}-\d{2}-\d{2}$/.test(ymd) ? ymd : undefined;
    if (!date) {
      note(issues.missing, "list[].ymd");
      continue;
    }
    out.push(post("affiliate_shop_period", "affiliateplatform/seller_daily", { start: date, end: date }, [dayRow(day)], null));
  }
  const split = isRecord(payload) && isRecord(payload.seller_attribution_breakdown) ? payload.seller_attribution_breakdown : null;
  if (split && response.period) {
    const row: Row = {};
    put(row, "direct_orders", nonNeg(split.direct_orders));
    put(row, "indirect_orders", nonNeg(split.indirect_orders));
    put(row, "direct_sales", money.of(split.direct_order_amount));
    put(row, "indirect_sales", money.of(split.indirect_order_amount));
    const single = response.period.start === response.period.end;
    const sameDay = single ? out.find((m) => m.date === response.period?.end) : undefined;
    if (sameDay) Object.assign(sameDay.rows[0] as Row, row);
    else if (Object.keys(row).length) out.push(post("affiliate_shop_period", "affiliateplatform/seller_daily", response.period, [row], null));
  }
  const drift = driftOf(issues.unexpected, issues.missing);
  if (drift) return [empty("affiliate_shop_period", "affiliateplatform/seller_daily", todayOf(capturedAt), drift)];
  return out;
}

// -- 4. Phân tích sản phẩm → affiliate_product_period --------------------------------------------

export function mapAffiliateProducts(responses: ReaderResponse[], capturedAt: number): Mapped {
  const got = captured(responses, "affiliate_item_detail", "affiliate_product_period", capturedAt);
  if ("dataset" in got) return got;
  const issues = { unexpected: [] as string[], missing: [] as string[] };
  const list = findList(payloadOf(got.response.body), (o) => "item_id" in o && ("gmv" in o || "orders" in o))?.list ?? [];
  const money = moneyFor(list, ["gmv", "price", "spend"], issues);
  const rows: Row[] = [];
  for (const item of list) {
    const id = digits(item.item_id);
    if (id === undefined) {
      note(issues.missing, "list[].item_id");
      continue;
    }
    const row: Row = { item_id: id };
    put(row, "price", money.of(item.price));
    put(row, "sales", money.of(item.gmv));
    put(row, "units", nonNeg(item.sale));
    put(row, "orders", nonNeg(item.orders));
    put(row, "clicks", nonNeg(item.clicks));
    put(row, "buyers", nonNeg(item.total_buyers));
    put(row, "new_buyers", nonNeg(item.new_buyers));
    // "spend" is what the programme charged for the product's affiliate orders.
    put(row, "est_commission", money.of(item.spend));
    const roi = nonNeg(item.roi);
    put(row, "roi", roi !== undefined && roi <= 100_000 ? roi : undefined);
    rows.push(row);
  }
  return post("affiliate_product_period", "affiliateplatform/seller_item_detail", got.period, rows, driftOf(issues.unexpected, issues.missing));
}

// -- 5. Chiến dịch mở rộng → affiliate_shop_campaigns (a snapshot of the capture day) -----------

export function mapAffiliateCampaigns(responses: ReaderResponse[], capturedAt: number): Mapped {
  const today = todayOf(capturedAt);
  const response = dataResponses(responses, "affiliate_shop_campaign")[0];
  if (!response) return empty("affiliate_shop_campaigns", "affiliateplatform/GetShopCampaign", today, null);
  const issues = { unexpected: [] as string[], missing: [] as string[] };
  const list = findList(payloadOf(response.body), (o) => "commissionId" in o, 6)?.list ?? [];
  const money = moneyFor(list, ["budget"], issues);
  const rows: Row[] = [];
  for (const campaign of list) {
    const id = digits(campaign.commissionId);
    const name = text(campaign.commissionName, 255);
    if (id === undefined || name === undefined) {
      note(issues.missing, id === undefined ? "shopCampaigns[].commissionId" : "shopCampaigns[].commissionName");
      continue;
    }
    const row: Row = { campaign_id: id, campaign_name: name };
    put(row, "commission_rate", rate(campaign.commissionRate));
    put(row, "status", label(campaign.commissionStatus));
    put(row, "starts_on", dayOfUnix(campaign.periodStartTime));
    put(row, "ends_on", dayOfUnix(campaign.periodEndTime));
    put(row, "budget", money.of(campaign.budget));
    rows.push(row);
  }
  return post("affiliate_shop_campaigns", "affiliateplatform/GetShopCampaign", { start: today, end: today }, rows, driftOf(issues.unexpected, issues.missing));
}

// -- 6. Phân tích chiến dịch → affiliate_commission_period ----------------------------------------

export function mapAffiliateCommissions(responses: ReaderResponse[], capturedAt: number): Mapped {
  const got = captured(responses, "affiliate_commission_list", "affiliate_commission_period", capturedAt);
  if ("dataset" in got) return got;
  const issues = { unexpected: [] as string[], missing: [] as string[] };
  const list = findList(payloadOf(got.response.body), (o) => "commissionId" in o, 6)?.list ?? [];
  const money = moneyFor(list, ["orderAmount", "estCommission"], issues);
  const rows: Row[] = [];
  for (const entry of list) {
    const id = digits(entry.commissionId);
    if (id === undefined) {
      note(issues.missing, "list[].commissionId");
      continue;
    }
    const row: Row = { campaign_id: id };
    put(row, "item_id", digits(entry.itemId));
    put(row, "kols", nonNeg(entry.affiliates));
    put(row, "units", nonNeg(entry.itemSold));
    put(row, "sales", money.of(entry.orderAmount));
    put(row, "est_commission", money.of(entry.estCommission));
    rows.push(row);
  }
  return post("affiliate_commission_period", "affiliateplatform/QueryCommissionList", got.period, rows, driftOf(issues.unexpected, issues.missing));
}

// -- 7. Phân tích Nội dung → affiliate_content_period (the summary; the list is not pinned) -----

export function mapAffiliateContent(responses: ReaderResponse[], capturedAt: number): Mapped {
  const got = captured(responses, "affiliate_content_summary", "affiliate_content_period", capturedAt);
  if ("dataset" in got) return got;
  const issues = { unexpected: [] as string[], missing: [] as string[] };
  const queue: unknown[] = [payloadOf(got.response.body)];
  let summary: Record<string, unknown> | undefined;
  while (queue.length && !summary) {
    const node = queue.shift();
    if (!isRecord(node)) continue;
    if ("gmv" in node && ("views" in node || "contentsCount" in node)) summary = node;
    else queue.push(...Object.values(node));
  }
  if (!summary) return empty("affiliate_content_period", "affiliateplatform/QuerySellerContentSummaryQuery", got.period.end, null);
  const money = moneyFor([summary], ["gmv", "gpm"], issues);
  const row: Row = {};
  put(row, "sales", money.of(summary.gmv));
  put(row, "units", nonNeg(summary.itemSold));
  put(row, "orders", nonNeg(summary.orders));
  put(row, "contents", nonNeg(summary.contentsCount));
  put(row, "views", nonNeg(summary.views));
  put(row, "likes", nonNeg(summary.likes));
  put(row, "comments", nonNeg(summary.comments));
  put(row, "gpm", money.of(summary.gpm));
  return post("affiliate_content_period", "affiliateplatform/QuerySellerContentSummaryQuery", got.period, [row], driftOf(issues.unexpected, issues.missing));
}

// -- 8. Báo cáo đối soát → affiliate_bill_period (one post per bill month) ----------------------

export function mapAffiliateBills(responses: ReaderResponse[], capturedAt: number): Mapped[] {
  const today = todayOf(capturedAt);
  const response = dataResponses(responses, "affiliate_validation")[0];
  if (!response) return [empty("affiliate_bill_period", "affiliateplatform/validation", today, null)];
  const issues = { unexpected: [] as string[], missing: [] as string[] };
  const list = findList(payloadOf(response.body), (o) => "validation_id" in o)?.list ?? [];
  const bills = list.map((b) => (isRecord(b.online_bill) ? b.online_bill : {}));
  const money = moneyFor(bills, ["commission_amount", "deducted_amount", "pending_amount"], issues);
  const out: Mapped[] = [];
  for (const bill of list) {
    const code = digits(bill.validation_id) ?? text(bill.validation_id, 64);
    const month = String(bill.validation_month ?? "");
    const m = /^(\d{4})-?(\d{2})/.exec(month);
    if (code === undefined || !m) {
      note(issues.missing, code === undefined ? "list[].validation_id" : "list[].validation_month");
      continue;
    }
    const start = `${m[1]}-${m[2]}-01`;
    const last = new Date(Date.UTC(Number(m[1]), Number(m[2]), 0)).toISOString().slice(0, 10);
    const end = last < today ? last : today;
    if (start > end) continue;
    const online = isRecord(bill.online_bill) ? bill.online_bill : {};
    const row: Row = { bill_code: code };
    put(row, "commission", money.of(online.commission_amount));
    put(row, "total_deduction", money.of(online.deducted_amount));
    put(row, "pending_amount", money.of(online.pending_amount));
    out.push(post("affiliate_bill_period", "affiliateplatform/validation", { start, end }, [row], null));
  }
  const drift = driftOf(issues.unexpected, issues.missing);
  if (drift) return [empty("affiliate_bill_period", "affiliateplatform/validation", today, drift)];
  return out;
}

/** The posts of one affiliate reader job. */
export function mapAffiliateJob(id: string, responses: ReaderResponse[], capturedAt: number): Mapped[] | null {
  switch (id) {
    case "affiliate":
      return [mapAffiliateConversions(responses, capturedAt)];
    case "affiliate_kols":
      return [mapAffiliatePartners(responses, capturedAt)];
    case "affiliate_dashboard":
      return mapAffiliateShop(responses, capturedAt);
    case "affiliate_products":
      return [mapAffiliateProducts(responses, capturedAt)];
    case "affiliate_campaigns":
      return [mapAffiliateCampaigns(responses, capturedAt)];
    case "affiliate_commissions":
      return [mapAffiliateCommissions(responses, capturedAt)];
    case "affiliate_content":
      return [mapAffiliateContent(responses, capturedAt)];
    case "affiliate_bills":
      return mapAffiliateBills(responses, capturedAt);
    default:
      return null;
  }
}
