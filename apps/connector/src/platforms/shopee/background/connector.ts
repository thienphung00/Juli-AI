// The service worker's logic, with Chrome injected so it can be unit-tested:
// captured responses → mapped → posted; drift → reported and that dataset
// stopped; the daily sync → sent to an open Seller Centre tab; token rotation.

import {
  READER_BLOCK_CAPTCHA_MS,
  READER_BLOCK_RATE_MS,
  BACKFILL_DAYS,
  BACKFILL_IN_FLIGHT_TIMEOUT_MS,
  BACKFILL_MAX_DAY_ATTEMPTS,
  type Dataset,
  HELD_DATASETS,
  MAX_ROWS_PER_POST,
  type ReaderDataset,
} from "../config";
import { GatewayClient, GatewayError, ingestBody, type TokenInfo } from "../ingest/client";
import { type Captured, mapCapturedAll, type Mapped } from "../map";
import { mapMarketSearch } from "../market";
import { importOrderRefKey, orderRef } from "../ingest/order-ref";
import { RAW_ORDER_ID } from "../affiliate-map";
import { mapReaderJob } from "../reader-map";
import { classify, type ReaderJob, type ReaderResponse } from "../reader";
import { isDataAnswer, type RequestResult } from "../runner";
import { backfillDatasets, buildBackfillDayPlan, buildSyncPlan } from "../sync";
import { parseReadDays, type ReadDays } from "./catchup";
import { gmt7Date, lastFinishedDays, yesterdayRange } from "../../../core/time";
import type { BlockEvent, TickReport } from "./scheduler";
import {
  addRequests,
  type Backfill,
  type BackfillStopReason,
  enqueue,
  loadState,
  backfillRequestsLeft,
  requestsLeft,
  saveState,
  type State,
  type Storage,
  stoppedFor,
} from "./state";

export interface Tabs {
  /** Ids of open Seller Centre tabs. */
  sellerCentreTabs(): Promise<number[]>;
  send(tabId: number, message: unknown): Promise<unknown>;
}

export interface Deps {
  storage: Storage;
  client: GatewayClient;
  tabs: Tabs;
  version: string;
  now: () => number;
  /** True while another Seller Centre reader (the scheduler's run) is using the pace budget. */
  busy?: () => Promise<boolean>;
}

export type CaptureOutcome =
  /** The gateway does not accept this dataset yet (config HELD_DATASETS): mapped, not sent. */
  | "held"
  | "ignored"
  /** Shopee answered with an empty list for the period: a real zero, nothing to post (0.3.15). */
  | "empty"
  | "unpaired"
  | "stopped"
  | "drift"
  | "posted"
  | "queued"
  | "rejected"
  /** Juli refused the shop (403 consent_required): nothing more is sent until the seller retries. */
  | "refused";

/** The backfill's provisional item pages (D31.6): an error code stops only that dataset (0.3.20). */
const ITEM_BACKFILL_DATASETS: ReadonlySet<Dataset> = new Set<Dataset>(["item_by_source", "item_performance"]);

/** After a transient Seller Centre failure, the backfill waits this long before the day again. */
const BACKFILL_RETRY_DELAY_MS = 10 * 60_000;

/** Juli's gateway refusing a shop without consent (PR #2199): a stop, never retried. */
export function isConsentRefusal(error: unknown): boolean {
  return error instanceof GatewayError && error.status === 403 && error.code === "consent_required";
}

/** Outcome heads of a reader page that was read (or had nothing to read): anything else is not "read". */
const READ_OUTCOMES: ReadonlySet<string> = new Set(["done", "no_items", "no_campaigns", "no_group_campaigns", "no_orders"]);

/**
 * 0.3.25: yesterday's numbers are "synced" only when every page of today's reader run was read: a
 * blocked / failed / waiting page keeps "Đồng bộ hôm qua" from answering already_synced. Without a
 * run of today (or with an old state that has no outcomes) nothing is known to be missing.
 */
export function todaysPagesAllRead(readers: State["readers"], today: string): boolean {
  if (readers?.lastRun?.day !== today) return true;
  return Object.values(readers.lastRun.outcomes).every((outcome) => READ_OUTCOMES.has(String(outcome).split(/[:|]/, 1)[0] ?? ""));
}

export class Connector {
  private lock: Promise<unknown> = Promise.resolve();

  constructor(private readonly deps: Deps) {}

  /** Backfill bookkeeping runs one step at a time (service-worker events interleave). */
  private exclusive<T>(work: () => Promise<T>): Promise<T> {
    const next = this.lock.then(work, work);
    this.lock = next.catch(() => undefined);
    return next;
  }

