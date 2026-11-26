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
import { mapCapturedAll } from "../src/platforms/shopee/map";
import { buildBackfillDayPlan, buildSyncPlan } from "../src/platforms/shopee/sync";
import { classify } from "../src/platforms/shopee/reader";
import { gmt7Date, gmt7DateStart } from "../src/core/time";
import { CATCHUP_BACKFILL_DATASETS, isDatacenterPath } from "../src/platforms/shopee/config";
import { isNoCampaign } from "../src/platforms/shopee/promotion-map";
import { mapTrafficJob } from "../src/platforms/shopee/reader-map";
import { type FetchedReaderResponse, pollingWaitFor, type ReaderEnv, type ReaderRequest, type ReaderResponse, runReaderJob, type Template } from "../src/platforms/shopee/reader";
import type { ReadDays } from "../src/platforms/shopee/background/catchup";
import type { ReaderEndpoint } from "../src/platforms/shopee/endpoints";
import { isDataAnswer, Pacer } from "../src/platforms/shopee/runner";

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
    expect(withHoleDays("traffic", ["2026-11-18"], h, 16, 0)).toEqual(["2026-11-18", "2026-11-05", "2026-11-06"]); // 8 requests a day (F6: product overview, promotions, flash sale)
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
    const traffic = jobs.filter((j) => j.id === "traffic");
    expect(traffic[0]?.days).toEqual(["2026-11-18", "2026-11-17", "2026-11-16", "2026-11-15"]);
    expect(traffic[1]?.days).toEqual(["2026-10-25", "2026-10-26"]);
    expect(jobs.find((j) => j.id === "ads" && j.days?.includes("2026-10-20"))?.days).toContain("2026-10-20");
    const none = planJobs({ ...base, holes: { traffic_overview: ["2026-10-25"] }, holeRoom: 0 });
    expect(none.find((j) => j.id === "traffic")?.days).not.toContain("2026-10-25");
  });

  it("a daily run fetches the list, reads the hole days and reports the days left", async () => {
    const ctx = setup(["traffic"], holes({ traffic_overview: ["2026-10-25", "2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30", "2026-10-31"], ads_campaign_daily: ["2026-10-20"] }));
    await drive(ctx);
    expect(ctx.posted[0]?.days).toEqual(["2026-11-18", "2026-11-17", "2026-11-16", "2026-11-15"]);
    expect(ctx.posted[1]?.days).toEqual(["2026-10-25", "2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29"]);
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
    expect(backfill?.accepted["2026-11-10"]).toEqual(["traffic_overview", "shop_traffic", "product_overview", "promotion_daily", "flash_sale"]);
    expect(backfill?.accepted["2026-11-18"]).toEqual(["traffic_overview", "item_by_source", "shop_traffic", "product_overview", "promotion_daily", "flash_sale"]);
    expect(backfill?.accepted["2026-11-17"]).toEqual(["item_by_source", "item_performance", "shop_traffic", "product_overview", "promotion_daily", "flash_sale"]);
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

  it("S1 #48: a backfill read queues its completed orders' page again, read before or not; a plain read does not", () => {
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
    const queued = (job: Record<string, unknown>, sched: Record<string, unknown> = {}) => {
      const out = (ctx.scheduler as unknown as { shopReaderState: (...a: unknown[]) => { incomeQueue?: { id: string }[] } }).shopReaderState(
        { adsDone: [], incomeSince: T0 - day, incomeReadAt: T0 - 3 * day, ...sched },
        { day: "2026-11-19" },
        { id: "orders", ...job },
        { order_lines: "posted" },
        responses,
        SHOP,
        true,
        "",
      );
      return (out.incomeQueue ?? []).map((o) => o.id);
    };
    const backfillSince = gmt7Date(Math.floor((T0 - 25 * day) / 1000));
    expect(queued({ sinceDay: backfillSince })).toEqual(["SN0002"]);
    expect(queued({ sinceDay: backfillSince, orderBackfill: true })).toEqual(["SN0001", "SN0002"]);
    // an order already waiting in the queue is not queued twice
    expect(queued({ sinceDay: backfillSince, orderBackfill: true }, { incomeQueue: [{ id: "SN0001", completedAt: T0 - 20 * day }] })).toEqual(["SN0001", "SN0002"]);
  });
});

