// Connector 0.3.29 (batch-1119-f4 t1b): F4.2 hole list, F4.3 blocks clear + re-run, F4.6 affiliate
// pages, F4.7 promotions, F4.9 order income, F4.13 popup. Made-up data only.
import { describe, expect, it } from "vitest";
import { catchupSummary, daysLeft, parseReadDays, withHoleDays } from "../src/platforms/shopee/background/catchup";
import { Connector, type Tabs } from "../src/platforms/shopee/background/connector";
import {
  planJobs,
  READER_KICK_ALARM,
  ReaderScheduler,
  type SchedulerAlarms,
  type SchedulerTabs,
  type TickReport,
} from "../src/platforms/shopee/background/scheduler";
import { loadState } from "../src/platforms/shopee/background/state";
import { DAILY_REQUEST_BUDGET, READER_CAPTURE_JOB_TIMEOUT_MS, READER_LOAD_GRACE_MS, READER_PAGE_GAP_JITTER_MS, READER_PAGE_GAP_MS, type ReaderId } from "../src/platforms/shopee/config";
import { GatewayClient, type TokenInfo } from "../src/platforms/shopee/ingest/client";
import { mapOrderIncome } from "../src/platforms/shopee/orders-map";
import { problemLabel, problemLines } from "../src/platforms/shopee/popup/guide";
import { mapPromotions } from "../src/platforms/shopee/promotions-map";
import { type FetchedReaderResponse, pollingWaitFor, rangeKeysOf, type ReaderEnv, type ReaderRequest, type ReaderResponse, runReaderJob, type Template } from "../src/platforms/shopee/reader";
import type { ReadDays } from "../src/platforms/shopee/background/catchup";
import type { ReaderEndpoint } from "../src/platforms/shopee/endpoints";
import { Pacer } from "../src/platforms/shopee/runner";

const SC = "https://banhang.shopee.vn";
const SHOP = "5b0c1d2e-3f40-4a51-8b62-7c83d94e0a15";
const T0 = Date.UTC(2026, 10, 19, 3, 0, 0); // 2026-11-19 10:00 GMT+7
const GAP = READER_PAGE_GAP_MS + READER_PAGE_GAP_JITTER_MS + 1;
const TOKEN: TokenInfo = { token: "jci_x", token_id: "t1", shop_id: SHOP, platform: "shopee", expires_at: "2027-01-10T00:00:00Z", rotate_after: "2026-12-01T00:00:00Z" };

class MemoryStorage {
  data: Record<string, unknown> = {};
  async get(keys?: string | string[] | null) {
    const list = keys == null ? Object.keys(this.data) : Array.isArray(keys) ? keys : [keys];
    return Object.fromEntries(list.filter((k) => this.data[k] != null).map((k) => [k, this.data[k]]));
  }
  async set(items: Record<string, unknown>) {
    Object.assign(this.data, JSON.parse(JSON.stringify(items)));
  }
}
class FakeTabs implements SchedulerTabs {
  nextId = 100;
  opened: { id: number; url: string }[] = [];
  closed: number[] = [];
  sent: { tabId: number; message: { job?: { id: string; days?: string[] } } }[] = [];
  failSend = false;
  async open(url: string) {
    const id = this.nextId++;
    this.opened.push({ id, url });
    return id;
  }
  async close(tabId: number) {
    this.closed.push(tabId);
  }
  async send(tabId: number, message: unknown) {
    if (this.failSend) throw new Error("no receiver");
    this.sent.push({ tabId, message: message as never });
  }
  async inspect(tabId: number) {
    return { open: true, url: this.opened.find((t) => t.id === tabId)?.url };
  }
  get current() {
    return this.opened[this.opened.length - 1] as { id: number; url: string };
  }
}
class FakeAlarms implements SchedulerAlarms {
  active = new Map<string, unknown>();
  async create(name: string, info: unknown) {
    this.active.set(name, info);
  }
  async clear(name: string) {
    return this.active.delete(name);
  }
}

