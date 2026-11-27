// The service worker's half of the fill queue (P97 D85.6): poll Juli for the token's shop's jobs,
// open the next queued page in a background tab (one page at a time, counted against the shared
// daily request budget), hand the job to the content script that asks for it, and pass its
// progress back. It decides nothing about the seller centre's pages beyond the platform pack's
// job parser (its page allowlist), never clicks anything, and stops for the shop on a password
// prompt. One instance serves one pairing: its storage is that pairing's scope.

import { FILL_HALT_MS, FILL_HASH_KEY, FILL_JOB_STALE_MS, fillJobsActive, READER_PAGE_LOAD_COST } from "../config";
import type { CoreJob, JobReply } from "../fill/form";
import { GatewayError, type IngestClient } from "../ingest/client";
import { gmt7Date } from "../time";
import { addRequests, type FillJobsState, loadCoreState, requestsLeft, saveState, type Storage } from "../state";

/** What the runner needs of a platform pack: where its pages are and which jobs are well formed. */
/** What Juli answers to a save report (E149). */
export interface ReportAnswer {
  /** Juli recorded the card's "Đã làm" itself. */
  cardDone: boolean;
}

export interface JobSource<J extends CoreJob> {
  /** The seller centre origin the job pages open on. */
  origin: string;
  /** One job of the server's answer, or null when anything is off (its page is not allowed, ...). */
  parseJob(raw: unknown): J | null;
  /** 0.3.27: the job tab landed on the platform's anti-bot page: the error code to report, else null. */
  blockedUrl?(url: string | undefined): string | null;
  /**
   * batch-1123-a2 C-K1: a served job of a kind this pack runs, still open, that does not parse: its
   * id (it is reported `failed` with JOB_MALFORMED, never silently dropped), else null.
   */
  malformedId?(raw: unknown): string | null;
  /** 0.3.27: a job whose page is only read (a read-back): its tab is closed once it reported captured. */
  closeWhenDone?(job: J): boolean;
}

/**
 * 0.3.27 (contract C): read-backs the platform's daily readers do (a list page read in the readers'
 * own background tab and posted through the usual ingest path). `pages` says which reader pages a
 * job needs, `"unsupported"` (no reader can read it: the job fails), or null (not a reader
 * read-back: the job's own page is opened like any job).
 */
export interface ReadbackRunner<J extends CoreJob> {
  pages(job: J): string[] | "unsupported" | null;
  /** Ask the readers to read these pages now (idempotent; called again on every poll until read). */
  start(pages: string[]): Promise<void>;
  /** Every page posted since `sinceMs`. */
  readSince(pages: string[], sinceMs: number): Promise<boolean>;
}

export interface FillJobsDeps<J extends CoreJob = CoreJob> {
  storage: Storage;
  client: Pick<IngestClient, "fillJobs" | "fillJobReport">;
  pack: JobSource<J>;
  now: () => number;
  tabs: {
    openPage(url: string): Promise<number | undefined>;
    inspect(tabId: number): Promise<{ open: boolean; url?: string }>;
    /** Closes a tab the runner opened (a read-back's); absent: the tab stays. */
    close?(tabId: number): Promise<void>;
  };
  readback?: ReadbackRunner<J>;
  /** Connector 0.3.18: what the poll tells Juli (a Seller Centre tab is open) and the one command it
   * can receive ("Đối chiếu ngay": run the readers now). Absent: no heartbeat, no command. */
  heartbeat?: {
    sellerCentreOpen(): Promise<boolean>;
    reconcile(): Promise<void>;
  };
  /** Another run (readers, backfill, market) holds the pace: wait. */
  busy(): Promise<boolean>;
  /**
   * A stop for the whole shop (a cool-down + a connector event for Ops): "login" for a password
   * prompt, "traffic_check" (0.3.28) for the platform's anti-bot page: ONE pause the readers, the
   * fills and the read-backs share.
   */
  halt(reason: "login" | "traffic_check", page: string, detail: string): Promise<void>;
}

/** How long a freshly opened job page holds the readers back. */
const FILL_JOB_BUSY_MS = 20 * 60_000;
/** C-K1: the error a served job that does not parse is reported with. */
export const JOB_MALFORMED = "job_malformed";
const EMPTY: FillJobsState = { autoOpened: [] };

export function jobUrl(origin: string, job: Pick<CoreJob, "id" | "openPath">): string {
  return `${origin}${job.openPath}#${FILL_HASH_KEY}=${job.id}`;
}

/** The tab really is this job's page (same origin, path and query, the job's id in the address). */
export function senderMatchesJob(origin: string, tabUrl: string | undefined, job: Pick<CoreJob, "id" | "openPath">): boolean {
  if (!tabUrl) return false;
  try {
    const url = new URL(tabUrl);
    const want = new URL(job.openPath, origin);
    return url.origin === origin && url.pathname === want.pathname && url.search === want.search && url.hash === `#${FILL_HASH_KEY}=${job.id}`;
  } catch {
    return false;
  }
}