  private iso(): string {
    return new Date(this.deps.now()).toISOString();
  }

  async state(): Promise<State> {
    return loadState(this.deps.storage);
  }

  async pair(code: string): Promise<TokenInfo> {
    const token = await this.deps.client.pair(code.trim(), `Juli Connector ${this.deps.version}`);
    const previous = await this.state();
    await saveState(this.deps.storage, {
      token,
      stopped: {},
      queue: [],
      lastError: undefined,
      consentBlocked: undefined,
      // One backfill per shop: pairing the same shop again resumes it (done days stay done).
      backfill: previous.backfill?.shopId === token.shop_id ? previous.backfill : undefined,
    });
    return token;
  }

  async unpair(): Promise<void> {
    await saveState(this.deps.storage, { token: undefined, queue: [], pendingSync: false });
  }

  private async onAuthError(error: unknown): Promise<boolean> {
    if (error instanceof GatewayError && error.status === 401) {
      // Revoked, expired or rotated away: the seller pairs again from Juli.
      await saveState(this.deps.storage, {
        token: undefined,
        lastError: { at: this.iso(), code: error.code },
      });
      return true;
    }
    return false;
  }

  private async onRefusal(error: unknown): Promise<boolean> {
    if (!isConsentRefusal(error)) return false;
    await saveState(this.deps.storage, {
      consentBlocked: { at: this.iso() },
      lastError: { at: this.iso(), code: "consent_required" },
    });
    return true;
  }

  async handleCapture(captured: Captured): Promise<CaptureOutcome> {
    const all = mapCapturedAll(captured);
    if (all.length === 0) return "ignored";
    // One answer can hold several order types (product_overview): the first outcome that is not a post wins.
    let outcome: CaptureOutcome = "posted";
    for (const mapped of all) {
      const result = await this.submit(mapped, captured.capturedAt);
      if (outcome === "posted") outcome = result;
      if (result === "unpaired" || result === "refused") return result;
    }
    return outcome;
  }

  /**
   * Post one mapped response: drift is reported and that dataset stopped; rows go to the
   * gateway in chunks of at most MAX_ROWS_PER_POST (a failed chunk is queued for a retry).
   */
  async submit(mapped: Mapped, capturedAt: number): Promise<CaptureOutcome> {
    const state = await this.state();
    if (!state.token) return "unpaired";
    if (state.consentBlocked) return "refused";
    const { version } = this.deps;
    if (HELD_DATASETS.has(mapped.dataset as ReaderDataset)) return "held";
    if (stoppedFor(state, version).has(mapped.dataset)) return "stopped";
    const token = state.token.token;

    if (mapped.drift) {
      await saveState(this.deps.storage, {
        stopped: {
          ...state.stopped,
          [mapped.dataset]: { version, at: this.iso(), ...mapped.drift },
        },
      });
      try {
        await this.deps.client.reportDrift(token, mapped.dataset, version, mapped.endpoint, mapped.drift);
      } catch (error) {
        if (!(await this.onAuthError(error))) await this.onRefusal(error);
      }
      return "drift";
    }
    if (mapped.rows.length === 0) return mapped.answeredEmpty ? "empty" : "ignored";
    // A raw Shopee order id never leaves the browser: such a row must have been hashed first.
    if (mapped.rows.some((row) => RAW_ORDER_ID in row)) return "rejected";

    let outcome: CaptureOutcome = "posted";
    for (let start = 0; start < mapped.rows.length; start += MAX_ROWS_PER_POST) {
      const chunk = { ...mapped, rows: mapped.rows.slice(start, start + MAX_ROWS_PER_POST) };
      const result = await this.postChunk(chunk, capturedAt, token);
      if (result !== "posted") {
        outcome = result;
        if (result === "unpaired" || result === "refused" || result === "stopped") break;
      }
    }
    return outcome;
  }