describe("F6.4: flash sale reader (promotion_daily rows, promo_type Flash Sale)", () => {
  const DAYSTART = gmt7DateStart("2026-11-17");
  const FLASH = "/api/mydata/marketing/flash-sale/key-metrics/";
  const url = (orderType: string, end = DAYSTART + 86_400, period = "day") =>
    `${SC}${FLASH}?start_time=${DAYSTART}&end_time=${end}&period=${period}&order_type=${orderType}`;
  const metric = (value: number) => ({ value, chain_ratio: 0.1, points: [{ timestamp: DAYSTART, value }] });
  const body = {
    code: 0,
    result: { sales: metric(900_000), orders: metric(6), buyers: metric(4), sales_per_buyer: metric(225_000), product_impression: metric(1200), product_clicks: metric(80), reminder_clicks: metric(9), conversion_rate: metric(0.05) },
  };
  const none = { code: 40001, msg: "err:no campaign, detail:no campaign" };

  it("is in the sync plan and the backfill day plan: placed and confirmed, end = next midnight, own dataset", () => {
    for (const plan of [buildBackfillDayPlan("2026-11-17", T0, new Set(), false), buildBackfillDayPlan("2026-11-18", T0, new Set(), false)]) {
      const flash = plan.filter((p) => p.dataset === "flash_sale");
      expect(flash.map((p) => p.params.order_type)).toEqual(["placed", "confirmed"]);
      const start = Number(flash[0]?.params.start_time);
      expect(flash[0]?.params).toMatchObject({ end_time: String(start + 86_400), period: "day" });
      expect(flash[0]?.path).toBe(FLASH);
    }
    expect(buildBackfillDayPlan("2026-11-17", T0, new Set(["flash_sale"] as const), false).some((p) => p.dataset === "flash_sale")).toBe(false);
    expect(buildSyncPlan(T0, new Set(), false).filter((p) => p.dataset === "flash_sale")).toHaveLength(2);
    expect(buildSyncPlan(T0, new Set(["flash_sale"] as const), false).some((p) => p.dataset === "flash_sale")).toBe(false);
    expect(CATCHUP_BACKFILL_DATASETS).toContain("flash_sale");
  });

  it("maps the values only into one promotion_daily row; impressions / clicks stay in extra", () => {
    const posts = mapCapturedAll({ url: url("placed"), body, capturedAt: T0 });
    expect(posts).toHaveLength(1);
    expect(posts[0]).toMatchObject({ dataset: "promotion_daily", date: "2026-11-17", orderType: "placed", drift: null });
    expect(posts[0]?.rows).toEqual([
      {
        date: "2026-11-17",
        promo_type: "Flash Sale",
        sales: 900_000,
        orders: 6,
        buyers: 4,
        sales_per_buyer: 225_000,
        extra: { product_impression: 1200, product_clicks: 80, reminder_clicks: 9, conversion_rate: 0.05 },
      },
    ]);
    expect(mapCapturedAll({ url: url("confirmed"), body, capturedAt: T0 })[0]?.orderType).toBe("confirmed");
  });

  it("code 40001 'no campaign' is an empty day: a zero row, not drift or an error", () => {
    const posts = mapCapturedAll({ url: url("placed"), body: none, capturedAt: T0 });
    expect(posts).toHaveLength(1);
    expect(posts[0]?.rows).toEqual([{ date: "2026-11-17", promo_type: "Flash Sale", sales: 0, orders: 0, buyers: 0 }]);
    expect(posts[0]?.drift).toBeNull();
    expect(isNoCampaign(none)).toBe(true);
    expect(isNoCampaign({ code: 40001, msg: "something else" })).toBe(false);
    expect(isDataAnswer(200, none)).toBe(true);
    expect(isDataAnswer(200, { code: 40001, msg: "something else" })).toBe(false);
    expect(classify(200, none)).toBe("ok");
    expect(classify(200, { code: 40001, msg: "something else" })).toBe("error");
  });

  it("other error codes, the paid basis, today (real_time) and a partial day are not posted", () => {
    expect(mapCapturedAll({ url: url("placed"), body: { code: 10006, msg: "err" }, capturedAt: T0 })).toEqual([]);
    expect(mapCapturedAll({ url: url("paid"), body, capturedAt: T0 })).toEqual([]);
    expect(mapCapturedAll({ url: url("placed", DAYSTART + 3600, "real_time"), body, capturedAt: T0 })).toEqual([]);
    expect(mapCapturedAll({ url: url("placed", DAYSTART + 86_399), body, capturedAt: T0 })).toEqual([]);
  });

  it("the traffic reader maps a flash answer and an empty-day answer through mapTrafficJob", () => {
    const answers = ["placed", "confirmed"].map((order_type, i) => ({ endpoint: "flash_sale", url: url(order_type), status: 200, body: i === 0 ? body : none, capturedAt: T0 }));
    const posts = mapTrafficJob(answers as never);
    expect(posts.map((p) => [p.dataset, p.orderType, p.rows[0]?.sales])).toEqual([["promotion_daily", "placed", 900_000], ["promotion_daily", "confirmed", 0]]);
  });
});

