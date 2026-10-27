// The once-a-day active sync (pure parts): which GET calls to re-issue for
// yesterday and how far apart. The calls are the ones Seller Centre's own pages
// make; the page hook sends them from the seller's open Seller Centre tab, with
// the session params it has seen the page use, at ≤ 1 request / 2 s.

import { DATASETS, ITEM_READERS_ACTIVE, MAX_REQUEST_JITTER_MS, MIN_REQUEST_GAP_MS, type Dataset } from "../config";
import { ENDPOINTS } from "./endpoints";
import { L1_SOURCES } from "./map";
import { compactDate, gmt7DateStart, yesterdayRange } from "./time";

const DAY = 86_400;

export interface PlannedRequest {
  dataset: Dataset;
  path: string;
  /** Query params (without the session params the hook adds). */
  params: Record<string, string>;
  /** Replay the page's own last call to this path instead of `params` (unknown param formats). */
  useTemplate?: boolean;
}

/** Item pages per L1 source, at the page size the UI uses. */
const ITEM_PAGES = 5;
const ITEM_PAGE_SIZE = "10";

type Range = { start_time: string; end_time: string; period: string };

/** Item pages for one range: only while the item readers are active (D31.6). */
function itemRequests(range: Range, wanted: (dataset: Dataset) => boolean): PlannedRequest[] {
  const plan: PlannedRequest[] = [];
  if (wanted("item_performance")) {
    for (let page = 1; page <= ITEM_PAGES; page += 1) {
      plan.push({
        dataset: "item_performance",
        path: ENDPOINTS.item_performance,
        params: {
          ...range,
          keyword: "",
          category_type: "shopee",
          category_id: "-1",
          page_size: ITEM_PAGE_SIZE,
          page_num: String(page),
          order_type: "confirmed",
          order_by: "confirmed_sales.desc",
        },
      });
    }
  }
  if (wanted("item_by_source")) {
    for (const source of L1_SOURCES) {
      plan.push({
        dataset: "item_by_source",
        path: ENDPOINTS.item_by_source,
        params: {
          ...range,
          keyword: "",
          order_by: "",
          page_size: ITEM_PAGE_SIZE,
          page_num: "1",
          category_type: "shopee",
          category_id: "-1",
          l1_source: source,
          order_type: "confirmed",
        },
      });
    }
  }
  return plan;
}

export function buildSyncPlan(
  nowMs: number,
  stopped: ReadonlySet<Dataset>,
  itemReadersActive: boolean = ITEM_READERS_ACTIVE,
): PlannedRequest[] {
  const day = yesterdayRange(nowMs);
  const range = {
    start_time: String(day.start_time),
    end_time: String(day.end_time),
    period: "yesterday",
  };
  const plan: PlannedRequest[] = [];
  const wanted = (dataset: Dataset) => DATASETS.includes(dataset) && !stopped.has(dataset);

  if (wanted("traffic_overview")) {
    plan.push({
      dataset: "traffic_overview",
      path: ENDPOINTS.traffic_overview,
      params: { ...range, order_type: "confirmed" },
    });
  }
  if (wanted("shop_traffic")) {
    // The daily sync replays the page's own "yesterday" call (kept as it works);
    // the backfill uses the recorded `period=day&dt=YYYYMMDD` shape instead.
    plan.push({ dataset: "shop_traffic", path: ENDPOINTS.shop_traffic, params: {}, useTemplate: true });
  }
  if (itemReadersActive) plan.push(...itemRequests(range, wanted));
  return plan;
}

/** The datasets the backfill asks for (item datasets only while their readers are active). */
export function backfillDatasets(itemReadersActive: boolean = ITEM_READERS_ACTIVE): Dataset[] {
  return DATASETS.filter(
    (dataset) => itemReadersActive || (dataset !== "item_performance" && dataset !== "item_by_source"),
  );
}

/**
 * One backfill day's calls, in the shapes Seller Centre's own date picker sends
 * (recorded 2026-10-26): yesterday as "Hôm qua" (`period=yesterday`, end = start +
 * 86399); any older day as "Theo ngày" (`period=day`, end = start + 86400, the next
 * midnight; + 86399 is refused with code 10006); the traffic dashboard as
 * `period=day&dt=YYYYMMDD` (no page template needed). `skip`: datasets already
 * accepted for that day or stopped.
 */
export function buildBackfillDayPlan(
  date: string,
  nowMs: number,
  skip: ReadonlySet<Dataset>,
  itemReadersActive: boolean = ITEM_READERS_ACTIVE,
): PlannedRequest[] {
  const start = gmt7DateStart(date);
  const isYesterday = date === yesterdayRange(nowMs).date;
  const range: Range = isYesterday
    ? { start_time: String(start), end_time: String(start + DAY - 1), period: "yesterday" }
    : { start_time: String(start), end_time: String(start + DAY), period: "day" };
  const datasets = backfillDatasets(itemReadersActive);
  const wanted = (dataset: Dataset) => datasets.includes(dataset) && !skip.has(dataset);
  const plan: PlannedRequest[] = [];
  if (wanted("traffic_overview")) {
    plan.push({
      dataset: "traffic_overview",
      path: ENDPOINTS.traffic_overview,
      params: { ...range, order_type: "confirmed" },
    });
  }
  if (wanted("shop_traffic")) {
    plan.push({
      dataset: "shop_traffic",
      path: ENDPOINTS.shop_traffic,
      params: { period: "day", dt: compactDate(date) },
    });
  }
  if (itemReadersActive) plan.push(...itemRequests(range, wanted));
  return plan;
}

/**
 * Wait before the next Seller Centre request when the previous one went at
 * `lastSentAt` (ms; undefined = none yet): ≥ 2 s + jitter after it, across plans,
 * so a daily sync followed by backfill days never bunches up.
 */
export function waitBefore(lastSentAt: number | undefined, nowMs: number, random: () => number = Math.random): number {
  if (lastSentAt === undefined) return 0;
  const due = lastSentAt + MIN_REQUEST_GAP_MS + Math.floor(random() * MAX_REQUEST_JITTER_MS);
  return Math.max(0, due - nowMs);
}

/** Wait before request `index` (the first goes at once): ≥ 2 s apart, plus jitter. */
export function gapBefore(index: number, random: () => number = Math.random): number {
  if (index === 0) return 0;
  return MIN_REQUEST_GAP_MS + Math.floor(random() * MAX_REQUEST_JITTER_MS);
}

/** The URL the hook sends: planned params (or the page's template) + the session params. */
export function requestUrl(
  origin: string,
  request: PlannedRequest,
  session: Record<string, string>,
  template?: Record<string, string>,
): string | null {
  const params = request.useTemplate ? template : request.params;
  if (!params) return null;
  if (request.useTemplate && params.period !== "yesterday") return null;
  const query = new URLSearchParams({ ...params, ...session });
  return `${origin}${request.path}?${query.toString()}`;
}
