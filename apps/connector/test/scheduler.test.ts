const PILOT = "5b0c1d2e-3f40-4a51-8b62-7c83d94e0a15";
import { describe, expect, it } from "vitest";
import {
  BACKFILL_REQUEST_SHARE,
  DAILY_REQUEST_BUDGET,
  READER_BLOCK_CAPTCHA_MS,
  READER_BLOCK_LOGIN_MS,
  READER_JOB_TIMEOUT_MS,
  READER_LOAD_GRACE_MS,
  READER_PAGE_GAP_JITTER_MS,
  READER_PAGE_GAP_MS,
  ORDERS_JOB_TIMEOUT_MS,
  ADS_JOB_TIMEOUT_MS,
  ADS_HISTORY_DAY_COST,
  TODAY_REQUEST_RESERVE,
  type ReaderDataset,
  type ReaderId,
} from "../src/platforms/shopee/config";
import {
  type BlockEvent,
  nextStockAt,
  ordersSinceDay,
  READER_KICK_ALARM,
  READER_WATCHDOG_ALARM,
  stockDueAt,
  type TickReport,
  ReaderScheduler,
  planJobs,
  type SchedulerAlarms,
  type SchedulerTabs,
} from "../src/platforms/shopee/background/scheduler";
import { loadState, saveState } from "../src/platforms/shopee/background/state";
import { lastFinishedDays } from "../src/core/time";
import type { ReaderJob, ReaderResponse } from "../src/platforms/shopee/reader";

const SC = "https://banhang.shopee.vn";
/** The run sequences below were written for the Seller Centre report pages; the affiliate pages
 *  (Connector 0.3.6) are planned by default and covered on their own (affiliate tests + below). */
