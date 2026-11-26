// The hole list (0.3.29, F4.2, contract C2): the backend names, per daily dataset, the days of the
// last 30 (before today, GMT+7) with no accepted row. The Connector turns each into a per-day read:
// a reader job with those days (traffic, ads, item traffic, shop totals) or, for the two
// mydata item datasets, a reopened day of the per-day backfill (buildBackfillDayPlan). Yesterday's
// reads come first; hole days follow oldest first, a few a run, only while the budget has room.

import {
  CATCHUP_BACKFILL_DATASETS,
  CATCHUP_DAY_COST,
  CATCHUP_DAYS_PER_JOB,
  CATCHUP_WINDOW_DAYS,
  type ReaderId,
} from "../config";
import { gmt7Date, gmt7DateStart } from "../../../core/time";

const dayMinus = (day: string, n: number): string => gmt7Date(gmt7DateStart(day) - n * 86_400);

export interface ReadDays {
  asOf: string;
  datasets: Record<string, string[]>;
  /** 7b: day -> keyed refs of the orders completed with no payment read yet (never a raw order id). */
  unsettled?: Record<string, string[]>;
}

const REF = /^[0-9a-f]{8,128}$/i;
const UNSETTLED_REFS_MAX = 300;

const DAY = /^\d{4}-\d{2}-\d{2}$/;

/** The answer of GET /v1/connector/shopee/read-days, checked: only real past days inside the window, oldest first. */
export function parseReadDays(raw: unknown, today: string): ReadDays | undefined {
  if (typeof raw !== "object" || raw === null) return undefined;
  const body = raw as { as_of?: unknown; datasets?: unknown; unsettled_orders?: unknown };
  if (typeof body.datasets !== "object" || body.datasets === null) return undefined;
  const floor = dayMinus(today, CATCHUP_WINDOW_DAYS);
  const datasets: Record<string, string[]> = {};
  for (const [name, entry] of Object.entries(body.datasets as Record<string, unknown>)) {
    const missing = (entry as { missing?: unknown } | null)?.missing;
    if (!Array.isArray(missing)) continue;
    const days = [...new Set(missing.filter((d): d is string => typeof d === "string" && DAY.test(d) && d < today && d >= floor))].sort();
    if (days.length > 0) datasets[name.slice(0, 48)] = days;
  }
  const unsettled: Record<string, string[]> = {};
  let kept = 0;
  if (typeof body.unsettled_orders === "object" && body.unsettled_orders !== null) {
    for (const [day, refs] of Object.entries(body.unsettled_orders as Record<string, unknown>).sort(([a], [b]) => a.localeCompare(b))) {
      if (!DAY.test(day) || day >= today || day < floor || !Array.isArray(refs)) continue;
      const list = refs.filter((r): r is string => typeof r === "string" && REF.test(r)).slice(0, UNSETTLED_REFS_MAX - kept);
      kept += list.length;
      if (list.length > 0) unsettled[day] = list;
    }
  }
  return {
    asOf: typeof body.as_of === "string" && DAY.test(body.as_of) ? body.as_of : today,
    datasets,
    ...(Object.keys(unsettled).length > 0 ? { unsettled } : {}),
  };
}

/** The reader that can read a dataset's hole days (a job with `days`). */
export const HOLE_READER: Record<string, ReaderId> = {
  traffic_overview: "traffic",
  shop_traffic: "traffic",
  ads_campaign_daily: "ads",
  item_traffic_sources: "item_traffic",
  shop_overview: "shop_totals",
  // F4.5 (t1a): the per-product ads read takes days (a 1-day window each, at most 60 requests a job)
  ads_campaign_period: "ads_products",
};

/** Datasets a hole of which is closed by reopening a day of the per-day backfill. */
export const isBackfillHole = (dataset: string): boolean => CATCHUP_BACKFILL_DATASETS.includes(dataset);

/**
 * `days` (yesterday and the usual catch-up, newest first) followed by this reader's hole days, oldest
 * first, as many as `room` requests allow (at most CATCHUP_DAYS_PER_JOB). `itemCount` prices item traffic.
 */
export function withHoleDays(
  reader: ReaderId,
  days: readonly string[],
  holes: Record<string, string[]> | undefined,
  room: number,
  itemCount: number,
): string[] {
  const mine = [...new Set(Object.entries(holes ?? {}).filter(([dataset]) => HOLE_READER[dataset] === reader).flatMap(([, list]) => list))].sort();
  const fresh = mine.filter((day) => !days.includes(day));
  const cost = reader === "item_traffic" ? Math.max(1, itemCount) : (CATCHUP_DAY_COST[reader] ?? 3);
  const allowed = Math.min(CATCHUP_DAYS_PER_JOB[reader] ?? 5, Math.floor(Math.max(0, room) / cost));
  return [...days, ...fresh.slice(0, allowed)];
}

/** 0.3.31: yesterday / catch-up days first; hole days (older backfill) separately for scheduling after today's readers. */
export function splitHoleDays(
  reader: ReaderId,
  days: readonly string[],
  holes: Record<string, string[]> | undefined,
  room: number,
  itemCount: number,
): { today: string[]; backfill: string[] } {
  const merged = withHoleDays(reader, days, holes, room, itemCount);
  const today = [...days];
  return { today, backfill: merged.filter((day) => !today.includes(day)) };
}

/** Hole days per dataset still open after `read` (days accepted this run). */
export function daysLeft(holes: Record<string, string[]>, read: Record<string, string[]> | undefined): Record<string, number> {
  return Object.fromEntries(Object.entries(holes).map(([dataset, list]) => [dataset, list.filter((d) => !(read?.[dataset] ?? []).includes(d)).length]));
}

/** `catchup:<dataset>=<n> days left` entries, the run report's progress (datasets with none left are dropped). */
export function catchupSummary(left: Record<string, number>): string {
  return Object.entries(left)
    .filter(([, n]) => n > 0)
    .map(([dataset, n]) => `catchup:${dataset}=${n} days left`)
    .join(",");
}
