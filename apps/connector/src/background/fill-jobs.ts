// The service worker's half of the fill queue (P97 D85.6): poll Juli for the token's shop's jobs,
// open the next queued page in a background tab (one page at a time, counted against the shared
// daily request budget), hand the job to the content script that asks for it, and pass its
// progress back. It decides nothing about Seller Centre pages beyond the allowlist in
// fill/job-types, never clicks anything, and stops for the shop on a password prompt.

import { FILL_HASH_KEY, FILL_JOB_STALE_MS, fillJobsActive, READER_PAGE_LOAD_COST, SELLER_CENTRE_ORIGIN } from "../config";
import { type JobReply, parseFillJob, type FillJob } from "../fill/job-types";
import { GatewayError, type GatewayClient } from "../ingest/client";
import { gmt7Date } from "../shopee/time";
import { addRequests, loadState, requestsLeft, saveState, type FillJobsState, type Storage } from "./state";

export interface FillJobsDeps {
  storage: Storage;
  client: Pick<GatewayClient, "fillJobs" | "fillJobReport">;
  now: () => number;
  tabs: {
    openPage(url: string): Promise<number | undefined>;
    inspect(tabId: number): Promise<{ open: boolean; url?: string }>;
  };
  /** Another run (readers, backfill, market) holds the pace: wait. */
  busy(): Promise<boolean>;
  /** A stop for the whole shop (cool-down like a login wall + a connector event for Ops). */
  halt(reason: "login", page: string, detail: string): Promise<void>;
}

/** How long a freshly opened job page holds the readers back. */
const FILL_JOB_BUSY_MS = 20 * 60_000;
const EMPTY: FillJobsState = { autoOpened: [] };

export function jobUrl(job: Pick<FillJob, "id" | "openPath">): string {
  return `${SELLER_CENTRE_ORIGIN}${job.openPath}#${FILL_HASH_KEY}=${job.id}`;
}

/** The tab really is this job's page (same path and query, the job's id in the address). */
export function senderMatchesJob(tabUrl: string | undefined, job: Pick<FillJob, "id" | "openPath">): boolean {
  if (!tabUrl) return false;
  try {
    const url = new URL(tabUrl);
    const want = new URL(job.openPath, SELLER_CENTRE_ORIGIN);
    return url.origin === SELLER_CENTRE_ORIGIN && url.pathname === want.pathname && url.search === want.search && url.hash === `#${FILL_HASH_KEY}=${job.id}`;
  } catch {
    return false;
  }
}

export class FillJobs {
  constructor(private readonly deps: FillJobsDeps) {}

  private today(): string {
    return gmt7Date(Math.floor(this.deps.now() / 1000));
  }

  private async fill(): Promise<FillJobsState> {
    return (await loadState(this.deps.storage)).fill ?? EMPTY;
  }

  private async setFill(patch: Partial<FillJobsState>): Promise<void> {
    await saveState(this.deps.storage, { fill: { ...(await this.fill()), ...patch } });
  }

  private async list(token: string): Promise<{ enabled: boolean; jobs: FillJob[] } | "unpaired" | "error"> {
    try {
      const raw = (await this.deps.client.fillJobs(token)) as { enabled?: boolean; jobs?: unknown[] } | null;
      const jobs = (Array.isArray(raw?.jobs) ? raw.jobs : []).map(parseFillJob).filter((j): j is FillJob => j !== null);
      return { enabled: raw?.enabled === true, jobs };
    } catch (error) {
      return error instanceof GatewayError && error.status === 401 ? "unpaired" : "error";
    }
  }

  /** A job page was opened a moment ago: the readers wait (one page at a time overall). */
  async isBusy(): Promise<boolean> {
    const active = (await this.fill()).active;
    return !!active && this.deps.now() - active.openedAt < FILL_JOB_BUSY_MS;
  }