function setup(readers: readonly ReaderId[], holes?: ReadDays | "fail") {
  const storage = new MemoryStorage();
  const tabs = new FakeTabs();
  const alarms = new FakeAlarms();
  const clock = { now: T0 };
  const ticks: TickReport[] = [];
  const queued: Record<string, string[]>[] = [];
  const posted: { id: string; days?: string[] }[] = [];
  const state = { holes };
  const scheduler = new ReaderScheduler({
    storage,
    tabs,
    alarms,
    readers,
    stockRun: false,
    origin: SC,
    version: "0.3.29",
    now: () => clock.now,
    random: () => 0.5,
    backfillBusy: async () => false,
    sink: {
      async reportBlock() {},
      async reportTick(report) {
        ticks.push(report);
      },
      async readDays() {
        if (state.holes === "fail") throw new Error("offline");
        return state.holes;
      },
      async queueBackfillHoles(datasets) {
        queued.push(datasets);
      },
      async postReader(job) {
        posted.push({ id: job.id, days: job.days });
        if (job.id === "traffic") return Object.fromEntries((job.days ?? []).map((d) => [`traffic_overview:${d}:confirmed`, "posted"]));
        if (job.id === "shop_totals") return { "shop_overview:confirmed": "posted" };
        return { [job.id]: "posted" };
      },
    },
  });
  storage.data.token = TOKEN;
  const read = async () => (await loadState(storage)).readers;
  return { scheduler, storage, tabs, alarms, clock, ticks, queued, posted, read, state };
}
type Ctx = ReturnType<typeof setup>;

async function answerPage(ctx: Ctx, status = "done", responses: unknown[] = []) {
  const tab = ctx.tabs.current;
  const run = (await ctx.read())?.run;
  const job = run?.jobs[run.index];
  await ctx.scheduler.onTabReady(tab.id, tab.url);
  await ctx.scheduler.onResult(tab.id, { job: job?.id, status, responses });
}
async function drive(ctx: Ctx, answers: Partial<Record<ReaderId, string[]>> = {}) {
  const seen: Record<string, number> = {};
  let result = await ctx.scheduler.tick();
  for (let i = 0; i < 40 && (await ctx.read())?.run; i += 1) {
    const run = (await ctx.read())?.run;
    if (run?.current) {
      const id = run.jobs[run.index]?.id as ReaderId;
      const n = (seen[id] = (seen[id] ?? 0) + 1);
      await answerPage(ctx, answers[id]?.[n - 1] ?? "done");
    }
    ctx.clock.now += GAP;
    result = await ctx.scheduler.tick();
  }
  return result;
}

const holes = (datasets: Record<string, string[]>): ReadDays => ({ asOf: "2026-11-19", datasets });

