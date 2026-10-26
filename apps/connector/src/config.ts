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

export type Dataset = "traffic_overview" | "item_by_source" | "item_performance" | "shop_traffic";
export const DATASETS: readonly Dataset[] = [
  "traffic_overview",
  "item_by_source",
  "item_performance",
  "shop_traffic",
];
