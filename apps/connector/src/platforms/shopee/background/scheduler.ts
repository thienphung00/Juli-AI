// The tab-opening schedule (ADR-120 d.14): once a day the Connector opens the Seller Centre
// report pages itself, ONE background tab at a time, lets the page hook read each page's own
// endpoints, closes the tab, and moves on after a gap. Read-only, the seller's own session.
// It never clicks anything. A login wall or CAPTCHA on one page, while a page of the other Seller
// Centre section read fine in this run, blocks that page only (0.3.22, "blocked:login"); a second
// one in the same section blocks the section's other pages; anything else stops the whole run.
//
// An MV3 service worker can be stopped at any time, so the run is a state machine kept in
// chrome.storage.local and advanced by events (alarm, tab ready, page result, tab closed).
// Chrome is injected (SchedulerDeps) so the whole thing is unit-tested with fakes.

import {
  ADS_CATCHUP_DAYS,
  ADS_HISTORY_DAY_COST,
  ADS_HISTORY_DAYS,
  ADS_HISTORY_DAYS_PER_RUN,
  ADS_JOB_TIMEOUT_MS,
  AFFILIATE_HISTORY_WINDOWS,
  AFFILIATE_WINDOW_DAYS,
  ADS_DETAIL_MAX_CAMPAIGNS,
  ADS_PRODUCTS_MAX_CAMPAIGNS,
  type Dataset,
  HELD_DATASETS,
  ORDER_INCOME_FIRST_RUN_DAYS,
  ORDER_INCOME_MAX_PER_DAY,
  ORDER_INCOME_MAX_FAILED_DAYS,
  ORDER_INCOME_QUEUE_DAYS,
  ORDER_INCOME_QUEUE_MAX,
  ORDER_CATCHUP_FIRST_DAYS,
  ORDER_CATCHUP_MAX_DAYS,
  ORDER_CATCHUP_OVERLAP_DAYS,
  ORDERS_JOB_TIMEOUT_MS,
  READER_KICK_DELAY_MINUTES,
  READER_KICK_RETRY_MINUTES,
  READER_REREAD_DELAY_MINUTES,
  READER_REREAD_MAX_PER_DAY,
  STOCK_MAX_ATTEMPTS_PER_DAY,
  STOCK_READ_HOUR_GMT7,
  STOCK_READ_MINUTE,
  TRAFFIC_OVERVIEW_CATCHUP_DAYS,
  READER_BLOCK_CAPTCHA_MS,
  READER_BLOCK_LOGIN_MS,
  READER_BLOCK_RATE_MS,
  READER_PAGE_LOAD_COST,
  SHOP_TOTALS_BACKFILL_DAYS,
  SHOP_TOTALS_REFRESH_DAYS,
  READER_DATASETS,
  READER_IDS,
  READER_JOB_TIMEOUT_MS,
  READER_LOAD_GRACE_MS,
  READER_PAGE_GAP_JITTER_MS,
  READER_PAGE_GAP_MS,
  READER_WATCHDOG_ALARM_MINUTES,
  type ReaderDataset,
  type ReaderId,
  readerActive,
  schedulerActive,
  TRAFFIC_CATCHUP_DAYS,
  TRAFFIC_JOB_TIMEOUT_MS,
  TRAFFIC_MAX_ITEMS,
} from "../config";
import { completedOrders, incomeReadIds, zeroRowsStep } from "../orders-map";
import { activeItemIds, adsDayAnswer, completedTrafficDays, ongoingAdsCampaigns } from "../reader-map";
import type { CaptureOutcome } from "./connector";
import { READER_PAGES, readerPageUrl, readerSection } from "../endpoints";
import { blockedPath, classify, type ReaderJob, type ReaderResponse } from "../reader";
import { gmt7Date, gmt7DateStart, lastFinishedDays } from "../../../core/time";
import {
  type PlannedJob,
  type ReaderBlockReason,
  type ReaderRun,
  type ReaderSchedule,
  type AdsHistory,
  addRequests,
  backfillRequestsLeft,
  loadState,
  readerRequestsLeft,
  requestsLeft,
  saveState,
  type TickRecord,
  type Storage,
  stoppedFor,
  type State,
} from "./state";

export const READER_RUN_ALARM = "juli-reader-run";
export const READER_WATCHDOG_ALARM = "juli-reader-watch";
/** 0.3.19: a one-off start (after pairing, a service-worker start, or a retry after a busy tick). */
export const READER_KICK_ALARM = "juli-reader-kick";
/** 0.3.19: the fixed daily 06:30 GMT+7 stock read (the product list only). */
export const STOCK_ALARM = "juli-stock-run";
const TICK_LOG_KEPT = 20;
/** 0.3.22: walls in a row in one section that block its remaining pages for the run. */
export const SECTION_WALLS_BLOCK = 2;
const TRAFFIC_OVERVIEW_DONE_KEPT = 14;

/** 06:30 GMT+7 of a GMT+7 day, in ms. */
export function stockDueAt(day: string): number {
  return (gmt7DateStart(day) + STOCK_READ_HOUR_GMT7 * 3600 + STOCK_READ_MINUTE * 60) * 1000;
}

/** The next 06:30 GMT+7 strictly after `nowMs` (the stock alarm's `when`). */
export function nextStockAt(nowMs: number): number {
  const today = stockDueAt(gmt7Date(Math.floor(nowMs / 1000)));
  return today > nowMs ? today : today + 86_400_000;
}

/** The GMT+7 day `n` days before `day`. */
export function dayMinus(day: string, n: number): string {
  return gmt7Date(gmt7DateStart(day) - n * 86_400);
}

/** The day the orders job reads back to: the first run 14 days; later the last complete read minus 3, at most 30. */
export function ordersSinceDay(today: string, coveredDay: string | undefined): string {
  if (!coveredDay) return dayMinus(today, ORDER_CATCHUP_FIRST_DAYS);
  const since = dayMinus(coveredDay, ORDER_CATCHUP_OVERLAP_DAYS);
  const floor = dayMinus(today, ORDER_CATCHUP_MAX_DAYS);
  return since < floor ? floor : since;
}

/** What the scheduler tells Juli about a tick (0.3.19): metadata only, never a body. */
export interface TickReport {
  kind: "run" | "skip";
  trigger: string;
  result: string;
  day: string;
  at: string;
  outcomes?: Record<string, string>;
}
/** A run older than this is a crash leftover and is dropped. */
const RUN_MAX_AGE_MS = 3 * 3_600_000;
const ADS_DONE_KEPT = 14;
const TRAFFIC_DONE_KEPT = 14;

export interface SchedulerTabs {
  /** Open `url` in a background (inactive) tab; the tab id, or undefined when it could not open. */
  open(url: string): Promise<number | undefined>;
  close(tabId: number): Promise<void>;
  send(tabId: number, message: unknown): Promise<unknown>;
  /** Whether the tab still exists and its URL (undefined when the host is not visible to us). */
  inspect(tabId: number): Promise<{ open: boolean; url?: string; discarded?: boolean }>;
}

export interface SchedulerAlarms {
  create(name: string, info: { when?: number; delayInMinutes?: number; periodInMinutes?: number }): Promise<void>;
  clear(name: string): Promise<unknown>;
}

/** What Ops sees of a stop: which reader, which page, what happened and when (never a body). */
export interface BlockEvent {
  reader: string;
  page: string;
  /** 0.3.26: "no_permission" blocks one page (never the run), so it is not a ReaderBlockReason. */
  status: ReaderBlockReason | "no_permission";
  code?: string;
  at: string;
}

export interface SchedulerDeps {
  storage: Storage;
  tabs: SchedulerTabs;
  alarms: SchedulerAlarms;
  /** Posts a finished job's responses (the Connector). */
  sink: {
    postReader(job: ReaderJob, responses: ReaderResponse[]): Promise<Record<string, string>>;
    /** A stop that halts every reader (CAPTCHA, login wall, 429 / 403): told to Juli so Ops can see it. */
    reportBlock?(event: BlockEvent): Promise<void>;
    /** 0.3.19: a finished run, or a tick that skipped (each distinct result once a day), told to Juli. */
    reportTick?(report: TickReport): Promise<void>;
  };
  /** The 30-day backfill has a day in flight: do not start a run on top of it. */
  backfillBusy: () => Promise<boolean>;
  origin: string;
  version: string;
  now: () => number;
  random?: () => number;
  /** Best effort: call `fn` after `ms` (the watchdog alarm is the guarantee). */
  later?: (ms: number, fn: () => void) => void;
  /** The readers a run may open, in order (default READER_IDS). */
  readers?: readonly ReaderId[];
  /** The 06:30 stock run (default on; off in tests of the daily run alone). */
  stockRun?: boolean;
}