describe("F4.7: promotion_daily from the per-programme performance list", () => {
  const DAYSTART = gmt7DateStart("2026-11-17");
  const url = (orderType: string, type = "1", end = DAYSTART + 86_400) =>
    `${SC}/api/mydata/marketing/new-discount/performance-list/?start_time=${DAYSTART}&end_time=${end}&period=day&promotion_type=${type}&order_type=${orderType}`;
  const programme = (over: Record<string, unknown>) => ({ promotion_id: 1, promotion_name: "Giảm giá thử", promotion_type: 2, status: 1, create_time: DAYSTART - 99, start_time: DAYSTART - 86_400, end_time: DAYSTART + 86_400 * 5, units: 4, orders: 3, buyers: 2, sales: 400_000, sales_per_buyer: 200_000, ...over });
  const answer = (orderType: string, result: unknown, type = "1") => mapCapturedAll({ url: url(orderType, type), body: { code: 0, result }, capturedAt: T0 });

  it("is a mydata day request in the sync plan and the backfill day plan, placed and confirmed, end = next midnight", () => {
    for (const plan of [buildBackfillDayPlan("2026-11-17", T0, new Set(), false), buildBackfillDayPlan("2026-11-18", T0, new Set(), false)]) {
      const promos = plan.filter((p) => p.dataset === "promotion_daily");
      expect(promos.map((p) => p.params.order_type)).toEqual(["placed", "confirmed"]);
      const start = Number(promos[0]?.params.start_time);
      expect(promos[0]?.params).toMatchObject({ end_time: String(start + 86_400), period: "day", promotion_type: "1" });
      expect(promos[0]?.path).toBe("/api/mydata/marketing/new-discount/performance-list/");
    }
    expect(buildBackfillDayPlan("2026-11-17", T0, new Set(["promotion_daily"] as const), false).some((p) => p.dataset === "promotion_daily")).toBe(false);
  });

  it("one row per promotion type and day plus the total, with the file import's fields", () => {
    const posts = answer("placed", [programme({}), programme({ promotion_id: 2, promotion_name: "Khác", sales: 100_000, orders: 1, units: 1, buyers: 1 }), programme({ promotion_id: 3, promotion_type: 3, promotion_name: "Combo thử", sales: 50_000, orders: 1, units: 2, buyers: 1 })]);
    const daily = posts.find((p) => p.dataset === "promotion_daily");
    expect(daily).toMatchObject({ date: "2026-11-17", orderType: "placed", drift: null });
    expect(daily?.rows).toEqual([
      { date: "2026-11-17", promo_type: "Tất cả", sales: 550_000, orders: 5, units: 7, buyers: 4, sales_per_buyer: 137_500 },
      { date: "2026-11-17", promo_type: "Chương Trình Khuyến Mãi", sales: 500_000, orders: 4, units: 5, buyers: 3, sales_per_buyer: 166_666.67 },
      { date: "2026-11-17", promo_type: "Combo Khuyến Mãi", sales: 50_000, orders: 2 - 1, units: 2, buyers: 1, sales_per_buyer: 50_000 },
    ]);
  });

  it("an unknown type only counts in the total; result null is an empty day posted as zeros, not an error", () => {
    const unknown = answer("confirmed", [programme({ promotion_type: 9, promotion_name: "Lạ" })]);
    expect(unknown[0]?.rows).toEqual([{ date: "2026-11-17", promo_type: "Tất cả", sales: 400_000, orders: 3, units: 4, buyers: 2, sales_per_buyer: 200_000 }]);
    const empty = answer("confirmed", null);
    expect(empty).toHaveLength(1);
    expect(empty[0]?.rows).toEqual([{ date: "2026-11-17", promo_type: "Tất cả", sales: 0, orders: 0, units: 0, buyers: 0 }]);
    expect(empty[0]?.drift).toBeNull();
  });

  it("a single-type answer, an error answer and an unfinished / partial day are not the day's total", () => {
    expect(answer("placed", [programme({})], "2")).toEqual([]);
    expect(mapCapturedAll({ url: url("placed"), body: { code: 10006, msg: "err" }, capturedAt: T0 })).toEqual([]);
    expect(mapCapturedAll({ url: url("placed", "1", DAYSTART + 86_399), body: { code: 0, result: null }, capturedAt: T0 })).toEqual([]);
    expect(mapCapturedAll({ url: url("paid"), body: { code: 0, result: null }, capturedAt: T0 })).toEqual([]);
  });

  it("the promotions snapshot comes from the placed answer's programmes (known types, terms only)", () => {
    const posts = answer("placed", [programme({}), programme({}), programme({ promotion_type: 9, promotion_name: "Lạ" })]);
    const snapshot = posts.find((p) => p.dataset === "promotions");
    expect(snapshot).toMatchObject({ granularity: "period", date: "2026-11-17", periodStart: "2026-11-17" });
    expect(snapshot?.rows).toEqual([
      { program_name: "Giảm giá thử", promo_type: "Chương Trình Khuyến Mãi", starts_at: "2026-11-16T00:00:00", ordinal: 0, ends_at: "2026-11-22T00:00:00" },
      { program_name: "Giảm giá thử", promo_type: "Chương Trình Khuyến Mãi", starts_at: "2026-11-16T00:00:00", ordinal: 1, ends_at: "2026-11-22T00:00:00" },
    ]);
    expect(answer("confirmed", [programme({})]).some((p) => p.dataset === "promotions")).toBe(false);
  });
});

