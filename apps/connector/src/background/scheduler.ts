// The tab-opening schedule (ADR-120 d.14): once a day the Connector opens the Seller Centre
// report pages itself, ONE background tab at a time, lets the page hook read each page's own
// endpoints, closes the tab, and moves on after a gap. Read-only, the seller's own session.
// It stops, and records `blocked`, on a CAPTCHA or a login wall; it never clicks anything.
//
// An MV3 service worker can be stopped at any time, so the run is a state machine kept in
// chrome.storage.local and advanced by events (alarm, tab ready, page result, tab closed).
// Chrome is injected (SchedulerDeps) so the whole thing is unit-tested with fakes.

import {
  ADS_CATCHUP_DAYS,
  ADS_DETAIL_MAX_CAMPAIGNS,
  ADS_PRODUCTS_MAX_CAMPAIGNS,
  type Dataset,
  HELD_DATASETS,
  ORDER_INCOME_FIRST_RUN_DAYS,
  ORDER_INCOME_MAX_PER_DAY,
  ORDER_INCOME_QUEUE_DAYS,
  ORDER_INCOME_QUEUE_MAX,
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
import { completedOrders } from "../shopee/orders-map";
import { activeItemIds, adsDayAnswer, completedTrafficDays, ongoingAdsCampaigns } from "../shopee/reader-map";
import type { CaptureOutcome } from "./connector";
import { READER_PAGES, readerPageUrl } from "../shopee/endpoints";
import { blockedPath, type ReaderJob, type ReaderResponse } from "../shopee/reader";
import { gmt7Date, lastFinishedDays } from "../shopee/time";
import {
  type PlannedJob,
  type ReaderBlockReason,
  type ReaderRun,
  type ReaderSchedule,
  addRequests,
  loadState,
  requestsLeft,
  saveState,
  type Storage,
  stoppedFor,
  type State,
} from "./state";

export const READER_RUN_ALARM = "juli-reader-run";
export const READER_WATCHDOG_ALARM = "juli-reader-watch";
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
  inspect(tabId: number): Promise<{ open: boolean; url?: string }>;
}

export interface SchedulerAlarms {
  create(name: string, info: { delayInMinutes?: number; periodInMinutes?: number }): Promise<void>;
  clear(name: string): Promise<unknown>;
}