describe("F4.2: the hole list", () => {
  it("parseReadDays keeps only real past days inside the 30-day window, oldest first", () => {
    const parsed = parseReadDays(
      { as_of: "2026-11-19", window_days: 30, datasets: { item_traffic_sources: { missing: ["2026-11-02", "2026-10-25", "2026-11-19", "2026-12-01", "x", "2026-10-01"] }, bad: { missing: "no" } } },
      "2026-11-19",
    );
    expect(parsed?.datasets).toEqual({ item_traffic_sources: ["2026-10-25", "2026-11-02"] });
    expect(parseReadDays(null, "2026-11-19")).toBeUndefined();
    expect(parseReadDays({ datasets: 3 }, "2026-11-19")).toBeUndefined();
  });

  it("withHoleDays: after yesterday's days, oldest first, capped per job and by the budget room", () => {
    const h = { traffic_overview: ["2026-11-10", "2026-11-05", "2026-11-18"], shop_traffic: ["2026-11-05", "2026-11-06"] };
    expect(withHoleDays("traffic", ["2026-11-18"], h, 1000, 0)).toEqual(["2026-11-18", "2026-11-05", "2026-11-06", "2026-11-10"]);
    expect(withHoleDays("traffic", ["2026-11-18"], h, 6, 0)).toEqual(["2026-11-18", "2026-11-05", "2026-11-06"]); // 3 requests a day
    expect(withHoleDays("traffic", ["2026-11-18"], h, 0, 0)).toEqual(["2026-11-18"]);
    const many = { item_traffic_sources: Array.from({ length: 10 }, (_, i) => `2026-11-${String(i + 1).padStart(2, "0")}`) };
    expect(withHoleDays("item_traffic", ["2026-11-18"], many, 800, 100)).toEqual(["2026-11-18", "2026-11-01", "2026-11-02"]);
    expect(withHoleDays("item_traffic", [], many, 150, 100)).toEqual(["2026-11-01"]);
  });

  it("daysLeft / catchupSummary report `catchup:<dataset>=<n> days left`", () => {
    const left = daysLeft({ a: ["2026-11-01", "2026-11-02"], b: ["2026-11-03"] }, { a: ["2026-11-01"], b: ["2026-11-03"] });
    expect(left).toEqual({ a: 1, b: 0 });
    expect(catchupSummary(left)).toBe("catchup:a=1 days left");
  });

  it("planJobs turns hole days into reader days, yesterday first, within the room", () => {
    const base = { shopId: SHOP, nowMs: T0, stopped: new Set<never>(), adsDone: [] as string[], readers: ["traffic", "ads"] as const };
    const jobs = planJobs({ ...base, holes: { traffic_overview: ["2026-10-25", "2026-10-26"], ads_campaign_daily: ["2026-10-20"] }, holeRoom: 100 });
    expect(jobs.find((j) => j.id === "traffic")?.days).toEqual(["2026-11-18", "2026-11-17", "2026-11-16", "2026-11-15", "2026-10-25", "2026-10-26"]);
    expect(jobs.find((j) => j.id === "ads")?.days?.slice(-1)).toEqual(["2026-10-20"]);
    const none = planJobs({ ...base, holes: { traffic_overview: ["2026-10-25"] }, holeRoom: 0 });
    expect(none.find((j) => j.id === "traffic")?.days).not.toContain("2026-10-25");
  });

  it("a daily run fetches the list, reads the hole days and reports the days left", async () => {
    const ctx = setup(["traffic"], holes({ traffic_overview: ["2026-10-25", "2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30", "2026-10-31"], ads_campaign_daily: ["2026-10-20"] }));
    await drive(ctx);
    expect(ctx.posted[0]?.days).toEqual(["2026-11-18", "2026-11-17", "2026-11-16", "2026-11-15", "2026-10-25", "2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29"]);
    const tick = ctx.ticks.find((t) => t.kind === "run");
    expect(tick?.outcomes?.catchup).toBe("done:catchup:traffic_overview=2 days left,catchup:ads_campaign_daily=1 days left");
    expect(tick?.outcomes?.traffic).toMatch(/^done/);
  });

  it("an unreachable hole list changes nothing: the run goes on without catch-up", async () => {
    const ctx = setup(["traffic"], "fail");
    await drive(ctx);
    expect(ctx.posted[0]?.days).toEqual(["2026-11-18", "2026-11-17", "2026-11-16", "2026-11-15"]);
    expect(ctx.ticks.find((t) => t.kind === "run")?.outcomes?.catchup).toBeUndefined();
  });

  it("the mydata item datasets are queued for the per-day backfill", async () => {
    const ctx = setup(["traffic"], holes({ item_performance: ["2026-10-25"], item_by_source: ["2026-10-25", "2026-10-26"], traffic_overview: ["2026-10-25"] }));
    await ctx.scheduler.tick();
    expect(ctx.queued).toEqual([{ item_performance: ["2026-10-25"], item_by_source: ["2026-10-25", "2026-10-26"] }]);
  });

  it("Connector.reopenBackfillDays reopens only the missing datasets of a day, yesterday first then oldest first", async () => {
    const storage = new MemoryStorage();
    const tabs: Tabs = { sellerCentreTabs: async () => [7], send: async () => undefined };
    const connector = new Connector({ storage, client: new GatewayClient(async () => new Response("{}")), tabs, version: "0.3.29", now: () => T0 });
    storage.data.token = TOKEN;
    const days = ["2026-11-18", "2026-11-17", "2026-11-10"];
    storage.data.backfill = { shopId: SHOP, createdAt: "x", days, done: [...days], accepted: {}, attempts: {}, status: "done" };
    await connector.reopenBackfillDays({ item_performance: ["2026-11-10", "2026-11-18"], item_by_source: ["2026-11-10"], traffic_overview: ["2026-11-17"], nope: ["2026-11-17"] });
    const { backfill } = await loadState(storage);
    expect(backfill?.status).toBe("running");
    expect(backfill?.days).toEqual(["2026-11-18", "2026-11-10", "2026-11-17"]);
    expect(backfill?.done).toEqual([]);
    expect(backfill?.accepted["2026-11-10"]).toEqual(["traffic_overview", "shop_traffic"]);
    expect(backfill?.accepted["2026-11-18"]).toEqual(["traffic_overview", "item_by_source", "shop_traffic"]);
    expect(backfill?.accepted["2026-11-17"]).toEqual(["item_by_source", "item_performance", "shop_traffic"]);
  });

  it("Connector.readDays fetches the contract route and parses it; a failure is undefined", async () => {
    const urls: string[] = [];
    const storage = new MemoryStorage();
    storage.data.token = TOKEN;
    const ok = new GatewayClient(async (url) => {
      urls.push(String(url));
      return new Response(JSON.stringify({ as_of: "2026-11-19", window_days: 30, datasets: { shop_overview: { missing: ["2026-11-03", "2026-11-01"] } } }));
    });
    const tabs: Tabs = { sellerCentreTabs: async () => [], send: async () => undefined };
    expect(await new Connector({ storage, client: ok, tabs, version: "0.3.29", now: () => T0 }).readDays()).toEqual({ asOf: "2026-11-19", datasets: { shop_overview: ["2026-11-01", "2026-11-03"] } });
    expect(urls[0]).toMatch(/\/v1\/connector\/shopee\/read-days$/);
    const bad = new GatewayClient(async () => new Response("{}", { status: 500 }));
    expect(await new Connector({ storage, client: bad, tabs, version: "0.3.29", now: () => T0 }).readDays()).toBeUndefined();
  });
});

