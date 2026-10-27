// The service worker's logic, with Chrome injected so it can be unit-tested:
// captured responses → mapped → posted; drift → reported and that dataset
// stopped; the daily sync → sent to an open Seller Centre tab; token rotation.

import {
  BACKFILL_DAYS,
  BACKFILL_IN_FLIGHT_TIMEOUT_MS,
  BACKFILL_MAX_DAY_ATTEMPTS,
  type Dataset,
} from "../config";
import { GatewayClient, GatewayError, ingestBody, type TokenInfo } from "../ingest/client";
import { type Captured, mapCaptured } from "../shopee/map";
import { isDataAnswer, type RequestResult } from "../shopee/runner";
import { buildBackfillDayPlan, buildSyncPlan } from "../shopee/sync";
import { lastFinishedDays, yesterdayRange } from "../shopee/time";
import {
  type Backfill,
  type BackfillStopReason,
  enqueue,
  loadState,
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
}

export type CaptureOutcome =
  | "ignored"
  | "unpaired"
  | "stopped"
  | "drift"
  | "posted"
  | "queued"
  | "rejected"
  /** Juli refused the shop (403 consent_required): nothing more is sent until the seller retries. */
  | "refused";

/** After a transient Seller Centre failure, the backfill waits this long before the day again. */
const BACKFILL_RETRY_DELAY_MS = 10 * 60_000;

/** Juli's gateway refusing a shop without consent (PR #2199): a stop, never retried. */
export function isConsentRefusal(error: unknown): boolean {
  return error instanceof GatewayError && error.status === 403 && error.code === "consent_required";
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
    const mapped = mapCaptured(captured);
    if (mapped === null) return "ignored";
    const state = await this.state();
    if (!state.token) return "unpaired";
    if (state.consentBlocked) return "refused";
    const { version } = this.deps;
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
    if (mapped.rows.length === 0) return "ignored";

    const body = ingestBody(mapped, version, captured.capturedAt);
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

  /**
   * The daily alarm (or a Seller Centre tab opening while a sync is pending):
   * ask an open Seller Centre tab to re-issue yesterday's calls. No tab → wait.
   */
  async dailySync(): Promise<string> {
    const state = await this.state();
    if (!state.token) return "unpaired";
    if (state.consentBlocked) return "consent_required";
    const day = yesterdayRange(this.deps.now()).date;
    if (state.lastSync?.day === day && state.lastSync.status === "done") return "already_synced";
    const tabs = await this.deps.tabs.sellerCentreTabs();
    const tab = tabs[0];
    if (tab === undefined) {
      await saveState(this.deps.storage, { pendingSync: true });
      return "no_tab";
    }
    const plan = buildSyncPlan(this.deps.now(), stoppedFor(state, this.deps.version));
    await saveState(this.deps.storage, {
      pendingSync: false,
      lastSync: { day, at: this.iso(), status: "requested" },
    });
    await this.deps.tabs.send(tab, { type: "sync", plan });
    return "requested";
  }

  async syncResult(status: string): Promise<void> {
    const state = await this.state();
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
      case "shopee_error":
        // Like a dataset stop: a new extension version tries again.
        return stop.version !== this.deps.version;
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
    if (status !== "done") {
      // needs_data_page: the tab has not loaded a data page yet; the page's next data call resumes.
      await saveState(this.deps.storage, { backfill: { ...backfill, needsDataPage: status === "needs_data_page" } });
      return status;
    }
    if (!state.token) return this.stopBackfill(backfill, "unpaired", { day });
    const accepted = new Set<Dataset>(backfill.accepted[day] ?? []);
    const keepAccepted = (): Backfill => ({
      ...backfill,
      accepted: { ...backfill.accepted, [day]: [...accepted] },
    });

    for (const result of results) {
      const body = result.body as { code?: unknown } | null;
      const ok2xx = result.status >= 200 && result.status < 300;
      const hasCode = typeof body === "object" && body !== null && "code" in body;
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
      if (result.status === 401 || result.status === 403 || (ok2xx && !hasCode)) {
        // Refused, or a login page instead of JSON: the Seller Centre session is gone.
        return this.stopBackfill(backfill, "session", { day, dataset: result.dataset, code: `http_${result.status}` });
      }
      if (ok2xx && body?.code === 10006) {
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
      const code = ok2xx ? String(body?.code) : `http_${result.status}`;
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
