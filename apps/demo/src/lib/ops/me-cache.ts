import type { OpsMe } from "./types";

/**
 * `GET /v1/ops/me` once per tab session (P22). Every Ops page used to wait for
 * it (~2.9 s in prod) before even asking for its own data. The answer is kept
 * in memory and in sessionStorage (per tab, keyed by the signed-in token so a
 * different account never sees another's role), and refreshed in the
 * background when it is older than {@link ME_MAX_AGE_MS}. sessionStorage may be
 * unavailable (private mode, blocked storage): every access is guarded and the
 * memory copy still works.
 */

export const ME_CACHE_KEY = "juli-ops-me";
export const ME_MAX_AGE_MS = 5 * 60 * 1000;

interface Entry {
  readonly me: OpsMe;
  readonly at: number;
  readonly who: string;
}

let memory: Entry | null = null;
let inflight: { who: string; promise: Promise<OpsMe> } | null = null;

/** Which signed-in session an entry belongs to: the tail of its access token. */
export function sessionKey(token: string): string {
  return token.slice(-24);
}

function readStored(who: string): Entry | null {
  try {
    const raw = window.sessionStorage.getItem(ME_CACHE_KEY);
    if (!raw) return null;
    const entry = JSON.parse(raw) as Partial<Entry>;
    if (entry.who !== who || !entry.me || typeof entry.at !== "number") return null;
    return entry as Entry;
  } catch {
    return null;
  }
}

/** The cached `me` of this session, or null. */
export function readCachedMe(token: string): { me: OpsMe; fresh: boolean } | null {
  const who = sessionKey(token);
  const entry = memory?.who === who ? memory : readStored(who);
  if (!entry) return null;
  memory = entry;
  return { me: entry.me, fresh: Date.now() - entry.at < ME_MAX_AGE_MS };
}

export function writeCachedMe(token: string, me: OpsMe): void {
  memory = { me, at: Date.now(), who: sessionKey(token) };
  try {
    window.sessionStorage.setItem(ME_CACHE_KEY, JSON.stringify(memory));
  } catch {
    // storage blocked: the memory copy is enough for this tab
  }
}

export function clearCachedMe(): void {
  memory = null;
  inflight = null;
  try {
    window.sessionStorage.removeItem(ME_CACHE_KEY);
  } catch {
    // nothing stored
  }
}

/** One `me` request at a time per session: concurrent gates share it. */
export function loadMe(token: string, fetchMe: () => Promise<OpsMe>): Promise<OpsMe> {
  const who = sessionKey(token);
  if (inflight && inflight.who === who) return inflight.promise;
  const promise = fetchMe().then(
    (me) => {
      writeCachedMe(token, me);
      if (inflight?.promise === promise) inflight = null;
      return me;
    },
    (error: unknown) => {
      if (inflight?.promise === promise) inflight = null;
      throw error;
    },
  );
  inflight = { who, promise };
  return promise;
}