export class FillJobs<J extends CoreJob = CoreJob> {
  constructor(private readonly deps: FillJobsDeps<J>) {}

  private today(): string {
    return gmt7Date(Math.floor(this.deps.now() / 1000));
  }

  private async fill(): Promise<FillJobsState> {
    return (await loadCoreState(this.deps.storage)).fill ?? EMPTY;
  }

  private async setFill(patch: Partial<FillJobsState>): Promise<void> {
    await saveState(this.deps.storage, { fill: { ...(await this.fill()), ...patch } });
  }

  private async list(token: string): Promise<{ enabled: boolean; jobs: J[]; malformed: string[]; elsewhere: string[] } | "unpaired" | "error"> {
    try {
      const raw = (await this.deps.client.fillJobs(token)) as { enabled?: boolean; jobs?: unknown[]; leased_elsewhere?: unknown } | null;
      const jobs: J[] = [];
      const malformed: string[] = [];
      for (const served of Array.isArray(raw?.jobs) ? raw.jobs : []) {
        const job = this.deps.pack.parseJob(served);
        if (job) jobs.push(job);
        else {
          const id = this.deps.pack.malformedId?.(served) ?? null;
          if (id) malformed.push(id);
        }
      }
      // E130: jobs another computer holds (the server withholds them from this list)
      const elsewhere = Array.isArray(raw?.leased_elsewhere) ? raw.leased_elsewhere.filter((x): x is string => typeof x === "string") : [];
      return { enabled: raw?.enabled === true, jobs, malformed, elsewhere };
    } catch (error) {
      return error instanceof GatewayError && error.status === 401 ? "unpaired" : "error";
    }
  }

  /**
   * 0.3.28 (F5.3): the job tab is on the platform's anti-bot page: the job fails with the pack's
   * code and the whole shop pauses (fills here, readers and read-backs through `halt`). The code, or
   * null when the URL is fine. Never works around the page.
   */
  private async walled(jobId: string, url: string | undefined): Promise<string | null> {
    const wall = this.deps.pack.blockedUrl?.(url) ?? null;
    if (!wall) return null;
    await this.report(jobId, "failed", { error: wall });
    await this.setFill({ active: undefined, pausedUntil: this.deps.now() + FILL_HALT_MS });
    let page = "";
    try {
      page = new URL(url ?? "").pathname;
    } catch {
      page = "";
    }
    await this.deps.halt("traffic_check", page, wall).catch(() => undefined);
    return wall;
  }

  /** 0.3.28 (F5.3): a tab's address changed; the active job's tab on the anti-bot page stops it at once. */
  async onTabUrl(tabId: number, url: string | undefined): Promise<string | null> {
    const active = (await this.fill()).active;
    if (!active || active.tabId !== tabId) return null;
    return this.walled(active.id, url);
  }

  /** 0.3.28 (F5.4): a fill / revert / read-back job's tab is open now (the readers open no page meanwhile). */
  async tabOpen(): Promise<boolean> {
    const active = (await this.fill()).active;
    if (!active || active.tabId === undefined) return false;
    if (this.deps.now() - active.openedAt >= FILL_JOB_STALE_MS) return false;
    return (await this.deps.tabs.inspect(active.tabId)).open;
  }

  /** A job page was opened a moment ago: the readers wait (one page at a time overall). */
  async isBusy(): Promise<boolean> {
    const active = (await this.fill()).active;
    return !!active && this.deps.now() - active.openedAt < FILL_JOB_BUSY_MS;
  }

  /** The poll doubles as the heartbeat: say whether a Seller Centre tab is open, acknowledge the last
   * command, and run a new "reconcile" command at once (once per command id). Never throws. */
  private async beat(token: string): Promise<void> {
    const hb = this.deps.heartbeat;
    if (!hb) return;
    try {
      const fill = await this.fill();
      const raw = (await this.deps.client.fillJobs(token, { scOpen: await hb.sellerCentreOpen(), ...(fill.doneCommand ? { ack: fill.doneCommand } : {}) })) as { commands?: { type?: unknown; id?: unknown }[] } | null;
      if (fill.doneCommand) await this.setFill({ doneCommand: undefined });
      for (const c of Array.isArray(raw?.commands) ? raw.commands : []) {
        if (c.type !== "reconcile" || typeof c.id !== "string" || c.id.length > 64 || c.id === fill.lastCommand) continue;
        await this.setFill({ lastCommand: c.id, doneCommand: c.id });
        await hb.reconcile();
      }
    } catch {
      // Juli unreachable: the next poll tries again.
    }
  }