/** The pages to open today, in order: products, vouchers, ads (one tab, several days), health. */
export function planJobs(args: {
  shopId: string | undefined;
  nowMs: number;
  stopped: ReadonlySet<Dataset>;
  adsDone: readonly string[];
  trafficDone?: readonly string[];
  /** The GMT+7 day the list's campaign settings were last posted (Connector 0.3.11). */
  adsSettingsDay?: string;
  /** Shop totals (0.3.11): the day they last posted; whether the 30-day backfill is done for this shop. */
  totalsDay?: string;
  totalsBackfilled?: boolean;
  /** The day the 30-day product table was last read and posted (0.3.12). */
  productPeriodDay?: string;
  ordersDay?: string;
  /** The day the per-order income was last read. */
  incomeDay?: string;
  /** The shop whose affiliate history is posted already (0.3.17). */
  affiliateHistoryShop?: string;
  /** Shop traffic days already posted by the traffic reader (0.3.19). */
  trafficOverviewDone?: readonly string[];
  /** Orders: the day of the last complete by-date read (0.3.19). */
  ordersCoveredDay?: string;
  /** The product list was read (with stock) today after 06:30 and its ids are known: not again today. */
  productsFresh?: boolean;
  /** Older ads days of the once-per-shop history to read in this run (0.3.19), newest first. */
  adsHistoryDays?: readonly string[];
  held?: ReadonlySet<ReaderDataset>;
  readers?: readonly ReaderId[];
}): PlannedJob[] {
  const todayDay = gmt7Date(Math.floor(args.nowMs / 1000));
  const held = args.held ?? HELD_DATASETS;
  const jobs: PlannedJob[] = [];
  for (const id of args.readers ?? READER_IDS) {
    if (!readerActive(id, args.shopId)) continue;
    // A page is only worth opening while at least one of its datasets can be posted.
    const postable = READER_DATASETS[id].some((dataset) => !held.has(dataset as ReaderDataset) && !args.stopped.has(dataset));
    if (!postable) continue;
    if (id === "products") {
      if (!args.productsFresh) jobs.push({ id });
    } else if (id === "traffic") {
      const days = lastFinishedDays(args.nowMs, 1 + TRAFFIC_OVERVIEW_CATCHUP_DAYS).filter(
        (day) => !(args.trafficOverviewDone ?? []).includes(day),
      );
      if (days.length > 0) jobs.push({ id, days });
    } else if (id === "ads") {
      const days = lastFinishedDays(args.nowMs, 1 + ADS_CATCHUP_DAYS).filter((day) => !args.adsDone.includes(day));
      // Every day posted: the list is still opened once a day for its campaign settings, once
      // a first settings capture has been recorded (before that, an open day always exists).
      const settingsDue = args.adsSettingsDay !== undefined && args.adsSettingsDay !== gmt7Date(Math.floor(args.nowMs / 1000));
      const historyDays = (args.adsHistoryDays ?? []).filter((day) => !days.includes(day));
      if (days.length > 0 || settingsDue || historyDays.length > 0) {
        jobs.push({ id, days, ...(historyDays.length > 0 ? { historyDays: [...historyDays] } : {}) });
      }
    } else if (id === "item_traffic") {
      // The item ids are filled in when the job's turn comes (the product list is read first).
      const days = lastFinishedDays(args.nowMs, 1 + TRAFFIC_CATCHUP_DAYS).filter(
        (day) => !(args.trafficDone ?? []).includes(day),
      );
      if (days.length > 0) jobs.push({ id, days });
    } else if (id === "shop_totals") {
      // 30 days right after pairing, then the last 7 finished days once a day (placed / paid settle late).
      if (args.totalsDay !== todayDay) {
        const count = args.totalsBackfilled ? SHOP_TOTALS_REFRESH_DAYS : SHOP_TOTALS_BACKFILL_DAYS;
        jobs.push({ id, days: lastFinishedDays(args.nowMs, count) });
      }
    } else if (id === "product_period") {
      // The 30-day product table, once a day (one page open; at most PRODUCT_PERIOD_MAX_PAGES requests).
      if (args.productPeriodDay !== todayDay) jobs.push({ id });
    } else if (id === "orders") {
      if (args.ordersDay !== todayDay) jobs.push({ id, sinceDay: ordersSinceDay(todayDay, args.ordersCoveredDay) });
    } else if (id === "order_income") {
      // Planned every day, right after "orders" (which fills the queue in the same run); its turn
      // opens nothing when no completed order is waiting.
      if (args.incomeDay !== todayDay) jobs.push({ id });
    } else if (id === "affiliate" && args.shopId && args.affiliateHistoryShop !== args.shopId) {
      jobs.push({ id, history: affiliateHistoryWindows(args.nowMs) });
    } else {
      jobs.push({ id });
    }
  }
  return jobs;
}

/**
 * The once-per-shop affiliate history (0.3.17): AFFILIATE_HISTORY_WINDOWS windows of 30 days
 * right before the regular 30-day window, newest first, each ≤ 31 days (Juli's period cap).
 */
export function affiliateHistoryWindows(nowMs: number): { start: string; end: string }[] {
  const recent = lastFinishedDays(nowMs, AFFILIATE_WINDOW_DAYS + AFFILIATE_WINDOW_DAYS * AFFILIATE_HISTORY_WINDOWS);
  const older = [...recent].sort().reverse().slice(AFFILIATE_WINDOW_DAYS);
  const windows: { start: string; end: string }[] = [];
  for (let i = 0; i < older.length; i += AFFILIATE_WINDOW_DAYS) {
    const chunk = older.slice(i, i + AFFILIATE_WINDOW_DAYS);
    windows.push({ start: chunk[chunk.length - 1] as string, end: chunk[0] as string });
  }
  return windows;
}

/**
 * An ads day is read when its campaigns were posted, or Shopee answered with no campaign of its own
 * (an empty list, or only shop-level entries). A day that came back with just the ROAS-target row
 * stays in the plan (F3, 0.3.11).
 */
export function adsDayRead(outcome: CaptureOutcome | undefined, responses: ReaderResponse[], day: string): boolean {
  if (outcome !== "posted" && outcome !== "ignored") return false;
  const answer = adsDayAnswer(responses, day);
  if (!answer.complete) return false;
  return outcome === "posted" || answer.withId === 0;
}

/** The ids of a fresh product-list read; the previous ids are kept when the read found none. */
/** The hook's detail as an outcome note: a short endpoint / http-status reason, nothing else. */
function outcomeNote(detail: unknown): string {
  return typeof detail === "string" ? detail.replace(/\s+/g, " ").trim().slice(0, 80) : "";
}

function ids(responses: ReaderResponse[], previous: string[] | undefined): string[] | undefined {
  const fresh = activeItemIds(responses);
  return fresh.length > 0 ? fresh : previous;
}

/** Reader notes that already name the step a 0-row orders run stopped at (0.3.26). */
const ZERO_ROW_NOTES: ReadonlySet<string> = new Set(["no_ids_from_page", "no_order_key"]);

/**
 * "error:<job>:0_rows:<step>[|<note>]" (0.3.26): WHY a run mapped 0 rows, metadata only. The step is
 * the dataset's own outcome when it was not plain "ignored" (drift, rejected, ...), else the
 * reader's step note, else what the answers show (zeroRowsStep); the reader's note is kept.
 */
function zeroRows(job: "orders" | "order_income", outcome: string | undefined, note: string, responses: ReaderResponse[]): string {
  const step =
    outcome && outcome !== "ignored"
      ? outcome
      : ZERO_ROW_NOTES.has(note)
        ? note
        : note && !responses.some((r) => r.endpoint.startsWith("order"))
          ? note
          : zeroRowsStep(job, responses);
  return `error:${job}:0_rows:${step}${note && note !== step ? `|${note}` : ""}`.slice(0, 120);
}

