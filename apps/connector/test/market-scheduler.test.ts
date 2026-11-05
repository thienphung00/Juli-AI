import { describe, expect, it } from "vitest";
import { Connector } from "../src/background/connector";
import { MarketScheduler, MARKET_WATCHDOG_ALARM } from "../src/background/market";
import { loadState, saveState } from "../src/background/state";
import { MARKET_JOB_TIMEOUT_MS, PILOT_SHOP_IDS, READER_BLOCK_CAPTCHA_MS, READER_PAGE_GAP_JITTER_MS, READER_PAGE_GAP_MS } from "../src/config";
import { GatewayClient, type IngestBody } from "../src/ingest/client";
import type { MarketPlan } from "../src/shopee/market";
import fixture from "./fixtures/market/search_items.json";

const PILOT = PILOT_SHOP_IDS[0] as string;
const T0 = Date.UTC(2026, 10, 5, 3, 0, 0); // 2026-11-05 10:00 GMT+7
const GAP = READER_PAGE_GAP_MS + READER_PAGE_GAP_JITTER_MS + 1;
const TOKEN = {
  token: "jci_x",
  token_id: "t1",
  shop_id: PILOT,
  platform: "shopee",
  expires_at: "2027-01-10T00:00:00Z",
  rotate_after: "2026-12-01T00:00:00Z",
};
const PLAN: MarketPlan = {
  enabled: true,
  max_per_product: 3,
  products: [{ item_id: "1", keywords: ["gang tay", "gang y te"] }, { item_id: "2", keywords: ["gang tay", "hop dung"] }],
  due_keywords: ["gang tay", "gang y te", "hop dung"],
};

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

class FakeClient extends GatewayClient {
  posts: { dataset: string; body: IngestBody }[] = [];
  drifts: string[] = [];
  async post(_t: string, dataset: string, body: IngestBody) {
    this.posts.push({ dataset, body });
    return { rows: body.rows.length, duplicate: false };
  }
  async reportDrift(_t: string, dataset: string) {
    this.drifts.push(dataset);
    return {};
  }
}

function setup(opts: { shop?: string; plan?: MarketPlan | null | Error; otherBusy?: boolean } = {}) {
  const storage = new MemoryStorage();
  storage.data.token = { ...TOKEN, shop_id: opts.shop ?? PILOT };
  const client = new FakeClient(async () => new Response("{}"));
  const clock = { now: T0 };
  const connector = new Connector({ storage, client, tabs: { sellerCentreTabs: async () => [], send: async () => undefined }, version: "0.3.5", now: () => clock.now });
  const opened: { id: number; url: string }[] = [];
  const closed: number[] = [];
  const alarms: string[] = [];
  const calls = { plan: 0 };
  let nextId = 50;
  const inspection = new Map<number, { open: boolean; url?: string }>();
  const market = new MarketScheduler({
    storage,
    version: "0.3.5",
    now: () => clock.now,
    random: () => 0,
    tabs: {
      open: async (url) => {
        const id = nextId++;
        opened.push({ id, url });
        return id;
      },
      close: async (id) => void closed.push(id),
      send: async () => undefined,
      inspect: async (id) => inspection.get(id) ?? { open: true, url: opened.find((o) => o.id === id)?.url },
    },
    alarms: { create: async (name) => void alarms.push(`+${name}`), clear: async (name) => void alarms.push(`-${name}`) },
    plan: async () => {
      calls.plan += 1;
      if (opts.plan instanceof Error) throw opts.plan;
      return opts.plan === undefined ? PLAN : opts.plan;
    },
    sink: { postMarket: (k, b, at) => connector.postMarket(k, b, at) },
    otherBusy: async () => opts.otherBusy ?? false,
  });
  return { storage, client, connector, market, clock, opened, closed, alarms, calls, inspection };
}

const answer = (keyword: string, extra: Record<string, unknown> = {}) => ({ keyword, status: 200, body: fixture, capturedAt: T0, ...extra });

