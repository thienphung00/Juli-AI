// The once-a-day active sync (pure parts): which GET calls to re-issue for
// yesterday and how far apart. The calls are the ones Seller Centre's own pages
// make; the page hook sends them from the seller's open Seller Centre tab, with
// the session params it has seen the page use, at ≤ 1 request / 2 s.

import { DATASETS, ITEM_READERS_ACTIVE, MAX_REQUEST_JITTER_MS, MIN_REQUEST_GAP_MS, type Dataset } from "../config";
import { ENDPOINTS } from "./endpoints";
import { L1_SOURCES } from "./map";
import { yesterdayRange } from "./time";

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
    // `dt`'s format was not pinned by the recon: replay the page's own call.
    plan.push({ dataset: "shop_traffic", path: ENDPOINTS.shop_traffic, params: {}, useTemplate: true });
  }
  if (itemReadersActive && wanted("item_performance")) {
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
  if (itemReadersActive && wanted("item_by_source")) {
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