/**
 * A finished job's outcome string (0.3.20: truthful). The orders reader that read the list page
 * but produced no order line is an error ("orders:0_rows:<step>", 0.3.26 says which step), never
 * "read and sent"; a list page with no orders (or none since the job's day) was read and had
 * nothing to send: "done:order_lines=empty" (0.3.26; "no_orders" stays the income page's "no
 * completed order to read"). An income read that posted nothing is "order_income:0_rows:<step>".
 */
export function jobOutcome(id: ReaderId, posted: Record<string, string>, summary: string, note: string, responses: ReaderResponse[] = []): string {
  if (id === "orders") {
    if (note === "no_orders" || note === "no_new_orders") return "done:order_lines=empty";
    const lines = posted.order_lines;
    if (lines !== "posted" && lines !== "queued") return zeroRows("orders", lines, note, responses);
  }
  if (id === "order_income") {
    const income = posted.order_income;
    if (income !== "posted" && income !== "queued") return zeroRows("order_income", income, note, responses);
  }
  return `${summary ? `done:${summary}` : "done"}${note ? `|${note}` : ""}`;
}

/** Tick results that mean "nothing started" for a reason worth telling Juli (once a day each). */
const SKIP_RESULTS: ReadonlySet<string> = new Set([
  "off",
  "consent_required",
  "blocked",
  "backfill_busy",
  "nothing_to_do",
]);

/** A read-back's pages start this soon (minutes; Chrome rounds alarms up to its own minimum). */
const READBACK_KICK_MINUTES = 0.1;

export class ReaderScheduler {
  private lock: Promise<unknown> = Promise.resolve();

  constructor(private readonly deps: SchedulerDeps) {}

  private exclusive<T>(work: () => Promise<T>): Promise<T> {
    const next = this.lock.then(work, work);
    this.lock = next.catch(() => undefined);
    return next;
  }

  private iso(): string {
    return new Date(this.deps.now()).toISOString();
  }

  private async load(): Promise<{ state: State; sched: ReaderSchedule }> {
    const state = await loadState(this.deps.storage);
    return { state, sched: state.readers ?? { adsDone: [], trafficDone: [] } };
  }

  private save(sched: ReaderSchedule): Promise<void> {
    return saveState(this.deps.storage, { readers: sched });
  }

  private gap(): number {
    const random = this.deps.random ?? Math.random;
    return READER_PAGE_GAP_MS + Math.floor(random() * READER_PAGE_GAP_JITTER_MS);
  }

  /** Tab ids the scheduler holds open (the Connector must not use them for the daily sync). */
  async activeTabIds(): Promise<number[]> {
    const { sched } = await this.load();
    const tabId = sched.run?.current?.tabId;
    return tabId === undefined ? [] : [tabId];
  }

  /** A run is in progress (the Seller Centre pace budget is taken). */
  async isBusy(): Promise<boolean> {
    const { sched } = await this.load();
    return !!sched.run && this.deps.now() - sched.run.startedAt < RUN_MAX_AGE_MS;
  }

  /** The alarm / watchdog / "Đồng bộ" entry point: start today's run, or advance the one running.
   * ``manual`` (the seller pressed "Đồng bộ"): after today's run, read again only the days that
   * are still missing (ads, item traffic) instead of answering ``done_today``. */
  tick(options: { manual?: boolean; trigger?: string } = {}): Promise<string> {
    return this.exclusive(async () => {
      const { sched } = await this.load();
      const now = this.deps.now();
      if (sched.run) {
        if (now - sched.run.startedAt >= RUN_MAX_AGE_MS) return this.finishRun(sched, sched.run, undefined, "expired");
        return this.advance(sched, sched.run);
      }
      // From rest: what woke the scheduler is recorded with how the tick ended (0.3.19).
      const trigger =
        options.trigger === "kick" ? (sched.kick?.reason ?? "kick") : (options.trigger ?? (options.manual ? "manual" : "alarm"));
      const kickReason = options.trigger === "kick" ? sched.kick?.reason : undefined;
      if (options.trigger === "kick" && sched.kick) await this.save({ ...sched, kick: undefined });
      const result = await this.start({ ...options, ...(kickReason ? { kickReason } : {}) });
      await this.record(trigger, result);
      return result;
    });
  }

  /** The stock run is due: the product list has not been read since today's 06:30 GMT+7. */
  private stockDue(sched: ReaderSchedule, shopId: string | undefined, now: number, today: string): boolean {
    if (this.deps.stockRun === false || !readerActive("products", shopId)) return false;
    if (this.deps.readers && !this.deps.readers.includes("products")) return false;
    const dueAt = stockDueAt(today);
    if (now < dueAt || (sched.productsAt ?? 0) >= dueAt) return false;
    return !(sched.stock?.day === today && sched.stock.attempts >= STOCK_MAX_ATTEMPTS_PER_DAY);
  }

  /** A start from rest: the stock run when due, else today's run; or why nothing started. */
  private async start(options: { manual?: boolean; kickReason?: string }): Promise<string> {
    const { state, sched } = await this.load();
    const now = this.deps.now();
    const shopId = state.token?.shop_id;
    if (!state.token) return "unpaired";
    if (!schedulerActive(shopId)) return "off";
    if (state.consentBlocked) return "consent_required";
    if (sched.blocked && sched.blocked.until > now) return "blocked";
    const today = gmt7Date(Math.floor(now / 1000));
    // 0.3.27 (contract C): a read-back's pages first, in a run of their own (the day's run is untouched)
    const asked = (sched.readback?.pages ?? []).filter((id) => readerActive(id, shopId));
    if (asked.length > 0) {
      if (await this.deps.backfillBusy()) {
        await this.setKick("readback", READER_KICK_RETRY_MINUTES);
        return "backfill_busy";
      }
      const run: ReaderRun = { day: today, startedAt: now, jobs: asked.map((id) => ({ id })), index: 0, outcomes: {}, trigger: "readback" };
      const next: ReaderSchedule = { ...sched, blocked: undefined, run, readback: undefined };
      await this.save(next);
      await this.deps.alarms.create(READER_WATCHDOG_ALARM, {
        delayInMinutes: READER_WATCHDOG_ALARM_MINUTES,
        periodInMinutes: READER_WATCHDOG_ALARM_MINUTES,
      });
      return `readback:${await this.startNext(next, run)}`;
    }
    if (sched.readback) await this.save({ ...sched, readback: undefined });
    if (this.stockDue(sched, shopId, now, today)) {
      if (await this.deps.backfillBusy()) {
        await this.setKick("retry", READER_KICK_RETRY_MINUTES);
        return "backfill_busy";
      }
      const attempts = (sched.stock?.day === today ? sched.stock.attempts : 0) + 1;
      const run: ReaderRun = { day: today, kind: "stock", startedAt: now, jobs: [{ id: "products" }], index: 0, outcomes: {} };
      const next = { ...sched, blocked: undefined, run, stock: { day: today, attempts, at: this.iso() } };
      await this.save(next);
      await this.deps.alarms.create(READER_WATCHDOG_ALARM, {
        delayInMinutes: READER_WATCHDOG_ALARM_MINUTES,
        periodInMinutes: READER_WATCHDOG_ALARM_MINUTES,
      });
      return `stock:${await this.startNext(next, run)}`;
    }
    const rerun = sched.lastRunDay === today;
    // 0.3.25: pages blocked by a login / password wall earlier today, to read again (once per block clear).
    const reread = sched.reread?.day === today ? sched.reread : undefined;
    if (rerun && !options.manual && !reread) return "done_today";
    if (await this.deps.backfillBusy()) {
      // Before 0.3.19 this waited for tomorrow's alarm: now it tries again in a few minutes.
      await this.setKick(reread ? "reread" : "retry", READER_KICK_RETRY_MINUTES);
      return "backfill_busy";
    }
    const productsFresh = (sched.productsAt ?? 0) >= stockDueAt(today) && (sched.itemIds?.length ?? 0) > 0;
    const adsHistory = this.adsHistoryPlan(sched, shopId as string);
    const adsHistoryDays = this.adsHistoryToday(adsHistory, sched, backfillRequestsLeft(state, today));
    const planned = planJobs({
      shopId,
      nowMs: now,
      stopped: stoppedFor(state, this.deps.version),
      adsDone: sched.adsPosted ?? [],
      trafficDone: sched.trafficDone,
      adsSettingsDay: sched.adsSettingsDay,
      totalsDay: sched.totalsDay,
      totalsBackfilled: sched.totalsBackfilledShop === shopId,
      productPeriodDay: sched.productPeriodDay,
      ordersDay: sched.ordersDay,
      incomeDay: sched.incomeDay,
      affiliateHistoryShop: sched.affiliateHistoryShop,
      trafficOverviewDone: sched.trafficOverviewDone,
      ordersCoveredDay: sched.ordersCoveredDay,
      productsFresh,
      adsHistoryDays,
      ...(this.deps.readers ? { readers: this.deps.readers } : {}),
    });
    // A same-day re-run opens pages that still have missing days. A manual
    // "Đồng bộ" also reopens a page whose last outcome did not post (KOL
    // needs_data_page), otherwise that page waits until tomorrow.
    const retry = new Set(
      Object.entries(sched.lastRun?.outcomes ?? {})
        .filter(([, outcome]) => !String(outcome).startsWith("done"))
        .map(([id]) => id),
    );
    const jobs = rerun
      ? reread && !options.manual
        ? planned.filter((job) => reread.pages.includes(job.id))
        : planned.filter((job) => (job.days?.length ?? 0) > 0 || (options.manual === true && retry.has(job.id)))
      : planned;
    if (rerun && jobs.length === 0) {
      if (reread) await this.save({ ...sched, reread: undefined });
      return "done_today";
    }
    if (jobs.length === 0) {
      await this.save({ ...sched, lastRunDay: today, reread: undefined });
      return "nothing_to_do";
    }
    const rereadCount = reread
      ? { day: today, n: (sched.rereadCount?.day === today ? sched.rereadCount.n : 0) + 1 }
      : sched.rereadCount;
    const run: ReaderRun = { day: today, startedAt: now, jobs, index: 0, outcomes: {}, ...(reread ? { trigger: "reread" } : {}) };
    // The re-read is consumed here: if the dialog comes back it is a new block, never a loop.
    const started: ReaderSchedule = { ...sched, adsHistory, blocked: undefined, run, reread: undefined, ...(rereadCount ? { rereadCount } : {}) };
    await this.save(started);
    await this.deps.alarms.create(READER_WATCHDOG_ALARM, {
      delayInMinutes: READER_WATCHDOG_ALARM_MINUTES,
      periodInMinutes: READER_WATCHDOG_ALARM_MINUTES,
    });
    return this.startNext(started, run);
  }

