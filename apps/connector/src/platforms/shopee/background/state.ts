// What the extension keeps in chrome.storage.local: the ingest token (never a
// Juli password or session), per-dataset stops after drift, the last sync, and a
// small retry queue of posts that failed on the network.

import { BACKFILL_REQUEST_SHARE, FILL_REQUEST_RESERVE, type Dataset, type ReaderId } from "../config";
import { requestsLeft, saveState as saveCoreState, type FillJobsState, type RequestBudget, type Storage } from "../../../core/state";

// The platform-free half (storage, the shared daily request budget, fill-job bookkeeping) is core's.
export {
  addRequests,
  backfillRequestsLeft,
  type FillJobsState,
  type RequestBudget,
  requestsLeft,
  type Storage,
} from "../../../core/state";

export function saveState(storage: Storage, patch: Partial<State>): Promise<void> {
  return saveCoreState(storage, patch);
}
import type { IngestBody, TokenInfo } from "../../../core/ingest/client";

export interface Stop {
  version: string;
  at: string;
  unexpected: string[];
  missing: string[];
}

/**
 * A completed order waiting for its income read. 0.3.26: an order whose income answer failed
 * (refused, not 2xx, no final amount yet) stays queued; `failedDays` counts the days it failed
 * (`failedDay` the last one), and it is dropped after ORDER_INCOME_MAX_FAILED_DAYS.
 */
export interface IncomeQueued {
  id: string;
  sn?: string;
  completedAt: number;
  failedDays?: number;
  failedDay?: string;
  /** 0.3.32: false = the order is not completed: its page is read only for its lines (no income yet). */
  income?: boolean;
  /** 0.3.32 (C1): the order's trimmed get_one_order answer when a line named no SKU (no buyer data). */
  fix?: unknown;
  /** 0.3.32: page reads that could not name the line (one a day); at PAGE_FIX_MAX_FAILS it is posted "unresolved_item". */
  fixFailedDays?: number;
  fixFailedDay?: string;
}

export interface Queued {
  dataset: Dataset;
  body: IngestBody;
  attempts: number;
}

export type BackfillStopReason =
  /** Seller Centre refused the session (logged out): resumes once the page loads data again. */
  | "session"
  /** Seller Centre answered code 10006 (invalid param) for a day: format drift; a new version retries. */
  | "invalid_param"
  /** Another Seller Centre error code, or repeated 5xx / network failures: a new version retries. */
  | "shopee_error"
  /** Juli refused the shop (403 consent_required): resumes when the seller retries or pairs again. */
  | "consent_required"
  /** Juli no longer accepts the token: resumes after pairing again. */
  | "unpaired";

/** The one-time backfill of the last 30 finished days (per shop). */
export interface Backfill {
  shopId: string;
  createdAt: string;
  /** The planned GMT+7 days, newest first; fixed when the backfill starts. */
  days: string[];
  /** Days whose every dataset was accepted (or had nothing to send): never fetched again. */
  done: string[];
  /** Datasets already accepted for a day not yet done (a partial day re-fetches only the rest). */
  accepted: Record<string, Dataset[]>;
  /** Transient failures per day. */
  attempts: Record<string, number>;
  status: "running" | "done" | "stopped";
  stop?: {
    reason: BackfillStopReason;
    at: string;
    version: string;
    day?: string;
    dataset?: Dataset;
    code?: string;
  };
  /** The tab had not loaded a Seller Centre data page yet: wait for the page's next data call. */
  needsDataPage?: boolean;
  /** After a transient failure: no day is sent before this time (ms since epoch). */
  notBefore?: number;
  /** The day sent to a tab and not answered yet (ms since epoch). */
  inFlight?: { day: string; at: number };
}

/**
 * One page the scheduler opens: its reader, and (ads, item_traffic) the finished days to read
 * there; item_traffic also carries the item ids to read (filled in when its turn comes).
 */
