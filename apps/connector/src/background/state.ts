// What the extension keeps in chrome.storage.local: the ingest token (never a
// Juli password or session), per-dataset stops after drift, the last sync, and a
// small retry queue of posts that failed on the network.

import { BACKFILL_REQUEST_SHARE, DAILY_REQUEST_BUDGET, TODAY_REQUEST_RESERVE, type Dataset, type ReaderId } from "../config";
import type { IngestBody, TokenInfo } from "../ingest/client";

export interface Stop {
  version: string;
  at: string;
  unexpected: string[];
  missing: string[];
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
  /** affiliate: older purchase windows to read once (0.3.17). */
  history?: { start: string; end: string }[];
}

/** One scheduled run: the pages in order, one open tab at a time (persisted: the worker may restart). */
export interface ReaderRun {
  /** The GMT+7 day the run belongs to (one run per day). */
  day: string;
  startedAt: number;
  jobs: PlannedJob[];
  index: number;
  current?: { tabId: number; openedAt: number; sentAt?: number; reopened?: boolean };
  /** No page is opened before this time (ms since epoch): the gap between pages. */
  nextAt?: number;
  /** Per page id: how it ended. */
  outcomes: Record<string, string>;
}

/** `rate_limit`: HTTP 429 / 403 or Shopee wording for "too many requests" (P97). */
export type ReaderBlockReason = "captcha" | "login" | "rate_limit";

/** The tab-opening schedule's bookkeeping. */
export interface ReaderSchedule {
  lastRunDay?: string;
  lastRun?: { day: string; at: string; outcomes: Record<string, string>; blocked?: ReaderBlockReason };
  run?: ReaderRun;
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
  incomeQueue?: { id: string; sn?: string; completedAt: number }[];
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

/** The fill-job runner's bookkeeping. At most one page is open for a job at a time. */
export interface FillJobsState {
  active?: { id: string; tabId?: number; openedAt: number; counted: boolean };
  /** Jobs this browser already opened by itself (never again by the poll; the person re-opens). */
  autoOpened: string[];
  lastPoll?: { at: string; status: string };
  /** The last Juli command this browser ran ("Đối chiếu ngay"), and the one still to acknowledge. */
  lastCommand?: string;
  doneCommand?: string;
}

/** The shared daily request budget's counter. */
export interface RequestBudget {
  day: string;
  used: number;
}

/** Requests left today (the budget resets with the GMT+7 day). */
export function requestsLeft(state: Pick<State, "budget">, day: string): number {
  const used = state.budget?.day === day ? state.budget.used : 0;
  return Math.max(0, DAILY_REQUEST_BUDGET - used);
}

/** What the 30-day backfill may still spend today: the budget minus the share reserved for today's readers. */
export function backfillRequestsLeft(state: Pick<State, "budget">, day: string): number {
  return Math.max(0, requestsLeft(state, day) - TODAY_REQUEST_RESERVE);
}

/** What today's readers may still spend: while a backfill runs, its share is left alone. */
export function readerRequestsLeft(state: Pick<State, "budget" | "backfill">, day: string): number {
  const share = state.backfill?.status === "running" ? BACKFILL_REQUEST_SHARE : 0;
  return Math.max(0, requestsLeft(state, day) - share);
}

/** Count `count` more requests today. Read-modify-write: sync, backfill and the scheduler never overlap. */
export async function addRequests(storage: Storage, day: string, count: number): Promise<void> {
  if (count <= 0) return;
  const raw = (await storage.get(["budget"])) as Partial<State>;
  const used = raw.budget?.day === day ? raw.budget.used : 0;
  await saveState(storage, { budget: { day, used: used + count } });
}

export const MAX_QUEUE = 20;

export interface Storage {
  get(keys?: string | string[] | null): Promise<Record<string, unknown>>;
  set(items: Record<string, unknown>): Promise<void>;
}

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

export async function saveState(storage: Storage, patch: Partial<State>): Promise<void> {
  const clean: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(patch)) clean[key] = value ?? null;
  await storage.set(clean);
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
