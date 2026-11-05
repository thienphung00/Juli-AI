// The market search schedule (P92 B-10): once a day the Connector asks Juli which of the shop's
// product keywords are due (weekly per keyword), opens the PUBLIC Shopee search page for each in a
// background tab, one at a time, lets the page make its own search call, keeps its answer
// (page 1), posts it and closes the tab. No login, never clicks, ORY pilot only. It stops, and
// records `blocked`, on a CAPTCHA / verification / login page or an anti-fraud answer.
//
// Same shape as ReaderScheduler: a state machine in chrome.storage.local advanced by events
// (alarm, tab ready, page answer, tab closed); Chrome is injected so it is unit-tested with fakes.

import {
  marketActive,
  MARKET_JOB_TIMEOUT_MS,
  MARKET_MAX_KEYWORDS_PER_RUN,
  MARKET_ORIGIN,
  MARKET_PAGE_PATH,
  READER_BLOCK_CAPTCHA_MS,
  READER_BLOCK_LOGIN_MS,
  READER_LOAD_GRACE_MS,
  READER_PAGE_GAP_JITTER_MS,
  READER_PAGE_GAP_MS,
  READER_WATCHDOG_ALARM_MINUTES,
} from "../config";
import { classifyAnswer, marketBlockedPath, type MarketPlan, pickKeywords, sameKeyword, searchPageUrl } from "../shopee/market";
import { gmt7Date } from "../shopee/time";
import { loadState, type MarketRun, type MarketSchedule, type ReaderBlockReason, saveState, type State, stoppedFor } from "./state";
import type { CaptureOutcome } from "./connector";
import type { SchedulerAlarms, SchedulerTabs } from "./scheduler";

export const MARKET_RUN_ALARM = "juli-market-run";
export const MARKET_WATCHDOG_ALARM = "juli-market-watch";
const RUN_MAX_AGE_MS = 3 * 3_600_000;
const LAST_READ_KEPT = 200;

export interface MarketDeps {
  storage: import("./state").Storage;
  tabs: SchedulerTabs;
  alarms: SchedulerAlarms;
  /** The server's keyword list for the paired shop; rejects (or returns null) when unavailable. */
  plan: (token: string) => Promise<MarketPlan | null>;
  sink: { postMarket(keyword: string, body: unknown, capturedAt: number): Promise<CaptureOutcome> };
  /** The Seller Centre reader run or the backfill holds the pace budget: do not start. */
  otherBusy: () => Promise<boolean>;
  version: string;
  now: () => number;
  random?: () => number;
  later?: (ms: number, fn: () => void) => void;
}

export class MarketScheduler {
  private lock: Promise<unknown> = Promise.resolve();

  constructor(private readonly deps: MarketDeps) {}

  private exclusive<T>(work: () => Promise<T>): Promise<T> {
    const next = this.lock.then(work, work);
    this.lock = next.catch(() => undefined);
    return next;
  }

  private iso(): string {
    return new Date(this.deps.now()).toISOString();
  }

  private async load(): Promise<{ state: State; sched: MarketSchedule }> {
    const state = await loadState(this.deps.storage);
    return { state, sched: state.market ?? { lastRead: {} } };
  }

  private save(sched: MarketSchedule): Promise<void> {
    return saveState(this.deps.storage, { market: sched });
  }

  private gap(): number {
    return READER_PAGE_GAP_MS + Math.floor((this.deps.random ?? Math.random)() * READER_PAGE_GAP_JITTER_MS);
  }

  async activeTabIds(): Promise<number[]> {
    const { sched } = await this.load();
    const tabId = sched.run?.current?.tabId;
    return tabId === undefined ? [] : [tabId];
  }