describe("MarketScheduler", () => {
  it("is off for any shop but the explicit pilot id, and when unpaired", async () => {
    expect(await setup({ shop: "someone-else" }).market.tick()).toBe("off");
    const s = setup();
    s.storage.data.token = null;
    expect(await s.market.tick()).toBe("unpaired");
  });

  it("opens one background tab per keyword, de-duplicated, one at a time, with a gap", async () => {
    const s = setup();
    expect(await s.market.tick()).toBe("opened");
    expect(s.opened.map((o) => o.url)).toEqual(["https://shopee.vn/search?keyword=gang%20tay"]);
    expect(await s.market.tick()).toBe("waiting"); // second tick never opens a second tab
    expect(s.opened).toHaveLength(1);
    expect(await s.market.activeTabIds()).toEqual([50]);
    expect(await s.market.isBusy()).toBe(true);
    expect(s.alarms).toContain(`+${MARKET_WATCHDOG_ALARM}`);

    expect(await s.market.onTabReady(50, "https://shopee.vn/search?keyword=gang%20tay")).toBe(true);
    expect(await s.market.onResult(50, answer("gang tay"))).toBe(true);
    expect(s.closed).toEqual([50]);
    expect(s.client.posts.map((p) => p.dataset)).toEqual(["market_search"]);
    expect(s.client.posts[0]?.body.rows).toHaveLength(3);
    expect(await s.market.tick()).toBe("gap");
    s.clock.now += GAP;
    expect(await s.market.tick()).toBe("opened");
    expect(s.opened.map((o) => o.url)[1]).toBe("https://shopee.vn/search?keyword=gang%20y%20te");
    // the third (hop dung) after the second
    await s.market.onResult(51, answer("gang y te"));
    s.clock.now += GAP;
    await s.market.tick();
    await s.market.onResult(52, answer("hop dung"));
    const state = await loadState(s.storage);
    expect(state.market?.run).toBeUndefined();
    expect(state.market?.lastRunDay).toBe("2026-11-05");
    expect(Object.keys(state.market?.lastRead ?? {}).sort()).toEqual(["gang tay", "gang y te", "hop dung"]);
    expect(s.alarms).toContain(`-${MARKET_WATCHDOG_ALARM}`);
    expect(await s.market.tick()).toBe("done_today");
  });

  it("weekly: skips keywords read in the last 6 days; the server's due list gates too", async () => {
    const s = setup();
    await saveState(s.storage, { market: { lastRead: { "gang tay": "2026-11-01", "hop dung": "2026-10-20" } } });
    await s.market.tick();
    expect(s.opened.map((o) => o.url)).toEqual(["https://shopee.vn/search?keyword=gang%20y%20te"]);
    const due = setup({ plan: { ...PLAN, due_keywords: ["hop dung"] } });
    await due.market.tick();
    expect(due.opened.map((o) => o.url)).toEqual(["https://shopee.vn/search?keyword=hop%20dung"]);
  });

  it("does nothing when the server disables it, has nothing due, or is unreachable", async () => {
    expect(await setup({ plan: { ...PLAN, enabled: false } }).market.tick()).toBe("disabled");
    expect(await setup({ plan: { ...PLAN, due_keywords: [] } }).market.tick()).toBe("nothing_to_do");
    const down = setup({ plan: new Error("net") });
    expect(await down.market.tick()).toBe("plan_failed");
    expect(down.opened).toEqual([]);
    expect((await loadState(down.storage)).market?.lastRunDay).toBeUndefined(); // retried at the next alarm
  });

  it("waits while the Seller Centre readers or the backfill hold the pace budget", async () => {
    const s = setup({ otherBusy: true });
    expect(await s.market.tick()).toBe("busy");
    expect(s.calls.plan).toBe(0);
    expect(s.opened).toEqual([]);
  });

  it("a CAPTCHA answer (403) closes the tab, records the block and opens nothing else", async () => {
    const s = setup();
    await s.market.tick();
    await s.market.onResult(50, answer("gang tay", { status: 403, body: null }));
    expect(s.closed).toEqual([50]);
    const state = await loadState(s.storage);
    expect(state.market?.blocked?.reason).toBe("captcha");
    expect(state.market?.blocked?.until).toBe(T0 + READER_BLOCK_CAPTCHA_MS);
    expect(state.market?.run).toBeUndefined();
    expect(s.opened).toHaveLength(1);
    s.clock.now += GAP;
    expect(await s.market.tick()).toBe("blocked");
    await s.market.clearBlock();
    expect((await loadState(s.storage)).market?.blocked).toBeUndefined();
  });

  it("a login / verify page blocks (path on ready, relay notice, redirect found by the watchdog)", async () => {
    const a = setup();
    await a.market.tick();
    await a.market.onTabReady(50, "https://shopee.vn/buyer/login?next=x");
    expect((await loadState(a.storage)).market?.blocked?.reason).toBe("login");

    const b = setup();
    await b.market.tick();
    expect(await b.market.onBlocked(50, "captcha")).toBe(true);
    expect((await loadState(b.storage)).market?.blocked?.reason).toBe("captcha");
    expect(await b.market.onBlocked(999, "captcha")).toBe(false);

    const c = setup();
    await c.market.tick();
    c.inspection.set(50, { open: true, url: "https://shopee.vn/verify/traffic/error" });
    c.clock.now += 30_000;
    expect(await c.market.tick()).toBe("blocked:captcha");
  });

  it("times out a tab with no answer, and moves on when the seller closes the tab", async () => {
    const s = setup();
    await s.market.tick();
    s.clock.now += MARKET_JOB_TIMEOUT_MS + 1;
    expect(await s.market.tick()).toBe("timeout");
    expect(s.closed).toEqual([50]);
    s.clock.now += GAP;
    await s.market.tick();
    await s.market.onTabRemoved(51);
    expect(s.closed).toEqual([50]); // the tab is already gone: not closed again
    const state = await loadState(s.storage);
    expect(state.market?.run?.index).toBe(2);
    expect(state.market?.lastRead).toEqual({});
  });

  it("ignores other tabs, and an answer for another keyword", async () => {
    const s = setup();
    await s.market.tick();
    expect(await s.market.onResult(999, answer("gang tay"))).toBe(false);
    expect(await s.market.onTabReady(999, "https://shopee.vn/search")).toBe(false);
    await s.market.onResult(50, answer("something else"));
    expect(s.client.posts).toEqual([]);
    expect(s.closed).toEqual([]);
  });

  it("drift pauses market_search for this version, posts nothing, reports once and ends the run", async () => {
    const s = setup();
    await s.market.tick();
    await s.market.onResult(50, answer("gang tay", { body: { error: null, nothing: true } }));
    expect(s.client.posts).toEqual([]);
    expect(s.client.drifts).toEqual(["market_search"]);
    expect(s.closed).toEqual([50]);
    expect((await loadState(s.storage)).market?.run).toBeUndefined();
    s.clock.now += 24 * 3_600_000;
    expect(await s.market.tick()).toBe("stopped");
    // a new extension version tries again
    const state = await loadState(s.storage);
    expect(state.stopped.market_search?.version).toBe("0.3.5");
  });
});

describe("Connector.postMarket", () => {
  it("does not post a stopped dataset; reports drift once", async () => {
    const s = setup();
    const bad = { error: null, items: [{ item_basic: { itemid: 1 } }] };
    expect(await s.connector.postMarket("k", bad, T0)).toBe("drift");
    expect(await s.connector.postMarket("k", fixture, T0)).toBe("stopped");
    expect(s.client.posts).toEqual([]);
    expect(s.client.drifts).toEqual(["market_search"]);
  });
  it("posts a good page to /shopee/market_search with period granularity", async () => {
    const s = setup();
    expect(await s.connector.postMarket("k", fixture, T0)).toBe("posted");
    expect(s.client.posts[0]?.dataset).toBe("market_search");
    expect(s.client.posts[0]?.body.period.granularity).toBe("period");
  });
});