  private async postChunk(mapped: Mapped, capturedAt: number, token: string): Promise<CaptureOutcome> {
    const { version } = this.deps;
    const state = await this.state();
    const body = ingestBody(mapped, version, capturedAt);
    try {
      const result = (await this.deps.client.post(token, mapped.dataset, body)) as {
        rows?: number;
        duplicate?: boolean;
      };
      await saveState(this.deps.storage, {
        lastPosts: {
          ...state.lastPosts,
          [mapped.dataset]: { at: this.iso(), rows: result?.rows ?? 0, duplicate: !!result?.duplicate },
        },
      });
      return "posted";
    } catch (error) {
      if (await this.onAuthError(error)) return "unpaired";
      if (await this.onRefusal(error)) return "refused";
      if (error instanceof GatewayError) {
        if (error.code === "dataset_in_drift") {
          await saveState(this.deps.storage, {
            stopped: {
              ...state.stopped,
              [mapped.dataset]: { version, at: this.iso(), unexpected: [], missing: [] },
            },
          });
          return "stopped";
        }
        // 4xx: the gateway refused the data itself; retrying the same body cannot help.
        if (error.status < 500 && error.status !== 429) {
          await saveState(this.deps.storage, { lastError: { at: this.iso(), code: error.code } });
          return "rejected";
        }
      }
      await saveState(this.deps.storage, {
        queue: enqueue(state.queue, { dataset: mapped.dataset, body, attempts: 1 }),
      });
      return "queued";
    }
  }

  /**
   * A reader job's responses (from the page hook) → mapped → posted. Returns how each dataset
   * ended, e.g. `{ item_catalog: "posted", item_snapshot: "held" }`.
   */
  async postReader(job: ReaderJob, responses: ReaderResponse[]): Promise<Record<string, CaptureOutcome>> {
    const capturedAt = responses.reduce((latest, r) => Math.max(latest, r.capturedAt), 0) || this.deps.now();
    const outcomes: Record<string, CaptureOutcome> = {};
    // "affiliate": one post per purchase window (0.3.17 history), keyed by the window's end.
    const perDate = new Set(["ads", "item_traffic", "affiliate", "affiliate_dashboard", "affiliate_bills"]);
    for (const raw of mapReaderJob(job, responses, capturedAt)) {
      const key =
        job.id === "shop_totals" || job.id === "product_period"
          ? `${raw.dataset}:${raw.orderType}`
          : job.id === "traffic"
            ? `${raw.dataset}:${raw.date}${raw.orderType ? `:${raw.orderType}` : ""}`
            : perDate.has(job.id)
              ? `${raw.dataset}:${raw.date}`
              : raw.dataset;
      const mapped = await this.hashOrderIds(raw);
      outcomes[key] = mapped ? await this.submit(mapped, capturedAt) : "rejected";
    }
    return outcomes;
  }

  /**
   * Affiliate conversion rows carry the raw order id only until here: it is replaced by
   * `order_ref` with the shop's key from Juli (never stored). No key, no post.
   */
  private async hashOrderIds(mapped: Mapped): Promise<Mapped | null> {
    if (!mapped.rows.some((row) => RAW_ORDER_ID in row)) return mapped;
    const state = await this.state();
    if (!state.token) return mapped; // submit() answers "unpaired"
    let key: CryptoKey;
    try {
      const answer = (await this.deps.client.orderRefKey(state.token.token)) as { order_ref_key?: unknown };
      if (typeof answer?.order_ref_key !== "string") throw new Error("no key");
      key = await importOrderRefKey(answer.order_ref_key);
    } catch (error) {
      if (await this.onAuthError(error)) return null;
      await saveState(this.deps.storage, { lastError: { at: this.iso(), code: "order_ref_key_unavailable" } });
      return null;
    }
    const rows = await Promise.all(
      mapped.rows.map(async (row) => {
        const { [RAW_ORDER_ID]: orderId, ...rest } = row;
        return { ...rest, order_ref: await orderRef(String(orderId), key) };
      }),
    );
    return { ...mapped, rows };
  }

  /**
   * 0.3.27 (contract D, E20 / E50): what a fill / read-back page showed Shopee holds for its
   * products (the first line of a description, the name, the open-campaign commission), posted as
   * `item_catalog` rows. Only these fields of well-formed rows pass; the gateway keeps a stored
   * name when a row carries none.
   */
  async postCurrent(raw: unknown): Promise<CaptureOutcome> {
    const rows = currentRowsOf(raw);
    if (rows.length === 0) return "ignored";
    const now = this.deps.now();
    return this.submit(
      { dataset: "item_catalog", endpoint: "page:current_values", date: gmt7Date(Math.floor(now / 1000)), orderType: null, rows, drift: null, granularity: "period" },
      now,
    );
  }

  /** One keyword's page-1 search answer -> mapped -> posted (dataset market_search). */
  async postMarket(keyword: string, body: unknown, capturedAt: number): Promise<CaptureOutcome> {
    return this.submit(mapMarketSearch(keyword, body, capturedAt), capturedAt);
  }