  /** The shop's ads history: kept while it is this shop's, else a new 90-day plan (newest first). */
  private adsHistoryPlan(sched: ReaderSchedule, shopId: string): AdsHistory {
    if (sched.adsHistory?.shopId === shopId) return sched.adsHistory;
    return {
      shopId,
      createdAt: this.iso(),
      days: lastFinishedDays(this.deps.now(), ADS_HISTORY_DAYS),
      done: [],
      status: "running",
    };
  }

  /** History days for today's run: not read yet, newest first, as many as the backfill's budget part allows. */
  private adsHistoryToday(history: AdsHistory, sched: ReaderSchedule, backfillLeft: number): string[] {
    if (history.status === "done") return [];
    // The last few days belong to the regular ads read (ADS_CATCHUP_DAYS); they count once posted.
    const regular = lastFinishedDays(this.deps.now(), 1 + ADS_CATCHUP_DAYS);
    const read = new Set([...history.done, ...(sched.adsPosted ?? []), ...regular]);
    const room = Math.min(ADS_HISTORY_DAYS_PER_RUN, Math.floor(backfillLeft / ADS_HISTORY_DAY_COST));
    return history.days.filter((day) => !read.has(day)).slice(0, Math.max(0, room));
  }

  /**
   * After an ads job: history days read are done; the first one Shopee refused ends the history (the
   * earliest readable day is the oldest one read). Every planned day read = done.
   */
  private adsHistoryAfter(
    history: AdsHistory | undefined,
    job: PlannedJob,
    posted: Record<string, string>,
    responses: ReaderResponse[],
    adsPosted: readonly string[],
  ): AdsHistory | undefined {
    if (!history || history.status === "done") return history;
    const done = new Set(history.done);
    for (const day of history.days) if (adsPosted.includes(day)) done.add(day);
    let limit = history.limit;
    for (const day of job.historyDays ?? []) {
      if (adsDayRead(posted[`ads_campaign_daily:${day}`] as CaptureOutcome | undefined, responses, day)) {
        done.add(day);
        continue;
      }
      const refused = responses.find(
        (r) => r.day === day && r.endpoint === "ads_homepage" && classify(r.status, r.body) === "error",
      );
      if (refused) {
        const code = (refused.body as { code?: unknown } | null)?.code;
        limit = { day, code: code !== undefined ? `code_${String(code)}` : `http_${refused.status}`, at: this.iso() };
        break;
      }
    }
    const doneDays = history.days.filter((day) => done.has(day));
    const earliest = doneDays[doneDays.length - 1];
    const finished = limit !== undefined || history.days.every((day) => done.has(day));
    return {
      ...history,
      done: doneDays,
      status: finished ? "done" : "running",
      ...(earliest ? { earliest } : {}),
      ...(limit ? { limit } : {}),
    };
  }

  /** Keep the tick (newest last) and tell Juli a skip once per distinct result per day. */
  private async record(trigger: string, result: string): Promise<void> {
    const { sched } = await this.load();
    const rec: TickRecord = { at: this.iso(), trigger, result };
    const day = gmt7Date(Math.floor(this.deps.now() / 1000));
    const skip = SKIP_RESULTS.has(result);
    const key = `skip:${result}`;
    const report = skip && !(sched.tickReported?.day === day && sched.tickReported.key === key);
    await this.save({
      ...sched,
      lastTick: rec,
      tickLog: [...(sched.tickLog ?? []), rec].slice(-TICK_LOG_KEPT),
      ...(report ? { tickReported: { day, key } } : {}),
    });
    if (report) {
      await this.deps.sink.reportTick?.({ kind: "skip", trigger, result, day, at: rec.at }).catch(() => undefined);
    }
  }

  /** Arm the one-off start alarm (kept across worker restarts) and remember why. */
  private async setKick(reason: string, minutes: number): Promise<void> {
    const { sched } = await this.load();
    await this.save({ ...sched, kick: { reason, at: this.iso() } });
    await this.deps.alarms.create(READER_KICK_ALARM, { delayInMinutes: minutes });
  }

  /**
   * 0.3.27 (contract C): a read-back job asked for these pages: they are read in a run of their own
   * as soon as the readers are free (a kick in a few seconds). Idempotent: asking again while
   * pending changes nothing but the kick.
   */
  readNow(pages: readonly ReaderId[]): Promise<void> {
    return this.exclusive(async () => {
      const { sched } = await this.load();
      const have = sched.readback?.pages ?? [];
      const merged = [...new Set([...have, ...pages])];
      await this.save({ ...sched, readback: { pages: merged, at: sched.readback?.at ?? this.iso() }, kick: { reason: "readback", at: this.iso() } });
      await this.deps.alarms.create(READER_KICK_ALARM, { delayInMinutes: READBACK_KICK_MINUTES });
    });
  }

  /** Every page read and posted at or after `sinceMs`. */
  async readSince(pages: readonly ReaderId[], sinceMs: number): Promise<boolean> {
    const { sched } = await this.load();
    return pages.every((id) => (sched.readAt?.[id] ?? 0) >= sinceMs);
  }

  /** Start soon (after pairing, or a worker start that found work due). */
  requestKick(reason: string, minutes: number = READER_KICK_DELAY_MINUTES): Promise<void> {
    return this.exclusive(() => this.setKick(reason, minutes));
  }

  /** Paired, nothing running, and today's run or today's stock read not done yet. */
  due(): Promise<boolean> {
    return this.exclusive(async () => {
      const { state, sched } = await this.load();
      const shopId = state.token?.shop_id;
      if (!state.token || !schedulerActive(shopId) || state.consentBlocked || sched.run) return false;
      const now = this.deps.now();
      if (sched.blocked && sched.blocked.until > now) return false;
      const today = gmt7Date(Math.floor(now / 1000));
      return sched.lastRunDay !== today || this.stockDue(sched, shopId, now, today);
    });
  }

