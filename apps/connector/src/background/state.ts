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

export interface State {
  token?: TokenInfo;
  stopped: Partial<Record<Dataset, Stop>>;
  lastSync?: { day: string; at: string; status: string };
  lastPosts: Partial<Record<Dataset, { at: string; rows: number; duplicate: boolean }>>;
  pendingSync?: boolean;
  queue: Queued[];
  lastError?: { at: string; code: string };
}

export const MAX_QUEUE = 20;

export interface Storage {
  get(keys?: string | string[] | null): Promise<Record<string, unknown>>;
  set(items: Record<string, unknown>): Promise<void>;
}

export async function loadState(storage: Storage): Promise<State> {
  const raw = (await storage.get(["token", "stopped", "lastSync", "lastPosts", "pendingSync", "queue", "lastError"])) as Partial<State>;
  return {
    token: raw.token,
    stopped: raw.stopped ?? {},
    lastSync: raw.lastSync,
    lastPosts: raw.lastPosts ?? {},
    pendingSync: raw.pendingSync,
    queue: raw.queue ?? [],
    lastError: raw.lastError,
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