  /** The alarm: open the next queued job's page, unless something says wait. */
  async poll(): Promise<string> {
    const state = await loadCoreState(this.deps.storage);
    const token = state.token;
    if (!token || !fillJobsActive(token.shop_id)) return "inactive";
    await this.beat(token.token);
    const now = this.deps.now();
    if ((state.readers?.blocked?.until ?? 0) > now) return this.noted("blocked");
    if (state.consentBlocked) return this.noted("consent_required");
    let fill = state.fill ?? EMPTY;
    if ((fill.pausedUntil ?? 0) > now) return this.noted("paused");
    // the job tab as it is now (0.3.28: checked on every poll, before anything else opens)
    const info = fill.active?.tabId === undefined ? { open: false } : await this.deps.tabs.inspect(fill.active.tabId);
    if (fill.active && info.open) {
      const wall = await this.walled(fill.active.id, info.url);
      if (wall) return this.noted(wall);
    }
    if (this.deps.readback) {
      // F5.4: a read-back's pages are not started while the person's fill tab is open
      await this.readbacks(token.token, !!fill.active && info.open);
      fill = await this.fill();
    }
    if (fill.active) {
      const age = now - fill.active.openedAt;
      // One page at a time: wait for the person to finish with it (or for the tab to go away).
      if (info.open && age < FILL_JOB_STALE_MS) return this.noted("job_open");
      await this.setFill({ active: undefined });
    }
    if (await this.deps.busy()) return this.noted("busy");
    const listed = await this.list(token.token);
    if (listed === "unpaired" || listed === "error") return this.noted(listed);
    if (!listed.enabled) return this.noted("disabled");
    await this.reportMalformed(listed.malformed);
    const handled = (j: J) => this.deps.readback?.pages(j) !== null && this.deps.readback?.pages(j) !== undefined;
    const next = listed.jobs.find((j) => j.status === "queued" && !(fill.autoOpened ?? []).includes(j.id) && !handled(j));
    if (!next) return this.noted("nothing_queued");
    if (requestsLeft(state, this.today()) < READER_PAGE_LOAD_COST) return this.noted("budget_spent");
    const tabId = await this.deps.tabs.openPage(jobUrl(this.deps.pack.origin, next));
    if (tabId === undefined) return this.noted("no_tab");
    await addRequests(this.deps.storage, this.today(), READER_PAGE_LOAD_COST);
    await this.setFill({
      active: { id: next.id, tabId, openedAt: now, counted: true, ...(this.deps.pack.closeWhenDone?.(next) ? { closeWhenDone: true } : {}) },
      autoOpened: [...(fill.autoOpened ?? []), next.id].slice(-50),
    });
    return this.noted("opened");
  }

  /**
   * Contract C: each served read-back the readers do is handed to them once (and again on each poll
   * until read: the call is idempotent), reported `opened`, then `captured` once every page posted
   * after the hand-over. One no reader can do is reported `failed` (`readback_unsupported`).
   */
  private async readbacks(token: string, fillOpen = false): Promise<void> {
    const rb = this.deps.readback!;
    const listed = await this.list(token);
    if (listed === "unpaired" || listed === "error" || !listed.enabled) return;
    const pending = { ...((await this.fill()).readbacks ?? {}) };
    const live = new Set<string>();
    for (const job of listed.jobs) {
      if (job.status !== "queued" && job.status !== "opened") continue;
      const pages = rb.pages(job);
      if (pages === null) continue;
      live.add(job.id);
      if (pages === "unsupported") {
        await this.report(job.id, "failed", { error: "readback_unsupported" });
        continue;
      }
      const since = pending[job.id];
      if (since !== undefined && (await rb.readSince(pages, since))) {
        await this.report(job.id, "captured");
        delete pending[job.id];
        continue;
      }
      if (since === undefined) {
        pending[job.id] = this.deps.now();
        await this.report(job.id, "opened");
      }
      if (!fillOpen) await rb.start(pages);
    }
    for (const id of Object.keys(pending)) if (!live.has(id)) delete pending[id];
    await this.setFill({ readbacks: pending });
  }

  /** C-K1: each served job that does not parse is told to Juli once (`failed`, JOB_MALFORMED). */
  private async reportMalformed(ids: string[]): Promise<void> {
    const told = (await this.fill()).malformed ?? [];
    const fresh = ids.filter((id) => !told.includes(id));
    if (fresh.length === 0) return;
    for (const id of fresh) await this.report(id, "failed", { error: JOB_MALFORMED });
    await this.setFill({ malformed: [...told, ...fresh].slice(-50) });
  }

  private async noted(status: string): Promise<string> {
    await this.setFill({ lastPoll: { at: new Date(this.deps.now()).toISOString(), status } });
    return status;
  }