  private async advance(sched: ReaderSchedule, run: ReaderRun): Promise<string> {
    const now = this.deps.now();
    const current = run.current;
    if (current) {
      const jobId = run.jobs[run.index]?.id;
      const limit =
        jobId === "item_traffic"
          ? TRAFFIC_JOB_TIMEOUT_MS
          : jobId === "orders"
            ? ORDERS_JOB_TIMEOUT_MS
            : jobId === "ads"
              ? ADS_JOB_TIMEOUT_MS
              : READER_JOB_TIMEOUT_MS;
      if (now - current.openedAt > limit) {
        if (jobId === "ads" && !current.reopened) return this.retryAds(sched, run);
        return this.finishJob(sched, run, "timeout");
      }
      if (current.sentAt === undefined && now - current.openedAt > READER_LOAD_GRACE_MS) {
        const info = await this.deps.tabs.inspect(current.tabId);
        if (!info.open || info.discarded) return this.tabLost(sched, run);
        if (info.url === undefined || !info.url.startsWith(`${this.deps.origin}/`)) {
          // Redirected away from Seller Centre (or to a host we cannot see): a login wall.
          return this.block(sched, run, "login");
        }
        const wall = blockedPath(new URL(info.url).pathname);
        if (wall) return this.wall(sched, run, wall);
      }
      if (current.sentAt !== undefined && run.jobs[run.index]?.id === "orders") {
        // The order list answers late: Chrome may have closed or discarded the tab meanwhile (0.3.15).
        const info = await this.deps.tabs.inspect(current.tabId);
        if (!info.open || info.discarded) return this.tabLost(sched, run);
      }
      return "waiting";
    }
    if ((run.nextAt ?? 0) > now) return "gap";
    return this.startNext(sched, run);
  }

  private async startNext(sched: ReaderSchedule, run: ReaderRun): Promise<string> {
    let job = run.jobs[run.index];
    if (!job) return this.finishRun(sched, run);
    const sectionWall = run.walls?.[readerSection(job.id)];
    if (sectionWall && sectionWall.count >= SECTION_WALLS_BLOCK) {
      // Two walls in a row in this section: its other pages are not opened in this run.
      const skipped: ReaderRun = { ...run, outcomes: { ...run.outcomes, [job.id]: `blocked:${sectionWall.reason}` }, index: run.index + 1 };
      return skipped.index >= skipped.jobs.length ? this.finishRun(sched, skipped) : this.startNext(sched, skipped);
    }
    if (job.id === "item_traffic") {
      // The ids come from the last product-list read; with none there is nothing to open.
      const itemIds = (sched.itemIds ?? []).slice(0, TRAFFIC_MAX_ITEMS);
      if (itemIds.length === 0) {
        const skipped: ReaderRun = { ...run, outcomes: { ...run.outcomes, [job.id]: "no_items" }, index: run.index + 1 };
        return skipped.index >= skipped.jobs.length ? this.finishRun(sched, skipped) : this.startNext(sched, skipped);
      }
      job = { ...job, itemIds };
      run = { ...run, jobs: run.jobs.map((j, i) => (i === run.index ? (job as PlannedJob) : j)) };
    }
    if (job.id === "ads_detail") {
      // The ongoing campaigns the last list read named; the first one's edit page is opened.
      const campaigns = (sched.adsCampaigns ?? []).slice(0, ADS_DETAIL_MAX_CAMPAIGNS);
      if (campaigns.length === 0) {
        const skipped: ReaderRun = { ...run, outcomes: { ...run.outcomes, [job.id]: "no_campaigns" }, index: run.index + 1 };
        return skipped.index >= skipped.jobs.length ? this.finishRun(sched, skipped) : this.startNext(sched, skipped);
      }
      job = { ...job, campaignIds: campaigns.map((c) => c.id), campaignKinds: campaigns.map((c) => c.kind) };
      run = { ...run, jobs: run.jobs.map((j, i) => (i === run.index ? (job as PlannedJob) : j)) };
    }
    if (job.id === "ads_products") {
      // The group campaigns (manual-mpd pages) the last list read named; the first one's page is opened.
      const groups = (sched.adsCampaigns ?? []).filter((c) => c.kind === "mpd").slice(0, ADS_PRODUCTS_MAX_CAMPAIGNS);
      if (groups.length === 0) {
        const skipped: ReaderRun = { ...run, outcomes: { ...run.outcomes, [job.id]: "no_group_campaigns" }, index: run.index + 1 };
        return skipped.index >= skipped.jobs.length ? this.finishRun(sched, skipped) : this.startNext(sched, skipped);
      }
      job = { ...job, campaignIds: groups.map((c) => c.id), campaignNames: groups.map((c) => c.name ?? "") };
      run = { ...run, jobs: run.jobs.map((j, i) => (i === run.index ? (job as PlannedJob) : j)) };
    }
    if (job.id === "order_income") {
      // Completed orders since the last run, oldest first, at most ORDER_INCOME_MAX_PER_DAY a day.
      const queued = (sched.incomeQueue ?? []).slice(0, ORDER_INCOME_MAX_PER_DAY);
      const orderIds = queued.map((o) => o.id);
      if (orderIds.length === 0) {
        const skipped: ReaderRun = { ...run, outcomes: { ...run.outcomes, [job.id]: "no_orders" }, index: run.index + 1 };
        return skipped.index >= skipped.jobs.length ? this.finishRun(sched, skipped) : this.startNext(sched, skipped);
      }
      job = { ...job, orderIds, orderSns: queued.map((o) => o.sn ?? "") };
      run = { ...run, jobs: run.jobs.map((j, i) => (i === run.index ? (job as PlannedJob) : j)) };
    }
    // The shared daily request budget: nothing is opened once it is spent; the rest waits for tomorrow.
    const { state } = await this.load();
    const left = this.requestsLeftFor(state, run);
    if (left <= READER_PAGE_LOAD_COST) return this.budgetSpent(sched, run);
    const tabId = await this.deps.tabs.open(`${this.deps.origin}${readerPageUrl(job)}`);
    if (tabId === undefined) return this.finishJob(sched, run, "open_failed", false);
    await addRequests(this.deps.storage, run.day, READER_PAGE_LOAD_COST);
    const next = { ...run, current: { tabId, openedAt: this.deps.now() } };
    await this.save({ ...sched, run: next });
    return "opened";
  }

  /**
   * 0.3.20: the ads page timed out once. Its tab is closed and opened again (one reload in the run)
   * for the catch-up days only (the history days wait for the next run). The first tab's requests
   * never came back to be counted, so the most it could have sent is charged to today's budget.
   */
  private async retryAds(sched: ReaderSchedule, run: ReaderRun): Promise<string> {
    const job = run.jobs[run.index] as PlannedJob;
    const current = run.current as NonNullable<ReaderRun["current"]>;
    await this.deps.tabs.close(current.tabId).catch(() => undefined);
    const closed: ReaderRun = { ...run, current: undefined };
    const { state } = await this.load();
    const planned = Math.max(1, (job.days?.length ?? 0) + (job.historyDays?.length ?? 0)) * ADS_HISTORY_DAY_COST;
    await addRequests(this.deps.storage, run.day, Math.min(planned, Math.max(0, this.requestsLeftFor(state, run))));
    const after = (await this.load()).state;
    if (this.requestsLeftFor(after, run) <= READER_PAGE_LOAD_COST) return this.finishJob(sched, closed, "timeout", false);
    const { historyDays: _history, ...retry } = job;
    const tabId = await this.deps.tabs.open(`${this.deps.origin}${readerPageUrl(retry)}`);
    if (tabId === undefined) return this.finishJob(sched, closed, "timeout", false);
    await addRequests(this.deps.storage, run.day, READER_PAGE_LOAD_COST);
    const jobs = run.jobs.map((j, i) => (i === run.index ? retry : j));
    await this.save({ ...sched, run: { ...run, jobs, current: { tabId, openedAt: this.deps.now(), reopened: true } } });
    return "reopened";
  }

  /** The stock run may use the whole daily budget; the daily run leaves a running backfill its share. */
  private requestsLeftFor(state: State, run: ReaderRun): number {
    return run.kind === "stock" ? requestsLeft(state, run.day) : readerRequestsLeft(state, run.day);
  }