describe("F4.3: a block clears on success and the pages are read again soon", () => {
  const READERS = ["products", "orders", "item_traffic", "product_period", "shop_totals"] as const;
  const ids = (url: string) => new URL(url).pathname;

  it("today's case: password dialog on three /datacenter pages, owner confirms, they are read again within 10 minutes", async () => {
    const ctx = setup(READERS);
    ctx.storage.data.readers = { adsDone: [], trafficDone: [], itemIds: ["1001"], adsHistory: { shopId: SHOP, createdAt: "x", days: [], done: [], status: "done" } };
    await drive(ctx, { item_traffic: ["blocked_password_recheck"], product_period: ["blocked_password_recheck"], shop_totals: ["blocked_password_recheck"] });
    const first = await ctx.read();
    expect(first?.lastRun?.outcomes).toMatchObject({ item_traffic: "blocked:password_recheck", product_period: "blocked:password_recheck", shop_totals: "blocked:password_recheck" });
    const before = ctx.tabs.opened.length;
    await ctx.scheduler.sessionSeen("datacenter"); // the owner confirmed: a data call answered
    const info = ctx.alarms.active.get(READER_KICK_ALARM) as { delayInMinutes: number };
    expect(info.delayInMinutes).toBeLessThanOrEqual(10);
    ctx.clock.now += info.delayInMinutes * 60_000;
    expect(await ctx.scheduler.tick({ trigger: "kick" })).toBe("opened");
    expect((await ctx.read())?.run?.live).toEqual(["datacenter"]);
    await drive(ctx); // pages answer "done" now
    const reopened = ctx.tabs.opened.slice(before).map((t) => ids(t.url));
    expect(reopened).toEqual(["/datacenter/product/traffic", "/datacenter/product/performance", "/datacenter/overview"]);
    const after = await ctx.read();
    expect(after?.lastRun?.outcomes.item_traffic).toMatch(/^done/);
    expect(after?.lastRun?.outcomes.shop_totals).toMatch(/^done/);
    const reread = ctx.ticks.filter((t) => t.kind === "run").at(-1);
    expect(reread?.trigger).toBe("reread");
    expect(Object.values(reread?.outcomes ?? {}).some((o) => String(o).startsWith("blocked"))).toBe(false);
  });

  it("the first page of a re-read that meets a login redirect is that page only, never a 6 h stop of the run", async () => {
    const ctx = setup(READERS);
    ctx.storage.data.readers = { adsDone: [], trafficDone: [], itemIds: ["1001"], adsHistory: { shopId: SHOP, createdAt: "x", days: [], done: [], status: "done" } };
    await drive(ctx, { product_period: ["blocked_password_recheck"], shop_totals: ["blocked_password_recheck"] });
    await ctx.scheduler.sessionSeen("datacenter");
    ctx.clock.now += 2 * 60_000;
    await ctx.scheduler.tick({ trigger: "kick" });
    await answerPage(ctx, "blocked_login");
    const state = await ctx.read();
    expect(state?.blocked).toBeUndefined();
    expect((await ctx.read())?.run?.outcomes.product_period).toBe("blocked:login");
  });

  it("a data call while a run is going arms the re-read when the run ends (not lost)", async () => {
    const ctx = setup(READERS);
    ctx.storage.data.readers = { adsDone: [], trafficDone: [], itemIds: ["1001"], adsHistory: { shopId: SHOP, createdAt: "x", days: [], done: [], status: "done" } };
    await drive(ctx, { shop_totals: ["blocked_password_recheck"] });
    // today's lastRun has the block; start a manual run and let the call arrive during it
    await ctx.scheduler.tick({ manual: true });
    expect((await ctx.read())?.run).toBeDefined();
    await ctx.scheduler.sessionSeen("datacenter");
    expect((await ctx.read())?.rereadAfterRun).toMatchObject({ section: "datacenter" });
    expect(ctx.alarms.active.has(READER_KICK_ALARM)).toBe(false);
    for (let i = 0; i < 20 && (await ctx.read())?.run; i += 1) {
      const run = (await ctx.read())?.run;
      if (run?.current) await answerPage(ctx, run.jobs[run.index]?.id === "shop_totals" ? "blocked_password_recheck" : "done");
      else {
        ctx.clock.now += GAP;
        await ctx.scheduler.tick();
      }
    }
    expect((await ctx.read())?.rereadAfterRun).toBeUndefined();
    expect((await ctx.read())?.reread?.pages).toEqual(["shop_totals"]);
    expect(ctx.alarms.active.has(READER_KICK_ALARM)).toBe(true);
  });

  it("a page blocked earlier in the run is read again at its end once its section answered; the report does not write the cleared block", async () => {
    const ctx = setup(["products", "item_traffic", "product_period"]);
    ctx.storage.data.readers = { adsDone: [], trafficDone: [], itemIds: ["1001"], adsHistory: { shopId: SHOP, createdAt: "x", days: [], done: [], status: "done" } };
    await drive(ctx, { item_traffic: ["blocked_password_recheck", "done"] });
    const report = ctx.ticks.find((t) => t.kind === "run");
    expect(report?.outcomes?.item_traffic).toMatch(/^done/);
    expect(report?.outcomes?.product_period).toMatch(/^done/);
    expect(Object.values(report?.outcomes ?? {}).some((o) => String(o).startsWith("blocked"))).toBe(false);
  });

  it("a data call lifts a password_recheck stop set by a fill page (before it only lifted a login stop)", async () => {
    const ctx = setup(READERS);
    await ctx.scheduler.haltFor("password_recheck", "/portal/product/1");
    expect((await ctx.read())?.blocked?.reason).toBe("password_recheck");
    await ctx.scheduler.sessionSeen("datacenter");
    expect((await ctx.read())?.blocked).toBeUndefined();
  });
});

