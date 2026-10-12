// The Seller Centre data endpoints the connector reads (recon 2026-10-12). Kept
// apart from map.ts so the page hook bundles only this list.

import type { Dataset } from "../config";

export const ENDPOINTS: Record<Dataset, string> = {
  traffic_overview: "/api/mydata/v1/product/traffic/overview/",
  item_by_source: "/api/mydata/v1/product/traffic/item-list/",
  item_performance: "/api/mydata/v4/product/performance/",
  shop_traffic: "/api/mydata/traffic/dashboard/overview/",
};

export const WATCHED_PATHS: ReadonlySet<string> = new Set(Object.values(ENDPOINTS));

/** Session query params Seller Centre adds to every call; never stored or sent to Juli. */
export const SESSION_PARAMS = ["SPC_CDS", "SPC_CDS_VER"] as const;