describe("mydata replays only from /datacenter/ (finding 2026-11-19)", () => {
  it("isDatacenterPath", () => {
    expect(isDatacenterPath("/datacenter/traffic/overview")).toBe(true);
    expect(isDatacenterPath("/portal/marketing/list/discount")).toBe(false);
  });

  it("a code 10000 'not login' answer is never a login verdict", () => {
    expect(classify(200, { code: 10000, msg: "permission denied", result: "not login" })).toBe("error");
    expect(classify(200, { code: 10000, msg: "not login" })).toBe("error");
  });

  it("the reader sends no mydata request from a page outside /datacenter/: needs_data_page, nothing sent", async () => {
    let sent = 0;
    const sleep = async () => {};
    const env = {
      origin: SC,
      pacer: new Pacer({ sleep, now: () => 0, random: () => 0 }),
      now: () => 1_000_000,
      session: () => ({ SPC_CDS: "s", SPC_CDS_VER: "2" }),
      hasSession: () => true,
      template: () => undefined,
      waitFor: async () => true,
      fetch: async (): Promise<FetchedReaderResponse> => {
        sent += 1;
        return { status: 200, text: async () => JSON.stringify({ code: 10000, msg: "permission denied", result: "not login" }) };
      },
      pathname: () => "/portal/marketing/list/discount",
    } as unknown as ReaderEnv;
    const outcome = await runReaderJob({ id: "traffic", days: ["2026-11-17"] }, env);
    expect(outcome.status).toBe("needs_data_page");
    expect(sent).toBe(0);
  });

  it("a backfill day answered 10000 waits for a Phân tích bán hàng tab instead of stopping or blocking", async () => {
    const storage = new MemoryStorage();
    const tabs: Tabs = { sellerCentreTabs: async () => [7], send: async () => undefined };
    const connector = new Connector({ storage, client: new GatewayClient(async () => new Response("{}")), tabs, version: "0.3.29", now: () => T0 });
    storage.data.token = TOKEN;
    await connector.backfillStep();
    const day = (await loadState(storage)).backfill?.inFlight?.day as string;
    const results = [{ dataset: "traffic_overview" as const, url: "u", status: 200, body: { code: 10000, msg: "permission denied", result: "not login" }, capturedAt: T0 }];
    expect(await connector.backfillResult(day, "done", results)).toBe("needs_data_page");
    const backfill = (await loadState(storage)).backfill;
    expect(backfill?.status).toBe("running");
    expect(backfill?.needsDataPage).toBe(true);
    expect(backfill?.stop).toBeUndefined();
    expect((await loadState(storage)).readers?.blocked).toBeUndefined();
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
    const jobs = planJobs({ ...base, holes, holeRoom: 1000 });
    expect(jobs.find((j) => j.id === "ads_products" && j.days)?.days).toEqual(holes.ads_campaign_period.slice(0, 10));
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

describe("0.3.30: fills and read-backs keep their own reserve", () => {
  it("readers (incl. catch-up) stop FILL_REQUEST_RESERVE short of the total, fills can still use it", async () => {
    const { readerRequestsLeft } = await import("../src/platforms/shopee/background/state");
    const { requestsLeft } = await import("../src/core/state");
    const { DAILY_REQUEST_BUDGET, FILL_REQUEST_RESERVE } = await import("../src/core/config");
    const day = "2026-11-19";
    const state = { budget: { day, used: DAILY_REQUEST_BUDGET - FILL_REQUEST_RESERVE } } as never;
    expect(readerRequestsLeft(state, day)).toBe(0);
    expect(requestsLeft(state, day)).toBe(FILL_REQUEST_RESERVE);
  });
});
