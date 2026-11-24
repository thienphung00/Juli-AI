// batch-1124-a C3: a token Juli refuses (401: revoked, superseded, expired) stops its pairing; with no
// live pairing left every alarm is cleared. Core only, fake platforms, synthetic ids.
import { afterEach, describe, expect, it } from "vitest";
import { stopDeadToken } from "../src/core/dead-token";
import { configureClientIdentity, GatewayError, IngestClient, type TokenInfo } from "../src/core/ingest/client";
import { Pairings, scopedStorage } from "../src/core/pairings";

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

const LEGACY = "legacyplat";
const NOW = Date.parse("2026-11-24T03:00:00Z");
const token = (shop_id: string, platform: string): TokenInfo => ({
  token: `jci_${shop_id}_secret`,
  token_id: `t_${shop_id}`,
  shop_id,
  platform,
  expires_at: "2027-01-10T00:00:00Z",
  rotate_after: "2026-12-01T00:00:00Z",
});

function setup() {
  const storage = new MemoryStorage();
  const pairings = new Pairings(storage, LEGACY);
  let cleared = 0;
  const deps = {
    storage,
    pairings,
    clearAlarms: async () => {
      cleared += 1;
    },
    now: () => NOW,
  };
  return { storage, pairings, deps, cleared: () => cleared };
}

afterEach(() => configureClientIdentity({}));

describe("a dead token", () => {
  it("drops the only pairing's token, records Juli's code and clears every alarm", async () => {
    const { storage, pairings, deps, cleared } = setup();
    const live = token("s1", LEGACY);
    await storage.set({ token: live });
    await pairings.record(live, LEGACY);
    expect(await stopDeadToken(deps, live.token, "invalid_token")).toBe("stopped");
    expect(storage.data.token).toBeNull();
    expect(storage.data.lastError).toEqual({ at: "2026-11-24T03:00:00.000Z", code: "invalid_token" });
    expect(await pairings.list()).toEqual([]);
    expect(cleared()).toBe(1);
  });

  it("keeps the alarms while another pairing still holds a live token", async () => {
    const { storage, pairings, deps, cleared } = setup();
    const legacy = token("s1", LEGACY);
    const other = token("s2", "otherplat");
    await storage.set({ token: legacy });
    await pairings.record(legacy, LEGACY);
    await pairings.record(other, "otherplat", true);
    expect(await stopDeadToken(deps, other.token, "invalid_token")).toBe("cleared");
    expect((await scopedStorage(storage, "p:s2:").get(["token"])).token).toBeUndefined();
    expect(storage.data.token).toEqual(legacy);
    expect(cleared()).toBe(0);
  });

  it("leaves a newer pairing alone when an old token's late answer is a 401", async () => {
    const { storage, pairings, deps, cleared } = setup();
    const fresh = token("s1", LEGACY);
    await storage.set({ token: fresh });
    await pairings.record(fresh, LEGACY);
    expect(await stopDeadToken(deps, "jci_s1_rotated_away", "invalid_token")).toBe("unknown");
    expect(storage.data.token).toEqual(fresh);
    expect(cleared()).toBe(0);
  });
});

describe("the gateway client", () => {
  const answer = (status: number, body: unknown) => async () =>
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

  it("names the refused token on a 401 (heartbeat poll, ingest post, rotation alike)", async () => {
    const seen: [string, string][] = [];
    configureClientIdentity({ onTokenDead: (t, code) => seen.push([t, code]) });
    const client = new IngestClient(LEGACY, answer(401, { detail: { code: "invalid_token" } }));
    const refused = await client.fillJobs("jci_dead").catch((e: unknown) => e);
    expect(refused).toBeInstanceOf(GatewayError);
    expect((refused as GatewayError).status).toBe(401);
    await client.post("jci_dead", "traffic", {} as never).catch(() => undefined);
    await client.rotate("jci_dead").catch(() => undefined);
    expect(seen).toEqual([
      ["jci_dead", "invalid_token"],
      ["jci_dead", "invalid_token"],
      ["jci_dead", "invalid_token"],
    ]);
  });

  it("says nothing for a pairing refusal (no token) or any other status", async () => {
    const seen: string[] = [];
    configureClientIdentity({ onTokenDead: (t) => seen.push(t) });
    await new IngestClient(LEGACY, answer(401, { detail: { code: "invalid_code" } })).pair("CODE", "label").catch(() => undefined);
    await new IngestClient(LEGACY, answer(500, {})).fillJobs("jci_live").catch(() => undefined);
    await new IngestClient(LEGACY, answer(409, {})).fillJobs("jci_live").catch(() => undefined);
    expect(seen).toEqual([]);
  });
});