  /** Retry queued posts (oldest first); a post that keeps failing is dropped after 5 tries. */
  async flushQueue(): Promise<void> {
    const state = await this.state();
    if (!state.token || state.consentBlocked || state.queue.length === 0) return;
    const remaining = [];
    for (const [index, item] of state.queue.entries()) {
      try {
        await this.deps.client.post(state.token.token, item.dataset, item.body);
      } catch (error) {
        if (await this.onAuthError(error)) return;
        if (await this.onRefusal(error)) {
          // Keep what is left for after the shop gets consent; stop sending now.
          await saveState(this.deps.storage, { queue: [...remaining, ...state.queue.slice(index)] });
          return;
        }
        if (error instanceof GatewayError && error.status < 500 && error.status !== 429) continue;
        if (item.attempts < 5) remaining.push({ ...item, attempts: item.attempts + 1 });
      }
    }
    await saveState(this.deps.storage, { queue: remaining });
  }

  async rotateIfDue(): Promise<void> {
    const state = await this.state();
    if (!state.token || Date.parse(state.token.rotate_after) > this.deps.now()) return;
    try {
      const token = await this.deps.client.rotate(state.token.token);
      await saveState(this.deps.storage, { token });
    } catch (error) {
      await this.onAuthError(error);
    }
  }

  private today(): string {
    return gmt7Date(Math.floor(this.deps.now() / 1000));
  }

  /** A CAPTCHA / login wall / rate-limit stop is in force: no request of any kind goes to Seller Centre. */
  private async halted(state: State): Promise<boolean> {
    return (state.readers?.blocked?.until ?? 0) > this.deps.now();
  }

  /**
   * 429 / 403 / CAPTCHA seen by the daily sync or the backfill stops ALL readers for the shop with
   * the scheduler's own cool-down, and is told to Juli (a connector event) so Ops can see it.
   */
  private async haltAll(reason: "captcha" | "rate_limit", reader: string, page: string, code: string): Promise<void> {
    const state = await this.state();
    const sched = state.readers ?? { adsDone: [], trafficDone: [] };
    const until = this.deps.now() + (reason === "captcha" ? READER_BLOCK_CAPTCHA_MS : READER_BLOCK_RATE_MS);
    await saveState(this.deps.storage, {
      readers: { ...sched, blocked: { at: this.iso(), reason, page: "products", until } },
    });
    await this.reportBlock({ reader, page, status: reason, code, at: this.iso() });
  }

  /**
   * 0.3.29 (F4.2, contract C2): the days of the last 30 Juli has no accepted row for, per daily
   * dataset. Undefined when Juli could not answer (the run goes on without catch-up).
   */
  async readDays(): Promise<ReadDays | undefined> {
    const state = await this.state();
    if (!state.token || state.consentBlocked) return undefined;
    try {
      return parseReadDays(await this.deps.client.readDays(state.token.token), gmt7Date(Math.floor(this.deps.now() / 1000)));
    } catch (error) {
      if (!(await this.onAuthError(error))) await this.onRefusal(error);
      return undefined;
    }
  }

  /**
   * 0.3.29 (F4.2): reopen days of the per-day backfill for the mydata item datasets the hole list names:
   * yesterday first, then oldest first; a reopened day asks only for the datasets that were missing.
   */
  reopenBackfillDays(datasets: Record<string, string[]>): Promise<void> {
    return this.exclusive(async () => {
      const state = await this.state();
      const backfill = state.backfill;
      if (!state.token || !backfill || backfill.shopId !== state.token.shop_id) return;
      const all = backfillDatasets() as Dataset[];
      const yesterday = yesterdayRange(this.deps.now()).date;
      const missing = new Map<string, Set<Dataset>>();
      for (const [dataset, days] of Object.entries(datasets)) {
        if (!all.includes(dataset as Dataset)) continue;
        for (const day of days) missing.set(day, new Set([...(missing.get(day) ?? []), dataset as Dataset]));
      }
      if (missing.size === 0) return;
      const holeDays = [...missing.keys()].sort();
      const ordered = holeDays.includes(yesterday) ? [yesterday, ...holeDays.filter((d) => d !== yesterday)] : holeDays;
      const accepted = { ...backfill.accepted };
      for (const [day, wanted] of missing) {
        const have = new Set<Dataset>(accepted[day] ?? (backfill.done.includes(day) ? all : []));
        for (const dataset of wanted) have.delete(dataset);
        accepted[day] = [...have];
      }
      const days = [...ordered, ...backfill.days.filter((d) => !missing.has(d))];
      await saveState(this.deps.storage, {
        backfill: {
          ...backfill,
          days,
          done: backfill.done.filter((d) => !missing.has(d)),
          accepted,
          status: backfill.status === "done" ? "running" : backfill.status,
        },
      });
    });
  }

