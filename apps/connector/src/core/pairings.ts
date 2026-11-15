// Pairings (T11): one install holds one pairing per shop, each scoped to its platform. The shop
// and the platform come only from the pairing token Juli issues; the Connector has no shop list.
//
// Storage: the index `pairings` maps shop id -> { platform, scope }. A pairing's own state (its
// token, stops, queue, budget, fill-job and reader bookkeeping) lives under its scope: the
// registry's first ("legacy") pack keeps the unprefixed keys every install used before the split
// (so an existing pairing is not touched: same keys, same values), any other pack's pairing keeps
// `p:<shop id>:<key>`. A platform holds one pairing at a time: pairing another shop of the same
// platform replaces it, as pairing again always did (one seller centre session per browser).
//
// Migration: an install paired before the split has a `token` and no index. The first load adds
// the index entry for that token (legacy scope) -- no re-pairing, nothing else changes.

import { GatewayError, type IngestClient, type TokenInfo } from "./ingest/client";
import type { Storage } from "./state";

export const PAIRINGS_KEY = "pairings";

export interface Pairing {
  shopId: string;
  /** A platform pack id (the token's `platform`). */
  platform: string;
  /** The storage key prefix of the pairing's state ("" = the legacy, unprefixed keys). */
  scope: string;
}

type Index = Record<string, Pairing>;

/** The scope of a pairing: "" for the legacy pack, `p:<shop id>:` for any other. */
export function scopeFor(legacyPlatform: string, platform: string, shopId: string): string {
  return platform === legacyPlatform ? "" : `p:${shopId}:`;
}

/** `storage` seen through a scope: every key is prefixed (the legacy scope is `storage` itself). */
export function scopedStorage(storage: Storage, scope: string): Storage {
  if (scope === "") return storage;
  const prefixed = (keys: string | string[] | null | undefined): string[] | null =>
    keys == null ? null : (Array.isArray(keys) ? keys : [keys]).map((key) => `${scope}${key}`);
  return {
    async get(keys) {
      const raw = await storage.get(prefixed(keys));
      const out: Record<string, unknown> = {};
      for (const [key, value] of Object.entries(raw)) if (key.startsWith(scope)) out[key.slice(scope.length)] = value;
      return out;
    },
    async set(items) {
      await storage.set(Object.fromEntries(Object.entries(items).map(([key, value]) => [`${scope}${key}`, value])));
    },
  };
}

/** Juli refused the code for this platform (the code is for a shop of another platform). */
export function isPlatformMismatch(error: unknown): boolean {
  return error instanceof GatewayError && error.status === 409 && error.code === "platform_mismatch";
}

/**
 * Offer a pairing code to each platform in turn until one takes it. Juli checks the code's shop
 * platform before it uses the code up, so a mismatch leaves the code valid for the next platform.
 * Any other refusal ends it; when every platform refuses, the last refusal is thrown.
 */
export async function pairAcross<P extends { id: string }>(
  packs: readonly P[],
  attempt: (pack: P) => Promise<TokenInfo>,
): Promise<{ pack: P; token: TokenInfo }> {
  let last: unknown = new Error("no platform pack");
  for (const pack of packs) {
    try {
      return { pack, token: await attempt(pack) };
    } catch (error) {
      if (!isPlatformMismatch(error)) throw error;
      last = error;
    }
  }
  throw last;
}

export class Pairings {
  constructor(
    private readonly storage: Storage,
    private readonly legacyPlatform: string,
  ) {}

  private async index(): Promise<Index> {
    const raw = (await this.storage.get([PAIRINGS_KEY, "token"])) as { pairings?: Index; token?: TokenInfo };
    const index: Index = { ...(raw.pairings ?? {}) };
    const legacy = raw.token;
    // Migration (and the legacy pack's own re-pairing, which writes `token` directly): the legacy
    // scope's token is the legacy pack's pairing.
    if (legacy?.shop_id && index[legacy.shop_id]?.scope !== "") {
      for (const [shopId, p] of Object.entries(index)) if (p.scope === "") delete index[shopId];
      index[legacy.shop_id] = { shopId: legacy.shop_id, platform: legacy.platform || this.legacyPlatform, scope: "" };
      await this.storage.set({ [PAIRINGS_KEY]: index });
    }
    return index;
  }

  /** The live pairings (an entry whose scope no longer holds a token -- revoked, unpaired -- is left out). */
  async list(): Promise<Pairing[]> {
    const index = await this.index();
    const live: Pairing[] = [];
    for (const pairing of Object.values(index)) {
      const { token } = (await scopedStorage(this.storage, pairing.scope).get(["token"])) as { token?: TokenInfo };
      if (token?.shop_id === pairing.shopId) live.push(pairing);
    }
    return live;
  }

  async get(shopId: string): Promise<Pairing | undefined> {
    return (await this.list()).find((p) => p.shopId === shopId);
  }

  async forPlatform(platform: string): Promise<Pairing | undefined> {
    return (await this.list()).find((p) => p.platform === platform);
  }

  /**
   * Record a pairing whose token is already in its scope (the legacy pack's connector writes it), or
   * write `token` into the scope first (`writeToken`). Another pairing of the same platform is replaced.
   */
  async record(token: TokenInfo, platform: string, writeToken = false): Promise<Pairing> {
    const scope = scopeFor(this.legacyPlatform, platform, token.shop_id);
    if (writeToken) await scopedStorage(this.storage, scope).set({ token });
    const index = await this.index();
    for (const [shopId, p] of Object.entries(index)) {
      if (p.platform !== platform || shopId === token.shop_id) continue;
      delete index[shopId];
      if (p.scope !== "") await scopedStorage(this.storage, p.scope).set({ token: null });
    }
    const pairing: Pairing = { shopId: token.shop_id, platform, scope };
    index[token.shop_id] = pairing;
    await this.storage.set({ [PAIRINGS_KEY]: index });
    return pairing;
  }

  /** Forget one pairing (its token goes; the rest of its scope stays, like an unpair always did). */
  async remove(shopId: string): Promise<void> {
    const index = await this.index();
    const pairing = index[shopId];
    if (!pairing) return;
    delete index[shopId];
    if (pairing.scope !== "") await scopedStorage(this.storage, pairing.scope).set({ token: null });
    await this.storage.set({ [PAIRINGS_KEY]: index });
  }
}

/** Rotate a scope's token when Juli says it is due; a 401 (revoked, expired) unpairs that scope. */
export async function rotateIfDue(storage: Storage, client: Pick<IngestClient, "rotate">, nowMs: number): Promise<string> {
  const { token } = (await storage.get(["token"])) as { token?: TokenInfo };
  if (!token) return "unpaired";
  if (Date.parse(token.rotate_after) > nowMs) return "not_due";
  try {
    await storage.set({ token: await client.rotate(token.token) });
    return "rotated";
  } catch (error) {
    if (error instanceof GatewayError && error.status === 401) {
      await storage.set({ token: null, lastError: { at: new Date(nowMs).toISOString(), code: error.code } });
      return "unpaired";
    }
    return "error";
  }
}
