// The Seller Centre data endpoints the connector reads (recon 2026-10-12). Kept
// apart from map.ts so the page hook bundles only this list.

import type { MydataDataset } from "../config";

export const ENDPOINTS: Record<MydataDataset, string> = {
  traffic_overview: "/api/mydata/v1/product/traffic/overview/",
  item_by_source: "/api/mydata/v1/product/traffic/item-list/",
  item_performance: "/api/mydata/v4/product/performance/",
  shop_traffic: "/api/mydata/traffic/dashboard/overview/",
};

export const WATCHED_PATHS: ReadonlySet<string> = new Set(Object.values(ENDPOINTS));

/** Session query params Seller Centre adds to every call; never stored or sent to Juli. */
export const SESSION_PARAMS = ["SPC_CDS", "SPC_CDS_VER"] as const;

// -- page readers (ADR-120 d.14; recon 2026-11-03) --------------------------------------
//
// The report pages' own endpoints. The hook learns each page's request (query, JSON body,
// headers) from the page's own call and replays it with a changed day / page number; it never
// invents values it has not seen. None of these carries buyer data. Allowed pages are listed
// in READER_PAGES: the scheduler opens nothing else.

import type { ReaderId } from "../config";

export const READER_ENDPOINTS = {
  product_list: { method: "GET", path: "/api/v3/opt/mpsku/list/v2/get_product_list" },
  campaign_info: { method: "POST", path: "/api/v3/opt/product/get_campaign_info_by_item_list/" },
  ads_homepage: { method: "POST", path: "/api/pas/v1/homepage/query/" },
  ads_time_graph: { method: "POST", path: "/api/pas/v1/report/get_time_graph/" },
  voucher_list: { method: "GET", path: "/api/marketing/v3/voucher/list/" },
  health_overview: { method: "GET", path: "/api/accounthealth/v1/sc/shops/overview" },
  health_metric_list: { method: "GET", path: "/api/accounthealth/v1/sc/shops/metric_list" },
  health_metric_configs: { method: "GET", path: "/api/accounthealth/v1/sc/metric/configs" },
} as const;

export type ReaderEndpoint = keyof typeof READER_ENDPOINTS;

const trimSlash = (path: string) => path.replace(/\/+$/, "");

/** The reader endpoint a (method, pathname) is, or null. */
export function readerEndpointOf(method: string, pathname: string): ReaderEndpoint | null {
  const wanted = trimSlash(pathname);
  for (const [key, endpoint] of Object.entries(READER_ENDPOINTS) as [ReaderEndpoint, { method: string; path: string }][]) {
    if (endpoint.method === method.toUpperCase() && trimSlash(endpoint.path) === wanted) return key;
  }
  return null;
}

/** The Seller Centre report pages the scheduler may open (read-only; one per reader). */
export const READER_PAGES: Record<ReaderId, { path: string }> = {
  products: { path: "/portal/product/list/all" },
  vouchers: { path: "/portal/marketing/vouchers/list" },
  ads: { path: "/portal/marketing/pas/index" },
  health: { path: "/portal/accounthealth" },
};
