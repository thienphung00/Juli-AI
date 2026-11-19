// The Shopee pack's fixed configuration. The platform-free part (API origin, the shared daily
// request budget, fill-engine timing, fill-job polling) lives in core/config.ts and is re-exported
// here, so Shopee code keeps one import.

export * from "../../core/config";

/** The pack id: the gateway's platform name and the pairing token's `platform`. */
export const PLATFORM_ID = "shopee";
export const SELLER_CENTRE_ORIGIN = "https://banhang.shopee.vn";

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
 * Item-level mydata pages (item_performance, item_by_source) in the daily sync and the backfill.
 * Off until 0.3.18 (D31.6: the first recon saw only empty item lists); Connector 0.3.19 turns them
 * on (P100 Part A) now that the 30-day product table and the product list have pinned the item rows.
 */
export const ITEM_READERS_ACTIVE = true;

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
  | "shop_overview"
  | "product_period"
  | "ads_campaign_period"
  | "order_lines"
  | "order_income"
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
// here, and it runs for the shop of the paired token: `readerActive(id, shopId)`.

export type ReaderId =
  | "products"
  | "item_traffic"
  | "ads"
  | "ads_detail"
  | "vouchers"
  | "health"
  | "shop_totals"
  | "product_period"
  | "ads_products"
  | "orders"
  | "order_income"
  /** Connector 0.3.19: Phân Tích Bán Hàng › Truy cập read in the scheduler's own tab (no open tab needed). */
  | "traffic"
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
/**
 * The run order. 0.3.22: the order list and the per-order income run right after the product list,
 * before every /datacenter (Phân tích bán hàng) page: a password re-confirmation there blocks only
 * those pages, and before 0.3.22 it ended the run before orders ever ran. item_traffic stays last:
 * it runs on the ids the product list just read.
 */
export const READER_IDS: readonly ReaderId[] = [
  "products",
  // Connector 0.3.11 (P97 T1): order lines, then the per-order income of the orders just read.
  "orders",
  "order_income",
  "vouchers",
  "ads",
  // Connector 0.3.7: right after the list, on the ongoing campaigns the list just named.
  "ads_detail",
  // Connector 0.3.12 (P97 T3): per-product ads of the group campaigns, right after their edit pages.
  "ads_products",
  "health",
  // /datacenter from here (one page at a time like every reader; the shared request budget caps all).
  // Connector 0.3.11 (P97 T1): shop totals.
  "shop_totals",
  // Connector 0.3.19: the shop's traffic overview (traffic_overview, shop_traffic), in the
  // scheduler's own background tab, so the seller no longer has to keep Truy cập open.
  "traffic",
  // Connector 0.3.12 (P97 T3, recorded 2026-11-09): the 30-day product table, once a day.
  "product_period",
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
  shop_totals: true,
  product_period: true,
  ads_products: true,
  orders: true,
  order_income: true,
  traffic: true,
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
 * T11 (2026-11-15): the shop comes only from the pairing token. There is no shop list in the
 * Connector: the readers and the scheduler run for the paired shop (`shopId` = the token's
 * `shop_id`), Juli's server decides what it accepts and serves (it never issues a code for the
 * reviewer sample shop, and its flags gate the fill and the market search per shop).
 */
export function readerActive(id: ReaderId, shopId: string | undefined): boolean {
  return READERS_ACTIVE[id] && !!shopId;
}

export function schedulerActive(shopId: string | undefined): boolean {
  return SCHEDULER_ACTIVE && !!shopId;
}