  /** Tell Juli a stop happened (reader, page, status, time). Best effort: a failed post changes nothing. */
  async reportBlock(event: BlockEvent): Promise<void> {
    const state = await this.state();
    if (!state.token) return;
    try {
      await this.deps.client.connectorEvent(state.token.token, event, this.deps.version);
    } catch (error) {
      if (!(await this.onAuthError(error))) await this.onRefusal(error);
    }
  }

  /** The scheduler's tick (0.3.19): a finished run or a skip, told to Juli. Best effort. */
  async reportTick(report: TickReport): Promise<void> {
    const state = await this.state();
    if (!state.token || state.consentBlocked) return;
    try {
      await this.deps.client.connectorTick(state.token.token, report, this.deps.version);
    } catch (error) {
      if (!(await this.onAuthError(error))) await this.onRefusal(error);
    }
  }

  /**
   * The daily alarm (or a Seller Centre tab opening while a sync is pending):
   * ask an open Seller Centre tab to re-issue yesterday's calls. No tab → wait.
   */
  async dailySync(): Promise<string> {
    const state = await this.state();
    if (!state.token) return "unpaired";
    if (state.consentBlocked) return "consent_required";
    const day = yesterdayRange(this.deps.now()).date;
    if (state.lastSync?.day === day && state.lastSync.status === "done" && todaysPagesAllRead(state.readers, this.today())) return "already_synced";
    if (await this.halted(state)) return "blocked";
    if (await this.deps.busy?.()) {
      // A scheduled reader run holds the Seller Centre pace budget: try again when a tab reports ready.
      await saveState(this.deps.storage, { pendingSync: true });
      return "busy";
    }
    const tabs = await this.deps.tabs.sellerCentreTabs();
    const tab = tabs[0];
    if (tab === undefined) {
      await saveState(this.deps.storage, { pendingSync: true });
      return "no_tab";
    }
    const plan = buildSyncPlan(this.deps.now(), stoppedFor(state, this.deps.version));
    // The shared daily request budget is checked before the plan goes out.
    if (plan.length > requestsLeft(state, this.today())) return "budget_spent";
    await saveState(this.deps.storage, {
      pendingSync: false,
      lastSync: { day, at: this.iso(), status: "requested" },
    });
    await this.deps.tabs.send(tab, { type: "sync", plan });
    return "requested";
  }

  async syncResult(status: string, sent = 0): Promise<void> {
    const state = await this.state();
    await addRequests(this.deps.storage, this.today(), sent);
    const day = yesterdayRange(this.deps.now()).date;
    await saveState(this.deps.storage, {
      lastSync: { day, at: this.iso(), status },
      // The page had not made a data call yet: try again when a tab next reports ready.
      pendingSync: status === "needs_data_page" ? true : state.pendingSync,
    });
  }

  async tabReady(): Promise<string> {
    const state = await this.state();
    return state.pendingSync ? this.dailySync() : "idle";
  }

  /** A backfill day is out at a Seller Centre tab: a scheduled run waits for it. */
  async backfillInFlight(): Promise<boolean> {
    const { backfill } = await this.state();
    return !!backfill?.inFlight && this.deps.now() - backfill.inFlight.at < BACKFILL_IN_FLIGHT_TIMEOUT_MS;
  }

  async serverStatus(): Promise<unknown> {
    const state = await this.state();
    if (!state.token) return null;
    try {
      return await this.deps.client.status(state.token.token);
    } catch (error) {
      if (!(await this.onAuthError(error))) await this.onRefusal(error);
      return null;
    }
  }

  /** Clear local stops (after the seller updated the extension, for example). */
  async resume(dataset: Dataset): Promise<void> {
    const state = await this.state();
    const stopped = { ...state.stopped };
    delete stopped[dataset];
    await saveState(this.deps.storage, { stopped });
  }

  /**
   * The seller pressed "Đồng bộ" in the popup: lift a consent refusal (the shop may
   * have been granted consent since) and try once more, daily sync then backfill.
   */
  async syncNow(): Promise<string> {
    const state = await this.state();
    if (state.consentBlocked) await saveState(this.deps.storage, { consentBlocked: undefined });
    return this.dailySync();
  }

