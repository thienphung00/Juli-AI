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
  | "ads_campaign_settings"
  | "ads_campaign_detail"
  | "voucher_settings"
  | "shop_health_daily"
  | "market_search"
  | "affiliate_order_lines"
  | "affiliate_partner_period"
  | "affiliate_shop_period"
  | "affiliate_product_period"
  | "affiliate_shop_campaigns"
  | "affiliate_commission_period"
  | "affiliate_content_period"
  | "affiliate_bill_period";
export type Dataset = MydataDataset | ReaderDataset;

// -- page readers + tab-opening scheduler (ADR-120 d.14) -----------------------------------
//
// Each reader reads one Seller Centre report page's own endpoints (read-only; the seller's
// own session) and posts mapped rows. Like ITEM_READERS_ACTIVE, a reader is a feature flag
// here, and it is ON only for the pilot shops below: `readerActive(id, shopId)`.

export type ReaderId =
  | "products"
  | "item_traffic"
  | "ads"
  | "ads_detail"
  | "vouchers"
  | "health"
  | AffiliateReaderId;
/** The affiliate ("Tăng Đơn Cùng KOL") pages, one reader per page (Connector 0.3.6, every paired shop in 0.3.7). */
export type AffiliateReaderId =
  | "affiliate"
  | "affiliate_kols"
  | "affiliate_dashboard"
  | "affiliate_products"
  | "affiliate_campaigns"
  | "affiliate_commissions"
  | "affiliate_content"
  | "affiliate_bills";
export const AFFILIATE_READER_IDS: readonly AffiliateReaderId[] = [
  "affiliate",
  "affiliate_kols",
  "affiliate_dashboard",
  "affiliate_products",
  "affiliate_campaigns",
  "affiliate_commissions",
  "affiliate_content",
  "affiliate_bills",
];
/** item_traffic stays last: it runs on the ids the product list just read. */
export const READER_IDS: readonly ReaderId[] = [
  "products",
  "vouchers",
  "ads",
  // Connector 0.3.7: right after the list, on the ongoing campaigns the list just named.
  "ads_detail",
  "health",
  ...AFFILIATE_READER_IDS,
  "item_traffic",
];

/** Master flag per reader (a build-time switch). */
export const READERS_ACTIVE: Record<ReaderId, boolean> = {
  products: true,
  item_traffic: true,
  ads: true,
  ads_detail: true,
  vouchers: true,
  health: true,
  affiliate: true,
  affiliate_kols: true,
  affiliate_dashboard: true,
  affiliate_products: true,
  affiliate_campaigns: true,
  affiliate_commissions: true,
  affiliate_content: true,
  affiliate_bills: true,
};

/** The scheduler that OPENS the report pages itself (a background tab per page, once a day). */
export const SCHEDULER_ACTIVE = true;

/**
 * Juli shop ids the readers and the scheduler run for. "*" = every paired shop.
 * Connector 0.3.7: the report readers, including the eight Tăng Đơn Cùng KOL pages,
 * run for every shop that has paired. Listing fill-in and market search stay on the
 * explicit id only (`fillActive` / `marketActive` ignore "*"). An empty list turns
 * every reader off.
 */
export const ORY_SHOP_ID = "d73a240b-a00a-4306-9b3e-9fdf75d72aaf";
export const PILOT_SHOP_IDS: readonly string[] = [ORY_SHOP_ID, "*"];

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
  ads: ["ads_campaign_daily", "ads_campaign_settings"],
  ads_detail: ["ads_campaign_detail"],
  health: ["shop_health_daily"],
  affiliate: ["affiliate_order_lines"],
  affiliate_kols: ["affiliate_partner_period"],
  affiliate_dashboard: ["affiliate_shop_period"],
  affiliate_products: ["affiliate_product_period"],
  affiliate_campaigns: ["affiliate_shop_campaigns"],
  affiliate_commissions: ["affiliate_commission_period"],
  affiliate_content: ["affiliate_content_period"],
  affiliate_bills: ["affiliate_bill_period"],
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
/** Ads edit pages (Connector 0.3.7): at most this many ongoing / scheduled campaigns a day. */
export const ADS_DETAIL_MAX_CAMPAIGNS = 20;
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
/**
 * Affiliate conversion report (Báo cáo chuyển đổi): the last this-many finished GMT+7 days by
 * purchase time, re-read every day (orders change status and commission for weeks). One post's
 * period may not exceed the gateway's 31 days.
 */
export const AFFILIATE_WINDOW_DAYS = 30;
export const AFFILIATE_MAX_ROWS = 2_000;
export const AFFILIATE_PAGE_SIZE_DEFAULT = 20;
/**
 * The affiliate service's money unit is NOT pinned yet (recon saw shapes only). Where a number
 * has its display twin (`dis_<field>`, e.g. "₫126.360") the scale is read from the pair; where
 * it has none this divisor is assumed (VND x 100 000 like the ads service) and the plausibility
 * floor below turns a wrong guess into drift instead of a wrong number. To verify on the first
 * capture.
 */
export const AFFILIATE_MONEY_DIVISOR_FALLBACK = 100_000;
/** A non-zero affiliate amount below this (VND) after scaling is read as a wrong scale. */
export const AFFILIATE_MIN_PLAUSIBLE_VND = 100;

/** Rows per ingest post (the gateway takes 2 000 rows and ~1 MB). */
export const MAX_ROWS_PER_POST = 400;