  /** A market run is in progress (the Seller Centre readers and the backfill wait). */
  async isBusy(): Promise<boolean> {
    const { sched } = await this.load();
    return !!sched.run && this.deps.now() - sched.run.startedAt < RUN_MAX_AGE_MS;
  }

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
      if (!marketActive(shopId)) return "off";
      if (state.consentBlocked) return "consent_required";
      if (stoppedFor(state, this.deps.version).has("market_search")) return "stopped";
      if (sched.blocked && sched.blocked.until > now) return "blocked";
      const today = gmt7Date(Math.floor(now / 1000));
      if (sched.lastRunDay === today) return "done_today";
      if (await this.deps.otherBusy()) return "busy";
      let plan: MarketPlan | null = null;
      try {
        plan = await this.deps.plan(state.token.token);
      } catch {
        return "plan_failed"; // tried again at the next alarm
      }
      if (!plan || plan.enabled !== true) {
        await this.save({ ...sched, lastRunDay: today });
        return "disabled";
      }
      const keywords = pickKeywords(plan, sched.lastRead, today).slice(0, MARKET_MAX_KEYWORDS_PER_RUN);
      if (keywords.length === 0) {
        await this.save({ ...sched, lastRunDay: today });
        return "nothing_to_do";
      }
      const run: MarketRun = { day: today, startedAt: now, keywords, index: 0, outcomes: {} };
      await this.save({ ...sched, blocked: undefined, run });
      await this.deps.alarms.create(MARKET_WATCHDOG_ALARM, {
        delayInMinutes: READER_WATCHDOG_ALARM_MINUTES,
        periodInMinutes: READER_WATCHDOG_ALARM_MINUTES,
      });
      return this.startNext({ ...sched, blocked: undefined, run }, run);
    });
  }

  private async advance(sched: MarketSchedule, run: MarketRun): Promise<string> {
    const now = this.deps.now();
    const current = run.current;
    if (current) {
      if (now - current.openedAt > MARKET_JOB_TIMEOUT_MS) return this.finishJob(sched, run, "timeout");
      if (now - current.openedAt > READER_LOAD_GRACE_MS) {
        const info = await this.deps.tabs.inspect(current.tabId);
        if (!info.open) return this.finishJob(sched, run, "closed", false);
        if (info.url === undefined || !info.url.startsWith(`${MARKET_ORIGIN}/`)) return this.block(sched, run, "login");
        const wall = marketBlockedPath(new URL(info.url).pathname);
        if (wall) return this.block(sched, run, wall);
      }
      return "waiting";
    }
    if ((run.nextAt ?? 0) > now) return "gap";
    return this.startNext(sched, run);
  }

  private async startNext(sched: MarketSchedule, run: MarketRun): Promise<string> {
    const keyword = run.keywords[run.index];
    if (keyword === undefined) return this.finishRun(sched, run);
    const tabId = await this.deps.tabs.open(searchPageUrl(keyword));
    if (tabId === undefined) return this.finishJob(sched, run, "open_failed", false);
    await this.save({ ...sched, run: { ...run, current: { tabId, openedAt: this.deps.now() } } });
    return "opened";
  }

  private async finishJob(sched: MarketSchedule, run: MarketRun, outcome: string, close = true): Promise<string> {
    const keyword = run.keywords[run.index];
    if (close && run.current) await this.deps.tabs.close(run.current.tabId).catch(() => undefined);
    const next: MarketRun = {
      ...run,
      outcomes: { ...run.outcomes, ...(keyword ? { [keyword]: outcome } : {}) },
      index: run.index + 1,
      current: undefined,
      nextAt: this.deps.now() + this.gap(),
    };
    if (next.index >= next.keywords.length) return this.finishRun(sched, next);
    await this.save({ ...sched, run: next });
    this.deps.later?.((next.nextAt ?? 0) - this.deps.now() + 1_000, () => void this.tick());
    return outcome;
  }

  private async finishRun(sched: MarketSchedule, run: MarketRun, blocked?: ReaderBlockReason, outcome = "finished"): Promise<string> {
    if (run.current) await this.deps.tabs.close(run.current.tabId).catch(() => undefined);
    await this.save({
      ...sched,
      run: undefined,
      lastRunDay: run.day,
      lastRun: { day: run.day, at: this.iso(), outcomes: run.outcomes, ...(blocked ? { blocked } : {}) },
    });
    await this.deps.alarms.clear(MARKET_WATCHDOG_ALARM).catch(() => undefined);
    return blocked ? `blocked:${blocked}` : outcome;
  }

  private async block(sched: MarketSchedule, run: MarketRun, reason: ReaderBlockReason): Promise<string> {
    const keyword = run.keywords[run.index];
    const until = this.deps.now() + (reason === "captcha" ? READER_BLOCK_CAPTCHA_MS : READER_BLOCK_LOGIN_MS);
    return this.finishRun(
      { ...sched, blocked: { at: this.iso(), reason, until } },
      { ...run, outcomes: { ...run.outcomes, ...(keyword ? { [keyword]: `blocked_${reason}` } : {}) } },
      reason,
    );
  }

  /** The relay of a search tab reports ready. True when the tab is the run's own. */
  onTabReady(tabId: number, url: string | undefined): Promise<boolean> {
    return this.exclusive(async () => {
      const { sched } = await this.load();
      const run = sched.run;
      if (!run?.current || run.current.tabId !== tabId) return false;
      let pathname = "";
      try {
        pathname = new URL(url ?? "").pathname;
      } catch {
        pathname = "";
      }
      const wall = marketBlockedPath(pathname);
      if (wall) await this.block(sched, run, wall);
      else if (!pathname.startsWith(MARKET_PAGE_PATH)) await this.finishJob(sched, run, "redirected");
      return true;
    });
  }

  /** A wall noticed by the relay (overlay / late redirect). */
  onBlocked(tabId: number, reason: string): Promise<boolean> {
    return this.exclusive(async () => {
      const { sched } = await this.load();
      const run = sched.run;
      if (!run?.current || run.current.tabId !== tabId) return false;
      await this.block(sched, run, reason === "login" ? "login" : "captcha");
      return true;
    });
  }

  /** The page's own search answer. True when the tab is the run's own. */
  onResult(tabId: number, message: { keyword?: unknown; status?: unknown; body?: unknown; capturedAt?: unknown }): Promise<boolean> {
    return this.exclusive(async () => {
      const { sched } = await this.load();
      const run = sched.run;
      if (!run?.current || run.current.tabId !== tabId) return false;
      const keyword = run.keywords[run.index] as string;
      if (typeof message.keyword !== "string" || !sameKeyword(message.keyword, keyword)) return true; // stale / other call
      const verdict = classifyAnswer(Number(message.status ?? 0), message.body);
      if (verdict === "captcha") {
        await this.block(sched, run, "captcha");
        return true;
      }
      if (verdict === "error") {
        await this.finishJob(sched, run, `error_${Number(message.status ?? 0)}`);
        return true;
      }
      const capturedAt = typeof message.capturedAt === "number" ? message.capturedAt : this.deps.now();
      const outcome = await this.deps.sink.postMarket(keyword, message.body, capturedAt);
      // The dataset was paused (drift), the shop is unpaired or refused: the rest of the run is pointless.
      if (outcome === "drift" || outcome === "stopped" || outcome === "unpaired" || outcome === "refused") {
        await this.finishRun(sched, { ...run, outcomes: { ...run.outcomes, [keyword]: outcome } }, undefined, outcome);
        return true;
      }
      const read = outcome === "posted" || outcome === "queued" || outcome === "ignored";
      const lastRead = read ? { ...sched.lastRead, [keyword]: run.day } : sched.lastRead;
      const trimmed = Object.fromEntries(Object.entries(lastRead).slice(-LAST_READ_KEPT));
      await this.finishJob({ ...sched, lastRead: trimmed }, run, outcome);
      return true;
    });
  }

  onTabRemoved(tabId: number): Promise<void> {
    return this.exclusive(async () => {
      const { sched } = await this.load();
      if (sched.run?.current?.tabId === tabId) await this.finishJob(sched, sched.run, "closed", false);
    });
  }

  /** "Đồng bộ" pressed: lift a block (they may have solved the CAPTCHA). */
  clearBlock(): Promise<void> {
    return this.exclusive(async () => {
      const { sched } = await this.load();
      if (sched.blocked) await this.save({ ...sched, blocked: undefined, lastRunDay: sched.lastRun?.blocked ? undefined : sched.lastRunDay });
    });
  }
}