  /** A response the page itself loaded: posted as before; a data answer proves the session. */
  async pageCapture(captured: Captured): Promise<CaptureOutcome> {
    const outcome = await this.handleCapture(captured);
    if (isDataAnswer(200, captured.body)) {
      await this.exclusive(async () => {
        const { backfill } = await this.state();
        if (!backfill) return;
        if (backfill.status === "stopped" && backfill.stop?.reason === "session") {
          await saveState(this.deps.storage, {
            backfill: { ...backfill, status: "running", stop: undefined, inFlight: undefined, needsDataPage: false },
          });
        } else if (backfill.needsDataPage) {
          await saveState(this.deps.storage, { backfill: { ...backfill, needsDataPage: false } });
        }
      });
    }
    return outcome;
  }

  // -- the one-time 30-day backfill -------------------------------------------------

  private newBackfill(shopId: string): Backfill {
    return {
      shopId,
      createdAt: this.iso(),
      days: lastFinishedDays(this.deps.now(), BACKFILL_DAYS),
      done: [],
      accepted: {},
      attempts: {},
      status: "running",
    };
  }

  private resumable(backfill: Backfill, state: State): boolean {
    const stop = backfill.stop;
    if (!stop) return true;
    switch (stop.reason) {
      case "consent_required":
        return !state.consentBlocked;
      case "unpaired":
        return !!state.token;
      case "invalid_param":
      case "shopee_error": {
        // Like a dataset stop: a new extension version tries again. 0.3.20: so does a backfill whose
        // stopping dataset has since posted (a reader / the daily sync read it fine after the stop).
        if (stop.version !== this.deps.version) return true;
        const posted = stop.dataset ? state.lastPosts[stop.dataset]?.at : undefined;
        return posted !== undefined && Date.parse(posted) > Date.parse(stop.at);
      }
      case "session":
        return false; // resumed by pageCapture once the page loads data again
    }
  }

  private async stopBackfill(
    backfill: Backfill,
    reason: BackfillStopReason,
    detail: { day?: string; dataset?: Dataset; code?: string } = {},
  ): Promise<string> {
    await saveState(this.deps.storage, {
      backfill: {
        ...backfill,
        status: "stopped",
        inFlight: undefined,
        stop: { reason, at: this.iso(), version: this.deps.version, ...detail },
      },
    });
    return `stopped:${reason}`;
  }

  /**
   * Send the next backfill day (newest first) to an open Seller Centre tab, or say
   * why not. Called after pairing, on the alarm, when a tab is ready, after each
   * day's answer and after the page loads data. Never sends a day twice at once.
   */
  backfillStep(): Promise<string> {
    return this.exclusive(() => this.step());
  }

  private async step(): Promise<string> {
    const state = await this.state();
    if (!state.token) return "unpaired";
    let backfill = state.backfill;
    if (!backfill || backfill.shopId !== state.token.shop_id) {
      backfill = this.newBackfill(state.token.shop_id);
      await saveState(this.deps.storage, { backfill });
    }
    if (backfill.status === "done") return "done";
    if (state.consentBlocked) {
      if (backfill.status !== "stopped") await this.stopBackfill(backfill, "consent_required");
      return "consent_required";
    }
    if (backfill.status === "stopped") {
      if (!this.resumable(backfill, state)) return "stopped";
      backfill = { ...backfill, status: "running", stop: undefined, inFlight: undefined };
    }
    const now = this.deps.now();
    if (backfill.inFlight && now - backfill.inFlight.at < BACKFILL_IN_FLIGHT_TIMEOUT_MS) return "in_flight";
    if (backfill.needsDataPage) return "needs_data_page";
    if (await this.halted(state)) return "blocked";
    if (await this.deps.busy?.()) return "busy";
    if ((backfill.notBefore ?? 0) > now) {
      await saveState(this.deps.storage, { backfill });
      return "waiting";
    }

    // The next day (newest first) with something left to ask for. A day whose
    // remaining datasets are stopped after drift stays open for a new version.
    const stopped = stoppedFor(state, this.deps.version);
    const done = new Set(backfill.done);
    const nowDone: string[] = [];
    let next: { day: string; plan: ReturnType<typeof buildBackfillDayPlan> } | undefined;
    for (const day of backfill.days) {
      if (done.has(day)) continue;
      const accepted = new Set<Dataset>(backfill.accepted[day] ?? []);
      if (buildBackfillDayPlan(day, now, accepted).length === 0) {
        nowDone.push(day);
        continue;
      }
      const plan = buildBackfillDayPlan(day, now, new Set([...accepted, ...stopped]));
      if (plan.length > 0) {
        next = { day, plan };
        break;
      }
    }
    if (nowDone.length > 0) backfill = { ...backfill, done: [...backfill.done, ...nowDone] };
    if (!next) {
      const finished = backfill.days.every((d) => backfill.done.includes(d));
      await saveState(this.deps.storage, {
        backfill: { ...backfill, status: finished ? "done" : backfill.status, inFlight: undefined },
      });
      return finished ? "done" : "datasets_stopped";
    }
    // The shared daily request budget: a backfill day waits for tomorrow once today's is spent.
    // F4.4: later pages of a paged list are sent only after a full page, so a day is planned at its first pages.
    if (next.plan.filter((r) => !r.page || r.params.page_num === "1").length > backfillRequestsLeft(state, this.today())) {
      await saveState(this.deps.storage, { backfill: { ...backfill, inFlight: undefined } });
      return "budget_spent";
    }
    const tab = (await this.deps.tabs.sellerCentreTabs())[0];
    if (tab === undefined) {
      await saveState(this.deps.storage, { backfill: { ...backfill, inFlight: undefined } });
      return "no_tab";
    }
    await saveState(this.deps.storage, { backfill: { ...backfill, inFlight: { day: next.day, at: now } } });
    try {
      await this.deps.tabs.send(tab, { type: "backfill", day: next.day, plan: next.plan });
    } catch {
      // The tab closed or has no content script yet: try again on the next trigger.
      await saveState(this.deps.storage, { backfill: { ...backfill, inFlight: undefined } });
      return "no_tab";
    }
    return "requested";
  }

