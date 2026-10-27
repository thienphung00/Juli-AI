// What the extension keeps in chrome.storage.local: the ingest token (never a
// Juli password or session), per-dataset stops after drift, the last sync, and a
// small retry queue of posts that failed on the network.

import type { Dataset } from "../config";
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