const CORE_READERS = ["products", "vouchers", "ads", "health", "item_traffic"] as const;
// 2026-11-03 10:00 GMT+7
const T0 = Date.UTC(2026, 10, 3, 3, 0, 0);
const GAP = READER_PAGE_GAP_MS + READER_PAGE_GAP_JITTER_MS + 1;
const TOKEN = {
  token: "jci_x",
  token_id: "t1",
  shop_id: PILOT,
  platform: "shopee",
  expires_at: "2027-01-10T00:00:00Z",
  rotate_after: "2026-12-01T00:00:00Z",
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

class FakeTabs implements SchedulerTabs {
  nextId = 100;
  opened: { id: number; url: string }[] = [];
  closed: number[] = [];
  sent: { tabId: number; message: unknown }[] = [];
  /** What `inspect` says per tab id; default: open at the url it was opened with. */
  inspection = new Map<number, { open: boolean; url?: string }>();
  failOpen = false;
  failSend = false;
  async open(url: string) {
    if (this.failOpen) return undefined;
    const id = this.nextId++;
    this.opened.push({ id, url });
    return id;
  }
  async close(tabId: number) {
    this.closed.push(tabId);
  }
  async send(tabId: number, message: unknown) {
    if (this.failSend) throw new Error("no receiver");
    this.sent.push({ tabId, message });
    return undefined;
  }
  async inspect(tabId: number) {
    return this.inspection.get(tabId) ?? { open: true, url: this.opened.find((t) => t.id === tabId)?.url };
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

function setup(options: { token?: boolean; backfillBusy?: boolean; readers?: readonly ReaderId[]; stockRun?: boolean } = {}) {
  const storage = new MemoryStorage();
  const tabs = new FakeTabs();
  const alarms = new FakeAlarms();
  const posted: { job: ReaderJob; responses: ReaderResponse[] }[] = [];
  const events: BlockEvent[] = [];
  const clock = { now: T0 };
  const flags = {
    backfillBusy: options.backfillBusy ?? false,
    /** How each ads day's upload ends (default "posted"), keyed like the real sink. */
    adsOutcome: {} as Record<string, string>,
    totalsOutcome: "posted",
  };
  const scheduler = new ReaderScheduler({
    storage,
    tabs,
    alarms,
    readers: options.readers ?? CORE_READERS,
    stockRun: options.stockRun ?? false,
    origin: SC,
    version: "0.3.4",
    now: () => clock.now,
    random: () => 0.5,
    backfillBusy: async () => flags.backfillBusy,
    sink: {
      async reportBlock(event) {
        events.push(event);
      },
      async postReader(job, responses) {
        posted.push({ job, responses });
        if (job.id === "shop_totals") return { "shop_overview:confirmed": flags.totalsOutcome };
        if (job.id === "ads") {
          return Object.fromEntries(
            [...(job.days ?? []), ...(job.historyDays ?? [])].map((day) => [`ads_campaign_daily:${day}`, flags.adsOutcome[day] ?? "posted"]),
          );
        }
        if (job.id === "orders") return { order_lines: "posted" };
        return { [job.id]: "posted" };
      },
    },
  });
  if (options.token !== false) storage.data.token = TOKEN;
  const read = async () => (await loadState(storage)).readers;
  return { scheduler, storage, tabs, alarms, posted, events, clock, flags, read };
}

/** The ads list's answer for each day (one campaign), as the hook returns it. */
function adsReplies(days: readonly string[] = []): unknown[] {
  return days.map((day) => ({
    endpoint: "ads_homepage",
    url: "u",
    status: 200,
    capturedAt: T0,
    source: "replay",
    day,
    page: 1,
    body: { code: 0, data: { entry_list: [{ title: "x", campaign: { campaign_id: 1 }, report: { cost: 1 } }] } },
  }));
}

/** Drive one page: tab ready, then the hook's answer. */
async function finishPage(
  ctx: ReturnType<typeof setup>,
  status = "done",
  responses: unknown[] = [],
): Promise<void> {
  const tab = ctx.tabs.current;
  const job = (await ctx.read())?.run?.jobs[(await ctx.read())?.run?.index ?? 0];
  expect(await ctx.scheduler.onTabReady(tab.id, tab.url)).toBe(true);
  const answers = job?.id === "ads" && responses.length === 0 ? adsReplies(job.days) : responses;
  expect(await ctx.scheduler.onResult(tab.id, { job: job?.id, status, responses: answers })).toBe(true);
}

/** A product_list answer with the given item ids (a normal status), optionally unlisted. */
function productList(ids: string[], page: number, tag?: "unlist") {
  return {
    endpoint: "product_list",
    url: "u",
    status: 200,
    capturedAt: T0,
    source: "replay",
    page,
    body: {
      code: 0,
      data: {
        products: ids.map((id) => ({ id: Number(id), name: "x", status: 1, stock_detail: {}, ...(tag ? { tag: { unlist: true } } : {}) })),
      },
    },
  };
}

describe("planJobs", () => {
  const base = { shopId: PILOT, nowMs: T0, stopped: new Set<never>(), adsDone: [] as string[], readers: CORE_READERS };

  it("by default the affiliate pages are planned too, before item_traffic (which stays last)", () => {
    const ids = planJobs({ ...base, readers: undefined }).map((j) => j.id);
    expect(ids).toEqual([
      "products",
      "orders",
      "order_income",
      "vouchers",
      "ads",
      "ads_detail",
      "ads_products",
      "health",
      "shop_totals",
      "traffic",
      "product_period",
      "affiliate",
      "affiliate_kols",
      "affiliate_dashboard",
      "affiliate_products",
      "affiliate_campaigns",
      "affiliate_commissions",
      "affiliate_content",
      "affiliate_bills",
      "item_traffic",
    ]);
  });

  it("opens every page whose dataset can be posted: health runs, nothing is held", () => {
    expect(planJobs(base).map((j) => j.id)).toEqual(["products", "vouchers", "ads", "health", "item_traffic"]);
    // a held dataset takes its page off the plan
    expect(planJobs({ ...base, held: new Set<ReaderDataset>(["shop_health_daily"]) }).map((j) => j.id)).toEqual([
      "products",
      "vouchers",
      "ads",
      "item_traffic",
    ]);
  });

  it("item_traffic: yesterday and up to three earlier finished days not read yet, newest first", () => {
    expect(planJobs(base).find((j) => j.id === "item_traffic")?.days).toEqual([
      "2026-11-02",
      "2026-11-01",
      "2026-10-31",
      "2026-10-30",
    ]);
    expect(
      planJobs({ ...base, trafficDone: ["2026-11-02", "2026-10-31"] }).find((j) => j.id === "item_traffic")?.days,
    ).toEqual(["2026-11-01", "2026-10-30"]);
    expect(
      planJobs({ ...base, trafficDone: ["2026-11-02", "2026-11-01", "2026-10-31", "2026-10-30"] }).map((j) => j.id),
    ).not.toContain("item_traffic");
  });

  it("ads: yesterday and up to three earlier finished days not read yet, newest first", () => {
    expect(planJobs(base).find((j) => j.id === "ads")?.days).toEqual([
      "2026-11-02",
      "2026-11-01",
      "2026-10-31",
      "2026-10-30",
    ]);
    expect(planJobs({ ...base, adsDone: ["2026-11-02", "2026-10-31"] }).find((j) => j.id === "ads")?.days).toEqual([
      "2026-11-01",
      "2026-10-30",
    ]);
    expect(planJobs({ ...base, adsDone: ["2026-11-02", "2026-11-01", "2026-10-31", "2026-10-30"] }).map((j) => j.id)).toEqual([
      "products",
      "vouchers",
      "health",
      "item_traffic",
    ]);
  });

  it("a dataset stopped after drift (this version) takes its page off the plan; no shop = nothing", () => {
    expect(planJobs({ ...base, stopped: new Set(["voucher_settings" as const]) }).map((j) => j.id)).toEqual(["products", "ads", "health", "item_traffic"]);
    expect(planJobs({ ...base, shopId: undefined })).toEqual([]);
  });
});

describe("a daily run", () => {
  it("opens one background tab per page, one at a time, with a gap, and closes each", async () => {
    const ctx = setup();
    ctx.storage.data.readers = { adsDone: [], trafficDone: [], adsHistory: { shopId: PILOT, createdAt: "x", days: [], done: [], status: "done" } };
    expect(await ctx.scheduler.tick()).toBe("opened");
    expect(ctx.tabs.opened.map((t) => t.url)).toEqual([`${SC}/portal/product/list/all`]);
    expect(ctx.alarms.active.has(READER_WATCHDOG_ALARM)).toBe(true);
    expect(await ctx.scheduler.isBusy()).toBe(true);
    expect(await ctx.scheduler.activeTabIds()).toEqual([ctx.tabs.current.id]);

    // tab ready -> the job is sent to that tab
    const first = ctx.tabs.current;
    expect(await ctx.scheduler.onTabReady(first.id, first.url)).toBe(true);
    expect(ctx.tabs.sent).toEqual([{ tabId: first.id, message: { type: "reader-job", job: { id: "products", budget: DAILY_REQUEST_BUDGET - 10 } } }]);
    // a second "ready" from a reload does not send it again
    await ctx.scheduler.onTabReady(first.id, first.url);
    expect(ctx.tabs.sent).toHaveLength(1);

    // answer: posted, tab closed, nothing else opened until the gap has passed
    await ctx.scheduler.onResult(first.id, { job: "products", status: "done", responses: [{ endpoint: "product_list" }] });
    expect(ctx.posted.map((p) => p.job.id)).toEqual(["products"]);
    expect(ctx.tabs.closed).toEqual([first.id]);
    expect(await ctx.scheduler.tick()).toBe("gap");
    expect(ctx.tabs.opened).toHaveLength(1);

    ctx.clock.now += GAP;
    expect(await ctx.scheduler.tick()).toBe("opened");
    expect(ctx.tabs.current.url).toBe(`${SC}/portal/marketing/vouchers/list`);
    await finishPage(ctx);
    ctx.clock.now += GAP;
    await ctx.scheduler.tick();
    expect(ctx.tabs.current.url).toBe(`${SC}/portal/marketing/pas/index`);
    await finishPage(ctx);
    ctx.clock.now += GAP;
    await ctx.scheduler.tick();
    expect(ctx.tabs.current.url).toBe(`${SC}/portal/accounthealth`);
    await finishPage(ctx);
    ctx.clock.now += GAP;
    expect(await ctx.scheduler.tick()).toBe("finished");

    // the run is over (item_traffic had no item ids: its page is not even opened): watchdog cleared, today recorded, no more pages today
    const state = await ctx.read();
    expect(state?.run).toBeUndefined();
    expect(state?.lastRunDay).toBe("2026-11-03");
    expect(state?.lastRun?.outcomes).toEqual({
      products: "done:products=posted",
      vouchers: "done:vouchers=posted",
      ads: "done:" + ["2026-11-02", "2026-11-01", "2026-10-31", "2026-10-30"].map((d) => `ads_campaign_daily:${d}=posted`).join(","),
      health: "done:health=posted",
      item_traffic: "no_items",
    });
    expect(ctx.alarms.active.has(READER_WATCHDOG_ALARM)).toBe(false);
    expect(ctx.tabs.closed).toHaveLength(4);
    expect(await ctx.scheduler.isBusy()).toBe(false);
    ctx.clock.now += 3_600_000;
    expect(await ctx.scheduler.tick()).toBe("done_today");
    expect(ctx.tabs.opened).toHaveLength(4);
  });

  it("the ads job carries its days; a read ads day is not planned again tomorrow", async () => {
    const ctx = setup();
    // the 90-day ads history is covered on its own below
    ctx.storage.data.readers = { adsDone: [], trafficDone: [], adsHistory: { shopId: PILOT, createdAt: "x", days: [], done: [], status: "done" } };
    await ctx.scheduler.tick();
    await finishPage(ctx);
    ctx.clock.now += GAP;
    await ctx.scheduler.tick();
    await finishPage(ctx);
    ctx.clock.now += GAP;
    await ctx.scheduler.tick();
    const tab = ctx.tabs.current;
    await ctx.scheduler.onTabReady(tab.id, tab.url);
    expect(ctx.tabs.sent.at(-1)?.message).toEqual({
      type: "reader-job",
      job: { id: "ads", days: ["2026-11-02", "2026-11-01", "2026-10-31", "2026-10-30"], budget: expect.any(Number) },
    });
    await ctx.scheduler.onResult(tab.id, {
      job: "ads",
      status: "done",
      responses: adsReplies(["2026-11-02", "2026-11-01", "2026-10-31", "2026-10-30"]),
    });
    ctx.clock.now += GAP;
    await ctx.scheduler.tick();
    await finishPage(ctx); // health
    ctx.clock.now += GAP;
    await ctx.scheduler.tick(); // item_traffic: no ids, skipped
    expect((await ctx.read())?.adsPosted).toEqual(["2026-11-02", "2026-11-01", "2026-10-31", "2026-10-30"]);
    // tomorrow: only the new finished day
    ctx.clock.now += 24 * 3_600_000;
    await ctx.scheduler.tick();
    expect(ctx.tabs.current.url).toContain("/portal/product/list/all");
    expect((await ctx.read())?.run?.jobs.find((j) => j.id === "ads")?.days).toEqual(["2026-11-03"]);
  });

  it("item_traffic: runs last on the product list's ids, needs a tab on /datacenter, records the days read", async () => {
    const ctx = setup();
    await ctx.scheduler.tick();
    const productsTab = ctx.tabs.current;
    await ctx.scheduler.onTabReady(productsTab.id, productsTab.url);
    await ctx.scheduler.onResult(productsTab.id, { job: "products", status: "done", responses: [productList(["11", "12"], 1), productList(["99"], 1, "unlist")] });
    expect((await ctx.read())?.itemIds).toEqual(["11", "12"]);
    for (const url of ["/portal/marketing/vouchers/list", "/portal/marketing/pas/index", "/portal/accounthealth"]) {
      ctx.clock.now += GAP;
      await ctx.scheduler.tick();
      expect(ctx.tabs.current.url).toBe(`${SC}${url}`);
      await finishPage(ctx);
    }
    ctx.clock.now += GAP;
    expect(await ctx.scheduler.tick()).toBe("opened");
    const tab = ctx.tabs.current;
    expect(tab.url).toBe(`${SC}/datacenter/product/traffic`);
    expect(await ctx.scheduler.onTabReady(tab.id, tab.url)).toBe(true);
    const days = ["2026-11-02", "2026-11-01", "2026-10-31", "2026-10-30"];
    expect(ctx.tabs.sent.at(-1)?.message).toEqual({ type: "reader-job", job: { id: "item_traffic", days, itemIds: ["11", "12"], budget: expect.any(Number) } });

    // day 2026-11-02 read for both items, 2026-11-01 for one only: only the first is done
    const answer = (day: string, itemId: string) => ({
      endpoint: "traffic_details",
      day,
      itemId,
      status: 200,
      body: { code: 0, result: {} },
      url: "u",
      capturedAt: T0,
      source: "replay",
    });
    await ctx.scheduler.onResult(tab.id, {
      job: "item_traffic",
      status: "done",
      responses: [answer("2026-11-02", "11"), answer("2026-11-02", "12"), answer("2026-11-01", "11")],
    });
    expect(ctx.posted.at(-1)?.job).toEqual({ id: "item_traffic", days, itemIds: ["11", "12"] });
    expect((await ctx.read())?.trafficDone).toEqual(["2026-11-02"]);
    // the next day: yesterday plus the three earlier days not yet read (11-01, 10-31, 10-30)
    ctx.clock.now += 24 * 3_600_000;
    await ctx.scheduler.tick();
    expect((await ctx.read())?.run?.jobs.find((j) => j.id === "item_traffic")?.days).toEqual([
      "2026-11-03",
      "2026-11-01",
      "2026-10-31",
    ]);
  });

  it("item_traffic: the password re-confirmation modal, after the portal pages read, blocks item_traffic only (0.3.22)", async () => {
    const ctx = setup();
    await ctx.scheduler.tick();
    await saveState(ctx.storage, { readers: { ...(await ctx.read())!, itemIds: ["11"] } });
    await finishPage(ctx);
    for (let i = 0; i < 3; i += 1) {
      ctx.clock.now += GAP;
      await ctx.scheduler.tick();
      await finishPage(ctx);
    }
    ctx.clock.now += GAP;
    await ctx.scheduler.tick();
    const tab = ctx.tabs.current;
    expect(tab.url).toBe(`${SC}/datacenter/product/traffic`);
    await ctx.scheduler.onTabReady(tab.id, tab.url);
    await ctx.scheduler.onResult(tab.id, { job: "item_traffic", status: "blocked_password_recheck", detail: "password_modal", responses: [] });
    const state = await ctx.read();
    expect(state?.blocked).toBeUndefined();
    expect(state?.run).toBeUndefined();
    expect(state?.lastRun?.blocked).toBeUndefined();
    expect(state?.lastRun?.outcomes.item_traffic).toBe("blocked:password_recheck");
    expect(ctx.tabs.closed).toContain(tab.id);
    expect(ctx.events).toEqual([expect.objectContaining({ reader: "item_traffic", status: "password_recheck", code: "reader_only:password_modal" })]);
    expect(await ctx.scheduler.tick()).toBe("done_today");
    expect(state?.trafficDone ?? []).toEqual([]);
  });

  it("a stop seen outside the readers (a fill page's password prompt) ends the run, closes its tab, blocks like a login wall and tells Juli", async () => {
    const ctx = setup();
    await ctx.scheduler.tick();
    const tab = ctx.tabs.current;
    await ctx.scheduler.haltFor("login", "/portal/marketing/vouchers/new", "password_prompt");
    const state = await ctx.read();
    expect(state?.blocked).toMatchObject({ reason: "login" });
    expect(state?.blocked!.until).toBeGreaterThan(ctx.clock.now);
    expect(state?.run).toBeUndefined();
    expect(ctx.tabs.closed).toContain(tab.id);
    expect(ctx.events).toEqual([
      expect.objectContaining({ reader: "fill", page: "/portal/marketing/vouchers/new", status: "login", code: "password_prompt" }),
    ]);
    expect(await ctx.scheduler.tick()).toBe("blocked");
  });

  it("does not start without a token, with a consent refusal, or on top of a backfill day in flight", async () => {
    const noToken = setup({ token: false });
    expect(await noToken.scheduler.tick()).toBe("unpaired");
    const consent = setup();
    await saveState(consent.storage, { consentBlocked: { at: "x" } });
    expect(await consent.scheduler.tick()).toBe("consent_required");
    const busy = setup({ backfillBusy: true });
    expect(await busy.scheduler.tick()).toBe("backfill_busy");
    for (const ctx of [noToken, consent, busy]) expect(ctx.tabs.opened).toEqual([]);
    busy.flags.backfillBusy = false;
    expect(await busy.scheduler.tick()).toBe("opened");
  });

  it("another extension tab is not the scheduler's: tab-ready and results from it are ignored", async () => {
    const ctx = setup();
    await ctx.scheduler.tick();
    expect(await ctx.scheduler.onTabReady(999, `${SC}/portal/dashboard`)).toBe(false);
    expect(await ctx.scheduler.onResult(999, { job: "products", status: "done", responses: [] })).toBe(false);
    expect(ctx.posted).toEqual([]);
  });

  it("a stale answer (another job's) changes nothing", async () => {
    const ctx = setup();
    await ctx.scheduler.tick();
    const tab = ctx.tabs.current;
    await ctx.scheduler.onTabReady(tab.id, tab.url);
    expect(await ctx.scheduler.onResult(tab.id, { job: "ads", status: "done", responses: [] })).toBe(true);
    expect(ctx.posted).toEqual([]);
    expect((await ctx.read())?.run?.index).toBe(0);
  });

  it("an unfinished page (no template, error) is recorded and the run moves on; nothing is posted", async () => {
    const ctx = setup();
    await ctx.scheduler.tick();
    await finishPage(ctx, "needs_template");
    expect(ctx.posted).toEqual([]);
    expect((await ctx.read())?.run?.outcomes).toEqual({ products: "needs_template" });
    ctx.clock.now += GAP;
    expect(await ctx.scheduler.tick()).toBe("opened");
  });
});

describe("timeouts and closed tabs", () => {
  it("a page that never answers is closed after the cap and the run goes on", async () => {
    const ctx = setup();
    await ctx.scheduler.tick();
    const tab = ctx.tabs.current;
    await ctx.scheduler.onTabReady(tab.id, tab.url);
    ctx.clock.now += READER_JOB_TIMEOUT_MS - 1000;
    expect(await ctx.scheduler.tick()).toBe("waiting");
    ctx.clock.now += 2000;
    expect(await ctx.scheduler.tick()).toBe("timeout");
    expect(ctx.tabs.closed).toEqual([tab.id]);
    expect((await ctx.read())?.run?.outcomes.products).toBe("timeout");
    expect((await ctx.read())?.blocked).toBeUndefined();
  });

  it("the seller closing the tab moves on without blocking", async () => {
    const ctx = setup();
    await ctx.scheduler.tick();
    const tab = ctx.tabs.current;
    await ctx.scheduler.onTabRemoved(tab.id);
    expect((await ctx.read())?.run?.outcomes.products).toBe("closed");
    expect(ctx.tabs.closed).toEqual([]);
    expect((await ctx.read())?.blocked).toBeUndefined();
  });

  it("a tab that cannot be opened, or a content script that is not listening yet, does not wedge the run", async () => {
    const ctx = setup();
    ctx.tabs.failOpen = true;
    await ctx.scheduler.tick();
    expect((await ctx.read())?.run?.outcomes.products).toBe("open_failed");
    const other = setup();
    await other.scheduler.tick();
    other.tabs.failSend = true;
    const tab = other.tabs.current;
    expect(await other.scheduler.onTabReady(tab.id, tab.url)).toBe(true);
    expect((await other.read())?.run?.current?.sentAt).toBeUndefined();
    other.tabs.failSend = false;
    await other.scheduler.onTabReady(tab.id, tab.url);
    expect(other.tabs.sent).toHaveLength(1);
  });

  it("a run left over from a crash is dropped after three hours", async () => {
    const ctx = setup();
    await ctx.scheduler.tick();
    ctx.clock.now += 3 * 3_600_000 + 1;
    expect(await ctx.scheduler.tick()).toBe("expired");
    expect(ctx.tabs.closed).toHaveLength(1);
    expect((await ctx.read())?.run).toBeUndefined();
  });
});

describe("login wall and CAPTCHA: stop and report blocked", () => {
  it("a tab redirected away from Seller Centre (url not visible) is a login wall", async () => {
    const ctx = setup();
    await ctx.scheduler.tick();
    const tab = ctx.tabs.current;
    ctx.tabs.inspection.set(tab.id, { open: true, url: undefined });
    ctx.clock.now += READER_LOAD_GRACE_MS + 1;
    expect(await ctx.scheduler.tick()).toBe("blocked:login");
    const state = await ctx.read();
    expect(state?.blocked).toMatchObject({ reason: "login", page: "products" });
    expect(state?.run).toBeUndefined();
    expect(state?.lastRun?.blocked).toBe("login");
    expect(ctx.tabs.closed).toEqual([tab.id]);
    expect(ctx.tabs.opened).toHaveLength(1); // no other page after a stop
    expect(ctx.alarms.active.has(READER_WATCHDOG_ALARM)).toBe(false);
  });

  it("a sign-in path on Seller Centre itself is a login wall, a verify path a CAPTCHA", async () => {
    const login = setup();
    await login.scheduler.tick();
    expect(await login.scheduler.onTabReady(login.tabs.current.id, `${SC}/account/signin?next=x`)).toBe(true);
    expect((await login.read())?.blocked?.reason).toBe("login");
    const verify = setup();
    await verify.scheduler.tick();
    verify.tabs.inspection.set(verify.tabs.current.id, { open: true, url: `${SC}/verify/traffic` });
    verify.clock.now += READER_LOAD_GRACE_MS + 1;
    expect(await verify.scheduler.tick()).toBe("blocked:captcha");
  });

  it("a CAPTCHA reported by the page stops the run for days, and the seller can lift it", async () => {
    const ctx = setup();
    await ctx.scheduler.tick();
    await finishPage(ctx, "blocked_captcha");
    expect(ctx.posted).toEqual([]);
    expect((await ctx.read())?.blocked).toMatchObject({ reason: "captcha", page: "products" });
    expect(ctx.tabs.opened).toHaveLength(1);
    // tomorrow and the day after: still blocked
    ctx.clock.now += 48 * 3_600_000;
    expect(await ctx.scheduler.tick()).toBe("blocked");
    expect(ctx.tabs.opened).toHaveLength(1);
    // after the cool-down it tries again
    ctx.clock.now += READER_BLOCK_CAPTCHA_MS;
    expect(await ctx.scheduler.tick()).toBe("opened");
  });

  it("'Đồng bộ' lifts the block and retries the same day", async () => {
    const ctx = setup();
    await ctx.scheduler.tick();
    await finishPage(ctx, "blocked_captcha");
    expect(await ctx.scheduler.tick()).toBe("blocked");
    await ctx.scheduler.clearBlock();
    expect(await ctx.scheduler.tick()).toBe("opened");
  });

  it("a data call in a Seller Centre tab ends a login block (not a CAPTCHA block)", async () => {
    const login = setup();
    await login.scheduler.tick();
    await finishPage(login, "blocked_login");
    expect(await login.scheduler.tick()).toBe("blocked");
    await login.scheduler.sessionSeen();
    expect(await login.scheduler.tick()).toBe("opened");
    const captcha = setup();
    await captcha.scheduler.tick();
    await finishPage(captcha, "blocked_captcha");
    await captcha.scheduler.sessionSeen();
    expect(await captcha.scheduler.tick()).toBe("blocked");
  });
});

describe("never reads outside the allowed pages", () => {
  it("only the four listed report pages are ever opened", async () => {
    const ctx = setup();
    const allowed = new Set(["/portal/product/list/all", "/portal/marketing/vouchers/list", "/portal/marketing/pas/index", "/portal/accounthealth"]);
    for (let i = 0; i < 6; i += 1) {
      await ctx.scheduler.tick();
      if ((await ctx.read())?.run?.current) await finishPage(ctx);
      ctx.clock.now += GAP;
    }
    expect(ctx.tabs.opened.length).toBeGreaterThan(0);
    for (const tab of ctx.tabs.opened) expect(allowed.has(new URL(tab.url).pathname)).toBe(true);
    for (const tab of ctx.tabs.opened) expect(tab.url.startsWith(`${SC}/`)).toBe(true);
  });
});

/** Run today's pages to the end, answering every page "done" (ads days per `flags.adsOutcome`). */
async function runDay(ctx: ReturnType<typeof setup>): Promise<void> {
  for (let i = 0; i < 8; i++) {
    const state = await ctx.read();
    if (!state?.run) {
      const started = await ctx.scheduler.tick();
      if (started !== "opened") return;
    }
    const run = (await ctx.read())?.run;
    if (!run) return;
    const job = run.jobs[run.index];
    if (!job) return;
    await finishPage(ctx);
    ctx.clock.now += GAP;
    const next = await ctx.scheduler.tick();
    if (next !== "opened" && !(await ctx.read())?.run) return;
  }
}

describe("P96c: an ads day is read only when its upload landed", () => {
  it("a day whose upload failed or came back empty is planned again tomorrow", async () => {
    const ctx = setup();
    ctx.flags.adsOutcome = { "2026-11-02": "ignored", "2026-11-01": "queued" };
    await runDay(ctx);
    expect((await ctx.read())?.adsPosted).toEqual(["2026-10-31", "2026-10-30"]);
    ctx.clock.now += 24 * 3_600_000;
    ctx.flags.adsOutcome = {};
    await ctx.scheduler.tick();
    // products, vouchers ... until the ads job: its days are the new one plus the two missed
    for (let i = 0; i < 4 && (await ctx.read())?.run?.jobs[(await ctx.read())?.run?.index ?? 0]?.id !== "ads"; i++) {
      await finishPage(ctx);
      ctx.clock.now += GAP;
      await ctx.scheduler.tick();
    }
    expect((await ctx.read())?.run?.jobs.find((j) => j.id === "ads")?.days).toEqual([
      "2026-11-03",
      "2026-11-02",
      "2026-11-01",
    ]);
  });

  it("days the old version marked read (adsDone) are read again", async () => {
    const ctx = setup();
    ctx.storage.data.readers = { adsDone: ["2026-11-02", "2026-11-01", "2026-10-31", "2026-10-30"], trafficDone: [] };
    await ctx.scheduler.tick();
    expect((await ctx.read())?.run?.jobs.find((j) => j.id === "ads")?.days).toEqual([
      "2026-11-02",
      "2026-11-01",
      "2026-10-31",
      "2026-10-30",
    ]);
  });

  it("'Đồng bộ' after today's run reads only the days still missing; nothing missing = done_today", async () => {
    const ctx = setup();
    ctx.flags.adsOutcome = { "2026-11-02": "ignored" };
    await runDay(ctx);
    expect(await ctx.scheduler.tick()).toBe("done_today");
    const opened = ctx.tabs.opened.length;
    ctx.flags.adsOutcome = {};
    expect(await ctx.scheduler.tick({ manual: true })).toBe("opened");
    const run = (await ctx.read())?.run;
    // only the pages with missing days: ads, and item traffic (no items here, so it opens nothing)
    expect(run?.jobs.map((j) => j.id)).toEqual(["ads", "item_traffic"]);
    expect(run?.jobs[0]?.days).toEqual(["2026-11-02"]);
    expect(ctx.tabs.opened.length).toBe(opened + 1);
    await finishPage(ctx);
    ctx.clock.now += GAP;
    await ctx.scheduler.tick();
    expect((await ctx.read())?.adsPosted).toContain("2026-11-02");
    // no ads day missing any more: a further press opens only item traffic (no items, no tab)
    const before = ctx.tabs.opened.length;
    await ctx.scheduler.tick({ manual: true });
    expect(ctx.tabs.opened.length).toBe(before);
  });
});


// -- P97 T1: shop totals, orders, income, the shared request budget and the rate-limit stop -------

const P97_READERS = ["shop_totals", "orders", "order_income"] as const;

function orderCard(id: string, completedSeconds: number) {
  return {
    endpoint: "order_cards",
    url: "u",
    status: 200,
    capturedAt: T0,
    source: "page",
    body: {
      code: 0,
      data: {
        list: [
          {
            order_id: id,
            status: "completed",
            create_time: completedSeconds - 86_400,
            complete_time: completedSeconds,
            items: [{ item_id: 1, quantity: 1, original_price: 10_000, order_price: 10_000 }],
          },
        ],
      },
    },
  };
}

describe("P97: shop totals, order lines and income in the plan", () => {
  const base = { shopId: PILOT, nowMs: T0, stopped: new Set<never>(), adsDone: [] as string[], readers: P97_READERS };

  it("shop totals: 30 finished days before the shop is backfilled, then the last 7, once a day", () => {
    const first = planJobs({ ...base }).find((j) => j.id === "shop_totals");
    expect(first?.days).toHaveLength(30);
    expect(first?.days?.[0]).toBe("2026-11-02");
    const refresh = planJobs({ ...base, totalsBackfilled: true }).find((j) => j.id === "shop_totals");
    expect(refresh?.days).toHaveLength(7);
    expect(planJobs({ ...base, totalsDay: "2026-11-03" }).some((j) => j.id === "shop_totals")).toBe(false);
  });

  it("orders and income once a day, income right after orders (it opens nothing with no order waiting)", () => {
    expect(planJobs({ ...base }).map((j) => j.id)).toEqual(["shop_totals", "orders", "order_income"]);
    expect(planJobs({ ...base, ordersDay: "2026-11-03" }).map((j) => j.id)).toEqual(["shop_totals", "order_income"]);
    expect(planJobs({ ...base, incomeDay: "2026-11-03" }).map((j) => j.id)).toEqual(["shop_totals", "orders"]);
  });
});

describe("P97: the day's flow, income queue and bookkeeping", () => {
  it("totals mark the shop backfilled; orders queue only orders completed since the last run; income reads oldest first, <= 100", async () => {
    const ctx = setup({ readers: P97_READERS });
    await ctx.scheduler.tick();
    await finishPage(ctx); // shop_totals (30 days)
    expect((await ctx.read())?.totalsDay).toBe("2026-11-03");
    expect((await ctx.read())?.totalsBackfilledShop).toBe(PILOT);
    ctx.clock.now += GAP;
    await ctx.scheduler.tick();
    // first run: orders completed in the last 3 days only (never a historical sweep)
    const recent = Math.floor(T0 / 1000) - 3600;
    const old = Math.floor(T0 / 1000) - 10 * 86_400;
    await finishPage(ctx, "done", [orderCard("2611010AAA", recent), orderCard("2610240BBB", old)]);
    expect((await ctx.read())?.incomeQueue?.map((o) => o.id)).toEqual(["2611010AAA"]);
    expect((await ctx.read())?.ordersDay).toBe("2026-11-03");
    ctx.clock.now += GAP;
    await ctx.scheduler.tick();
    expect(ctx.tabs.current.url).toBe(`${SC}/portal/sale/order/2611010AAA`);
    const tab = ctx.tabs.current;
    await ctx.scheduler.onTabReady(tab.id, tab.url);
    expect(ctx.tabs.sent.at(-1)?.message).toMatchObject({ type: "reader-job", job: { id: "order_income", orderIds: ["2611010AAA"] } });
    await ctx.scheduler.onResult(tab.id, { job: "order_income", status: "done", responses: [] });
    expect((await ctx.read())?.incomeQueue).toEqual([]);
    expect((await ctx.read())?.incomeDay).toBe("2026-11-03");
  });

  it("keeps the hook's detail with the outcome (trimmed) and a partial done note", async () => {
    const ctx = setup({ readers: ["shop_totals"] });
    await ctx.scheduler.tick();
    const tab = ctx.tabs.current;
    await ctx.scheduler.onTabReady(tab.id, tab.url);
    await ctx.scheduler.onResult(tab.id, { job: "shop_totals", status: "error", detail: `order_search:http_500${" x".repeat(100)}`, responses: [] });
    const outcome = (await ctx.read())?.lastRun?.outcomes.shop_totals as string;
    expect(outcome.startsWith("error:order_search:http_500")).toBe(true);
    expect(outcome.length).toBeLessThanOrEqual("error:".length + 80);

    const ctx2 = setup({ readers: ["shop_totals"] });
    await ctx2.scheduler.tick();
    const tab2 = ctx2.tabs.current;
    await ctx2.scheduler.onTabReady(tab2.id, tab2.url);
    await ctx2.scheduler.onResult(tab2.id, { job: "shop_totals", status: "done", detail: "partial:order_search:http_500", responses: [] });
    expect(((await ctx2.read())?.lastRun?.outcomes.shop_totals as string).endsWith("|partial:order_search:http_500")).toBe(true);
  });

  it("a day with an unposted totals read is planned again", async () => {
    const ctx = setup({ readers: ["shop_totals"] });
    ctx.flags.totalsOutcome = "drift";
    await ctx.scheduler.tick();
    await finishPage(ctx);
    expect((await ctx.read())?.totalsDay).toBeUndefined();
  });

  it("income takes at most 100 orders, oldest first", async () => {
    const ctx = setup({ readers: ["order_income"] });
    const queue = Array.from({ length: 150 }, (_, i) => ({ id: `26110${String(1000 + i)}`, completedAt: T0 - 1000 + i }));
    ctx.storage.data.readers = { adsDone: [], trafficDone: [], incomeQueue: queue };
    await ctx.scheduler.tick();
    const tab = ctx.tabs.current;
    await ctx.scheduler.onTabReady(tab.id, tab.url);
    const job = (ctx.tabs.sent.at(-1)?.message as { job: { orderIds: string[] } }).job;
    expect(job.orderIds).toHaveLength(100);
    expect(job.orderIds[0]).toBe("261101000");
  });
});

describe("P97: shared daily request budget", () => {
  it("the job is told what is left; replayed requests are counted, page-made answers are not", async () => {
    const ctx = setup({ readers: ["shop_totals"] });
    await ctx.scheduler.tick();
    const tab = ctx.tabs.current;
    await ctx.scheduler.onTabReady(tab.id, tab.url);
    expect(ctx.tabs.sent.at(-1)?.message).toMatchObject({ job: { id: "shop_totals", budget: DAILY_REQUEST_BUDGET - 10 } });
    const replay = (n: number) => Array.from({ length: n }, () => ({ endpoint: "shop_key_metrics", url: "u", status: 200, capturedAt: T0, source: "replay", body: { code: 0, data: {} } }));
    await ctx.scheduler.onResult(tab.id, { job: "shop_totals", status: "done", responses: [...replay(2), { ...replay(1)[0], source: "page" }] });
    expect(((await loadState(ctx.storage as never)).budget)).toEqual({ day: "2026-11-03", used: 12 });
  });

  it("when the budget is spent no page is opened and the remaining jobs wait for tomorrow", async () => {
    const ctx = setup({ readers: ["shop_totals", "orders"] });
    ctx.storage.data.budget = { day: "2026-11-03", used: DAILY_REQUEST_BUDGET - 5 };
    expect(await ctx.scheduler.tick()).toBe("budget_spent");
    expect(ctx.tabs.opened).toHaveLength(0);
    expect((await ctx.read())?.lastRun?.outcomes).toEqual({ shop_totals: "waiting_budget", orders: "waiting_budget" });
    // the next GMT+7 day starts with a fresh budget
    ctx.clock.now += 24 * 3_600_000;
    expect(await ctx.scheduler.tick()).toBe("opened");
  });

  it("a job that runs the budget dry (budget_spent from the page) closes the tab and the rest waits", async () => {
    const ctx = setup({ readers: ["shop_totals", "orders"] });
    await ctx.scheduler.tick();
    const tab = ctx.tabs.current;
    await ctx.scheduler.onTabReady(tab.id, tab.url);
    await ctx.scheduler.onResult(tab.id, { job: "shop_totals", status: "budget_spent", responses: [] });
    expect(ctx.tabs.closed).toContain(tab.id);
    expect((await ctx.read())?.run).toBeUndefined();
    expect((await ctx.read())?.lastRun?.outcomes).toMatchObject({ shop_totals: "waiting_budget", orders: "waiting_budget" });
  });
});

describe("P97: a rate-limit stop halts every reader and is told to Juli", () => {
  it("blocked_rate: the run stops, the block is rate_limit for the CAPTCHA cool-down, one event is posted", async () => {
    const ctx = setup({ readers: ["shop_totals", "orders"] });
    await ctx.scheduler.tick();
    const tab = ctx.tabs.current;
    await ctx.scheduler.onTabReady(tab.id, tab.url);
    await ctx.scheduler.onResult(tab.id, { job: "shop_totals", status: "blocked_rate", detail: "http_429", responses: [] } as never);
    const sched = await ctx.read();
    expect(sched?.blocked).toMatchObject({ reason: "rate_limit", page: "shop_totals", until: T0 + READER_BLOCK_CAPTCHA_MS });
    expect(sched?.run).toBeUndefined();
    expect(ctx.events).toEqual([
      { reader: "shop_totals", page: "/datacenter/overview", status: "rate_limit", code: "http_429", at: new Date(T0).toISOString() },
    ]);
    ctx.clock.now += GAP;
    expect(await ctx.scheduler.tick()).toBe("blocked");
    expect(ctx.tabs.opened).toHaveLength(1);
  });

  it("'Đồng bộ' lifts a CAPTCHA block but not a rate-limit block", async () => {
    const ctx = setup({ readers: ["shop_totals"] });
    await saveState(ctx.storage as never, { readers: { adsDone: [], trafficDone: [], blocked: { at: "x", reason: "rate_limit", page: "orders", until: T0 + 1000 } } });
    await ctx.scheduler.clearBlock();
    expect((await ctx.read())?.blocked?.reason).toBe("rate_limit");
    await saveState(ctx.storage as never, { readers: { adsDone: [], trafficDone: [], blocked: { at: "x", reason: "captcha", page: "orders", until: T0 + 1000 } } });
    await ctx.scheduler.clearBlock();
    expect((await ctx.read())?.blocked).toBeUndefined();
  });

  it("CAPTCHA and login walls are told to Juli too", async () => {
    const ctx = setup({ readers: ["shop_totals"] });
    await ctx.scheduler.tick();
    const tab = ctx.tabs.current;
    await ctx.scheduler.onTabReady(tab.id, tab.url);
    await ctx.scheduler.onResult(tab.id, { job: "shop_totals", status: "blocked_captcha", responses: [] });
    expect(ctx.events.map((e) => e.status)).toEqual(["captcha"]);
  });

  it("a failed event post never changes the stop", async () => {
    const ctx = setup({ readers: ["shop_totals"] });
    (ctx.scheduler as unknown as { deps: { sink: { reportBlock: () => Promise<void> } } }).deps.sink.reportBlock = async () => {
      throw new Error("offline");
    };
    await ctx.scheduler.tick();
    const tab = ctx.tabs.current;
    await ctx.scheduler.onTabReady(tab.id, tab.url);
    await ctx.scheduler.onResult(tab.id, { job: "shop_totals", status: "blocked_rate", responses: [] });
    expect((await ctx.read())?.blocked?.reason).toBe("rate_limit");
  });
});

describe("P97: an empty income queue opens no page", () => {
  it("the income job is skipped with no_orders", async () => {
    const ctx = setup({ readers: ["order_income"] });
    expect(await ctx.scheduler.tick()).toBe("finished");
    expect(ctx.tabs.opened).toHaveLength(0);
    expect((await ctx.read())?.lastRun?.outcomes).toEqual({ order_income: "no_orders" });
  });
});

describe("0.3.15: the orders reader keeps its tab until the page answers", () => {
  const ordersReply = { endpoint: "order_list", url: "u", status: 200, capturedAt: T0, source: "page", body: { code: 0, data: {} } };

  it("a tab closed before the page answered is opened once more, and the answer is posted", async () => {
    const ctx = setup({ readers: ["orders"] });
    await ctx.scheduler.tick();
    const first = ctx.tabs.current;
    await ctx.scheduler.onTabReady(first.id, first.url);
    await ctx.scheduler.onTabRemoved(first.id); // Chrome / the seller closed it
    expect(ctx.tabs.opened).toHaveLength(2);
    const second = ctx.tabs.current;
    expect(second.id).not.toBe(first.id);
    expect((await ctx.read())?.run?.current).toMatchObject({ tabId: second.id, reopened: true });
    expect((await ctx.read())?.run?.current?.sentAt).toBeUndefined();
    await ctx.scheduler.onTabReady(second.id, second.url);
    expect(ctx.tabs.sent.at(-1)).toMatchObject({ tabId: second.id, message: { job: { id: "orders" } } });
    await ctx.scheduler.onResult(second.id, { job: "orders", status: "done", responses: [ordersReply] });
    expect(ctx.posted.map((p) => p.job.id)).toEqual(["orders"]);
    expect((await ctx.read())?.lastRun?.outcomes.orders).toMatch(/^done/);
  });

  it("a tab Chrome discarded after the job was sent is replaced the same way", async () => {
    const ctx = setup({ readers: ["orders"] });
    await ctx.scheduler.tick();
    const first = ctx.tabs.current;
    await ctx.scheduler.onTabReady(first.id, first.url);
    ctx.tabs.inspection.set(first.id, { open: true, url: first.url, discarded: true } as never);
    ctx.clock.now += 5_000;
    expect(await ctx.scheduler.tick()).toBe("reopened");
    expect(ctx.tabs.closed).toContain(first.id);
    expect(ctx.tabs.opened).toHaveLength(2);
  });

  it("closed twice: the outcome is closed and nothing is posted", async () => {
    const ctx = setup({ readers: ["orders"] });
    await ctx.scheduler.tick();
    const first = ctx.tabs.current;
    await ctx.scheduler.onTabRemoved(first.id);
    const second = ctx.tabs.current;
    await ctx.scheduler.onTabRemoved(second.id);
    expect(ctx.tabs.opened).toHaveLength(2);
    expect(ctx.posted).toEqual([]);
    expect((await ctx.read())?.lastRun?.outcomes.orders).toBe("closed");
  });

  it("other readers are not re-opened when their tab is closed", async () => {
    const ctx = setup();
    await ctx.scheduler.tick();
    await ctx.scheduler.onTabRemoved(ctx.tabs.current.id);
    expect(ctx.tabs.opened).toHaveLength(1);
    expect((await ctx.read())?.run?.outcomes.products).toBe("closed");
  });
});

describe("0.3.15: today's readers and the backfill share the daily budget", () => {
  it("while a backfill runs, the readers leave its share alone", async () => {
    const ctx = setup({ readers: ["orders"] });
    ctx.storage.data.backfill = { shopId: PILOT, createdAt: "x", days: ["2026-11-02"], done: [], accepted: {}, attempts: {}, status: "running" };
    ctx.storage.data.budget = { day: "2026-11-03", used: DAILY_REQUEST_BUDGET - BACKFILL_REQUEST_SHARE - 5 };
    expect(await ctx.scheduler.tick()).toBe("budget_spent");
    expect(ctx.tabs.opened).toHaveLength(0);
  });

  it("without a running backfill the readers may use the whole budget", async () => {
    const ctx = setup({ readers: ["orders"] });
    ctx.storage.data.budget = { day: "2026-11-03", used: DAILY_REQUEST_BUDGET - BACKFILL_REQUEST_SHARE - 5 };
    expect(await ctx.scheduler.tick()).toBe("opened");
  });
});

describe("0.3.19: the 06:30 stock read", () => {
  // 2026-11-03 06:00 GMT+7 = 2026-11-02 23:00 UTC
  const BEFORE = Date.UTC(2026, 10, 2, 23, 0, 0);
  const snapshotPosted = { item_snapshot: "posted", item_catalog: "posted" };

  function stockSetup(readers: readonly ReaderId[] = ["products", "vouchers"]) {
    const ctx = setup({ readers, stockRun: true });
    ctx.clock.now = BEFORE;
    return ctx;
  }

  it("the alarm time is the next 06:30 GMT+7", () => {
    expect(new Date(nextStockAt(BEFORE)).toISOString()).toBe("2026-11-02T23:30:00.000Z");
    expect(new Date(nextStockAt(Date.UTC(2026, 10, 2, 23, 30, 0))).toISOString()).toBe("2026-11-03T23:30:00.000Z");
    expect(new Date(stockDueAt("2026-11-03")).toISOString()).toBe("2026-11-02T23:30:00.000Z");
  });

  it("from 06:30 a run of ONLY the product list goes first; the daily run follows, without the list again", async () => {
    const ctx = stockSetup();
    // before 06:30: the daily run (no stock run yet)
    expect(await ctx.scheduler.due()).toBe(true);
    ctx.clock.now = BEFORE + 31 * 60_000; // 06:31
    expect(await ctx.scheduler.tick({ trigger: "stock_alarm" })).toBe("stock:opened");
    expect(ctx.tabs.current.url).toBe(`${SC}/portal/product/list/all`);
    const run = (await ctx.read())?.run;
    expect(run?.kind).toBe("stock");
    expect(run?.jobs.map((j) => j.id)).toEqual(["products"]);
    const tab = ctx.tabs.current;
    await ctx.scheduler.onTabReady(tab.id, tab.url);
    const sink = ctx.posted;
    // the sink of this harness answers { products: "posted" }: make the snapshot land
    (ctx.scheduler as unknown as { deps: { sink: { postReader: unknown } } }).deps.sink.postReader = async (job: ReaderJob, responses: ReaderResponse[]) => {
      sink.push({ job, responses });
      return snapshotPosted;
    };
    await ctx.scheduler.onResult(tab.id, { job: "products", status: "done", responses: [productList(["11", "12"], 1)] });
    const after = await ctx.read();
    expect(after?.run).toBeUndefined();
    expect(after?.stock).toMatchObject({ day: "2026-11-03", attempts: 1, outcome: "done:item_snapshot=posted,item_catalog=posted" });
    expect(after?.productsAt).toBe(ctx.clock.now);
    // the daily run is not marked done by the stock run; it is kicked a minute later
    expect(after?.lastRunDay).toBeUndefined();
    expect(ctx.alarms.active.get(READER_KICK_ALARM)).toEqual({ delayInMinutes: 1 });
    expect(after?.kick?.reason).toBe("after_stock");
    ctx.clock.now += GAP;
    expect(await ctx.scheduler.tick({ trigger: "kick" })).toBe("opened");
    expect((await ctx.read())?.run?.jobs.map((j) => j.id)).toEqual(["vouchers"]);
    expect((await ctx.read())?.lastTick).toMatchObject({ trigger: "after_stock", result: "opened" });
  });

  it("uses the whole daily budget (not only the readers' part while a backfill runs)", async () => {
    const ctx = stockSetup();
    ctx.clock.now = BEFORE + 40 * 60_000;
    ctx.storage.data.backfill = { shopId: PILOT, createdAt: "x", days: ["2026-11-02"], done: [], accepted: {}, attempts: {}, status: "running" };
    ctx.storage.data.budget = { day: "2026-11-03", used: DAILY_REQUEST_BUDGET - BACKFILL_REQUEST_SHARE - 5 };
    expect(await ctx.scheduler.tick()).toBe("stock:opened");
    const tab = ctx.tabs.current;
    await ctx.scheduler.onTabReady(tab.id, tab.url);
    expect(ctx.tabs.sent.at(-1)?.message).toMatchObject({ job: { id: "products", budget: BACKFILL_REQUEST_SHARE + 5 - 10 } });
  });

  it("Chrome closed at 06:30: the next start finds it due; two failed tries a day at most", async () => {
    const ctx = stockSetup(["products"]);
    ctx.clock.now = BEFORE + 3 * 3_600_000; // 09:00
    ctx.storage.data.readers = { adsDone: [], trafficDone: [], lastRunDay: "2026-11-03" };
    expect(await ctx.scheduler.due()).toBe(true);
    for (let attempt = 1; attempt <= 2; attempt += 1) {
      expect(await ctx.scheduler.tick({ trigger: "kick" })).toBe("stock:opened");
      const tab = ctx.tabs.current;
      await ctx.scheduler.onTabReady(tab.id, tab.url);
      await ctx.scheduler.onResult(tab.id, { job: "products", status: "needs_data_page" });
      expect((await ctx.read())?.stock).toMatchObject({ attempts: attempt, outcome: "needs_data_page" });
    }
    expect(await ctx.scheduler.due()).toBe(false);
    expect(await ctx.scheduler.tick()).toBe("done_today");
  });
});

describe("0.3.19: ticks are recorded, retried and told to Juli", () => {
  function reporting(options: Parameters<typeof setup>[0] = {}) {
    const ctx = setup(options);
    const reports: TickReport[] = [];
    (ctx.scheduler as unknown as { deps: { sink: { reportTick: unknown } } }).deps.sink.reportTick = async (report: TickReport) => {
      reports.push(report);
    };
    return { ...ctx, reports };
  }

  it("every tick from rest is kept with its trigger and result; a skip is told to Juli once a day", async () => {
    const ctx = reporting({ backfillBusy: true });
    expect(await ctx.scheduler.tick({ trigger: "daily_alarm" })).toBe("backfill_busy");
    expect(await ctx.scheduler.tick({ trigger: "kick" })).toBe("backfill_busy");
    const sched = await ctx.read();
    expect(sched?.tickLog?.map((t) => [t.trigger, t.result])).toEqual([
      ["daily_alarm", "backfill_busy"],
      ["retry", "backfill_busy"],
    ]);
    // a busy backfill no longer means "wait for tomorrow": a one-off start in 5 minutes
    expect(ctx.alarms.active.get(READER_KICK_ALARM)).toEqual({ delayInMinutes: 5 });
    expect(ctx.reports.map((r) => [r.kind, r.result])).toEqual([["skip", "backfill_busy"]]);
  });

  it("a finished run is told to Juli with each page's outcome", async () => {
    const ctx = reporting({ readers: ["vouchers"] });
    await ctx.scheduler.tick({ trigger: "pair" });
    await finishPage(ctx);
    expect(ctx.reports).toEqual([
      { kind: "run", trigger: "daily", result: "finished", day: "2026-11-03", at: expect.any(String), outcomes: { vouchers: "done:vouchers=posted" } },
    ]);
  });

  it("pairing asks for a start a minute later, and says why", async () => {
    const ctx = setup();
    await ctx.scheduler.requestKick("pair");
    expect(ctx.alarms.active.get(READER_KICK_ALARM)).toEqual({ delayInMinutes: 1 });
    expect(await ctx.scheduler.tick({ trigger: "kick" })).toBe("opened");
    expect((await ctx.read())?.lastTick).toMatchObject({ trigger: "pair", result: "opened" });
    expect((await ctx.read())?.kick).toBeUndefined();
  });

  it("due(): paired and today's run not done; never without a pairing", async () => {
    const ctx = setup();
    expect(await ctx.scheduler.due()).toBe(true);
    delete ctx.storage.data.token;
    expect(await ctx.scheduler.due()).toBe(false);
    expect(await ctx.scheduler.tick()).toBe("unpaired");
    expect(ctx.tabs.opened).toHaveLength(0);
  });
});

describe("0.3.19: the traffic page and the orders catch-up in the plan", () => {
  const base = { shopId: PILOT, nowMs: T0, stopped: new Set<never>(), adsDone: [] as string[] };

  it("traffic: yesterday and up to three earlier days not posted yet", () => {
    expect(planJobs({ ...base, readers: ["traffic"] })).toEqual([
      { id: "traffic", days: ["2026-11-02", "2026-11-01", "2026-10-31", "2026-10-30"] },
    ]);
    expect(planJobs({ ...base, readers: ["traffic"], trafficOverviewDone: ["2026-11-02", "2026-11-01", "2026-10-31"] })).toEqual([
      { id: "traffic", days: ["2026-10-30"] },
    ]);
    expect(planJobs({ ...base, readers: ["traffic"], trafficOverviewDone: ["2026-11-02", "2026-11-01", "2026-10-31", "2026-10-30"] })).toEqual([]);
  });

  it("orders read back 14 days the first time, then from the last complete read minus 3 days, at most 30", () => {
    expect(ordersSinceDay("2026-11-03", undefined)).toBe("2026-10-20");
    expect(ordersSinceDay("2026-11-03", "2026-11-02")).toBe("2026-10-30");
    expect(ordersSinceDay("2026-11-03", "2026-09-01")).toBe("2026-10-04");
    expect(planJobs({ ...base, readers: ["orders"], ordersCoveredDay: "2026-11-02" })).toEqual([{ id: "orders", sinceDay: "2026-10-30" }]);
  });

  it("the product list is not read again when today's stock read already has it", () => {
    expect(planJobs({ ...base, readers: ["products", "vouchers"], productsFresh: true }).map((j) => j.id)).toEqual(["vouchers"]);
  });

  it("the traffic job opens Truy cập, carries its days, and a posted confirmed day is not read again", async () => {
    const ctx = setup({ readers: ["traffic"] });
    (ctx.scheduler as unknown as { deps: { sink: { postReader: unknown } } }).deps.sink.postReader = async (job: ReaderJob) => ({
      "traffic_overview:2026-11-02:confirmed": "posted",
      "traffic_overview:2026-11-02:placed": "posted",
      "shop_traffic:2026-11-02": "posted",
      "traffic_overview:2026-11-01:confirmed": "ignored",
      job: job.id,
    });
    expect(await ctx.scheduler.tick()).toBe("opened");
    expect(ctx.tabs.current.url).toBe(`${SC}/datacenter/traffic/overview`);
    const tab = ctx.tabs.current;
    await ctx.scheduler.onTabReady(tab.id, tab.url);
    expect(ctx.tabs.sent.at(-1)?.message).toMatchObject({ job: { id: "traffic", days: ["2026-11-02", "2026-11-01", "2026-10-31", "2026-10-30"] } });
    await ctx.scheduler.onResult(tab.id, { job: "traffic", status: "done", responses: [] });
    expect((await ctx.read())?.trafficOverviewDone).toEqual(["2026-11-02"]);
  });

  it("orders: a complete by-date read moves the start forward; a page-cap read does not", async () => {
    const ctx = setup({ readers: ["orders"] });
    (ctx.scheduler as unknown as { deps: { sink: { postReader: unknown } } }).deps.sink.postReader = async () => ({ order_lines: "posted" });
    await ctx.scheduler.tick();
    let tab = ctx.tabs.current;
    await ctx.scheduler.onTabReady(tab.id, tab.url);
    expect(ctx.tabs.sent.at(-1)?.message).toMatchObject({ job: { id: "orders", sinceDay: "2026-10-20" } });
    await ctx.scheduler.onResult(tab.id, { job: "orders", status: "done", detail: "partial:page_cap", responses: [] });
    expect((await ctx.read())?.ordersCoveredDay).toBeUndefined();
    ctx.clock.now += 24 * 3_600_000;
    await ctx.scheduler.tick();
    tab = ctx.tabs.current;
    await ctx.scheduler.onTabReady(tab.id, tab.url);
    await ctx.scheduler.onResult(tab.id, { job: "orders", status: "done", responses: [] });
    expect((await ctx.read())?.ordersCoveredDay).toBe("2026-11-04");
  });

  it("the orders job gets the long timeout (it pages for up to ~30 minutes)", async () => {
    const ctx = setup({ readers: ["orders", "vouchers"] });
    await ctx.scheduler.tick();
    const tab = ctx.tabs.current;
    await ctx.scheduler.onTabReady(tab.id, tab.url);
    ctx.clock.now += READER_JOB_TIMEOUT_MS + 1;
    expect(await ctx.scheduler.tick()).toBe("waiting");
    ctx.clock.now += ORDERS_JOB_TIMEOUT_MS;
    expect(await ctx.scheduler.tick()).toBe("timeout");
  });
});

describe("0.3.19: the 90-day ads history", () => {
  const history = (days: string[]) => days.map((day) => ({ ...(adsReplies([day])[0] as object), day }));
  const refused = (day: string) => ({ endpoint: "ads_homepage", url: "u", status: 200, capturedAt: T0, source: "replay", day, page: 1, body: { code: 10006, msg: "err:invalid param" } });

  async function adsJob(ctx: ReturnType<typeof setup>) {
    expect(await ctx.scheduler.tick()).toBe("opened");
    const tab = ctx.tabs.current;
    await ctx.scheduler.onTabReady(tab.id, tab.url);
    return { tab, job: (ctx.tabs.sent.at(-1)?.message as { job: { days: string[]; historyDays?: string[]; budget: number } }).job };
  }

  it("plans the 90 finished days before today's, newest first, 10 a run after the regular days", async () => {
    const ctx = setup({ readers: ["ads"] });
    const { job } = await adsJob(ctx);
    expect(job.days).toEqual(["2026-11-02", "2026-11-01", "2026-10-31", "2026-10-30"]);
    expect(job.historyDays).toEqual(["2026-10-29", "2026-10-28", "2026-10-27", "2026-10-26", "2026-10-25", "2026-10-24", "2026-10-23", "2026-10-22", "2026-10-21", "2026-10-20"]);
    const plan = (await ctx.read())?.adsHistory;
    expect(plan).toMatchObject({ shopId: PILOT, status: "running", done: [] });
    expect(plan?.days).toHaveLength(90);
    expect(plan?.days[0]).toBe("2026-11-02");
    expect(plan?.days[89]).toBe("2026-08-05");
  });

  it("is resumable: read days are done, the next run takes the next ten, a day that did not post stays", async () => {
    const ctx = setup({ readers: ["ads"] });
    const { tab, job } = await adsJob(ctx);
    const readNow = (job.historyDays ?? []).filter((d) => d !== "2026-10-25");
    await ctx.scheduler.onResult(tab.id, { job: "ads", status: "done", responses: [...adsReplies(job.days), ...history(readNow)] });
    const after = (await ctx.read())?.adsHistory;
    expect(after?.done).toHaveLength(4 + 9);
    expect(after?.done).not.toContain("2026-10-25");
    expect(after?.earliest).toBe("2026-10-20");
    ctx.clock.now += 24 * 3_600_000;
    const next = await adsJob(ctx);
    expect(next.job.historyDays?.[0]).toBe("2026-10-25");
    expect(next.job.historyDays).toHaveLength(10);
  });

  it("stays inside the backfill's part of the budget: nothing when only today's reserve is left", async () => {
    const ctx = setup({ readers: ["ads"] });
    ctx.storage.data.budget = { day: "2026-11-03", used: DAILY_REQUEST_BUDGET - TODAY_REQUEST_RESERVE - 2 * ADS_HISTORY_DAY_COST };
    const { job } = await adsJob(ctx);
    expect(job.historyDays).toHaveLength(2);
    const spent = setup({ readers: ["ads"] });
    spent.storage.data.budget = { day: "2026-11-03", used: DAILY_REQUEST_BUDGET - TODAY_REQUEST_RESERVE };
    expect((await adsJob(spent)).job.historyDays).toBeUndefined();
  });

  it("the first day Shopee refuses ends it: that limit and the earliest day read are kept, older days never asked", async () => {
    const ctx = setup({ readers: ["ads"] });
    const { tab, job } = await adsJob(ctx);
    const [d1, d2, d3] = job.historyDays ?? [];
    await ctx.scheduler.onResult(tab.id, { job: "ads", status: "done", responses: [...adsReplies(job.days), ...history([d1!, d2!]), refused(d3!)] });
    const after = (await ctx.read())?.adsHistory;
    expect(after).toMatchObject({ status: "done", earliest: d2, limit: { day: d3, code: "code_10006" } });
    ctx.clock.now += 24 * 3_600_000;
    const next = await adsJob(ctx);
    expect(next.job.historyDays).toBeUndefined();
    expect(next.job.days).toEqual(["2026-11-03"]);
  });

  it("done for the shop once every planned day is read; a new shop starts its own", async () => {
    const ctx = setup({ readers: ["ads"] });
    const days = lastFinishedDays(T0, 90);
    ctx.storage.data.readers = { adsDone: [], trafficDone: [], adsHistory: { shopId: PILOT, createdAt: "x", days, done: days.slice(0, 89), status: "running" } };
    const { tab, job } = await adsJob(ctx);
    expect(job.historyDays).toEqual([days[89]]);
    await ctx.scheduler.onResult(tab.id, { job: "ads", status: "done", responses: [...adsReplies(job.days), ...history([days[89]!])] });
    expect((await ctx.read())?.adsHistory).toMatchObject({ status: "done", earliest: days[89] });
    expect((await ctx.read())?.adsHistory?.limit).toBeUndefined();
  });
});

describe("0.3.20: the ads page gets a longer wait and one reload", () => {
  it("waits twice the general cap, reloads once without the history days, then gives up", async () => {
    const ctx = setup({ readers: ["ads"] });
    expect(await ctx.scheduler.tick()).toBe("opened");
    const first = ctx.tabs.current;
    await ctx.scheduler.onTabReady(first.id, first.url);
    const planned = (ctx.tabs.sent.at(-1)?.message as { job: { historyDays?: string[] } }).job;
    expect(planned.historyDays?.length).toBeGreaterThan(0);
    ctx.clock.now += READER_JOB_TIMEOUT_MS + 1;
    expect(await ctx.scheduler.tick()).toBe("waiting"); // past the general cap: the ads page still loads
    const usedBefore = (ctx.storage.data.budget as { used: number }).used;
    ctx.clock.now += ADS_JOB_TIMEOUT_MS;
    expect(await ctx.scheduler.tick()).toBe("reopened");
    expect(ctx.tabs.closed).toContain(first.id);
    // the first tab's unreported requests are charged (budget kept), plus the new page load
    expect((ctx.storage.data.budget as { used: number }).used).toBeGreaterThan(usedBefore);
    const second = ctx.tabs.current;
    expect(second.id).not.toBe(first.id);
    await ctx.scheduler.onTabReady(second.id, second.url);
    const retry = (ctx.tabs.sent.at(-1)?.message as { job: { id: string; days: string[]; historyDays?: string[] } }).job;
    expect(retry.id).toBe("ads");
    expect(retry.days.length).toBeGreaterThan(0);
    expect(retry.historyDays).toBeUndefined();
    ctx.clock.now += ADS_JOB_TIMEOUT_MS + 1;
    expect(await ctx.scheduler.tick()).toBe("finished");
    expect((await ctx.read())?.lastRun?.outcomes.ads).toBe("timeout");
    expect(ctx.tabs.opened).toHaveLength(2);
  });

  it("the reloaded page's answer is posted like any other", async () => {
    const ctx = setup({ readers: ["ads"] });
    await ctx.scheduler.tick();
    await ctx.scheduler.onTabReady(ctx.tabs.current.id, ctx.tabs.current.url);
    ctx.clock.now += ADS_JOB_TIMEOUT_MS + 1;
    expect(await ctx.scheduler.tick()).toBe("reopened");
    const second = ctx.tabs.current;
    await ctx.scheduler.onTabReady(second.id, second.url);
    const retry = (ctx.tabs.sent.at(-1)?.message as { job: { days: string[] } }).job;
    await ctx.scheduler.onResult(second.id, { job: "ads", status: "done", responses: adsReplies(retry.days) });
    expect((await ctx.read())?.lastRun?.outcomes.ads).toMatch(/^done:/);
  });
});

describe("0.3.20: the orders outcome is truthful", () => {
  it("a list read that produced no order line is an error, and a page with no orders is no_orders", async () => {
    const ctx = setup({ readers: ["orders"] });
    (ctx.scheduler as unknown as { deps: { sink: { postReader: unknown } } }).deps.sink.postReader = async () => ({ order_lines: "ignored" });
    await ctx.scheduler.tick();
    const tab = ctx.tabs.current;
    await ctx.scheduler.onTabReady(tab.id, tab.url);
    await ctx.scheduler.onResult(tab.id, { job: "orders", status: "done", responses: [] });
    // 0.3.26: the step is named (nothing came back from the list page)
    expect((await ctx.read())?.lastRun?.outcomes.orders).toBe("error:orders:0_rows:no_list_answer");

    const empty = setup({ readers: ["orders"] });
    (empty.scheduler as unknown as { deps: { sink: { postReader: unknown } } }).deps.sink.postReader = async () => ({ order_lines: "ignored" });
    await empty.scheduler.tick();
    const t2 = empty.tabs.current;
    await empty.scheduler.onTabReady(t2.id, t2.url);
    await empty.scheduler.onResult(t2.id, { job: "orders", status: "done", detail: "no_new_orders", responses: [] });
    // 0.3.26: a day with no order is read and empty ("no_orders" stays the income page's outcome)
    expect((await empty.read())?.lastRun?.outcomes.orders).toBe("done:order_lines=empty");
    expect((await empty.read())?.ordersCoveredDay).toBe("2026-11-03");
  });

  it("0.3.26: an income page without the Tài chính right is blocked:no_permission; the run goes on, the queue is kept", async () => {
    const ctx = setup({ readers: ["order_income", "vouchers"] });
    const queue = [{ id: "26110777", completedAt: T0 - 1000 }];
    ctx.storage.data.readers = { adsDone: [], trafficDone: [], incomeQueue: queue };
    await ctx.scheduler.tick();
    const tab = ctx.tabs.current;
    await ctx.scheduler.onTabReady(tab.id, tab.url);
    await ctx.scheduler.onResult(tab.id, { job: "order_income", status: "blocked_no_permission", detail: "http_403_code_10013", responses: [] });
    const after = await ctx.read();
    expect(after?.run?.outcomes.order_income).toBe("blocked:no_permission|http_403_code_10013");
    expect(after?.run?.index).toBe(1);
    expect(after?.blocked).toBeUndefined();
    expect(after?.incomeQueue).toEqual(queue);
    expect(after?.incomeDay).toBeUndefined();
  });
});

describe("0.3.22: a login wall on one reader blocks that reader, not the run", () => {
  /** Drive the run to its end: each page answers with `answers[id]` (default "done"). */
  async function driveRun(ctx: ReturnType<typeof setup>, answers: Partial<Record<ReaderId, string>>): Promise<string> {
    const ticks: TickReport[] = [];
    (ctx.scheduler as unknown as { deps: { sink: { reportTick: unknown } } }).deps.sink.reportTick = async (report: TickReport) => {
      ticks.push(report);
    };
    let result = await ctx.scheduler.tick();
    for (let i = 0; i < 20 && (await ctx.read())?.run; i += 1) {
      const run = (await ctx.read())?.run;
      if (run?.current) {
        const id = run.jobs[run.index]?.id as ReaderId;
        const status = answers[id] ?? "done";
        await finishPage(ctx, status);
      }
      ctx.clock.now += GAP;
      result = await ctx.scheduler.tick();
    }
    (ctx as unknown as { ticks: TickReport[] }).ticks = ticks;
    return result;
  }
  const ticksOf = (ctx: ReturnType<typeof setup>) => (ctx as unknown as { ticks: TickReport[] }).ticks;

  it("a Phân tích bán hàng login wall after portal pages read: the run goes on; a second blocks the section", async () => {
    const ctx = setup({ readers: ["products", "orders", "shop_totals", "traffic", "product_period", "health"] });
    await driveRun(ctx, { shop_totals: "blocked_login", traffic: "blocked_login" });
    const state = await ctx.read();
    expect(state?.blocked).toBeUndefined();
    expect(state?.lastRun?.blocked).toBeUndefined();
    expect(state?.lastRun?.outcomes).toMatchObject({
      orders: expect.stringMatching(/^done/),
      shop_totals: "blocked:login",
      traffic: "blocked:login",
      product_period: "blocked:login",
      health: expect.stringMatching(/^done/),
    });
    // product_period was never opened (two walls in /datacenter); health (portal) was.
    const paths = ctx.tabs.opened.map((t) => new URL(t.url).pathname);
    expect(paths).not.toContain("/datacenter/product/performance");
    expect(paths).toContain("/portal/accounthealth");
    expect(ctx.posted.map((p) => p.job.id)).toEqual(["products", "orders", "health"]);
    // The run report Juli gets carries each blocked reader.
    const run = ticksOf(ctx).find((t) => t.kind === "run");
    expect(run?.result).toBe("finished");
    expect(run?.outcomes).toMatchObject({ shop_totals: "blocked:login", traffic: "blocked:login", product_period: "blocked:login" });
    expect(ctx.events.map((e) => [e.reader, e.status, e.code])).toEqual([
      ["shop_totals", "login", "reader_only"],
      ["traffic", "login", "reader_only"],
    ]);
  });

  it("a read in the section between two walls starts its count again", async () => {
    const ctx = setup({ readers: ["products", "shop_totals", "traffic", "product_period", "item_traffic"] });
    await saveState(ctx.storage, { readers: { adsDone: [], trafficDone: [], itemIds: ["11"] } });
    await driveRun(ctx, { shop_totals: "blocked_login", product_period: "blocked_login" });
    expect((await ctx.read())?.lastRun?.outcomes).toMatchObject({
      shop_totals: "blocked:login",
      traffic: expect.stringMatching(/^done/),
      product_period: "blocked:login",
      item_traffic: expect.stringMatching(/^done/),
    });
  });

  it("a wall on the run's first page is a session-wide logout: the run stops after one tab, as before", async () => {
    const ctx = setup({ readers: ["products", "orders", "shop_totals", "health"] });
    const result = await driveRun(ctx, { products: "blocked_login" });
    expect(result).toBe("blocked");
    const state = await ctx.read();
    expect(state?.blocked).toMatchObject({ reason: "login", page: "products" });
    expect(state?.lastRun?.blocked).toBe("login");
    expect(ctx.tabs.opened).toHaveLength(1);
    expect(ticksOf(ctx).find((t) => t.kind === "run")?.result).toBe("blocked:login");
  });

  it("walls in both sections are a session-wide logout: the rest of the run is not opened", async () => {
    const ctx = setup({ readers: ["products", "shop_totals", "orders", "health"] });
    await driveRun(ctx, { shop_totals: "blocked_login", orders: "blocked_login" });
    const state = await ctx.read();
    expect(state?.blocked).toMatchObject({ reason: "login", page: "orders" });
    expect(state?.lastRun?.outcomes).toMatchObject({ shop_totals: "blocked:login", orders: "blocked_login" });
    expect(state?.lastRun?.outcomes.health).toBeUndefined();
    expect(ctx.tabs.opened).toHaveLength(3);
  });

  it("a tab sent off Seller Centre is a session-wide logout even after a page read", async () => {
    const ctx = setup({ readers: ["products", "shop_totals", "health"] });
    await ctx.scheduler.tick();
    await finishPage(ctx);
    ctx.clock.now += GAP;
    await ctx.scheduler.tick();
    const tab = ctx.tabs.current;
    ctx.tabs.inspection.set(tab.id, { open: true, url: undefined });
    ctx.clock.now += READER_LOAD_GRACE_MS + 1;
    expect(await ctx.scheduler.tick()).toBe("blocked:login");
    expect(ctx.tabs.opened).toHaveLength(2);
  });

  it("a CAPTCHA on one Phân tích bán hàng page blocks that page only", async () => {
    const ctx = setup({ readers: ["products", "shop_totals", "health"] });
    await driveRun(ctx, { shop_totals: "blocked_captcha" });
    const state = await ctx.read();
    expect(state?.blocked).toBeUndefined();
    expect(state?.lastRun?.outcomes).toMatchObject({ shop_totals: "blocked:captcha", health: expect.stringMatching(/^done/) });
  });

  it("job order: orders and order_income run before every /datacenter reader", () => {
    const ids = planJobs({ shopId: PILOT, nowMs: T0, stopped: new Set<never>(), adsDone: [] }).map((j) => j.id);
    const at = (id: ReaderId) => ids.indexOf(id);
    expect(at("order_income")).toBe(at("orders") + 1);
    for (const id of ["shop_totals", "traffic", "product_period", "item_traffic"] as const) {
      expect(at("orders")).toBeLessThan(at(id));
      expect(at("order_income")).toBeLessThan(at(id));
    }
  });
});

describe("0.3.25: the password re-check dialog is its own block reason, and its pages are read again", () => {
  const READERS = ["products", "orders", "shop_totals", "traffic", "health"] as const;
  async function driveRun(ctx: ReturnType<typeof setup>, answers: Partial<Record<ReaderId, string>>): Promise<string> {
    const ticks: TickReport[] = [];
    (ctx.scheduler as unknown as { deps: { sink: { reportTick: unknown } } }).deps.sink.reportTick = async (report: TickReport) => {
      ticks.push(report);
    };
    (ctx as unknown as { ticks: TickReport[] }).ticks = ticks;
    let result = await ctx.scheduler.tick();
    for (let i = 0; i < 20 && (await ctx.read())?.run; i += 1) {
      const run = (await ctx.read())?.run;
      if (run?.current) await finishPage(ctx, answers[run.jobs[run.index]?.id as ReaderId] ?? "done");
      ctx.clock.now += GAP;
      result = await ctx.scheduler.tick();
    }
    return result;
  }
  const ticksOf = (ctx: ReturnType<typeof setup>) => (ctx as unknown as { ticks: TickReport[] }).ticks;
  const kick = (ctx: ReturnType<typeof setup>) => ctx.scheduler.tick({ trigger: "kick" });

  it("C1/C2: a page-only dialog is blocked:password_recheck, the other readers go on, the stop event says password_recheck", async () => {
    const ctx = setup({ readers: READERS });
    await driveRun(ctx, { shop_totals: "blocked_password_recheck" });
    const state = await ctx.read();
    expect(state?.blocked).toBeUndefined();
    expect(state?.lastRun?.outcomes).toMatchObject({ shop_totals: "blocked:password_recheck", traffic: expect.stringMatching(/^done/), health: expect.stringMatching(/^done/) });
    expect(ctx.events.map((e) => [e.reader, e.status])).toEqual([["shop_totals", "password_recheck"]]);
  });

  it("C1/C2: the dialog is always this page only, even on the run's first page: no run-wide stop, no cool-down", async () => {
    const ctx = setup({ readers: READERS });
    await driveRun(ctx, { products: "blocked_password_recheck" });
    const state = await ctx.read();
    expect(state?.blocked).toBeUndefined();
    expect(state?.lastRun?.blocked).toBeUndefined();
    expect(state?.lastRun?.outcomes.products).toBe("blocked:password_recheck");
    expect(state?.lastRun?.outcomes.orders).toMatch(/^done/);
    expect(ticksOf(ctx).find((t) => t.kind === "run")?.result).toBe("finished");
    expect(ctx.events.map((e) => e.status)).toEqual(["password_recheck"]);
  });

  it("C4: a /datacenter data call re-reads only the blocked pages within 10 minutes, as a reread run tick", async () => {
    const ctx = setup({ readers: READERS });
    await driveRun(ctx, { shop_totals: "blocked_password_recheck" });
    const opened = ctx.tabs.opened.length;
    await ctx.scheduler.sessionSeen("portal"); // another section proves nothing about the dialog
    expect(ctx.alarms.active.has(READER_KICK_ALARM)).toBe(false);
    await ctx.scheduler.sessionSeen("datacenter");
    const info = ctx.alarms.active.get(READER_KICK_ALARM) as { delayInMinutes: number };
    expect(info.delayInMinutes).toBeLessThanOrEqual(10);
    ctx.clock.now += info.delayInMinutes * 60_000;
    expect(await kick(ctx)).toBe("opened");
    expect(new URL(ctx.tabs.current.url).pathname).toBe("/datacenter/overview");
    await finishPage(ctx);
    ctx.clock.now += GAP;
    await ctx.scheduler.tick();
    expect(ctx.tabs.opened.length - opened).toBe(1); // only that page
    const state = await ctx.read();
    expect(state?.lastRun?.outcomes).toMatchObject({ shop_totals: expect.stringMatching(/^done/), traffic: expect.stringMatching(/^done/) });
    const reread = ticksOf(ctx).filter((t) => t.kind === "run").at(-1);
    expect(reread).toMatchObject({ trigger: "reread", result: "finished", outcomes: { shop_totals: expect.stringMatching(/^done/) } });
    expect(Object.keys(reread?.outcomes ?? {})).toEqual(["shop_totals"]);
  });

  it("C4: the re-read fires once per clear: more data calls, or the dialog again, never loop", async () => {
    const ctx = setup({ readers: READERS });
    await driveRun(ctx, { shop_totals: "blocked_password_recheck" });
    await ctx.scheduler.sessionSeen("datacenter");
    await ctx.scheduler.sessionSeen("datacenter"); // an armed re-read is not armed twice
    expect((await ctx.read())?.reread?.pages).toEqual(["shop_totals"]);
    ctx.clock.now += 2 * 60_000;
    await kick(ctx);
    await finishPage(ctx, "blocked_password_recheck"); // the dialog is back
    const state = await ctx.read();
    expect(state?.reread).toBeUndefined();
    expect(state?.lastRun?.outcomes.shop_totals).toMatch(/^blocked/);
    expect(await ctx.scheduler.tick({ trigger: "kick" })).not.toBe("opened");
    // a new clear arms a new one, up to the daily cap
    for (let i = 0; i < 5; i += 1) {
      ctx.clock.now += 24 * 60_000;
      await ctx.scheduler.clearBlock();
      ctx.clock.now += 2 * 60_000;
      if ((await kick(ctx)) === "opened") await finishPage(ctx, "blocked_password_recheck");
    }
    expect((await ctx.read())?.rereadCount?.n).toBe(3);
  });

  it("C4: a reread run whose only page hits the dialog is blocked:password_recheck, no block; a later datacenter call re-arms within the cap", async () => {
    const ctx = setup({ readers: READERS });
    await driveRun(ctx, { shop_totals: "blocked_password_recheck" });
    await ctx.scheduler.sessionSeen("datacenter");
    ctx.clock.now += 2 * 60_000;
    expect(await kick(ctx)).toBe("opened");
    expect((await ctx.read())?.run?.jobs.map((j) => j.id)).toEqual(["shop_totals"]);
    await finishPage(ctx, "blocked_password_recheck"); // still up: the only page of the run
    const state = await ctx.read();
    expect(state?.lastRun?.outcomes.shop_totals).toBe("blocked:password_recheck");
    expect(state?.blocked).toBeUndefined();
    expect(state?.lastRun?.blocked).toBeUndefined();
    expect(ticksOf(ctx).filter((t) => t.kind === "run").at(-1)).toMatchObject({ trigger: "reread", result: "finished" });
    await ctx.scheduler.sessionSeen("datacenter");
    expect((await ctx.read())?.reread?.pages).toEqual(["shop_totals"]);
    expect(ctx.alarms.active.has(READER_KICK_ALARM)).toBe(true);
  });

  it("C4: a login stop lifted by a data call starts again soon, reported as reread", async () => {
    const ctx = setup({ readers: READERS });
    await driveRun(ctx, { products: "blocked_login" });
    expect((await ctx.read())?.blocked).toMatchObject({ reason: "login" });
    await ctx.scheduler.sessionSeen("datacenter");
    expect((await ctx.read())?.blocked).toBeUndefined();
    ctx.clock.now += 2 * 60_000;
    expect(await kick(ctx)).toBe("opened");
    expect((await ctx.read())?.run?.trigger).toBe("reread");
  });

  it("C4: 'Đồng bộ' (clearBlock) re-reads the blocked pages too", async () => {
    const ctx = setup({ readers: READERS });
    await driveRun(ctx, { shop_totals: "blocked_password_recheck" });
    await ctx.scheduler.clearBlock();
    ctx.clock.now += 2 * 60_000;
    expect(await kick(ctx)).toBe("opened");
    expect(new URL(ctx.tabs.current.url).pathname).toBe("/datacenter/overview");
    expect((await ctx.read())?.run?.jobs.map((j) => j.id)).toEqual(["shop_totals"]);
  });

  it("C4: another day's blocks are not re-read; nothing blocked means nothing armed", async () => {
    const ctx = setup({ readers: READERS });
    await driveRun(ctx, {});
    await ctx.scheduler.sessionSeen("datacenter");
    expect((await ctx.read())?.reread).toBeUndefined();
    expect(ctx.alarms.active.has(READER_KICK_ALARM)).toBe(false);
  });
});