  /** One backfill day's answer from the page hook. */
  backfillResult(day: string, status: string, results: RequestResult[]): Promise<string> {
    return this.exclusive(() => this.dayResult(day, status, results));
  }

  private async dayResult(day: string, status: string, results: RequestResult[]): Promise<string> {
    const state = await this.state();
    const current = state.backfill;
    if (!current || current.inFlight?.day !== day) return "stale";
    let backfill: Backfill = { ...current, inFlight: undefined };
    await addRequests(this.deps.storage, this.today(), results.length);
    if (status !== "done") {
      // needs_data_page: the tab has not loaded a data page yet; the page's next data call resumes.
      await saveState(this.deps.storage, { backfill: { ...backfill, needsDataPage: status === "needs_data_page" } });
      return status;
    }
    if (!state.token) return this.stopBackfill(backfill, "unpaired", { day });
    // 0.3.29: code 10000 "not login" is mydata's answer to a call made outside /datacenter/: not a stop, the
    // day waits for a Phân tích bán hàng tab (the page's next data call resumes it)
    if (results.some((r) => (r.body as { code?: unknown } | null)?.code === 10000)) {
      await saveState(this.deps.storage, { backfill: { ...backfill, needsDataPage: true } });
      return "needs_data_page";
    }
    const accepted = new Set<Dataset>(backfill.accepted[day] ?? []);
    const keepAccepted = (): Backfill => ({
      ...backfill,
      accepted: { ...backfill.accepted, [day]: [...accepted] },
    });

    for (const result of results) {
      const body = result.body as { code?: unknown; error?: unknown } | null;
      const ok2xx = result.status >= 200 && result.status < 300;
      // 0.3.20: `{error, data}` answers carry their code as `error`.
      const hasCode = typeof body === "object" && body !== null && ("code" in body || "error" in body);
      const answerCode = typeof body === "object" && body !== null ? ("code" in body ? body.code : body.error) : undefined;
      if (isDataAnswer(result.status, result.body) || (ok2xx && typeof body === "object" && body !== null && !hasCode)) {
        // Data (or a reshaped answer, which handleCapture reports as drift).
        const outcome = await this.handleCapture({ url: result.url, body: result.body, capturedAt: result.capturedAt });
        if (outcome === "unpaired") {
          backfill = keepAccepted();
          return this.stopBackfill(backfill, "unpaired", { day, dataset: result.dataset });
        }
        if (outcome === "refused") {
          backfill = keepAccepted();
          return this.stopBackfill(backfill, "consent_required", { day, dataset: result.dataset });
        }
        // posted / queued (retried by the queue) / ignored / rejected: fetching this
        // day again would not change the outcome. drift / stopped: the day stays
        // open for that dataset until a new extension version.
        if (outcome !== "drift" && outcome !== "stopped") accepted.add(result.dataset);
        continue;
      }
      backfill = keepAccepted();
      if (result.status === 429 || result.status === 403) {
        // Rate limit / refusal: every reader stops, not just this day (P97).
        const verdict = classify(result.status, result.body) === "captcha" ? "captcha" : "rate_limit";
        await this.haltAll(verdict, "backfill", new URL(result.url, "https://banhang.shopee.vn").pathname, `http_${result.status}`);
        return this.stopBackfill(backfill, result.status === 403 ? "session" : "shopee_error", {
          day,
          dataset: result.dataset,
          code: `http_${result.status}`,
        });
      }
      if (result.status === 401 || (ok2xx && !hasCode)) {
        // Refused, or a login page instead of JSON: the Seller Centre session is gone.
        return this.stopBackfill(backfill, "session", { day, dataset: result.dataset, code: `http_${result.status}` });
      }
      if (ok2xx && hasCode && ITEM_BACKFILL_DATASETS.has(result.dataset) && classify(result.status, result.body) === "error") {
        // 0.3.20: an item page (provisional, D31.6) answering with an error code stops THAT dataset
        // for this version (like drift), not the whole 30-day backfill; the other datasets go on.
        const current = await this.state();
        await saveState(this.deps.storage, {
          stopped: {
            ...current.stopped,
            [result.dataset]: { version: this.deps.version, at: this.iso(), unexpected: [`code=${String(answerCode).slice(0, 20)}`], missing: [] },
          },
          lastError: { at: this.iso(), code: `shopee_${String(answerCode).slice(0, 20)}` },
        });
        continue;
      }
      if (ok2xx && answerCode === 10006) {
        // "err:invalid param": the recorded day shape no longer works. Record, do not loop.
        await saveState(this.deps.storage, { lastError: { at: this.iso(), code: "shopee_10006" } });
        return this.stopBackfill(backfill, "invalid_param", { day, dataset: result.dataset, code: "10006" });
      }
      if (result.status === 0 || result.status === 429 || result.status >= 500) {
        const attempts = (backfill.attempts[day] ?? 0) + 1;
        backfill = { ...backfill, attempts: { ...backfill.attempts, [day]: attempts } };
        if (attempts >= BACKFILL_MAX_DAY_ATTEMPTS) {
          return this.stopBackfill(backfill, "shopee_error", { day, dataset: result.dataset, code: `http_${result.status}` });
        }
        await saveState(this.deps.storage, {
          backfill: { ...backfill, notBefore: this.deps.now() + BACKFILL_RETRY_DELAY_MS },
        });
        return "retry_later";
      }
      const code = ok2xx ? String(answerCode) : `http_${result.status}`;
      return this.stopBackfill(backfill, "shopee_error", { day, dataset: result.dataset, code });
    }

    const attempts = { ...backfill.attempts };
    delete attempts[day];
    const dayDone = buildBackfillDayPlan(day, this.deps.now(), accepted).length === 0;
    const acceptedByDay = { ...backfill.accepted, [day]: [...accepted] };
    if (dayDone) delete acceptedByDay[day];
    const doneDays = dayDone ? [...backfill.done, day] : backfill.done;
    const finished = backfill.days.every((d) => doneDays.includes(d));
    await saveState(this.deps.storage, {
      backfill: {
        ...backfill,
        done: doneDays,
        accepted: acceptedByDay,
        attempts,
        notBefore: undefined,
        status: finished ? "done" : backfill.status,
      },
    });
    return dayDone ? "accepted" : "partial";
  }
}

