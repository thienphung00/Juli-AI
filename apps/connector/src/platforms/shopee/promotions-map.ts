// Khuyến mãi của Shop (Connector 0.3.29, F4.7): the discount programmes' answers -> `promotion_daily`
// (one row per day: the shop's discount programmes together) and `promotions` (one row per
// programme, a snapshot of the capture day). Field names are the file import's (contract C5:
// services/ingest/schemas.py ShopeePromotionDailyRow / ShopeePromotionRow).
//
// Captured 2026-11-19 (shapes only): GET /api/marketing/v3/public/discount/metrics/ answers
// {code, data: {date_range: {start_time, end_time}, metrics: {sales, orders, units, buyers, *_pct_diff}}}.
// The list answers' field names were not pinned: the list is found by the shape of its entries and a
// list that cannot be read posts nothing (it is never drift, and never a guess).
//
// Per-programme daily numbers (Combo khuyến mãi, Mua kèm deal sốc, Flash sale, and each programme's
// "Dữ liệu" page) need a capture of those pages' own requests: not read here yet.

import { MONEY_DIVISOR } from "./config";
import { type Mapped, type Row } from "./map";
import { classify, payloadOf, type ReaderResponse } from "./reader";
import { gmt7Date } from "../../core/time";

/** The file import's promotion type of the "Chương trình của Shop" tab. */
export const PROMO_TYPE_DISCOUNT = "Chương Trình Khuyến Mãi";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function nonNeg(value: unknown): number | undefined {
  const n = typeof value === "number" ? value : typeof value === "string" && value.trim() !== "" ? Number(value) : NaN;
  return Number.isFinite(n) && n >= 0 ? n : undefined;
}

/** Unix seconds (or ms) of a metrics range end -> the GMT+7 day it falls on. */
function dayOfSeconds(value: unknown): string | undefined {
  const n = nonNeg(value);
  if (n === undefined || n <= 0) return undefined;
  return gmt7Date(Math.floor(n > 1e12 ? n / 1000 : n));
}

const todayOf = (capturedAt: number) => gmt7Date(Math.floor(capturedAt / 1000));

/** The answers of one endpoint that carry data. */
const ok = (responses: ReaderResponse[], endpoint: string) => responses.filter((r) => r.endpoint === endpoint && classify(r.status, r.body) === "ok");

/**
 * One `promotion_daily` post per answer whose range is exactly one GMT+7 day (the replayed days; the
 * page's own multi-day range is not a day and is left out). Two answers for one day: the later wins.
 */
export function mapPromotionDaily(responses: ReaderResponse[]): Mapped[] {
  const byDay = new Map<string, { row: Row; at: number }>();
  for (const response of ok(responses, "promotion_metrics")) {
    const payload = payloadOf(response.body);
    if (!isRecord(payload) || !isRecord(payload.date_range) || !isRecord(payload.metrics)) continue;
    const start = nonNeg(payload.date_range.start_time);
    const end = nonNeg(payload.date_range.end_time);
    const day = dayOfSeconds(start);
    if (start === undefined || end === undefined || day === undefined || dayOfSeconds(end - 1) !== day) continue;
    const m = payload.metrics;
    const row: Row = { promo_type: PROMO_TYPE_DISCOUNT };
    const sales = nonNeg(m.sales);
    const orders = nonNeg(m.orders);
    const units = nonNeg(m.units);
    const buyers = nonNeg(m.buyers);
    if (sales !== undefined) row.sales = Math.round((sales / MONEY_DIVISOR.promotions) * 100) / 100;
    if (orders !== undefined) row.orders = orders;
    if (units !== undefined) row.units = units;
    if (buyers !== undefined) row.buyers = buyers;
    if (Object.keys(row).length === 1) continue; // none of the four numbers: nothing to say
    const previous = byDay.get(day);
    if (!previous || response.capturedAt >= previous.at) byDay.set(day, { row, at: response.capturedAt });
  }
  return [...byDay.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([day, { row }]) => ({
      dataset: "promotion_daily" as const,
      endpoint: "marketing/discount/metrics",
      date: day,
      orderType: null,
      rows: [row],
      drift: null,
    }));
}