export interface PlannedJob {
  id: ReaderId;
  days?: string[];
  itemIds?: string[];
  /** ads_detail: the ongoing campaigns to read (filled in when its turn comes) and their kind. */
  campaignIds?: string[];
  campaignKinds?: string[];
  /** ads_products: the group campaigns' titles (parallel to `campaignIds`). */
  campaignNames?: string[];
  /** order_income: the completed orders to read (raw ids stay in this browser; filled in at its turn). */
  orderIds?: string[];
  orderSns?: string[];
  /** order_income (0.3.32): per order, whether its income is read, and its stored answer to put SKUs on. */
  incomeFor?: boolean[];
  fixBodies?: (unknown | null)[];
  fixLast?: boolean[];
  /** affiliate: older purchase windows to read once (0.3.17). */
  history?: { start: string; end: string }[];
  /** orders (0.3.19): read back to orders placed on this GMT+7 day (catch-up by date). */
  sinceDay?: string;
  /** orders (batch-1124-a S1): `sinceDay` reaches back into the server's order_lines_backfill days. */
  orderBackfill?: boolean;
  /** ads (0.3.19): older days of the once-per-shop ads history, newest first, after `days`. */
  historyDays?: string[];
  /** 0.3.32: a page read again in this run after its section answered (F4.3); its outcome replaces the block. */
  retry?: boolean;
}

/** One scheduled run: the pages in order, one open tab at a time (persisted: the worker may restart). */
export interface ReaderRun {
  /** The GMT+7 day the run belongs to (one run per day). */
  day: string;
  /** "stock" (0.3.19): the 06:30 product-list-only run; absent = the daily run. */
  kind?: "stock";
  startedAt: number;
  jobs: PlannedJob[];
  index: number;
  current?: { tabId: number; openedAt: number; sentAt?: number; reopened?: boolean };
  /** No page is opened before this time (ms since epoch): the gap between pages. */
  nextAt?: number;
  /** Per page id: how it ended. */
  outcomes: Record<string, string>;
  /** 0.3.22: Seller Centre sections ("portal", "datacenter") with a page read in this run. */
  live?: string[];
  /** 0.3.25: "reread" for a run started after a block cleared (reported to Juli as that trigger). */
  trigger?: string;
  /** 0.3.22: per section, the login / CAPTCHA walls since its last read (two block its other pages). */
  walls?: Record<string, { count: number; reason: ReaderBlockReason }>;
  /** 0.3.29 (F4.2): per dataset, the hole days this run read (accepted by Juli). */
  catchupRead?: Record<string, string[]>;
  /** 0.3.29 (F4.3): pages already queued a second time in this run after their section answered. */
  retried?: ReaderId[];
  /** 0.3.29 (F4.6): the affiliate programme showed data in this run (an empty period after that is an error). */
  affiliateData?: boolean;
}

/** `rate_limit`: HTTP 429 / 403 or Shopee wording for "too many requests" (P97). */
/** 0.3.28 (contract R): "traffic_check" = Shopee's anti-bot page (/verify/traffic…): readers, fills and read-backs pause 6 h. */
export type ReaderBlockReason = "captcha" | "login" | "password_recheck" | "rate_limit" | "traffic_check";

/** One scheduler tick that started from rest: what woke it and how it ended (a skip reason or a start). */
export interface TickRecord {
  at: string;
  trigger: string;
  result: string;
}

/** The ads history of one shop: the planned days (fixed at its start), the days read, how it ended. */
export interface AdsHistory {
  shopId: string;
  createdAt: string;
  /** GMT+7 days, newest first. */
  days: string[];
  done: string[];
  status: "running" | "done";
  /** The oldest day read so far. */
  earliest?: string;
  /** Shopee refused this day (the end of what it keeps): older days are not asked for. */
  limit?: { day: string; code: string; at: string };
}