const MAX_CURRENT_ROWS = 200;

/** Contract D rows from a page message: digits item_id, bounded text, a 0–100 commission; nothing else. */
export function currentRowsOf(raw: unknown): Record<string, string | number>[] {
  if (!Array.isArray(raw)) return [];
  const out: Record<string, string | number>[] = [];
  for (const r of raw.slice(0, MAX_CURRENT_ROWS)) {
    if (typeof r !== "object" || r === null) continue;
    const x = r as Record<string, unknown>;
    if (typeof x.item_id !== "string" || !/^\d{1,20}$/.test(x.item_id)) continue;
    const row: Record<string, string | number> = { item_id: x.item_id };
    if (typeof x.item_name === "string" && x.item_name.trim()) row.item_name = x.item_name.trim().slice(0, 500);
    if (typeof x.description_first_line === "string" && x.description_first_line.trim()) {
      row.description_first_line = x.description_first_line.replace(/[\r\n]+/g, " ").trim().slice(0, 300);
    }
    if (typeof x.commission_pct === "number" && Number.isFinite(x.commission_pct) && x.commission_pct >= 0 && x.commission_pct <= 100) {
      row.commission_pct = x.commission_pct;
    }
    if (Object.keys(row).length > 1) out.push(row);
  }
  return out;
}