  /**
   * The job's tab is gone (closed, or discarded by Chrome) before the page answered. The orders
   * reader opens its page once more (the owner accepts one extra tab for a moment); every other
   * reader, and a second loss, ends the job as ``closed``.
   */
  private async tabLost(sched: ReaderSchedule, run: ReaderRun): Promise<string> {
    const job = run.jobs[run.index];
    const current = run.current;
    if (job?.id === "orders" && current && !current.reopened) {
      await this.deps.tabs.close(current.tabId).catch(() => undefined); // a discarded tab is still there
      const { state } = await this.load();
      if (this.requestsLeftFor(state, run) > READER_PAGE_LOAD_COST) {
        const tabId = await this.deps.tabs.open(`${this.deps.origin}${readerPageUrl(job)}`);
        if (tabId !== undefined) {
          await addRequests(this.deps.storage, run.day, READER_PAGE_LOAD_COST);
          await this.save({ ...sched, run: { ...run, current: { tabId, openedAt: this.deps.now(), reopened: true } } });
          return "reopened";
        }
      }
    }
    return this.finishJob(sched, run, "closed", false);
  }

  private async finishJob(sched: ReaderSchedule, run: ReaderRun, outcome: string, close = true): Promise<string> {
    const job = run.jobs[run.index];
    if (close && run.current) await this.deps.tabs.close(run.current.tabId).catch(() => undefined);
    const outcomes = { ...run.outcomes, ...(job ? { [job.id]: outcome } : {}) };
    // 0.3.27: when each page last read and posted (a read-back's captured waits for it)
    if (job && outcome.startsWith("done")) sched = { ...sched, readAt: { ...sched.readAt, [job.id]: this.deps.now() } };
    const next: ReaderRun = {
      ...run,
      outcomes,
      index: run.index + 1,
      current: undefined,
      nextAt: this.deps.now() + this.gap(),
    };
    if (next.index >= next.jobs.length) return this.finishRun(sched, next);
    await this.save({ ...sched, run: next });
    this.deps.later?.((next.nextAt ?? 0) - this.deps.now() + 1_000, () => void this.tick());
    return outcome;
  }

  private async finishRun(
    sched: ReaderSchedule,
    run: ReaderRun,
    blocked?: ReaderBlockReason,
    outcome = "finished",
  ): Promise<string> {
    if (run.current) await this.deps.tabs.close(run.current.tabId).catch(() => undefined);
    const result = blocked ? `blocked:${blocked}` : outcome;
    if (run.kind === "stock") {
      // The 06:30 stock read: its own bookkeeping; today's daily run is untouched (and starts next).
      await this.save({
        ...sched,
        run: undefined,
        stock: {
          ...(sched.stock ?? { attempts: 1 }),
          day: run.day,
          at: this.iso(),
          outcome: run.outcomes.products ?? result,
        },
      });
      await this.deps.alarms.clear(READER_WATCHDOG_ALARM).catch(() => undefined);
      await this.reportRun("stock", result, run);
      if (!blocked && sched.lastRunDay !== run.day) await this.setKick("after_stock", READER_KICK_DELAY_MINUTES);
      return `stock_${result}`;
    }
    if (run.trigger === "readback") {
      // a read-back's own run: the day's run and its outcomes are untouched
      await this.save({ ...sched, run: undefined });
      await this.deps.alarms.clear(READER_WATCHDOG_ALARM).catch(() => undefined);
      await this.reportRun("readback", result, run);
      return result;
    }
    await this.save({
      ...sched,
      run: undefined,
      lastRunDay: run.day,
      // A re-read keeps the day's earlier outcomes and replaces those of the pages it read again.
      lastRun: {
        day: run.day,
        at: this.iso(),
        outcomes: run.trigger === "reread" && sched.lastRun?.day === run.day ? { ...sched.lastRun.outcomes, ...run.outcomes } : run.outcomes,
        ...(blocked ? { blocked } : {}),
      },
    });
    await this.deps.alarms.clear(READER_WATCHDOG_ALARM).catch(() => undefined);
    await this.reportRun(run.trigger ?? "daily", result, run);
    return result;
  }

  private async reportRun(trigger: string, result: string, run: ReaderRun): Promise<void> {
    await this.deps.sink
      .reportTick?.({ kind: "run", trigger, result, day: run.day, at: this.iso(), outcomes: run.outcomes })
      .catch(() => undefined);
  }

  /** The day's request budget is spent: this job and the rest wait for tomorrow's run. */
  private async budgetSpent(sched: ReaderSchedule, run: ReaderRun): Promise<string> {
    const outcomes = { ...run.outcomes };
    for (const job of run.jobs.slice(run.index)) outcomes[job.id] = "waiting_budget";
    return this.finishRun(sched, { ...run, outcomes }, undefined, "budget_spent");
  }

  /**
   * A login wall or CAPTCHA on the current page (0.3.22). It blocks only this page when a page of
   * ANOTHER section read fine in this run and that section has no wall since: the session is alive,
   * this section asks again (Phân tích bán hàng's password re-confirmation). The run goes on; the
   * page's outcome is "blocked:<reason>", told to Juli in the run report and as a stop event. With
   * no such proof (the first page of a run, or walls in both sections) it is a session-wide logout:
   * the whole run stops as before, so a logged-out session gets no more tabs than before 0.3.22.
   */
  private async wall(sched: ReaderSchedule, run: ReaderRun, reason: "login" | "captcha" | "password_recheck", detail?: string): Promise<string> {
    const job = run.jobs[run.index];
    if (!job || (run.kind === "stock" && reason !== "password_recheck")) return this.block(sched, run, reason, detail);
    const section = readerSection(job.id);
    const walls = run.walls ?? {};
    // The password dialog itself proves the session is logged in: it is always this page only
    // (0.3.25), in any run, even on its first page; no run-wide stop, no cool-down.
    const proof = reason === "password_recheck" || (run.live ?? []).some((s) => s !== section && !walls[s]);
    if (!proof) return this.block(sched, run, reason, detail);
    const count = (walls[section]?.count ?? 0) + 1;
    await this.deps.sink
      .reportBlock?.({
        reader: job.id,
        page: READER_PAGES[job.id].path,
        status: reason,
        code: `reader_only${detail ? `:${detail}` : ""}`.slice(0, 40),
        at: this.iso(),
      })
      .catch(() => undefined);
    return this.finishJob(sched, { ...run, walls: { ...walls, [section]: { count, reason } } }, `blocked:${reason}`);
  }

  /** A stop that halts every reader: close the tab, remember why, tell Juli, open no other page. */
  private async block(sched: ReaderSchedule, run: ReaderRun, reason: ReaderBlockReason, detail?: string): Promise<string> {
    const job = run.jobs[run.index];
    const now = this.deps.now();
    const until =
      now + (reason === "captcha" ? READER_BLOCK_CAPTCHA_MS : reason === "rate_limit" ? READER_BLOCK_RATE_MS : READER_BLOCK_LOGIN_MS);
    const outcomes = { ...run.outcomes, ...(job ? { [job.id]: `blocked_${reason}` } : {}) };
    // Ops sees the stop (reader, page, status, time); a failed post never changes the stop.
    await this.deps.sink
      .reportBlock?.({
        reader: job?.id ?? "products",
        page: job ? READER_PAGES[job.id].path : "",
        status: reason,
        ...(detail ? { code: detail.slice(0, 40) } : {}),
        at: this.iso(),
      })
      .catch(() => undefined);
    return this.finishRun(
      { ...sched, blocked: { at: this.iso(), reason, page: job?.id ?? "products", until } },
      { ...run, outcomes },
      reason,
    );
  }

  /**
   * A stop seen OUTSIDE the readers (a fill job's page asked for the Shopee password again): the
   * same cool-down as a login wall, the run in progress is ended (its tab closed), and Juli is told.
   */
  haltFor(reason: ReaderBlockReason, page: string, detail?: string): Promise<void> {
    return this.exclusive(async () => {
      const { sched } = await this.load();
      const now = this.deps.now();
      const until =
        now + (reason === "captcha" ? READER_BLOCK_CAPTCHA_MS : reason === "rate_limit" ? READER_BLOCK_RATE_MS : READER_BLOCK_LOGIN_MS);
      const blocked = { at: this.iso(), reason, page: sched.run?.jobs[sched.run.index]?.id ?? ("products" as ReaderId), until };
      if (sched.run) await this.finishRun({ ...sched, blocked }, sched.run, reason);
      else await this.save({ ...sched, blocked });
      await this.deps.sink
        .reportBlock?.({ reader: "fill", page, status: reason, ...(detail ? { code: detail.slice(0, 40) } : {}), at: this.iso() })
        .catch(() => undefined);
    });
  }

