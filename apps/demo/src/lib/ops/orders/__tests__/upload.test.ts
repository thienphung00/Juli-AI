import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { OrderLinesUploaded, OrderRefKeyResponse } from "../../types";
import { postOrderLines, prepareOrderUpload } from "../upload";
import { CANARIES, KEY_HEX, PLAIN, RAW_ORDER_IDS } from "./fixtures";

function fakeApi(over: Partial<OrderRefKeyResponse> = {}) {
  const calls = { keys: [] as string[], uploads: [] as { shopId: string; body: string }[] };
  return {
    calls,
    api: {
      async orderRefKey(shopId: string): Promise<OrderRefKeyResponse> {
        calls.keys.push(shopId);
        return { order_ref_key: KEY_HEX, algorithm: "HMAC-SHA256", key_version: 1, expires_at: "2026-11-03T03:10:00Z", ...over };
      },
      async uploadOrderLines(shopId: string, lines: unknown[]): Promise<OrderLinesUploaded> {
        calls.uploads.push({ shopId, body: JSON.stringify({ lines }) });
        return { lines: lines.length, duplicate: false };
      },
    },
  };
}

/** Node's experimental `localStorage` getter is unusable without a file; a plain in-memory store stands in. */
class MemoryStorage {
  private readonly items = new Map<string, string>();
  readonly setItem = vi.fn((key: string, value: string) => void this.items.set(key, String(value)));
  getItem(key: string): string | null {
    return this.items.get(key) ?? null;
  }
  removeItem(key: string): void {
    this.items.delete(key);
  }
  clear(): void {
    this.items.clear();
  }
  dump(): string {
    return JSON.stringify([...this.items.entries()]);
  }
}

describe("the upload", () => {
  const local = new MemoryStorage();
  const session = new MemoryStorage();
  beforeEach(() => {
    local.clear();
    session.clear();
    local.setItem.mockClear();
    session.setItem.mockClear();
    Object.defineProperty(window, "localStorage", { configurable: true, value: local });
    Object.defineProperty(window, "sessionStorage", { configurable: true, value: session });
  });
  afterEach(() => vi.restoreAllMocks());

  it("fetches the key once for the shop, posts only hashed PII-free lines, and never stores the key", async () => {
    const { api, calls } = fakeApi();
    const parsed = await prepareOrderUpload(PLAIN, "shop-1", api);
    expect(calls.keys).toEqual(["shop-1"]);
    const progress = await postOrderLines(parsed, "shop-1", api);
    expect(progress).toEqual({ posted: 11, total: 11, duplicates: 0 });
    expect(calls.keys).toEqual(["shop-1"]); // the key is not asked for again to post
    expect(calls.uploads.length).toBe(2);
    expect(calls.uploads.every((u) => u.shopId === "shop-1")).toBe(true);
    const posted = calls.uploads.map((u) => u.body).join("\n");
    for (const forbidden of [...CANARIES, ...RAW_ORDER_IDS, KEY_HEX, "parity-fixture-key"]) expect(posted).not.toContain(forbidden);
    // The key is in no browser storage, cookie or the parsed result.
    expect(local.setItem).not.toHaveBeenCalled();
    expect(session.setItem).not.toHaveBeenCalled();
    expect(local.dump()).not.toContain(KEY_HEX);
    expect(session.dump()).not.toContain(KEY_HEX);
    expect(document.cookie).not.toContain(KEY_HEX);
    expect(JSON.stringify(parsed)).not.toContain(KEY_HEX);
  });

  it("reports progress after each lot and counts a duplicate lot", async () => {
    const { api } = fakeApi();
    const parsed = await prepareOrderUpload(PLAIN, "shop-1", api);
    const seen: number[] = [];
    let n = 0;
    const result = await postOrderLines(
      parsed,
      "shop-1",
      { uploadOrderLines: async (_s, lines) => ({ lines: lines.length, duplicate: (n += 1) === 1 }) },
      (p) => seen.push(p.posted),
    );
    expect(seen.length).toBe(2);
    expect(result.duplicates).toBe(1);
  });

  it("refuses a key of another algorithm and parses nothing", async () => {
    const { api } = fakeApi({ algorithm: "HMAC-MD5" });
    await expect(prepareOrderUpload(PLAIN, "shop-1", api)).rejects.toThrow();
  });
});
