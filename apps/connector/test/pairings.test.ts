// Pairings keyed by shop, each scoped to its platform (T11). Core only, fake platforms.
import { describe, expect, it } from "vitest";
import manifest from "../public/manifest.json";
import pkg from "../package.json";
import { GatewayError, type TokenInfo } from "../src/core/ingest/client";
import { PAIRINGS_KEY, Pairings, pairAcross, rotateIfDue, scopedStorage, scopeFor } from "../src/core/pairings";
import { loadCoreState } from "../src/core/state";

class MemoryStorage {
  data: Record<string, unknown> = {};
  async get(keys?: string | string[] | null) {
    const list = keys == null ? Object.keys(this.data) : Array.isArray(keys) ? keys : [keys];
    return Object.fromEntries(list.filter((k) => this.data[k] != null).map((k) => [k, this.data[k]]));
  }
  async set(items: Record<string, unknown>) {
    Object.assign(this.data, items);
  }
}

const token = (shop_id: string, platform: string, over: Partial<TokenInfo> = {}): TokenInfo => ({
  token: `jci_${shop_id}`,
  token_id: `t_${shop_id}`,
  shop_id,
  platform,
  expires_at: "2027-01-10T00:00:00Z",
  rotate_after: "2026-12-01T00:00:00Z",
  ...over,
});

const LEGACY = "legacyplat";

describe("the storage scope of a pairing", () => {
  it("is the unprefixed keys for the legacy platform and p:<shop>: for any other", () => {
    expect(scopeFor(LEGACY, LEGACY, "s1")).toBe("");
    expect(scopeFor(LEGACY, "otherplat", "s2")).toBe("p:s2:");
  });

  it("prefixes every key it reads and writes; the legacy scope is the storage itself", async () => {
    const storage = new MemoryStorage();
    expect(scopedStorage(storage, "")).toBe(storage);
    const scoped = scopedStorage(storage, "p:s2:");
    await scoped.set({ token: token("s2", "otherplat"), budget: { day: "2026-11-15", used: 3 } });
    expect(Object.keys(storage.data).sort()).toEqual(["p:s2:budget", "p:s2:token"]);
    expect(await scoped.get(["budget"])).toEqual({ budget: { day: "2026-11-15", used: 3 } });
    expect((await loadCoreState(scoped)).token?.shop_id).toBe("s2");
    expect((await loadCoreState(storage)).token).toBeUndefined();
  });
});

describe("Pairings", () => {
  it("migrates the single pre-split pairing on load: an index entry, nothing else touched", async () => {
    const storage = new MemoryStorage();
    const before = { token: token("s1", LEGACY), readers: { adsDone: [] }, budget: { day: "d", used: 7 } };
    Object.assign(storage.data, structuredClone(before));
    const pairings = new Pairings(storage, LEGACY);
    expect(await pairings.list()).toEqual([{ shopId: "s1", platform: LEGACY, scope: "" }]);
    expect(storage.data[PAIRINGS_KEY]).toEqual({ s1: { shopId: "s1", platform: LEGACY, scope: "" } });
    const { [PAIRINGS_KEY]: _index, ...rest } = storage.data;
    expect(rest).toEqual(before);
  });

  it("takes the platform of an old token without one from the legacy pack", async () => {
    const storage = new MemoryStorage();
    storage.data.token = { ...token("s1", LEGACY), platform: "" };
    expect(await new Pairings(storage, LEGACY).list()).toEqual([{ shopId: "s1", platform: LEGACY, scope: "" }]);
  });

  it("holds one pairing per shop across platforms, each in its own scope", async () => {
    const storage = new MemoryStorage();
    storage.data.token = token("s1", LEGACY);
    const pairings = new Pairings(storage, LEGACY);
    await pairings.record(token("s2", "otherplat"), "otherplat", true);
    expect(await pairings.list()).toEqual([
      { shopId: "s1", platform: LEGACY, scope: "" },
      { shopId: "s2", platform: "otherplat", scope: "p:s2:" },
    ]);
    expect((storage.data.token as TokenInfo).shop_id).toBe("s1");
    expect((storage.data["p:s2:token"] as TokenInfo).shop_id).toBe("s2");
    expect(await pairings.forPlatform("otherplat")).toMatchObject({ shopId: "s2" });
    expect(await pairings.get("s1")).toMatchObject({ platform: LEGACY });
  });

  it("replaces the pairing of the same platform when another shop of it pairs", async () => {
    const storage = new MemoryStorage();
    const pairings = new Pairings(storage, LEGACY);
    await pairings.record(token("s2", "otherplat"), "otherplat", true);
    await pairings.record(token("s3", "otherplat"), "otherplat", true);
    expect((await pairings.list()).map((p) => p.shopId)).toEqual(["s3"]);
    expect(storage.data["p:s2:token"]).toBeNull();
    // the legacy pack re-pairing another shop (its connector writes `token`): the index follows
    storage.data.token = token("s1", LEGACY);
    expect((await pairings.list()).map((p) => p.shopId).sort()).toEqual(["s1", "s3"]);
    storage.data.token = token("s9", LEGACY);
    expect((await pairings.list()).map((p) => p.shopId).sort()).toEqual(["s3", "s9"]);
  });

  it("leaves out a pairing whose token is gone, and forgets one on remove", async () => {
    const storage = new MemoryStorage();
    storage.data.token = token("s1", LEGACY);
    const pairings = new Pairings(storage, LEGACY);
    await pairings.record(token("s2", "otherplat"), "otherplat", true);
    storage.data.token = null; // a 401 cleared it
    expect((await pairings.list()).map((p) => p.shopId)).toEqual(["s2"]);
    await pairings.remove("s2");
    expect(await pairings.list()).toEqual([]);
    expect(storage.data["p:s2:token"]).toBeNull();
  });
});