  /** The content script of a tab reports ready. True when the tab is the scheduler's own. */
  onTabReady(tabId: number, url: string | undefined): Promise<boolean> {
    return this.exclusive(async () => {
      const { sched } = await this.load();
      const run = sched.run;
      if (!run?.current || run.current.tabId !== tabId) return false;
      if (run.current.sentAt !== undefined) return true; // a reload / SPA re-run: the job is already sent
      const job = run.jobs[run.index] as PlannedJob;
      const pathname = (() => {
        try {
          return new URL(url ?? "").pathname;
        } catch {
          return "";
        }
      })();
      const wall = blockedPath(pathname);
      if (wall) {
        await this.wall(sched, run, wall);
        return true;
      }
      if (!pathname.startsWith(READER_PAGES[job.id].path)) {
        // Seller Centre sent the tab elsewhere (a section this sub-account may not have).
        await this.finishJob(sched, run, "redirected");
        return true;
      }
      try {
        await this.deps.tabs.send(tabId, {
          type: "reader-job",
          job: {
            id: job.id,
            ...(job.days ? { days: job.days } : {}),
            ...(job.itemIds ? { itemIds: job.itemIds } : {}),
            ...(job.campaignIds ? { campaignIds: job.campaignIds } : {}),
            // The list titles reach the page (0.3.16): before, the reader never saw them.
            ...(job.campaignNames ? { campaignNames: job.campaignNames.map((n) => n.slice(0, 255)) } : {}),
            ...(job.orderIds ? { orderIds: job.orderIds } : {}),
            ...(job.orderSns ? { orderSns: job.orderSns } : {}),
            ...(job.history ? { history: job.history } : {}),
            ...(job.sinceDay ? { sinceDay: job.sinceDay } : {}),
            ...(job.historyDays ? { historyDays: job.historyDays } : {}),
            // What is left of today's shared budget for this job's own requests.
            budget: Math.max(0, this.requestsLeftFor((await this.load()).state, run)),
          },
        });
      } catch {
        return true; // the content script is not listening yet: the next tab-ready / watchdog retries
      }
      await this.save({ ...sched, run: { ...run, current: { ...run.current, sentAt: this.deps.now() } } });
      return true;
    });
  }

  /** A page hook's answer for the job it was sent. True when the tab is the scheduler's own. */
  onResult(tabId: number, message: { job?: unknown; status?: unknown; detail?: unknown; responses?: unknown }): Promise<boolean> {
    return this.exclusive(async () => {
      const { state, sched } = await this.load();
      const run = sched.run;
      if (!run?.current || run.current.tabId !== tabId) return false;
      const job = run.jobs[run.index] as PlannedJob;
      if (message.job !== job.id) return true; // stale
      const status = String(message.status ?? "error");
      if (status === "blocked_captcha" || status === "blocked_login" || status === "blocked_password_recheck") {
        const detail = outcomeNote(message.detail).replace(/[^A-Za-z0-9_.:-]/g, "_");
        const reason = status === "blocked_captcha" ? "captcha" : status === "blocked_password_recheck" ? "password_recheck" : "login";
        await this.wall(sched, run, reason, detail || undefined);
        return true;
      }
      if (status === "blocked_rate") {
        await this.countRequests(run.day, message.responses);
        await this.block(sched, run, "rate_limit", String((message as { detail?: unknown }).detail ?? ""));
        return true;
      }
      if (status === "blocked_no_permission") {
        // 0.3.26: the account may not open this page (Tài chính): this page only, the run goes on.
        // Told to Juli in the run report ("blocked:no_permission" -> Thực hiện's block line).
        // The queue is kept whole (shopReaderState does not run) and the page is tried again tomorrow.
        await this.countRequests(run.day, message.responses);
        const detail = outcomeNote(message.detail).replace(/[^A-Za-z0-9_.:-]/g, "_");
        await this.deps.sink
          .reportBlock?.({
            reader: job.id,
            page: READER_PAGES[job.id].path,
            status: "no_permission",
            code: `reader_only${detail ? `:${detail}` : ""}`.slice(0, 40),
            at: this.iso(),
          })
          .catch(() => undefined);
        await this.finishJob(sched, run, `blocked:no_permission${detail ? `|${detail}` : ""}`);
        return true;
      }
      if (status === "budget_spent") {
        await this.countRequests(run.day, message.responses);
        if (run.current) await this.deps.tabs.close(run.current.tabId).catch(() => undefined);
        await this.budgetSpent(sched, { ...run, current: undefined, outcomes: { ...run.outcomes } });
        return true;
      }
      // The hook's reason, short and free of order ids / buyer data (endpoint + http status only).
      const note = outcomeNote(message.detail);
      if (status !== "done") {
        await this.finishJob(sched, run, note ? `${status}:${note}` : status);
        return true;
      }
      const responses = Array.isArray(message.responses) ? (message.responses as ReaderResponse[]) : [];
      await this.countRequests(run.day, responses);
      const readerJob: ReaderJob = {
        id: job.id,
        days: job.days,
        ...(job.itemIds ? { itemIds: job.itemIds } : {}),
        ...(job.campaignIds ? { campaignIds: job.campaignIds } : {}),
        ...(job.campaignNames ? { campaignNames: job.campaignNames } : {}),
        ...(job.orderIds ? { orderIds: job.orderIds } : {}),
        ...(job.orderSns ? { orderSns: job.orderSns } : {}),
        ...(job.history ? { history: job.history } : {}),
        ...(job.sinceDay ? { sinceDay: job.sinceDay } : {}),
        ...(job.historyDays ? { historyDays: job.historyDays } : {}),
      };
      const posted = await this.deps.sink.postReader(readerJob, responses);
      const skippedEntries =
        job.id === "ads" ? (job.days ?? []).reduce((sum, day) => sum + adsDayAnswer(responses, day).skipped, 0) : 0;
      const summary = [
        ...Object.entries(posted).map(([key, outcome]) => `${key}=${outcome}`),
        // Entries without a campaign id (GMV Max shop-level, totals) are counted, never drift.
        ...(skippedEntries > 0 ? [`ads_entries_skipped=${skippedEntries}`] : []),
      ].join(",");
      // An ads day is read only when Juli accepted its upload: a failed, queued or empty
      // ("ignored" -- Shopee had not finished the day) answer leaves it in the plan.
      const adsPosted =
        job.id === "ads"
          ? [
              ...(sched.adsPosted ?? []),
              ...(job.days ?? []).filter((day) => adsDayRead(posted[`ads_campaign_daily:${day}`] as CaptureOutcome | undefined, responses, day)),
            ].slice(-ADS_DONE_KEPT)
          : sched.adsPosted;
      const adsHistory = job.id === "ads" ? this.adsHistoryAfter(sched.adsHistory, job, posted, responses, adsPosted ?? []) : sched.adsHistory;
      const itemIds = job.id === "products" ? ids(responses, sched.itemIds) : sched.itemIds;
      const trafficDone =
        job.id === "item_traffic"
          ? [...(sched.trafficDone ?? []), ...completedTrafficDays(readerJob, responses)].slice(-TRAFFIC_DONE_KEPT)
          : sched.trafficDone;
      // The list's settings landed: remember the day and the ongoing campaigns for ads_detail.
      const settingsPosted =
        job.id === "ads" &&
        Object.entries(posted).some(([key, outcome]) => key.startsWith("ads_campaign_settings:") && outcome === "posted");
      const adsSettingsDay = settingsPosted ? run.day : sched.adsSettingsDay;
      const adsCampaigns = job.id === "ads" && settingsPosted ? ongoingAdsCampaigns(responses) : sched.adsCampaigns;
      const extra = this.shopReaderState(sched, run, job, posted, responses, state.token?.shop_id, !note.startsWith("partial"), note);
      // 0.3.19: the product list with stock landed (the 06:30 stock read counts it), the traffic days posted.
      const productsAt = job.id === "products" && posted.item_snapshot === "posted" ? this.deps.now() : sched.productsAt;
      const trafficOverviewDone =
        job.id === "traffic"
          ? [
              ...(sched.trafficOverviewDone ?? []),
              ...(job.days ?? []).filter((day) => posted[`traffic_overview:${day}:confirmed`] === "posted"),
            ].slice(-TRAFFIC_OVERVIEW_DONE_KEPT)
          : sched.trafficOverviewDone;
      // The page read: its section's session is alive (0.3.22), and its wall count starts again.
      const section = readerSection(job.id);
      const { [section]: _cleared, ...walls } = run.walls ?? {};
      const read: ReaderRun = { ...run, live: [...new Set([...(run.live ?? []), section])], walls };
      await this.finishJob(
        { ...sched, adsPosted, adsHistory, itemIds, trafficDone, adsSettingsDay, adsCampaigns, productsAt, trafficOverviewDone, ...extra },
        read,
        jobOutcome(job.id, posted, summary, note, responses),
      );
      return true;
    });
  }