/** The tab-opening schedule's bookkeeping. */
export interface ReaderSchedule {
  /** 0.3.19: the last tick from rest and the last few (every skip reason is kept, newest last). */
  lastTick?: TickRecord;
  tickLog?: TickRecord[];
  /** Why the pending one-off start alarm was set (pair / boot / retry). */
  kick?: { reason: string; at: string };
  /** What was last told to Juli (one report per distinct result per day). */
  tickReported?: { day: string; key: string };
  /** Shop traffic days (traffic_overview confirmed) posted by the traffic reader (last 14). */
  trafficOverviewDone?: string[];
  /** Orders: the GMT+7 day of the last run that read back to its `sinceDay` (complete). */
  ordersCoveredDay?: string;
  /** When the product list (with stock) last posted its item_snapshot (ms). */
  productsAt?: number;
  /** The once-per-shop 90-day ads history (0.3.19), kept beside the 30-day mydata backfill. */
  adsHistory?: AdsHistory;
  /** The 06:30 stock run: its GMT+7 day, attempts that day, and the last outcome. */
  stock?: { day: string; attempts: number; at?: string; outcome?: string };
  lastRunDay?: string;
  lastRun?: { day: string; at: string; outcomes: Record<string, string>; blocked?: ReaderBlockReason };
  run?: ReaderRun;
  /** 0.3.25: pages blocked today by a login / password wall, to read again once the block clears (once per clear). */
  reread?: { day: string; pages: ReaderId[]; /** 0.3.29: the section a data call proved alive. */ section?: string };
  /** 0.3.29 (F4.3): a data call proved a section while a run was going: re-read its blocked pages when the run ends. */
  rereadAfterRun?: { day: string; section?: string };
  /** 0.3.29 (F4.2, contract C2): the backend's hole list of today (days missing per dataset). */
  holes?: { day: string; datasets: Record<string, string[]> };
  /** 0.3.29 (F4.4): the items with product views in the last product-table read (most viewed first): item traffic reads these. */
  viewedItems?: { day: string; ids: string[] };
  /** 0.3.29 (F4.9): when a per-order income read last landed (ms): orders completed since then are queued. */
  incomeReadAt?: number;
  /** 0.3.25: re-read starts today (capped, so a dialog that keeps coming back cannot loop). */
  rereadCount?: { day: string; n: number };
  /** 0.3.31: failed reader runs today (outcome not "done"); at READER_FAIL_ATTEMPTS_PER_DAY the page waits until tomorrow. */
  readerFails?: { day: string; counts: Partial<Record<ReaderId, number>> };
  /** 0.3.27 (contract C): pages a read-back job asked for, read in a run of their own as soon as possible. */
  readback?: { pages: ReaderId[]; at: string; /** 0.3.32: not before this time (ms): Phân tích Nội dung after 13:30. */ notBefore?: number };
  /** 0.3.27: when each page last finished "done" (ms), for the read-back's captured. */
  readAt?: Partial<Record<ReaderId, number>>;
  /** A CAPTCHA / login wall stopped the readers: nothing is opened before `until` (ms since epoch). */
  blocked?: { at: string; reason: ReaderBlockReason; page: ReaderId; until: number };
  /** Legacy (≤ 0.3.5): days marked read whether or not their upload landed. No longer read. */
  adsDone: string[];
  /** Ads days whose upload Juli accepted (trimmed to the last 14): a missed, empty or failed day
   * stays in the plan until it posts. Replaces `adsDone`, which also counted failed days. */
  adsPosted?: string[];
  /** Item-traffic days read for every item (trimmed to the last 14). */
  trafficDone?: string[];
  /** Active, visible item ids of the shop, from the last product-list read. */
  itemIds?: string[];
  /** The GMT+7 day the campaign settings were last posted (Connector 0.3.11). */
  adsSettingsDay?: string;
  /** Ongoing / scheduled product campaigns from that list read: the ads_detail work list. */
  adsCampaigns?: { id: string; kind: string; name?: string }[];
  /** Shop totals (0.3.11): the GMT+7 day they last posted, and the shop whose 30-day backfill is done. */
  totalsDay?: string;
  totalsBackfilledShop?: string;
  /** Product table (0.3.12): the day it was last read and posted. */
  productPeriodDay?: string;
  /** Order lines (0.3.11): the day the list was last read and posted. */
  ordersDay?: string;
  /**
   * Per-order income (0.3.11): completed orders waiting for their income read, oldest first. The raw
   * order ids stay in this browser (chrome.storage.local) -- only hashed refs are ever posted.
   */
  incomeQueue?: IncomeQueued[];
  /** 0.3.32: orders whose SKU-less lines were posted "unresolved_item": never queued for their lines again (newest last, capped). */
  pageFixGivenUp?: string[];
  /** Orders completing before this time (ms) were queued already: only later ones are added. */
  incomeSince?: number;
  incomeDay?: string;
  /** The shop whose 6-month affiliate conversion history was posted (0.3.17): read once per shop. */
  affiliateHistoryShop?: string;
}

