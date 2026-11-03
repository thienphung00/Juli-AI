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
  type Dataset,
  HELD_DATASETS,
  READER_BLOCK_CAPTCHA_MS,
  READER_BLOCK_LOGIN_MS,
  READER_DATASETS,
  READER_IDS,
  READER_JOB_TIMEOUT_MS,
  READER_LOAD_GRACE_MS,
  READER_PAGE_GAP_JITTER_MS,
  READER_PAGE_GAP_MS,
  READER_WATCHDOG_ALARM_MINUTES,
  type ReaderDataset,
  readerActive,
  schedulerActive,
  TRAFFIC_CATCHUP_DAYS,
  TRAFFIC_JOB_TIMEOUT_MS,
  TRAFFIC_MAX_ITEMS,
} from "../config";
import { activeItemIds, completedTrafficDays } from "../shopee/reader-map";
import { READER_PAGES } from "../shopee/endpoints";
import { blockedPath, type ReaderJob, type ReaderResponse } from "../shopee/reader";
import { gmt7Date, lastFinishedDays } from "../shopee/time";
import {
  type PlannedJob,
  type ReaderBlockReason,
  type ReaderRun,
  type ReaderSchedule,
  loadState,
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

export interface SchedulerDeps {
  storage: Storage;
  tabs: SchedulerTabs;
  alarms: SchedulerAlarms;
  /** Posts a finished job's responses (the Connector). */
  sink: { postReader(job: ReaderJob, responses: ReaderResponse[]): Promise<Record<string, string>> };
  /** The 30-day backfill has a day in flight: do not start a run on top of it. */
  backfillBusy: () => Promise<boolean>;
  origin: string;
  version: string;
  now: () => number;
  random?: () => number;
  /** Best effort: call `fn` after `ms` (the watchdog alarm is the guarantee). */
  later?: (ms: number, fn: () => void) => void;
}

/** The pages to open today, in order: products, vouchers, ads (one tab, several days), health. */
export function planJobs(args: {
  shopId: string | undefined;
  nowMs: number;
  stopped: ReadonlySet<Dataset>;
  adsDone: readonly string[];
  trafficDone?: readonly string[];
  held?: ReadonlySet<ReaderDataset>;
}): PlannedJob[] {
  const held = args.held ?? HELD_DATASETS;
  const jobs: PlannedJob[] = [];
  for (const id of READER_IDS) {
    if (!readerActive(id, args.shopId)) continue;
    // A page is only worth opening while at least one of its datasets can be posted.
    const postable = READER_DATASETS[id].some((dataset) => !held.has(dataset) && !args.stopped.has(dataset));
    if (!postable) continue;
    if (id === "ads") {
      const days = lastFinishedDays(args.nowMs, 1 + ADS_CATCHUP_DAYS).filter((day) => !args.adsDone.includes(day));
      if (days.length > 0) jobs.push({ id, days });
    } else if (id === "item_traffic") {
      // The item ids are filled in when the job's turn comes (the product list is read first).
      const days = lastFinishedDays(args.nowMs, 1 + TRAFFIC_CATCHUP_DAYS).filter(
        (day) => !(args.trafficDone ?? []).includes(day),
      );
      if (days.length > 0) jobs.push({ id, days });
    } else {
      jobs.push({ id });
    }
  }
  return jobs;
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

  /** The alarm / watchdog / "Đồng bộ" entry point: start today's run, or advance the one running. */
  tick(): Promise<string> {
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
      if (sched.lastRunDay === today) return "done_today";
      if (await this.deps.backfillBusy()) return "backfill_busy";
      const jobs = planJobs({
        shopId,
        nowMs: now,
        stopped: stoppedFor(state, this.deps.version),
        adsDone: sched.adsDone,
        trafficDone: sched.trafficDone,
      });
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
    const tabId = await this.deps.tabs.open(`${this.deps.origin}${READER_PAGES[job.id].path}`);
    if (tabId === undefined) return this.finishJob(sched, run, "open_failed", false);
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

  /** CAPTCHA or login wall: close the tab, remember why, stop the run (no other page is opened). */
  private async block(sched: ReaderSchedule, run: ReaderRun, reason: ReaderBlockReason): Promise<string> {
    const job = run.jobs[run.index];
    const now = this.deps.now();
    const until = now + (reason === "captcha" ? READER_BLOCK_CAPTCHA_MS : READER_BLOCK_LOGIN_MS);
    const outcomes = { ...run.outcomes, ...(job ? { [job.id]: `blocked_${reason}` } : {}) };
    return this.finishRun(
      { ...sched, blocked: { at: this.iso(), reason, page: job?.id ?? "products", until } },
      { ...run, outcomes },
      reason,
    );
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
          job: { id: job.id, ...(job.days ? { days: job.days } : {}), ...(job.itemIds ? { itemIds: job.itemIds } : {}) },
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
      const { sched } = await this.load();
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
      if (status !== "done") {
        await this.finishJob(sched, run, status);
        return true;
      }
      const responses = Array.isArray(message.responses) ? (message.responses as ReaderResponse[]) : [];
      const readerJob: ReaderJob = { id: job.id, days: job.days, ...(job.itemIds ? { itemIds: job.itemIds } : {}) };
      const posted = await this.deps.sink.postReader(readerJob, responses);
      const summary = Object.entries(posted)
        .map(([key, outcome]) => `${key}=${outcome}`)
        .join(",");
      const adsDone = job.id === "ads" ? [...sched.adsDone, ...(job.days ?? [])].slice(-ADS_DONE_KEPT) : sched.adsDone;
      const itemIds = job.id === "products" ? ids(responses, sched.itemIds) : sched.itemIds;
      const trafficDone =
        job.id === "item_traffic"
          ? [...(sched.trafficDone ?? []), ...completedTrafficDays(readerJob, responses)].slice(-TRAFFIC_DONE_KEPT)
          : sched.trafficDone;
      await this.finishJob({ ...sched, adsDone, itemIds, trafficDone }, run, summary ? `done:${summary}` : "done");
      return true;
    });
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
      await this.save({ ...sched, blocked: undefined, lastRunDay: sched.lastRun?.blocked ? undefined : sched.lastRunDay });
    });
  }
}
