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

/** The affiliate service GraphQL path (`?q=<OperationName>`). */
export const AFFILIATE_GQL_PATH = "/api/v3/affiliateplatform/gql";

export const READER_ENDPOINTS = {
  product_list: { method: "GET", path: "/api/v3/opt/mpsku/list/v2/get_product_list" },
  campaign_info: { method: "POST", path: "/api/v3/opt/product/get_campaign_info_by_item_list/" },
  ads_homepage: { method: "POST", path: "/api/pas/v1/homepage/query/" },
  ads_time_graph: { method: "POST", path: "/api/pas/v1/report/get_time_graph/" },
  // -- one ad campaign's edit page (Connector 0.3.11, recon 2026-11-06). Captured as the page
  // loads them for the campaign it opened, and replayed (only `campaign_id` changed) for the
  // other ongoing campaigns. All four are reads: isReadOnlyPasPath guards every replay.
  ads_product_get: { method: "POST", path: "/api/pas/v1/product/get/", capture: true },
  ads_roi_recommend: { method: "POST", path: "/api/pas/v1/setup_helper/get_recommended_roi_two_target/", capture: true },
  ads_budget_edit: { method: "POST", path: "/api/pas/v1/setup_helper/get_budget_data_for_edit/", capture: true },
  ads_expense_stats: { method: "POST", path: "/api/pas/v1/setup_helper/get_campaign_expense_statistics/", capture: true },
  voucher_list: { method: "GET", path: "/api/marketing/v3/voucher/list/" },
  traffic_details: { method: "GET", path: "/api/mydata/v1/product/traffic/details/" },
  health_overview: { method: "GET", path: "/api/accounthealth/v1/sc/shops/overview" },
  health_metric_list: { method: "GET", path: "/api/accounthealth/v1/sc/shops/metric_list" },
  health_metric_configs: { method: "GET", path: "/api/accounthealth/v1/sc/metric/configs" },
  // -- affiliate ("Tăng Đơn Cùng KOL", recon 2026-11-06). Only the conversion report is replayed
  // (a GET, page by page). Every other affiliate answer is CAPTURED as the page loads it and
  // never replayed. GraphQL calls share one path and are told apart by `?q=<operation>`: only the
  // read-only *Query* operations below are known; a `*Mutation` never matches (HARD RULE).
  affiliate_conversion: { method: "GET", path: "/api/v3/affiliateplatform/conversion/report/list" },
  affiliate_latest_date: { method: "GET", path: "/api/v3/affiliateplatform/dashboard/latest_report_date", capture: true },
  affiliate_performance: { method: "GET", path: "/api/v3/affiliateplatform/dashboard/affiliate_performance", capture: true },
  affiliate_seller_daily: { method: "GET", path: "/api/v3/affiliateplatform/dashboard/seller_daily", capture: true },
  affiliate_item_detail: { method: "GET", path: "/api/v3/affiliateplatform/dashboard/seller_item_detail", capture: true },
  affiliate_validation: { method: "GET", path: "/api/v3/affiliateplatform/validation/list", capture: true },
  affiliate_shop_campaign: { method: "POST", path: AFFILIATE_GQL_PATH, op: "GetShopCampaign", capture: true },
  affiliate_commission_list: { method: "POST", path: AFFILIATE_GQL_PATH, op: "QueryCommissionList", capture: true },
  affiliate_content_summary: { method: "POST", path: AFFILIATE_GQL_PATH, op: "QuerySellerContentSummaryQuery", capture: true },
} as const;

export type ReaderEndpoint = keyof typeof READER_ENDPOINTS;

interface EndpointSpec {
  method: string;
  path: string;
  op?: string;
  capture?: boolean;
}

const trimSlash = (path: string) => path.replace(/\/+$/, "");

/** A GraphQL operation the Connector must never send, replay or keep. */
export function isMutationOp(op: string | null | undefined): boolean {
  return typeof op === "string" && /mutation/i.test(op);
}

/**
 * The reader endpoint a (method, pathname[, gql operation]) is, or null. A GraphQL call matches
 * only its own listed operation; a mutation never matches anything.
 */
export function readerEndpointOf(method: string, pathname: string, op?: string | null): ReaderEndpoint | null {
  const wanted = trimSlash(pathname);
  if (isMutationOp(op)) return null;
  for (const [key, endpoint] of Object.entries(READER_ENDPOINTS) as [ReaderEndpoint, EndpointSpec][]) {
    if (endpoint.method !== method.toUpperCase() || trimSlash(endpoint.path) !== wanted) continue;
    if (endpoint.op !== undefined && endpoint.op !== op) continue;
    return key;
  }
  return null;
}

/** Endpoints whose answer is kept as the page loads it (their requests are never replayed). */
export function isCapturedEndpoint(endpoint: ReaderEndpoint): boolean {
  return endpoint === "campaign_info" || (READER_ENDPOINTS[endpoint] as EndpointSpec).capture === true;
}

/** The Seller Centre report pages the scheduler may open (read-only; one per reader). */
export const READER_PAGES: Record<ReaderId, { path: string }> = {
  products: { path: "/portal/product/list/all" },
  item_traffic: { path: "/datacenter/product/traffic" },
  vouchers: { path: "/portal/marketing/vouchers/list" },
  ads: { path: "/portal/marketing/pas/index" },
  // The prefix of every campaign edit page; readerPageUrl names the campaign.
  ads_detail: { path: "/portal/marketing/pas/product/" },
  health: { path: "/portal/accounthealth" },
  affiliate: { path: "/portal/web-seller-affiliate/conversion_report" },
  affiliate_kols: { path: "/portal/web-seller-affiliate/affiliate_analytics" },
  affiliate_dashboard: { path: "/portal/web-seller-affiliate/dashboard" },
  affiliate_products: { path: "/portal/web-seller-affiliate/product_analytics" },
  affiliate_campaigns: { path: "/portal/web-seller-affiliate/open_campaign" },
  affiliate_commissions: { path: "/portal/web-seller-affiliate/commission_analytics" },
  affiliate_content: { path: "/portal/web-seller-affiliate/content_analytics" },
  affiliate_bills: { path: "/portal/web-seller-affiliate/validation_bill" },
};

/**
 * A /api/pas/ path the Connector may replay: its last segment must read (get / query / list).
 * The ads pages also call create / edit / update / delete / modify endpoints (the list page
 * itself calls banner/modify); none of them is ever sent by the Connector.
 */
export function isReadOnlyPasPath(pathname: string): boolean {
  const segments = pathname.replace(/\/+$/, "").split("/");
  const last = segments[segments.length - 1] ?? "";
  if (!pathname.startsWith("/api/pas/")) return false;
  if (/(create|edit|update|delete|modify|save|submit|set|toggle|pause|resume|enable|disable)/i.test(last.replace(/^get_.*$/, ""))) {
    return false;
  }
  return /^(get|query|list)(_|$)/.test(last);
}

/** The page a reader job opens: the campaign's own edit page for ads_detail, else the reader's page. */
export function readerPageUrl(job: { id: ReaderId; campaignIds?: string[]; campaignKinds?: string[] }): string {
  if (job.id === "ads_detail") {
    const id = job.campaignIds?.[0] ?? "";
    const kind = job.campaignKinds?.[0] === "mpd" ? "manual-mpd" : "manual";
    return `${READER_PAGES.ads_detail.path}${kind}/${id}`;
  }
  return READER_PAGES[job.id].path;
}
