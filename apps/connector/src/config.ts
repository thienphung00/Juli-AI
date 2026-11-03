// Fixed configuration. The API origin is baked in at build time (scripts/build.mjs
// replaces __JULI_API_ORIGIN__); it must match the manifest's host permission.

declare const __JULI_API_ORIGIN__: string;

export const SELLER_CENTRE_ORIGIN = "https://banhang.shopee.vn";
export const API_ORIGIN: string =
  typeof __JULI_API_ORIGIN__ === "string" ? __JULI_API_ORIGIN__ : "https://api.app-juli.com";

/** The window.postMessage channel between the page hook and the content script. */
export const CHANNEL = "juli-connector/v1";

/** Active sync: at most one Seller Centre request per this many ms, plus jitter. */
export const MIN_REQUEST_GAP_MS = 2_000;
export const MAX_REQUEST_JITTER_MS = 1_500;
/** Daily alarm, and the random start offset so pilot shops do not sync in lock-step. */
export const SYNC_PERIOD_MINUTES = 24 * 60;
export const SYNC_START_JITTER_MINUTES = 90;

/**
 * One-time backfill after pairing: the last this-many finished GMT+7 days, one
 * day per round trip to the Seller Centre tab, at the same ≥ 2 s + jitter pace.
 */
export const BACKFILL_DAYS = 30;
/** A backfill day sent to a tab with no answer after this long is sent again. */
export const BACKFILL_IN_FLIGHT_TIMEOUT_MS = 3 * 60_000;
/** Transient Seller Centre failures (5xx, 429, network) tolerated per day before stopping. */
export const BACKFILL_MAX_DAY_ATTEMPTS = 3;

/**
 * Item-level readers wait for the second Seller Centre recon (D31.6): the first
 * recon saw only empty item lists, so the item row schema is not pinned. Passive
 * capture still maps what it can; the ACTIVE sync does not ask for item pages yet.
 */
export const ITEM_READERS_ACTIVE = false;

/** The four `/api/mydata` datasets the page's own responses feed (passive capture + daily sync). */
export type MydataDataset = "traffic_overview" | "item_by_source" | "item_performance" | "shop_traffic";
export const DATASETS: readonly MydataDataset[] = [
  "traffic_overview",
  "item_by_source",
  "item_performance",
  "shop_traffic",
];

/** Datasets the page readers post (ADR-120 d.14); the gateway's names, see services/ingest. */
export type ReaderDataset =
  | "item_catalog"
  | "item_snapshot"
  | "item_traffic_sources"
  | "ads_campaign_daily"
  | "voucher_settings"
  | "shop_health_daily";
export type Dataset = MydataDataset | ReaderDataset;

// -- page readers + tab-opening scheduler (ADR-120 d.14) -----------------------------------
//
// Each reader reads one Seller Centre report page's own endpoints (read-only; the seller's
// own session) and posts mapped rows. Like ITEM_READERS_ACTIVE, a reader is a feature flag
// here, and it is ON only for the pilot shops below: `readerActive(id, shopId)`.

export type ReaderId = "products" | "item_traffic" | "ads" | "vouchers" | "health";
export const READER_IDS: readonly ReaderId[] = ["products", "vouchers", "ads", "health", "item_traffic"];

/** Master flag per reader (a build-time switch). */
export const READERS_ACTIVE: Record<ReaderId, boolean> = {
  products: true,
  item_traffic: true,
  ads: true,
  vouchers: true,
  health: true,
};

/** The scheduler that OPENS the report pages itself (a background tab per page, once a day). */
export const SCHEDULER_ACTIVE = true;

/**
 * Juli shop ids the readers and the scheduler run for. "*" = every paired shop: this build is
 * the Unlisted pilot build (STORE_LISTING.md), so every shop that can pair is a pilot shop.
 * Replace "*" with explicit ids before the extension is listed publicly; an empty list turns
 * every reader off.
 */
// Owner 2026-11-04: ORY only (Juli Ops shop "ORY") until its first live run is confirmed
// (request bodies, money units). Widen to "*" (every paired shop) only after that.
export const PILOT_SHOP_IDS: readonly string[] = ["d73a240b-a00a-4306-9b3e-9fdf75d72aaf"];