/** The market search run's bookkeeping (P92 B-10), kept apart from the Seller Centre readers'. */
export interface MarketSchedule {
  lastRunDay?: string;
  lastRun?: { day: string; at: string; outcomes: Record<string, string>; blocked?: ReaderBlockReason };
  run?: MarketRun;
  blocked?: { at: string; reason: ReaderBlockReason; until: number };
  /** keyword -> the GMT+7 day it was last read and accepted (trimmed). */
  lastRead: Record<string, string>;
}

export interface MarketRun {
  day: string;
  startedAt: number;
  keywords: string[];
  index: number;
  current?: { tabId: number; openedAt: number };
  nextAt?: number;
  outcomes: Record<string, string>;
}

export interface State {
  token?: TokenInfo;
  stopped: Partial<Record<Dataset, Stop>>;
  lastSync?: { day: string; at: string; status: string };
  lastPosts: Partial<Record<Dataset, { at: string; rows: number; duplicate: boolean }>>;
  pendingSync?: boolean;
  queue: Queued[];
  lastError?: { at: string; code: string };
  backfill?: Backfill;
  /** Juli answered 403 consent_required: nothing is sent until the seller retries or pairs again. */
  consentBlocked?: { at: string };
  readers?: ReaderSchedule;
  market?: MarketSchedule;
  /** Requests sent to Seller Centre today (GMT+7), all readers + sync + backfill together. */
  budget?: RequestBudget;
  /** Fill jobs (P97 D85.6): the page being worked on and the poll bookkeeping. */
  fill?: FillJobsState;
}


/** What today's readers may still spend: while a backfill runs, its share is left alone. */
export function readerRequestsLeft(state: Pick<State, "budget" | "backfill">, day: string): number {
  const share = state.backfill?.status === "running" ? BACKFILL_REQUEST_SHARE : 0;
  return Math.max(0, requestsLeft(state, day) - share - FILL_REQUEST_RESERVE);
}

export const MAX_QUEUE = 20;

export async function loadState(storage: Storage): Promise<State> {
  const raw = (await storage.get([
    "token",
    "stopped",
    "lastSync",
    "lastPosts",
    "pendingSync",
    "queue",
    "lastError",
    "backfill",
    "consentBlocked",
    "readers",
    "market",
    "budget",
    "fill",
  ])) as Partial<State>;
  return {
    token: raw.token,
    stopped: raw.stopped ?? {},
    lastSync: raw.lastSync,
    lastPosts: raw.lastPosts ?? {},
    pendingSync: raw.pendingSync,
    queue: raw.queue ?? [],
    lastError: raw.lastError,
    backfill: raw.backfill,
    consentBlocked: raw.consentBlocked,
    readers: raw.readers,
    market: raw.market,
    budget: raw.budget,
    fill: raw.fill,
  };
}

/** Datasets stopped for THIS extension version (a new version tries again). */
export function stoppedFor(state: State, version: string): Set<Dataset> {
  return new Set(
    (Object.entries(state.stopped) as [Dataset, Stop | undefined][])
      .filter(([, stop]) => stop?.version === version)
      .map(([dataset]) => dataset),
  );
}

export function enqueue(queue: Queued[], item: Queued): Queued[] {
  return [...queue, item].slice(-MAX_QUEUE);
}
