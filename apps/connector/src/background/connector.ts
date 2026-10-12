// The service worker's logic, with Chrome injected so it can be unit-tested:
// captured responses → mapped → posted; drift → reported and that dataset
// stopped; the daily sync → sent to an open Seller Centre tab; token rotation.

import { type Dataset } from "../config";
import { GatewayClient, GatewayError, ingestBody, type TokenInfo } from "../ingest/client";
import { type Captured, mapCaptured } from "../shopee/map";
import { buildSyncPlan } from "../shopee/sync";
import { yesterdayRange } from "../shopee/time";
import { enqueue, loadState, saveState, type State, type Storage, stoppedFor } from "./state";

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

export type CaptureOutcome = "ignored" | "unpaired" | "stopped" | "drift" | "posted" | "queued" | "rejected";

export class Connector {
  constructor(private readonly deps: Deps) {}

  private iso(): string {
    return new Date(this.deps.now()).toISOString();
  }

  async state(): Promise<State> {
    return loadState(this.deps.storage);
  }

  async pair(code: string): Promise<TokenInfo> {
    const token = await this.deps.client.pair(code.trim(), `Juli Connector ${this.deps.version}`);
    await saveState(this.deps.storage, { token, stopped: {}, queue: [], lastError: undefined });
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

  async handleCapture(captured: Captured): Promise<CaptureOutcome> {
    const mapped = mapCaptured(captured);
    if (mapped === null) return "ignored";
    const state = await this.state();
    if (!state.token) return "unpaired";
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
        await this.onAuthError(error);
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
    if (!state.token || state.queue.length === 0) return;
    const remaining = [];
    for (const item of state.queue) {
      try {
        await this.deps.client.post(state.token.token, item.dataset, item.body);
      } catch (error) {
        if (await this.onAuthError(error)) return;
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
      await this.onAuthError(error);
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
}