/**
 * Checked on the first live run (2026-11-04): the ads service (`/api/pas`) sends money AND the
 * per-campaign ROAS target in VND x 100 000 (daily budget 8 000 000 000 = 80 000 đ; ROAS target
 * 550 000 = 5,5); product prices and vouchers arrive in VND. A reader divides by these; the
 * plausibility ceilings below still turn a wrong scale into drift instead of a wrong number.
 */
export const MONEY_DIVISOR = { products: 1, ads: 100_000, vouchers: 1 } as const;
/** The ads service's ratio scale for ROAS targets (`roi_two_target`, `roi_target_setting.value`). */
export const ADS_TARGET_DIVISOR = 100_000;
/** Shopee's "no value" placeholder in mydata metrics (e.g. paid_ads ctr / conversion). */
export const SHOPEE_NO_VALUE = -1_000_000;
export const MAX_PLAUSIBLE_PRICE_VND = 500_000_000;
export const MAX_PLAUSIBLE_AD_VND = 5_000_000_000;

// -- listing fill-in (p91 D-13, flag `fill_listing`) ----------------------------------------
//
// On a product's edit page the Connector can type an APPROVED card's text into the title and the
// first line of the description, highlight the fields and say "kiểm tra rồi bấm Lưu của Shopee".
// It NEVER clicks or submits anything (no Lưu / Cập nhật / Xác nhận / Ẩn), never navigates, and
// reads no buyer data. It runs only when ALL of these hold: this flag is on, the paired shop is
// on the explicit pilot list (the "*" wildcard of the readers does NOT count), the address carries
// `#juli-fill=<card code>` (set by the Juli button "Điền bằng Connector"), and Juli's server
// (CONNECTOR_FILL_LISTING) serves the card. An unknown layout fills nothing and shows copy buttons.

export const FILL_LISTING_ACTIVE = true;

/** The address fragment the Juli button adds: `#juli-fill=JC-2611-0007`. Only the card's code. */
export const FILL_HASH_KEY = "juli-fill";
export const FILL_CODE_PATTERN = /^JC-\d{4}-\d{4,}$/;
/** The product edit page: `/portal/product/<item id>` (list pages and the new-product form never match). */
export const FILL_EDIT_PATH = /^\/portal\/product\/(\d{1,20})(?:\/|$)/;
/** How long the page gets to draw its form before the Connector gives up and offers copy buttons. */
export const FILL_WAIT_MS = 25_000;
export const FILL_POLL_MS = 400;

/**
 * Visible Vietnamese labels the fields are found by, as the real edit page draws them (read-only
 * recon 2026-11-04, ORY product edit page): the required star is part of the label text and the
 * title shows a counter ("23/120"). Matching ignores the star, the colon and the counter, so
 * "*Tên sản phẩm", "Tên sản phẩm" and "Tên sản phẩm 23/120" are the same label. The title is an
 * `<input type=text>`, the description a contenteditable rich editor (one block per line).
 */
export const FILL_LABELS = {
  title: "*Tên sản phẩm",
  description_first_line: "*Mô tả sản phẩm",
} as const;

export function fillActive(shopId: string | undefined): boolean {
  return FILL_LISTING_ACTIVE && !!shopId && PILOT_SHOP_IDS.includes(shopId);
}

// -- market search reader (P92 B-10, Connector 0.3.5) -----------------------------------------
//
// Once a week per keyword the Connector opens the PUBLIC Shopee search page for a product's 1-3
// main keywords (the list comes from Juli: GET /v1/ingest/market/keywords) in a background tab,
// keeps the page's OWN search answer (page 1, relevancy) and posts the cards to the dataset
// `market_search`. No login, no buyer data, never clicks. ORY only: `marketActive` needs the
// explicit shop id in PILOT_SHOP_IDS (the "*" wildcard does NOT count, like fillActive).
// Everything marked "to verify" below is a recon GUESS to confirm on a real capture
// (docs/integrations/shopee/market-search-recon.md).

export const MARKET_ORIGIN = "https://shopee.vn";
/** The window.postMessage channel between the market hook and its relay (not the Seller Centre one). */
export const MARKET_CHANNEL = "juli-connector/market/v1";
/** The page's own search answer (to verify on a real capture). */
export const MARKET_SEARCH_PATH = "/api/v4/search/search_items";
/** The public search page the tab is opened on: `${MARKET_ORIGIN}${MARKET_PAGE_PATH}?keyword=...`. */
export const MARKET_PAGE_PATH = "/search";
/** Shopee v4 sends money as VND x 100 000, e.g. 12900000000 = 129 000 d (to verify). */
export const MARKET_PRICE_DIVISOR = 100_000;
/** A page whose cards have a median price below this is read as a wrong scale -> drift. */
export const MARKET_MIN_PLAUSIBLE_VND = 100;
/** Cards kept from page 1 (Shopee shows about 60). */
export const MARKET_MAX_CARDS = 80;
/** Keywords per product and per run, and the minimum days between two reads of one keyword. */
export const MARKET_MAX_PER_PRODUCT = 3;
export const MARKET_MAX_KEYWORDS_PER_RUN = 12;
export const MARKET_MIN_DAYS_BETWEEN_READS = 6;
/** The market run's own daily alarm starts after the Seller Centre readers (minutes, plus jitter). */
export const MARKET_RUN_START_MIN_MINUTES = 150;
export const MARKET_RUN_START_JITTER_MINUTES = 120;
/** A search tab with no answer after this long is closed and counted as a timeout. */
export const MARKET_JOB_TIMEOUT_MS = 90_000;
export const MARKET_SORT = "relevancy";

export function marketActive(shopId: string | undefined): boolean {
  return !!shopId && PILOT_SHOP_IDS.includes(shopId);
}