  /** The job's own replayed requests count against today's shared budget (page-made calls do not). */
  private async countRequests(day: string, responses: unknown): Promise<void> {
    const list = Array.isArray(responses) ? (responses as ReaderResponse[]) : [];
    await addRequests(this.deps.storage, day, list.filter((r) => r.source === "replay").length);
  }

  /** Bookkeeping of the shop totals / order list / per-order income jobs after a finished read. */
  private shopReaderState(
    sched: ReaderSchedule,
    run: ReaderRun,
    job: PlannedJob,
    posted: Record<string, string>,
    responses: ReaderResponse[],
    shopId: string | undefined,
    complete = true,
    note = "",
  ): Partial<ReaderSchedule> {
    if (job.id === "shop_totals") {
      // Done when the confirmed post (the one Tổng quan reads) landed; the 30-day read marks the shop backfilled.
      if (posted["shop_overview:confirmed"] !== "posted") return {};
      return {
        totalsDay: run.day,
        totalsBackfilledShop: (job.days?.length ?? 0) >= SHOP_TOTALS_BACKFILL_DAYS ? shopId : sched.totalsBackfilledShop,
      };
    }
    if (job.id === "product_period") {
      // Done when the confirmed post (the one Tổng quan reads) landed.
      return posted["product_period:confirmed"] === "posted" ? { productPeriodDay: run.day } : {};
    }
    if (job.id === "orders") {
      const now = this.deps.now();
      const since = sched.incomeSince ?? now - ORDER_INCOME_FIRST_RUN_DAYS * 86_400_000;
      const known = new Set((sched.incomeQueue ?? []).map((o) => o.id));
      const fresh = completedOrders(responses)
        .filter((o) => o.completedAt >= since && !known.has(o.id))
        .sort((a, b) => a.completedAt - b.completedAt);
      const horizon = now - ORDER_INCOME_QUEUE_DAYS * 86_400_000;
      const queue = [...(sched.incomeQueue ?? []), ...fresh].filter((o) => o.completedAt >= horizon).slice(0, ORDER_INCOME_QUEUE_MAX);
      return {
        ordersDay: posted.order_lines === "posted" || responses.length > 0 ? run.day : sched.ordersDay,
        // Read back to its sinceDay: the next run starts from here (minus the overlap).
        // 0.3.20: a list with no order since sinceDay is read back to it too.
        ordersCoveredDay:
          (posted.order_lines === "posted" || note === "no_new_orders" || note === "no_orders") && complete ? run.day : sched.ordersCoveredDay,
        incomeQueue: queue,
        incomeSince: now,
      };
    }
    if (job.id === "order_income") {
      // 0.3.26: only orders whose income was read (and posted / queued to post) leave the queue; an
      // order whose own request was answered with a refusal / no final amount stays for tomorrow,
      // counted once per day, and is dropped after ORDER_INCOME_MAX_FAILED_DAYS failed days. An
      // order never requested (no order key on the page, a stop before its turn) is left unchanged.
      const sent = new Set(job.orderIds ?? []);
      const answered = new Set(
        responses.filter((r) => r.endpoint === "order_income_components" && r.orderId).map((r) => r.orderId as string),
      );
      const landed = posted.order_income === "posted" || posted.order_income === "queued";
      const read = landed ? incomeReadIds(responses) : new Set<string>();
      const incomeQueue = (sched.incomeQueue ?? []).flatMap((o) => {
        if (!sent.has(o.id) || !answered.has(o.id)) return [o];
        if (read.has(o.id)) return [];
        if (o.failedDay === run.day) return [o];
        const failedDays = (o.failedDays ?? 0) + 1;
        return failedDays >= ORDER_INCOME_MAX_FAILED_DAYS ? [] : [{ ...o, failedDays, failedDay: run.day }];
      });
      return { incomeDay: run.day, incomeQueue };
    }
    if (job.id === "affiliate" && job.history && shopId) {
      // The history is done once every window posted (or Shopee answered it empty); a failed
      // window keeps it planned for tomorrow's run.
      const lines = Object.entries(posted).filter(([key]) => key.startsWith("affiliate_order_lines"));
      const ok = lines.length > 0 && lines.every(([, outcome]) => outcome === "posted" || outcome === "empty");
      return ok ? { affiliateHistoryShop: shopId } : {};
    }
    return {};
  }

  /** The seller (or an extension page) closed the scheduler's tab: move on, do not block. */
  onTabRemoved(tabId: number): Promise<void> {
    return this.exclusive(async () => {
      const { sched } = await this.load();
      if (sched.run?.current?.tabId === tabId) await this.tabLost(sched, sched.run);
    });
  }

  /**
   * The pages today's run left blocked by a login / password wall (0.3.25): the outcome heads are
   * "blocked:login", "blocked:password_recheck" (this page only) and "blocked_login" (the page
   * that stopped the run; the password dialog never stops a run).
   */
  private blockedPages(sched: ReaderSchedule, today: string): ReaderId[] {
    if (sched.lastRun?.day !== today) return [];
    return Object.entries(sched.lastRun.outcomes)
      .filter(([, outcome]) => /^(blocked[:_]login|blocked:password_recheck)/.test(String(outcome)))
      .map(([id]) => id as ReaderId);
  }

  /**
   * A block has cleared (a data call proved the session, or the seller pressed "Đồng bộ"): arm ONE
   * re-read of today's blocked pages a few minutes from now (0.3.25). Not while a run is going, not
   * when one is armed already, and at most READER_REREAD_MAX_PER_DAY starts a day.
   */
  private async armReread(sched: ReaderSchedule): Promise<void> {
    const today = gmt7Date(Math.floor(this.deps.now() / 1000));
    const pages = this.blockedPages(sched, today);
    if (pages.length === 0 || sched.run || sched.reread?.day === today) return;
    if (sched.rereadCount?.day === today && sched.rereadCount.n >= READER_REREAD_MAX_PER_DAY) return;
    await this.save({ ...sched, reread: { day: today, pages }, kick: { reason: "reread", at: this.iso() } });
    await this.deps.alarms.create(READER_KICK_ALARM, { delayInMinutes: READER_REREAD_DELAY_MINUTES });
  }

  /**
   * A data call succeeded in a Seller Centre tab: a login block is over (retry today), and the
   * pages today's walls blocked are read again, only those, when the call was on /datacenter
   * (Phân tích bán hàng: its password dialog is confirmed). `section` is that tab's section.
   */
  sessionSeen(section?: string): Promise<void> {
    return this.exclusive(async () => {
      let { sched } = await this.load();
      const lifts = sched.blocked?.reason === "login";
      if (lifts) {
        const wasRunWide = sched.lastRun?.blocked === "login";
        sched = { ...sched, blocked: undefined, lastRunDay: wasRunWide ? undefined : sched.lastRunDay };
        await this.save(sched);
      }
      if (lifts || section === "datacenter") await this.armReread(sched);
    });
  }

  /** The seller pressed "Đồng bộ": lift a block (they may have solved the CAPTCHA) and retry today. */
  clearBlock(): Promise<void> {
    return this.exclusive(async () => {
      let { sched } = await this.load();
      // A rate-limit stop is Shopee asking us to slow down: the button does not lift it.
      if (sched.blocked?.reason === "rate_limit" && sched.blocked.until > this.deps.now()) return;
      if (sched.blocked) {
        sched = { ...sched, blocked: undefined, lastRunDay: sched.lastRun?.blocked ? undefined : sched.lastRunDay };
        await this.save(sched);
      }
      await this.armReread(sched);
    });
  }
}