  /** A fill page asks for its job. The page must be exactly the job's page. */
  async jobFor(tabUrl: string | undefined, jobId: string): Promise<JobReply<J>> {
    const state = await loadCoreState(this.deps.storage);
    const token = state.token;
    if (!token || !fillJobsActive(token.shop_id)) return { ok: false, reason: "inactive" };
    const listed = await this.list(token.token);
    if (listed === "unpaired") return { ok: false, reason: "unpaired" };
    if (listed === "error") return { ok: false, reason: "error" };
    if (!listed.enabled) return { ok: false, reason: "inactive" };
    const job = listed.jobs.find((j) => j.id === jobId);
    if (!job && listed.malformed.includes(jobId)) {
      await this.reportMalformed([jobId]);
      return { ok: false, reason: "malformed_job" };
    }
    if (!job && listed.elsewhere.includes(jobId)) return { ok: false, reason: "leased_elsewhere" };
    if (!job) return { ok: false, reason: "unknown_job" };
    if (!senderMatchesJob(this.deps.pack.origin, tabUrl, job)) return { ok: false, reason: "wrong_page" };
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
  async report(
    jobId: string,
    status: "opened" | "filled" | "saved" | "captured" | "failed",
    extra: { capturedRef?: string; error?: string; progress?: { filled: number; total: number }; detail?: ReportDetail } = {},
  ): Promise<ReportAnswer | void> {
    const token = (await loadCoreState(this.deps.storage)).token;
    if (!token || !fillJobsActive(token.shop_id)) return;
    let answer: ReportAnswer | undefined;
    try {
      const raw = await this.deps.client.fillJobReport(token.token, jobId, {
        status,
        ...(extra.capturedRef ? { captured_ref: extra.capturedRef } : {}),
        ...(extra.error ? { error: extra.error.slice(0, 64) } : {}),
        ...(extra.progress ? { progress: extra.progress } : {}),
        ...(extra.detail ? extra.detail : {}),
      });
      // E149: after a save Juli says whether it recorded "Đã làm" itself
      if (typeof raw === "object" && raw !== null && typeof (raw as { card_done?: unknown }).card_done === "boolean") answer = { cardDone: (raw as { card_done: boolean }).card_done };
    } catch {
      // Juli unreachable or the job moved on: nothing changes on the page; the checklist catches up.
    }
    if (status === "captured" || status === "failed") {
      const fill = await this.fill();
      if (fill.active?.id === jobId) {
        await this.setFill({ active: undefined });
        // a read-back's page was only read: its tab goes (never the person's own tab of a fill)
        const tabId = fill.active.tabId;
        // 0.3.28: a read-back that could not read (failed) also closes its background tab
        if ((status === "captured" || status === "failed") && tabId !== undefined && fill.active.closeWhenDone && this.deps.tabs.close) await this.deps.tabs.close(tabId).catch(() => undefined);
      }
    }
    return answer;
  }

  /** The platform asked for the password again on a fill page: stop everything for the shop. */
  async halt(jobId: string, pathname: string): Promise<void> {
    await this.report(jobId, "failed", { error: "password_prompt" });
    await this.setFill({ active: undefined });
    await this.deps.halt("login", pathname, "password_prompt");
  }
}

/**
 * 0.3.24: what a fill saw, as Juli stores it on the job: each field's value before Juli wrote it
 * (the revert puts it back), whether a time-bound form's period holds the card's dates, and each
 * field's last read. Validated here: bounded keys and values, nothing else passes.
 */
export interface ReportDetail {
  before_values: Record<string, string>;
  period_ok?: boolean;
  fields: { key: string; ok: boolean; seen: string }[];
}

const DETAIL_KEY = /^[a-z][a-z0-9_]{0,39}$/;
const MAX_DETAIL_FIELDS = 40;

export function reportDetailOf(raw: unknown): ReportDetail | undefined {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return undefined;
  const r = raw as Record<string, unknown>;
  const before: Record<string, string> = {};
  const b = r.before_values;
  if (typeof b === "object" && b !== null && !Array.isArray(b)) {
    for (const [k, v] of Object.entries(b as Record<string, unknown>).slice(0, MAX_DETAIL_FIELDS)) {
      if (DETAIL_KEY.test(k) && typeof v === "string") before[k] = v.slice(0, 600);
    }
  }
  const fields: ReportDetail["fields"] = [];
  for (const f of Array.isArray(r.fields) ? r.fields.slice(0, MAX_DETAIL_FIELDS) : []) {
    const x = f as Record<string, unknown> | null;
    if (x && typeof x.key === "string" && DETAIL_KEY.test(x.key) && typeof x.ok === "boolean") {
      fields.push({ key: x.key, ok: x.ok, seen: typeof x.seen === "string" ? x.seen.slice(0, 120) : "" });
    }
  }
  return { before_values: before, fields, ...(typeof r.period_ok === "boolean" ? { period_ok: r.period_ok } : {}) };
}