describe("F4.6: affiliate pages", () => {
  const AFF = ["affiliate_commissions"] as const;

  it("a job the page was never given (content script not listening yet) is sent again by the watchdog", async () => {
    const ctx = setup(AFF);
    await ctx.scheduler.tick();
    const tab = ctx.tabs.current;
    ctx.tabs.failSend = true;
    await ctx.scheduler.onTabReady(tab.id, tab.url);
    expect(ctx.tabs.sent).toHaveLength(0);
    ctx.tabs.failSend = false;
    ctx.clock.now += READER_LOAD_GRACE_MS + 1;
    expect(await ctx.scheduler.tick()).toBe("resent");
    expect(ctx.tabs.sent.map((s) => s.message.job?.id)).toEqual(["affiliate_commissions"]);
    expect((await ctx.read())?.run?.current?.sentAt).toBeDefined();
    ctx.clock.now += 60_000;
    expect(await ctx.scheduler.tick()).toBe("waiting"); // not sent a third time
    expect(ctx.tabs.sent).toHaveLength(1);
  });

  it("needs_template: the page is loaded once more in the same run (navigation only, budgeted); a second miss is the outcome", async () => {
    const ctx = setup(AFF);
    await ctx.scheduler.tick();
    const used = async () => (await loadState(ctx.storage)).budget?.used ?? 0;
    const before = await used();
    await answerPage(ctx, "needs_template", []);
    expect(ctx.tabs.opened).toHaveLength(2);
    expect(ctx.tabs.opened[1]?.url).toBe(ctx.tabs.opened[0]?.url);
    expect(ctx.tabs.closed).toContain(ctx.tabs.opened[0]?.id);
    expect((await ctx.read())?.run?.current?.reopened).toBe(true);
    expect(await used()).toBe(before + 10);
    await answerPage(ctx, "needs_template", []);
    expect(ctx.tabs.opened).toHaveLength(2);
    expect((await ctx.read())?.lastRun?.outcomes.affiliate_commissions).toBe("needs_template");
  });

  it("a timeout loads the page once more after the shorter first wait; the second timeout ends the job", async () => {
    const ctx = setup(AFF);
    await ctx.scheduler.tick();
    ctx.clock.now += READER_CAPTURE_JOB_TIMEOUT_MS + 1;
    expect(await ctx.scheduler.tick()).toBe("reopened");
    expect(ctx.tabs.opened).toHaveLength(2);
    ctx.clock.now += READER_CAPTURE_JOB_TIMEOUT_MS + 1;
    expect(await ctx.scheduler.tick()).toBe("resent"); // the reload gets the full 4 minutes
    ctx.clock.now += 3 * 60_000;
    await ctx.scheduler.tick();
    expect((await ctx.read())?.lastRun?.outcomes.affiliate_commissions).toBe("timeout");
  });

  it("no reload when the day's budget has no room", async () => {
    const ctx = setup(AFF);
    await ctx.scheduler.tick();
    ctx.storage.data.budget = { day: "2026-11-19", used: DAILY_REQUEST_BUDGET - 5 };
    await answerPage(ctx, "needs_template", []);
    expect(ctx.tabs.opened).toHaveLength(1);
  });

  it("an affiliate period that answers empty while the shop's own numbers showed data is an error, not empty", async () => {
    const ctx = setup(["affiliate_dashboard", "affiliate_kols"]);
    (ctx.scheduler as unknown as { deps: { sink: { postReader: unknown } } }).deps.sink.postReader = async (job: { id: string }) =>
      job.id === "affiliate_dashboard" ? { "affiliate_shop_period:2026-11-18": "posted" } : { affiliate_partner_period: "empty" };
    await drive(ctx);
    expect((await ctx.read())?.lastRun?.outcomes).toMatchObject({ affiliate_dashboard: expect.stringMatching(/^done/), affiliate_kols: "error:affiliate_kols:empty_with_data" });
  });

  it("without data elsewhere an empty period stays a real empty", async () => {
    const ctx = setup(["affiliate_dashboard", "affiliate_kols"]);
    (ctx.scheduler as unknown as { deps: { sink: { postReader: unknown } } }).deps.sink.postReader = async () => ({ affiliate_partner_period: "empty" });
    await drive(ctx);
    expect((await ctx.read())?.lastRun?.outcomes.affiliate_kols).toBe("done:affiliate_partner_period=empty");
  });
});