/** What Ops sees of a stop: which reader, which page, what happened and when (never a body). */
export interface BlockEvent {
  reader: string;
  page: string;
  status: ReaderBlockReason;
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
  held?: ReadonlySet<ReaderDataset>;
  readers?: readonly ReaderId[];
}): PlannedJob[] {
  const todayDay = gmt7Date(Math.floor(args.nowMs / 1000));
  const held = args.held ?? HELD_DATASETS;
  const jobs: PlannedJob[] = [];
  for (const id of args.readers ?? READER_IDS) {
    if (!readerActive(id, args.shopId)) continue;
    // A page is only worth opening while at least one of its datasets can be posted.
    const postable = READER_DATASETS[id].some((dataset) => !held.has(dataset) && !args.stopped.has(dataset));
    if (!postable) continue;
    if (id === "ads") {
      const days = lastFinishedDays(args.nowMs, 1 + ADS_CATCHUP_DAYS).filter((day) => !args.adsDone.includes(day));
      // Every day posted: the list is still opened once a day for its campaign settings, once
      // a first settings capture has been recorded (before that, an open day always exists).
      const settingsDue = args.adsSettingsDay !== undefined && args.adsSettingsDay !== gmt7Date(Math.floor(args.nowMs / 1000));
      if (days.length > 0 || settingsDue) jobs.push({ id, days });
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
      if (args.ordersDay !== todayDay) jobs.push({ id });
    } else if (id === "order_income") {
      // Planned every day, right after "orders" (which fills the queue in the same run); its turn
      // opens nothing when no completed order is waiting.
      if (args.incomeDay !== todayDay) jobs.push({ id });
    } else {
      jobs.push({ id });
    }
  }
  return jobs;
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
function ids(responses: ReaderResponse[], previous: string[] | undefined): string[] | undefined {
  const fresh = activeItemIds(responses);
  return fresh.length > 0 ? fresh : previous;
}

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
  tick(options: { manual?: boolean } = {}): Promise<string> {
    return this.exclusive(async () => {
      const { state, sched } = await this.load();
      const now = this.deps.now();
      if (sched.run) {
        if (now - sched.run.startedAt >= RUN_MAX_AGE_MS) return this.finishRun(sched, sched.run, undefined, "expired");
        return this.advance(sched, sched.run);
      }
      const shopId = state.token?.shop_id;
      if (!state.token) return "unpaired";
      if (!schedulerActive(shopId)) return "off";
      if (state.consentBlocked) return "consent_required";
      if (sched.blocked && sched.blocked.until > now) return "blocked";
      const today = gmt7Date(Math.floor(now / 1000));
      const rerun = sched.lastRunDay === today;
      if (rerun && !options.manual) return "done_today";
      if (await this.deps.backfillBusy()) return "backfill_busy";
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
        ? planned.filter((job) => (job.days?.length ?? 0) > 0 || (options.manual === true && retry.has(job.id)))
        : planned;
      if (rerun && jobs.length === 0) return "done_today";
      if (jobs.length === 0) {
        await this.save({ ...sched, lastRunDay: today });
        return "nothing_to_do";
      }
      const run: ReaderRun = { day: today, startedAt: now, jobs, index: 0, outcomes: {} };
      await this.save({ ...sched, blocked: undefined, run });
      await this.deps.alarms.create(READER_WATCHDOG_ALARM, {
        delayInMinutes: READER_WATCHDOG_ALARM_MINUTES,
        periodInMinutes: READER_WATCHDOG_ALARM_MINUTES,
      });
      return this.startNext({ ...sched, blocked: undefined, run }, run);
    });
  }

  private async advance(sched: ReaderSchedule, run: ReaderRun): Promise<string> {
    const now = this.deps.now();
    const current = run.current;
    if (current) {
      const limit = run.jobs[run.index]?.id === "item_traffic" ? TRAFFIC_JOB_TIMEOUT_MS : READER_JOB_TIMEOUT_MS;
      if (now - current.openedAt > limit) return this.finishJob(sched, run, "timeout");
      if (current.sentAt === undefined && now - current.openedAt > READER_LOAD_GRACE_MS) {
        const info = await this.deps.tabs.inspect(current.tabId);
        if (!info.open) return this.finishJob(sched, run, "closed", false);
        if (info.url === undefined || !info.url.startsWith(`${this.deps.origin}/`)) {
          // Redirected away from Seller Centre (or to a host we cannot see): a login wall.
          return this.block(sched, run, "login");
        }
        const wall = blockedPath(new URL(info.url).pathname);
        if (wall) return this.block(sched, run, wall);
      }
      return "waiting";
    }
    if ((run.nextAt ?? 0) > now) return "gap";
    return this.startNext(sched, run);
  }

  private async startNext(sched: ReaderSchedule, run: ReaderRun): Promise<string> {
    let job = run.jobs[run.index];
    if (!job) return this.finishRun(sched, run);
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
    const left = requestsLeft(state, run.day);
    if (left <= READER_PAGE_LOAD_COST) return this.budgetSpent(sched, run);
    const tabId = await this.deps.tabs.open(`${this.deps.origin}${readerPageUrl(job)}`);
    if (tabId === undefined) return this.finishJob(sched, run, "open_failed", false);
    await addRequests(this.deps.storage, run.day, READER_PAGE_LOAD_COST);
    const next = { ...run, current: { tabId, openedAt: this.deps.now() } };
    await this.save({ ...sched, run: next });
    return "opened";
  }

  private async finishJob(sched: ReaderSchedule, run: ReaderRun, outcome: string, close = true): Promise<string> {
    const job = run.jobs[run.index];
    if (close && run.current) await this.deps.tabs.close(run.current.tabId).catch(() => undefined);
    const outcomes = { ...run.outcomes, ...(job ? { [job.id]: outcome } : {}) };
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
    await this.save({
      ...sched,
      run: undefined,
      lastRunDay: run.day,
      lastRun: { day: run.day, at: this.iso(), outcomes: run.outcomes, ...(blocked ? { blocked } : {}) },
    });
    await this.deps.alarms.clear(READER_WATCHDOG_ALARM).catch(() => undefined);
    return blocked ? `blocked:${blocked}` : outcome;
  }

  /** The day's request budget is spent: this job and the rest wait for tomorrow's run. */
  private async budgetSpent(sched: ReaderSchedule, run: ReaderRun): Promise<string> {
    const outcomes = { ...run.outcomes };
    for (const job of run.jobs.slice(run.index)) outcomes[job.id] = "waiting_budget";
    return this.finishRun(sched, { ...run, outcomes }, undefined, "budget_spent");
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
        await this.block(sched, run, wall);
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
            ...(job.orderIds ? { orderIds: job.orderIds } : {}),
            ...(job.orderSns ? { orderSns: job.orderSns } : {}),
            // What is left of today's shared budget for this job's own requests.
            budget: Math.max(0, requestsLeft((await this.load()).state, run.day)),
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
  onResult(tabId: number, message: { job?: unknown; status?: unknown; responses?: unknown }): Promise<boolean> {
    return this.exclusive(async () => {
      const { state, sched } = await this.load();
      const run = sched.run;
      if (!run?.current || run.current.tabId !== tabId) return false;
      const job = run.jobs[run.index] as PlannedJob;
      if (message.job !== job.id) return true; // stale
      const status = String(message.status ?? "error");
      if (status === "blocked_captcha") {
        await this.block(sched, run, "captcha");
        return true;
      }
      if (status === "blocked_login") {
        await this.block(sched, run, "login");
        return true;
      }
      if (status === "blocked_rate") {
        await this.countRequests(run.day, message.responses);
        await this.block(sched, run, "rate_limit", String((message as { detail?: unknown }).detail ?? ""));
        return true;
      }
      if (status === "budget_spent") {
        await this.countRequests(run.day, message.responses);
        if (run.current) await this.deps.tabs.close(run.current.tabId).catch(() => undefined);
        await this.budgetSpent(sched, { ...run, current: undefined, outcomes: { ...run.outcomes } });
        return true;
      }
      if (status !== "done") {
        await this.finishJob(sched, run, status);
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
      const extra = this.shopReaderState(sched, run, job, posted, responses, state.token?.shop_id);
      await this.finishJob(
        { ...sched, adsPosted, itemIds, trafficDone, adsSettingsDay, adsCampaigns, ...extra },
        run,
        summary ? `done:${summary}` : "done",
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
        incomeQueue: queue,
        incomeSince: now,
      };
    }
    if (job.id === "order_income") {
      const sent = new Set(job.orderIds ?? []);
      return { incomeDay: run.day, incomeQueue: (sched.incomeQueue ?? []).filter((o) => !sent.has(o.id)) };
    }
    return {};
  }

  /** The seller (or an extension page) closed the scheduler's tab: move on, do not block. */
  onTabRemoved(tabId: number): Promise<void> {
    return this.exclusive(async () => {
      const { sched } = await this.load();
      if (sched.run?.current?.tabId === tabId) await this.finishJob(sched, sched.run, "closed", false);
    });
  }

  /** A data call succeeded in a Seller Centre tab: a login block is over (retry today). */
  sessionSeen(): Promise<void> {
    return this.exclusive(async () => {
      const { sched } = await this.load();
      if (sched.blocked?.reason !== "login") return;
      await this.save({ ...sched, blocked: undefined, lastRunDay: sched.lastRun?.blocked === "login" ? undefined : sched.lastRunDay });
    });
  }

  /** The seller pressed "Đồng bộ": lift a block (they may have solved the CAPTCHA) and retry today. */
  clearBlock(): Promise<void> {
    return this.exclusive(async () => {
      const { sched } = await this.load();
      if (!sched.blocked) return;
      // A rate-limit stop is Shopee asking us to slow down: the button does not lift it.
      if (sched.blocked.reason === "rate_limit" && sched.blocked.until > this.deps.now()) return;
      await this.save({ ...sched, blocked: undefined, lastRunDay: sched.lastRun?.blocked ? undefined : sched.lastRunDay });
    });
  }
}