/** The datasets each reader produces. */
export const READER_DATASETS: Record<ReaderId, readonly Dataset[]> = {
  products: ["item_catalog", "item_snapshot"],
  item_traffic: ["item_traffic_sources"],
  vouchers: ["voucher_settings"],
  ads: ["ads_campaign_daily", "ads_campaign_settings"],
  ads_detail: ["ads_campaign_detail"],
  health: ["shop_health_daily"],
  shop_totals: ["shop_overview"],
  product_period: ["product_period"],
  ads_products: ["ads_campaign_period"],
  orders: ["order_lines"],
  order_income: ["order_income"],
  traffic: ["traffic_overview", "shop_traffic"],
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
/**
 * 0.3.20: the ads page (Quảng Cáo Shopee) reads its catch-up days AND up to ten history days, and
 * timed out at the general cap ("Trang tải quá lâu", nothing posted): twice the cap, and one reload
 * in the same run (without the history days) before the job gives up.
 */
export const ADS_JOB_TIMEOUT_MS = 2 * READER_JOB_TIMEOUT_MS;
/** A tab that has not reported its content script ready after this long is inspected. */
export const READER_LOAD_GRACE_MS = 25_000;
/** How long the page hook waits for the page's own first call (session, request template). */
export const READER_TEMPLATE_WAIT_MS = 40_000;
export const READER_POLL_MS = 500;
/** Cool-downs after a stop: a CAPTCHA is left alone for days; a login wall is retried sooner. */
export const READER_BLOCK_CAPTCHA_MS = 72 * 3_600_000;
export const READER_BLOCK_LOGIN_MS = 6 * 3_600_000;
/** 0.3.28 (F5.3): Shopee's traffic-check page pauses readers, fills and read-backs together this long. */
export const READER_BLOCK_TRAFFIC_MS = 6 * 3_600_000;

// -- request budget and rate-limit stop (P97 T1, owner concern: no bot detection on the sub-account) --
// DAILY_REQUEST_BUDGET, TODAY_REQUEST_RESERVE, BACKFILL_REQUEST_SHARE and READER_PAGE_LOAD_COST
// (the one shared daily request budget) live in core/config.ts.
/**
 * Order list (0.3.19: by date, not a fixed 5 pages): pages are read until the oldest order on a page
 * was placed before the job's `sinceDay`, at least ORDER_LIST_MIN_PAGES (the 0.3.18 depth, in case
 * the list is not sorted by date) and at most ORDER_LIST_MAX_PAGES_PER_RUN (a safety cap; the daily
 * budget still applies). Each page = an index call + a card call.
 */
export const ORDER_LIST_MIN_PAGES = 5;
export const ORDER_LIST_MAX_PAGES_PER_RUN = 40;
/** The first run reads back this many days; later runs from the last complete read minus the overlap
 *  (orders change status for days), never more than ORDER_CATCHUP_MAX_DAYS back. */
export const ORDER_CATCHUP_FIRST_DAYS = 14;
export const ORDER_CATCHUP_OVERLAP_DAYS = 3;
export const ORDER_CATCHUP_MAX_DAYS = 30;
/** 40 pages x (20-45 s gap + 2 calls) can take ~30 min: the orders job has its own timeout. */
export const ORDERS_JOB_TIMEOUT_MS = 45 * 60_000;
/** Extra wait before an order-list page after the first (ms, plus jitter): 20-45 s like page gaps. */
export const ORDER_LIST_PAGE_GAP_MS = 20_000;
/** 0.3.20: at most this many orders are read one by one (get_one_order) in one run (a safety cap). */
export const ORDER_DETAIL_MAX_PER_RUN = 300;
export const ORDER_LIST_PAGE_GAP_JITTER_MS = 25_000;
/** Per-order income: only orders completed since the last run, oldest first, at most this many a day. */
export const ORDER_INCOME_MAX_PER_DAY = 100;
/** On the first run only orders completed in the last this-many days are queued (never a sweep). */
export const ORDER_INCOME_FIRST_RUN_DAYS = 3;
/** Completed orders waiting for their income read are kept at most this long / this many. */
export const ORDER_INCOME_QUEUE_MAX = 300;
export const ORDER_INCOME_QUEUE_DAYS = 14;
/** 0.3.26: an order whose income read failed on this many days is dropped from the queue. */
export const ORDER_INCOME_MAX_FAILED_DAYS = 3;
/** Shop totals: the 30 days after pairing, then the last 7 each day (placed / paid settle late). */
export const SHOP_TOTALS_BACKFILL_DAYS = 30;
export const SHOP_TOTALS_REFRESH_DAYS = 7;
/** Rate limit / 403 / CAPTCHA stops ALL readers for the shop for this long (the CAPTCHA cool-down). */
export const READER_BLOCK_RATE_MS = READER_BLOCK_CAPTCHA_MS;

/**
 * Product table (Hiệu quả của sản phẩm, recorded 2026-11-09): the last 30 finished days, ordered by
 * confirmed sales, 10 a page, at most this many pages a run. One answer holds placed, paid and
 * confirmed values per item, so one read posts both order types Tổng quan and Quảng cáo need.
 */
export const PRODUCT_PERIOD_DAYS = 30;
export const PRODUCT_PERIOD_PAGE_SIZE = 10;
/** 0.3.19: every row (until the answer's own total / a short page); this is only a safety cap. */
export const PRODUCT_PERIOD_MAX_PAGES = 100;
/** Group-campaign pages whose per-product table is read (the page opened + the others replayed). */
export const ADS_PRODUCTS_MAX_CAMPAIGNS = 10;

/** Shop traffic (0.3.19): yesterday plus up to this many earlier finished days not read yet. */
export const TRAFFIC_OVERVIEW_CATCHUP_DAYS = 3;

/**
 * Stock (0.3.19, P100 stock alert): every day at 06:30 GMT+7 a run of ONLY the product list
 * (item_snapshot carries each variation's stock), on its own alarm; when Chrome was closed at that
 * time it runs at the next start. It may use the whole daily budget (not only the readers' part).
 */
export const STOCK_READ_HOUR_GMT7 = 6;
export const STOCK_READ_MINUTE = 30;
export const STOCK_MAX_ATTEMPTS_PER_DAY = 2;
/** A tick that found the backfill busy tries again after this long (a one-off alarm). */
export const READER_KICK_RETRY_MINUTES = 5;
/** After pairing / a service-worker start that finds today's run not done: start after this long. */
export const READER_KICK_DELAY_MINUTES = 1;
/** 0.3.25: pages blocked by a login / password wall are read again this long after a data call proves the session. */
export const READER_REREAD_DELAY_MINUTES = 2;
/** 0.3.25: at most this many re-read starts a day (a dialog that keeps coming back cannot loop). */
export const READER_REREAD_MAX_PER_DAY = 3;

/** Ads: yesterday plus up to this many earlier finished days not read yet (one day per call). */
export const ADS_CATCHUP_DAYS = 3;
/**
 * Ads history (0.3.19, owner 2026-11-14: no more Shopee ad report files): once per shop the same
 * per-day list read goes back over the last ADS_HISTORY_DAYS finished days, newest first, a few days
 * per daily run, inside the backfill's part of the budget (what is left above TODAY_REQUEST_RESERVE),
 * resumable. The first day Shopee refuses ends it there (its earliest readable day is recorded).
 */
export const ADS_HISTORY_DAYS = 90;
export const ADS_HISTORY_DAYS_PER_RUN = 10;
/** Requests one history day is planned at (list page(s) + the ROAS graph). */
export const ADS_HISTORY_DAY_COST = 3;
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
/** Connector 0.3.17: once per shop, the conversion report is also read for the ~6 months before
 *  that window, in 30-day windows (Juli takes ≤ 31 days per post), so affiliate cost and
 *  performance can be compared over time. Seller Centre kept ≥ 6 months on 2026-11-13. */
export const AFFILIATE_HISTORY_WINDOWS = 6;
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
// reads no buyer data. It runs only when ALL of these hold: this flag is on, a shop is paired, the
// address carries `#juli-fill=<card code>` (set by the Juli button "Điền bằng Connector"), and
// Juli's server (CONNECTOR_FILL_LISTING) serves the card for the token's shop. An unknown layout
// fills nothing and shows copy buttons.

export const FILL_LISTING_ACTIVE = true;

/** The product edit page: `/portal/product/<item id>` (list pages and the new-product form never match). */
export const FILL_EDIT_PATH = /^\/portal\/product\/(\d{1,20})(?:\/|$)/;

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
  return FILL_LISTING_ACTIVE && !!shopId;
}