describe("F4.9: order income", () => {
  const answer = (items: { name: string; amount: number }[]): ReaderResponse => ({
    endpoint: "order_income_components",
    url: "u",
    status: 200,
    capturedAt: T0,
    source: "page",
    orderId: "9001",
    orderSn: "SN-1",
    body: { code: 0, data: { items } },
  });

  it("keeps the infrastructure fee and the extra voucher fee as their own columns", () => {
    const mapped = mapOrderIncome(
      [answer([{ name: "Giá sản phẩm", amount: 200_000 }, { name: "Phí dịch vụ", amount: 20_000 }, { name: "Phí hạ tầng", amount: 3_000 }, { name: "Phí Voucher Xtra", amount: 4_000 }, { name: "Số tiền cuối cùng", amount: 170_000 }])],
      T0,
    );
    expect(mapped.rows[0]).toMatchObject({ product_price: 200_000, fee_service: 20_000, fee_infra: 3_000, fee_voucher_xtra: 4_000, payout: 170_000 });
  });

  it("the orders read queues orders completed since the last income read that LANDED, not since the last run", () => {
    const day = 86_400_000;
    const ctx = setup(["orders"]);
    const detail = (sn: string, completedMs: number): ReaderResponse => ({
      endpoint: "order_detail",
      url: "u",
      status: 200,
      capturedAt: T0,
      source: "replay",
      body: { code: 0, data: { order_sn: sn, order_id: sn.replace("SN", "9"), complete_time: Math.floor(completedMs / 1000), status: 4 } },
    });
    const responses = [detail("SN0001", T0 - 20 * day), detail("SN0002", T0 - 2 * day)];
    const queued = (sched: Record<string, unknown>) => {
      const out = (ctx.scheduler as unknown as { shopReaderState: (...a: unknown[]) => { incomeQueue?: { id: string }[] } }).shopReaderState(
        { adsDone: [], ...sched },
        { day: "2026-11-19" },
        { id: "orders" },
        { order_lines: "posted" },
        responses,
        SHOP,
        true,
        "",
      );
      return (out.incomeQueue ?? []).map((o) => o.id);
    };
    // an install that read an income 3 days ago: only the newer order
    expect(queued({ incomeSince: T0 - day, incomeReadAt: T0 - 3 * day })).toEqual(["SN0002"]);
    // an install that never read one since the last runs (0.3.28: incomeSince advanced daily): the whole window
    expect(queued({ incomeSince: T0 - 1000 })).toEqual(["SN0001", "SN0002"]);
    // a brand-new install: the last 3 days only
    expect(queued({})).toEqual(["SN0002"]);
  });
});

