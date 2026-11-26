// batch-1124-a C3: a token Juli no longer accepts (401: revoked, superseded by a re-pair of this
// install, expired) stops its pairing by itself. Its token leaves its scope (the popup then shows
// its usual "not connected" state and pairing form), and once no pairing holds a live token every
// alarm goes, so nothing keeps waking up to poll, beat or read for a shop Juli has let go.
// Pairing again re-creates the alarms (the service worker's `ensureAlarms`).

import type { TokenInfo } from "./ingest/client";
import { type Pairings, scopedStorage } from "./pairings";
import type { Storage } from "./state";

export interface DeadTokenDeps {
  storage: Storage;
  pairings: Pick<Pairings, "list">;
  /** Clears every alarm of the extension. */
  clearAlarms(): Promise<void>;
  now: () => number;
}

export type DeadTokenOutcome = "stopped" | "cleared" | "unknown";

/**
 * The 401 for `token` (with Juli's error code): every scope still holding exactly that token drops
 * it and records the code; "stopped" when no live pairing is left (alarms cleared), "cleared" when
 * another pairing still runs, "unknown" when no scope held it (already handled, or a rotated-away
 * token after a successful rotation).
 */
export async function stopDeadToken(deps: DeadTokenDeps, token: string, code: string): Promise<DeadTokenOutcome> {
  const lastError = { at: new Date(deps.now()).toISOString(), code };
  let found = false;
  // The scopes the index knows, and the unprefixed one (a legacy install without an index yet).
  const scopes = new Set<string>([""]);
  for (const pairing of await deps.pairings.list()) scopes.add(pairing.scope);
  for (const scope of scopes) {
    const scoped = scopedStorage(deps.storage, scope);
    const held = ((await scoped.get(["token"])) as { token?: TokenInfo | null }).token;
    if (!held || held.token !== token) continue;
    await scoped.set({ token: null, lastError });
    found = true;
  }
  if (!found) return "unknown";
  if ((await deps.pairings.list()).length > 0) return "cleared";
  await deps.clearAlarms();
  return "stopped";
}
