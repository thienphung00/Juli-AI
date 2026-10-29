/**
 * The partner trial account record kept beside the auth session (fast track
 * P32-A). Written after a password sign-in confirmed by `GET /v1/reviewer/me`;
 * read by the shell to enter reviewer mode. Presentation only — the server
 * refuses every write of a reviewer whatever this record says. Pure browser
 * storage, no network call site.
 */

import { readPersistent, removePersistent, writePersistent } from "../persistent-storage";

export const REVIEWER_STORAGE_KEY = "juli_demo_reviewer";

/**
 * P74-A (D77): one shop the reviewer may switch to. A masked shop comes as its
 * alias id and masked name only; the sandbox shop as it is.
 */
export interface ReviewerShopOption {
  readonly id: string;
  readonly name: string;
  readonly mode: "sandbox" | "masked";
  readonly writesEnabled: boolean;
}

/** P74-A: the `shops` list of `GET /v1/reviewer/me` (or a stored record), malformed entries dropped. */
export function parseReviewerShops(value: unknown): ReviewerShopOption[] {
  if (!Array.isArray(value)) return [];
  const shops: ReviewerShopOption[] = [];
  for (const entry of value as Array<Record<string, unknown> | null>) {
    if (!entry || typeof entry.id !== "string" || !entry.id) continue;
    if (entry.mode !== "sandbox" && entry.mode !== "masked") continue;
    shops.push({
      id: entry.id,
      name: typeof entry.name === "string" ? entry.name : "",
      mode: entry.mode,
      writesEnabled: entry.writes_enabled === true || entry.writesEnabled === true,
    });
  }
  return shops;
}


export interface ReviewerRecord {
  readonly platform: string;
  readonly expiresAt: string | null;
  /**
   * P32-D (D42 amendment): no reference shop pinned (reviewer "me" says
   * `shop: null`) — the reviewer sees the bundled sample shop, no shop API.
   */
  readonly sample?: boolean;
  /**
   * P64 (D73): "sandbox" — pinned to Juli's live TikTok sandbox shop: real
   * data and real writes, no sample, no simulation. "masked" / absent: P32.
   */
  readonly mode?: "sandbox" | "masked";
  readonly writesEnabled?: boolean;
  /**
   * P74-A (D77): every pinned shop, default first — the shop menu offers a
   * switch when there are two or more. Absent / empty: nothing to switch to.
   */
  readonly shops?: readonly ReviewerShopOption[];
}

export function storeReviewerRecord(record: ReviewerRecord): void {
  if (typeof window === "undefined") return;
  writePersistent(REVIEWER_STORAGE_KEY, JSON.stringify(record));
}

export function readReviewerRecord(): ReviewerRecord | null {
  if (typeof window === "undefined") return null;
  const raw = readPersistent(REVIEWER_STORAGE_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<ReviewerRecord>;
    if (typeof parsed.platform !== "string" || !parsed.platform) return null;
    return {
      platform: parsed.platform,
      expiresAt: typeof parsed.expiresAt === "string" ? parsed.expiresAt : null,
      ...(parsed.sample === true ? { sample: true } : {}),
      ...(parsed.mode === "sandbox" || parsed.mode === "masked" ? { mode: parsed.mode } : {}),
      ...(parsed.writesEnabled === true ? { writesEnabled: true } : {}),
      ...(Array.isArray(parsed.shops) && parsed.shops.length > 0 ? { shops: parseReviewerShops(parsed.shops) } : {}),
    };
  } catch {
    return null;
  }
}

export function clearReviewerRecord(): void {
  if (typeof window === "undefined") return;
  removePersistent(REVIEWER_STORAGE_KEY);
}