describe("F4.7: promotions", () => {
  const metrics = (day: string, m: Record<string, number>): ReaderResponse => {
    const start = Math.floor(Date.parse(`${day}T00:00:00+07:00`) / 1000);
    return { endpoint: "promotion_metrics", url: "u", status: 200, capturedAt: T0, source: "replay", day, body: { code: 0, message: "ok", data: { date_range: { start_time: start, end_time: start + 86_399 }, metrics: m } } };
  };

  it("promotion_daily: one row per single-day answer, with the file import's field names", () => {
    const mapped = mapPromotions([metrics("2026-11-17", { sales: 1_500_000, orders: 12, units: 20, buyers: 11, sales_pct_diff: 3 }), metrics("2026-11-18", { sales: 0, orders: 0, units: 0, buyers: 0 })], T0);
    expect(mapped.map((m) => [m.dataset, m.date])).toEqual([["promotion_daily", "2026-11-17"], ["promotion_daily", "2026-11-18"]]);
    expect(mapped[0]?.rows).toEqual([{ promo_type: "Chương Trình Khuyến Mãi", sales: 1_500_000, orders: 12, units: 20, buyers: 11 }]);
  });

  it("a multi-day answer (the page's own range) is not a day; an unreadable list posts nothing", () => {
    const wide = metrics("2026-11-17", { sales: 1, orders: 1, units: 1, buyers: 1 });
    ((wide.body as { data: { date_range: { end_time: number } } }).data.date_range.end_time as number) += 3 * 86_400;
    expect(mapPromotions([wide, { endpoint: "promotion_list", url: "u", status: 200, capturedAt: T0, source: "page", body: { code: 0, data: { stuff: [1, 2] } } }], T0)).toEqual([]);
  });

  it("promotions: programme entries of the list answer, wall-clock times, de-duplicated", () => {
    const entry = { id: 77, name: "Giảm giá mùa mưa", start_time: Math.floor(Date.parse("2026-11-10T00:00:00+07:00") / 1000), end_time: Math.floor(Date.parse("2026-11-20T00:00:00+07:00") / 1000), status: "Đang diễn ra" };
    const list: ReaderResponse = { endpoint: "promotion_list", url: "u", status: 200, capturedAt: T0, source: "page", body: { code: 0, data: { list: [entry] } } };
    const mapped = mapPromotions([list, { ...list, endpoint: "promotion_active" }], T0);
    expect(mapped).toHaveLength(1);
    expect(mapped[0]).toMatchObject({ dataset: "promotions", granularity: "period", date: "2026-11-19" });
    expect(mapped[0]?.rows).toEqual([{ program_name: "Giảm giá mùa mưa", promo_type: "Chương Trình Khuyến Mãi", starts_at: "2026-11-10T00:00:00", ordinal: 0, ends_at: "2026-11-20T00:00:00", status: "Đang diễn ra" }]);
  });

  it("the reader replays the page's own metrics GET once per day with only the range changed", async () => {
    let clock = 1_000_000;
    const sleep = async (ms: number) => void (clock += ms);
    const sent: ReaderRequest[] = [];
    const templates: Partial<Record<ReaderEndpoint, Template>> = {
      promotion_metrics: { query: { start_time: "1", end_time: "2", scope: "all" }, lastResponse: { code: 0, data: { metrics: {} } } },
      promotion_list: { query: {}, lastResponse: { code: 0, data: { list: [] } } },
    };
    const env: ReaderEnv = {
      origin: SC,
      pacer: new Pacer({ sleep, now: () => clock, random: () => 0 }),
      now: () => clock,
      session: () => ({ SPC_CDS: "s", SPC_CDS_VER: "2" }),
      hasSession: () => true,
      template: (endpoint) => templates[endpoint],
      waitFor: pollingWaitFor(sleep, () => clock),
      fetch: async (request): Promise<FetchedReaderResponse> => {
        sent.push(request);
        return { status: 200, text: async () => JSON.stringify({ code: 0, data: { metrics: {} } }) };
      },
      pathname: () => "/portal/marketing/discount/list",
    };
    const outcome = await runReaderJob({ id: "promotions", days: ["2026-11-17", "2026-11-18"] }, env);
    expect(outcome.status).toBe("done");
    expect(sent.map((r) => [r.method, new URL(r.url).pathname, new URL(r.url).searchParams.get("start_time"), new URL(r.url).searchParams.get("scope")])).toEqual([
      ["GET", "/api/marketing/v3/public/discount/metrics/", String(Math.floor(Date.parse("2026-11-17T00:00:00+07:00") / 1000)), "all"],
      ["GET", "/api/marketing/v3/public/discount/metrics/", String(Math.floor(Date.parse("2026-11-18T00:00:00+07:00") / 1000)), "all"],
    ]);
    expect(outcome.responses.filter((r) => r.source === "page").map((r) => r.endpoint)).toEqual(["promotion_list", "promotion_metrics"]);
  });

  it("no range keys in the page's own call: needs_template, never a guessed request", async () => {
    expect(rangeKeysOf({ page: "1" })).toBeUndefined();
    expect(rangeKeysOf({ from: "1", to: "2" })).toEqual({ start: "from", end: "to" });
    const env = { origin: SC, pacer: new Pacer({ sleep: async () => {}, now: () => 0, random: () => 0 }), now: () => 0, session: () => ({}), hasSession: () => true, template: (e: string) => (e === "promotion_metrics" ? { query: { page: "1" }, lastResponse: {} } : undefined), waitFor: async () => true, fetch: async () => ({ status: 200, text: async () => "{}" }) } as unknown as ReaderEnv;
    expect((await runReaderJob({ id: "promotions", days: ["2026-11-17"] }, env)).status).toBe("needs_template");
  });

  it("a daily run plans promotions with yesterday and the hole days", () => {
    const jobs = planJobs({ shopId: SHOP, nowMs: T0, stopped: new Set<never>(), adsDone: [], readers: ["promotions"], holes: { promotion_daily: ["2026-11-01"] }, holeRoom: 100 });
    expect(jobs).toEqual([{ id: "promotions", days: ["2026-11-18", "2026-11-01"] }]);
  });
});