describe("pairAcross", () => {
  const mismatch = () => new GatewayError(409, "platform_mismatch");

  it("offers the code to each platform in order until one takes it", async () => {
    const tried: string[] = [];
    const out = await pairAcross([{ id: "a" }, { id: "b" }], async (pack) => {
      tried.push(pack.id);
      if (pack.id === "a") throw mismatch();
      return token("s2", "b");
    });
    expect(tried).toEqual(["a", "b"]);
    expect(out.pack.id).toBe("b");
  });

  it("stops at once on any other refusal, and throws the mismatch when no platform takes it", async () => {
    const tried: string[] = [];
    await expect(
      pairAcross([{ id: "a" }, { id: "b" }], async (pack) => {
        tried.push(pack.id);
        throw new GatewayError(400, "invalid_code");
      }),
    ).rejects.toMatchObject({ code: "invalid_code" });
    expect(tried).toEqual(["a"]);
    await expect(pairAcross([{ id: "a" }], async () => Promise.reject(mismatch()))).rejects.toMatchObject({ code: "platform_mismatch" });
  });
});

describe("rotateIfDue for a scoped pairing", () => {
  const NOW = Date.parse("2026-12-02T00:00:00Z");

  it("rotates a due token in its scope and unpairs that scope on a 401", async () => {
    const storage = new MemoryStorage();
    const scoped = scopedStorage(storage, "p:s2:");
    await scoped.set({ token: token("s2", "otherplat") });
    expect(await rotateIfDue(scoped, { rotate: async () => token("s2", "otherplat", { token: "jci_new" }) }, NOW)).toBe("rotated");
    expect((storage.data["p:s2:token"] as TokenInfo).token).toBe("jci_new");
    await scoped.set({ token: token("s2", "otherplat") });
    expect(await rotateIfDue(scoped, { rotate: async () => Promise.reject(new GatewayError(401, "token_revoked")) }, NOW)).toBe("unpaired");
    expect(storage.data["p:s2:token"]).toBeNull();
    expect(await rotateIfDue(scoped, { rotate: async () => token("x", "y") }, NOW)).toBe("unpaired");
  });

  it("leaves a token that is not due", async () => {
    const storage = new MemoryStorage();
    await storage.set({ token: token("s1", LEGACY) });
    expect(await rotateIfDue(storage, { rotate: async () => Promise.reject(new Error("never")) }, Date.parse("2026-11-15T00:00:00Z"))).toBe("not_due");
  });
});

describe("the manifest", () => {
  it("keeps the Shopee host permissions and adds the TikTok Seller Centre only as an optional host", () => {
    expect(manifest.host_permissions).toEqual(["https://banhang.shopee.vn/*", "https://shopee.vn/*", "__JULI_API_ORIGIN__/*"]);
    expect(manifest.optional_host_permissions).toEqual(["https://seller-vn.tiktok.com/*"]);
    expect(manifest.version).toBe("0.3.30");
    expect(pkg.version).toBe(manifest.version);
  });
});