  /** The alarm: open the next queued job's page, unless something says wait. */
  async poll(): Promise<string> {
    const state = await loadState(this.deps.storage);
    const token = state.token;
    if (!token || !fillJobsActive(token.shop_id)) return "inactive";
    const now = this.deps.now();
    if ((state.readers?.blocked?.until ?? 0) > now) return this.noted("blocked");
    if (state.consentBlocked) return this.noted("consent_required");
    const fill = state.fill ?? EMPTY;
    if (fill.active) {
      const age = now - fill.active.openedAt;
      const info = fill.active.tabId === undefined ? { open: false } : await this.deps.tabs.inspect(fill.active.tabId);
      // One page at a time: wait for the person to finish with it (or for the tab to go away).
      if (info.open && age < FILL_JOB_STALE_MS) return this.noted("job_open");
      await this.setFill({ active: undefined });
    }
    if (await this.deps.busy()) return this.noted("busy");
    const listed = await this.list(token.token);
    if (listed === "unpaired" || listed === "error") return this.noted(listed);
    if (!listed.enabled) return this.noted("disabled");
    const next = listed.jobs.find((j) => j.status === "queued" && !(fill.autoOpened ?? []).includes(j.id));
    if (!next) return this.noted("nothing_queued");
    if (requestsLeft(state, this.today()) < READER_PAGE_LOAD_COST) return this.noted("budget_spent");
    const tabId = await this.deps.tabs.openPage(jobUrl(next));
    if (tabId === undefined) return this.noted("no_tab");
    await addRequests(this.deps.storage, this.today(), READER_PAGE_LOAD_COST);
    await this.setFill({
      active: { id: next.id, tabId, openedAt: now, counted: true },
      autoOpened: [...(fill.autoOpened ?? []), next.id].slice(-50),
    });
    return this.noted("opened");
  }

  private async noted(status: string): Promise<string> {
    await this.setFill({ lastPoll: { at: new Date(this.deps.now()).toISOString(), status } });
    return status;
  }

  /** A fill page asks for its job. The page must be exactly the job's page. */
  async jobFor(tabUrl: string | undefined, jobId: string): Promise<JobReply> {
    const state = await loadState(this.deps.storage);
    const token = state.token;
    if (!token || !fillJobsActive(token.shop_id)) return { ok: false, reason: "inactive" };
    const listed = await this.list(token.token);
    if (listed === "unpaired") return { ok: false, reason: "unpaired" };
    if (listed === "error") return { ok: false, reason: "error" };
    if (!listed.enabled) return { ok: false, reason: "inactive" };
    const job = listed.jobs.find((j) => j.id === jobId);
    if (!job) return { ok: false, reason: "unknown_job" };
    if (!senderMatchesJob(tabUrl, job)) return { ok: false, reason: "wrong_page" };
    const fill = state.fill ?? EMPTY;
    // A page the person opened with the Demo button counts like one the poll opened.
    if (fill.active?.id !== jobId || !fill.active.counted) {
      if (requestsLeft(state, this.today()) < READER_PAGE_LOAD_COST) return { ok: false, reason: "budget" };
      await addRequests(this.deps.storage, this.today(), READER_PAGE_LOAD_COST);
      await this.setFill({ active: { id: jobId, ...(fill.active?.id === jobId && fill.active.tabId !== undefined ? { tabId: fill.active.tabId } : {}), openedAt: this.deps.now(), counted: true } });
    }
    return { ok: true, value: job };
  }

  /** Progress from the page (or the capture of the new id). */
  async report(jobId: string, status: "opened" | "filled" | "saved" | "captured" | "failed", extra: { capturedRef?: string; error?: string } = {}): Promise<void> {
    const token = (await loadState(this.deps.storage)).token;
    if (!token || !fillJobsActive(token.shop_id)) return;
    try {
      await this.deps.client.fillJobReport(token.token, jobId, {
        status,
        ...(extra.capturedRef ? { captured_ref: extra.capturedRef } : {}),
        ...(extra.error ? { error: extra.error.slice(0, 64) } : {}),
      });
    } catch {
      // Juli unreachable or the job moved on: nothing changes on the page; the checklist catches up.
    }
    if (status === "captured" || status === "failed") {
      const fill = await this.fill();
      if (fill.active?.id === jobId) await this.setFill({ active: undefined });
    }
  }

  /** Shopee asked for the password again on a fill page: stop everything for the shop. */
  async halt(jobId: string, pathname: string): Promise<void> {
    await this.report(jobId, "failed", { error: "password_prompt" });
    await this.setFill({ active: undefined });
    await this.deps.halt("login", pathname, "password_prompt");
  }
}