describe("F4.13: the popup lists every reader that is not done / fresh / skipped", () => {
  const readers = {
    adsDone: [],
    lastRun: {
      day: "2026-11-19",
      at: "x",
      outcomes: {
        products: "done:item_catalog=posted",
        item_traffic: "blocked:password_recheck",
        affiliate_content: "timeout",
        affiliate_kols: "needs_template:affiliate_performance",
        order_income: "blocked:no_permission|http_403",
        orders: "done:order_lines=posted|partial:first_page",
        vouchers: "no_items",
        catchup: "done:catchup:traffic_overview=2 days left",
        ads: "waiting_budget",
        health: "open_failed",
      },
    },
  };
  it("one short Vietnamese line per page, nothing for done / skipped / the catch-up note", () => {
    expect(problemLines(readers, "2026-11-19").map((l) => l.text)).toEqual([
      "Phân Tích Bán Hàng › Sản phẩm › Truy cập: Cần xác nhận mật khẩu",
      "Tiếp Thị Liên Kết › Phân tích nội dung: Quá thời gian",
      "Tiếp Thị Liên Kết › Phân tích KOL: Chưa đọc được trang",
      "Đơn hàng › chi tiết từng đơn đã hoàn thành: Cần quyền Tài chính",
      "Đơn hàng › Tất cả: Mới đọc một phần",
      "Kênh Marketing › Quảng Cáo Shopee: Hết lượt hôm nay",
      "Tài khoản › Sức khỏe tài khoản: Không mở được tab",
    ]);
  });
  it("is empty for another day, and labels the new empty-with-data error", () => {
    expect(problemLines(readers, "2026-11-20")).toEqual([]);
    expect(problemLabel("error:affiliate_kols:empty_with_data")).toBe("Trang trống dù có số liệu");
    expect(problemLabel("done:x=posted")).toBeNull();
  });
});

describe("F4.4 / F4.5 wiring (t1a's readers)", () => {
  it("ads_products gets its days from the ads_campaign_period holes, oldest first, capped", () => {
    const base = { shopId: SHOP, nowMs: T0, stopped: new Set<never>(), adsDone: [] as string[], readers: ["ads_products"] as const };
    const holes = { ads_campaign_period: Array.from({ length: 14 }, (_, i) => `2026-10-${String(20 + i).padStart(2, "0")}`) };
    const days = planJobs({ ...base, holes, holeRoom: 1000 })[0]?.days;
    expect(days).toEqual(holes.ads_campaign_period.slice(0, 10));
    expect(planJobs({ ...base, holes: {}, holeRoom: 1000 })).toEqual([{ id: "ads_products" }]);
    expect(planJobs({ ...base, holes, holeRoom: 0 })).toEqual([{ id: "ads_products" }]);
  });

  it("item_traffic reads the items with views in the last product table, most viewed first", async () => {
    const ctx = setup(["product_period", "item_traffic"]);
    ctx.storage.data.readers = { adsDone: [], trafficDone: [], itemIds: ["1", "2", "3", "4"], adsHistory: { shopId: SHOP, createdAt: "x", days: [], done: [], status: "done" } };
    const table = { endpoint: "product_performance", url: "u", status: 200, capturedAt: T0, source: "replay", body: { code: 0, data: { items: [{ id: "3001", pv: 5 }, { id: "3002", pv: 0, uv: 0 }, { id: "3003", pv: 40 }] } } };
    await ctx.scheduler.tick();
    await answerPage(ctx, "done", [table]);
    expect((await ctx.read())?.viewedItems?.ids).toEqual(["3003", "3001"]);
    ctx.clock.now += GAP;
    await ctx.scheduler.tick();
    expect((await ctx.read())?.run?.jobs[1]?.itemIds).toEqual(["3003", "3001"]);
  });
});