const NAME_KEYS = ["name", "title", "discount_name", "promotion_name", "program_name"] as const;
const START_KEYS = ["start_time", "begin_time", "start_at", "starts_at"] as const;
const END_KEYS = ["end_time", "finish_time", "end_at", "ends_at"] as const;

function firstOf(source: Record<string, unknown>, keys: readonly string[]): unknown {
  for (const key of keys) if (source[key] !== undefined && source[key] !== null) return source[key];
  return undefined;
}

/** Seller Centre's wall clock (GMT+7), no zone suffix, from unix seconds / ms. */
function wallClock(value: unknown): string | undefined {
  const n = nonNeg(value);
  if (n === undefined || n <= 0) return undefined;
  const seconds = n > 1e12 ? Math.floor(n / 1000) : n;
  return new Date((seconds + 7 * 3600) * 1000).toISOString().slice(0, 19);
}

/** Programme entries of a list answer: records with a name and a start time, found anywhere in the payload. */
function programmeEntries(body: unknown): Record<string, unknown>[] {
  const found: Record<string, unknown>[] = [];
  const queue: { node: unknown; level: number }[] = [{ node: payloadOf(body), level: 0 }];
  while (queue.length > 0) {
    const { node, level } = queue.shift() as { node: unknown; level: number };
    if (Array.isArray(node)) {
      for (const item of node) {
        if (isRecord(item) && typeof firstOf(item, NAME_KEYS) === "string" && wallClock(firstOf(item, START_KEYS)) !== undefined) found.push(item);
        else if (level < 4) queue.push({ node: item, level: level + 1 });
      }
    } else if (isRecord(node) && level < 4) {
      for (const value of Object.values(node)) queue.push({ node: value, level: level + 1 });
    }
  }
  return found;
}

/**
 * One `promotions` post: every programme of the page's list and active answers, de-duplicated by
 * name and start (ordinal = place among equal ones). Posts nothing when no entry can be read.
 */
export function mapPromotionList(responses: ReaderResponse[], capturedAt: number): Mapped | null {
  const entries = [...ok(responses, "promotion_list"), ...ok(responses, "promotion_active")].flatMap((r) => programmeEntries(r.body));
  const rows: Row[] = [];
  const seen = new Map<string, number>();
  for (const entry of entries) {
    const name = String(firstOf(entry, NAME_KEYS)).trim().slice(0, 255);
    const startsAt = wallClock(firstOf(entry, START_KEYS));
    if (!name || !startsAt) continue;
    const id = entry.id ?? entry.discount_id ?? entry.promotion_id;
    const key = `${name}|${startsAt}|${typeof id === "string" || typeof id === "number" ? String(id) : ""}`;
    if (rows.some((row) => (row as { _key?: string })._key === key)) continue;
    const base = `${name}|${startsAt}`;
    const ordinal = seen.get(base) ?? 0;
    seen.set(base, ordinal + 1);
    const row: Row = { program_name: name, promo_type: PROMO_TYPE_DISCOUNT, starts_at: startsAt, ordinal, _key: key };
    const endsAt = wallClock(firstOf(entry, END_KEYS));
    if (endsAt) row.ends_at = endsAt;
    const status = firstOf(entry, ["status", "status_text", "state"]);
    if (typeof status === "string" && status.trim()) row.status = status.trim().slice(0, 64);
    rows.push(row);
  }
  if (rows.length === 0) return null;
  const today = todayOf(capturedAt);
  return {
    dataset: "promotions",
    endpoint: "marketing/discount/list",
    date: today,
    periodStart: today,
    orderType: null,
    granularity: "period",
    rows: rows.map(({ _key: _drop, ...row }) => row),
    drift: null,
  };
}

/** A promotions reader job's posts: the per-day numbers, then the programme list. */
export function mapPromotions(responses: ReaderResponse[], capturedAt: number): Mapped[] {
  const list = mapPromotionList(responses, capturedAt);
  return [...mapPromotionDaily(responses), ...(list ? [list] : [])];
}