export function readerActive(id: ReaderId, shopId: string | undefined): boolean {
  if (!READERS_ACTIVE[id] || !shopId) return false;
  return PILOT_SHOP_IDS.includes("*") || PILOT_SHOP_IDS.includes(shopId);
}

export function schedulerActive(shopId: string | undefined): boolean {
  return SCHEDULER_ACTIVE && !!shopId && (PILOT_SHOP_IDS.includes("*") || PILOT_SHOP_IDS.includes(shopId));
}

/** The datasets each reader produces. */
export const READER_DATASETS: Record<ReaderId, readonly ReaderDataset[]> = {
  products: ["item_catalog", "item_snapshot"],
  item_traffic: ["item_traffic_sources"],
  vouchers: ["voucher_settings"],
  ads: ["ads_campaign_daily"],
  health: ["shop_health_daily"],
};

/**
 * Datasets the gateway does not accept yet: the readers still map them, but nothing is posted
 * and a page that only feeds held datasets is not opened. Empty since the backend registered
 * item_snapshot and shop_health_daily (migration 112); add a name here to hold a dataset back.
 */
export const HELD_DATASETS: ReadonlySet<ReaderDataset> = new Set<ReaderDataset>();

/** The scheduler's pace: one page (tab) at a time, a gap between pages, a cap on waiting. */
export const READER_RUN_PERIOD_MINUTES = 24 * 60;
export const READER_RUN_START_MIN_MINUTES = 20;
export const READER_RUN_START_JITTER_MINUTES = 100;
export const READER_WATCHDOG_ALARM_MINUTES = 1;
export const READER_PAGE_GAP_MS = 20_000;
export const READER_PAGE_GAP_JITTER_MS = 25_000;
/** A page that has not answered after this long is closed and counted as a timeout. */
export const READER_JOB_TIMEOUT_MS = 4 * 60_000;
/** A tab that has not reported its content script ready after this long is inspected. */
export const READER_LOAD_GRACE_MS = 25_000;
/** How long the page hook waits for the page's own first call (session, request template). */
export const READER_TEMPLATE_WAIT_MS = 40_000;
export const READER_POLL_MS = 500;
/** Cool-downs after a stop: a CAPTCHA is left alone for days; a login wall is retried sooner. */
export const READER_BLOCK_CAPTCHA_MS = 72 * 3_600_000;
export const READER_BLOCK_LOGIN_MS = 6 * 3_600_000;
/** Ads: yesterday plus up to this many earlier finished days not read yet (one day per call). */
export const ADS_CATCHUP_DAYS = 3;
export const ADS_MAX_ROWS_PER_DAY = 300;
export const ADS_PAGE_LIMIT_DEFAULT = 20;
/**
 * Per-product traffic sources (/datacenter/product/traffic): yesterday plus up to this many
 * earlier finished days not read yet; one request per item per day, so a job is capped.
 */
export const TRAFFIC_CATCHUP_DAYS = 3;
export const TRAFFIC_MAX_ITEMS = 300;
export const TRAFFIC_MAX_REQUESTS_PER_JOB = 600;
/** A traffic job makes hundreds of paced requests: it gets its own, longer, timeout. */
export const TRAFFIC_JOB_TIMEOUT_MS = 45 * 60_000;
/** Transient per-item errors tolerated in a row before the traffic job stops. */
export const TRAFFIC_MAX_CONSECUTIVE_ERRORS = 5;
export const PRODUCT_MAX_PAGES = 40;
export const VOUCHER_MAX_ROWS = 600;
export const VOUCHER_PAGE_LIMIT_DEFAULT = 20;
/** Rows per ingest post (the gateway takes 2 000 rows and ~1 MB). */
export const MAX_ROWS_PER_POST = 400;

/**
 * UNVERIFIED (recon recorded response SHAPES only): Seller Centre money may arrive in VND or in
 * VND x 100 000. A reader divides by these; the plausibility ceilings below turn a wrong
 * scale into drift (dataset stopped, nothing posted) instead of a silently wrong number.
 * Confirm on the first live run against a price / budget the page shows.
 */
export const MONEY_DIVISOR = { products: 1, ads: 1, vouchers: 1 } as const;
export const MAX_PLAUSIBLE_PRICE_VND = 500_000_000;
export const MAX_PLAUSIBLE_AD_VND = 5_000_000_000;