// -- fill jobs (P97 D85.6): approved cards queued by Juli, opened and filled page by page -------
//
// The allowlist is "this token's shop" (a paired Connector): Juli serves jobs
// only for the token's own shop and only while its server flag CONNECTOR_FILL_LISTING is on (the
// kill switch). Same rules as the listing fill: the Connector types and highlights, the person
// presses Shopee's own Lưu / Xác nhận / Gửi. A job page open costs READER_PAGE_LOAD_COST against
// the shared daily request budget; a CAPTCHA / login wall / password prompt stops it. The runner
// and its constants are core's (core/jobs/fill-jobs.ts, core/config.ts); the pages are Shopee's.

/** The only Seller Centre pages a job may open (path only; a query string is allowed on vouchers). */
/** Shopee's anti-bot page ("Trang không khả dụng", /verify/traffic/error, 2026-11-18): a job that lands there stops. */
export const TRAFFIC_CHECK = "shopee_traffic_check";
export function trafficCheckUrl(url: string | undefined): boolean {
  try {
    return /\/verify\/traffic/.test(new URL(url ?? "").pathname);
  } catch {
    return false;
  }
}

export const FILL_JOB_PAGES = {
  product_edit: /^\/portal\/product\/(\d{1,20})$/,
  voucher_new: /^\/portal\/marketing\/vouchers\/new$/,
  ads_edit: /^\/portal\/marketing\/pas\/product\/(manual|manual-mpd)\/(\d{1,20})$/,
  affiliate_open: /^\/portal\/web-seller-affiliate\/open_campaign$/,
  bundle_new: /^\/portal\/marketing\/bundle\/new$/,
  /** 0.3.27: the lists a revert (voucher_end / combo_end) opens and a save lands on. */
  voucher_list: /^\/portal\/marketing\/vouchers\/list$/,
  bundle_list: /^\/portal\/marketing\/bundle\/list$/,
} as const;

// -- market search reader (P92 B-10, Connector 0.3.5) -----------------------------------------
//
// Once a week per keyword the Connector opens the PUBLIC Shopee search page for a product's 1-3
// main keywords (the list comes from Juli: GET /v1/ingest/market/keywords) in a background tab,
// keeps the page's OWN search answer (page 1, relevancy) and posts the cards to the dataset
// `market_search`. No login, no buyer data, never clicks. For the paired shop; Juli's server
// decides per shop whether it has keywords to read (`market.enabled`, else an empty list).
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
  return !!shopId;
}
