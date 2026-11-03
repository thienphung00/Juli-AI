import { describe, expect, it } from "vitest";
import {
  READER_BLOCK_CAPTCHA_MS,
  READER_JOB_TIMEOUT_MS,
  READER_LOAD_GRACE_MS,
  READER_PAGE_GAP_JITTER_MS,
  READER_PAGE_GAP_MS,
  type ReaderDataset,
} from "../src/config";
import {
  READER_WATCHDOG_ALARM,
  ReaderScheduler,
  planJobs,
  type SchedulerAlarms,
  type SchedulerTabs,
} from "../src/background/scheduler";
import { loadState, saveState } from "../src/background/state";
import type { ReaderJob, ReaderResponse } from "../src/shopee/reader";

const SC = "https://banhang.shopee.vn";
// 2026-11-03 10:00 GMT+7
const T0 = Date.UTC(2026, 10, 3, 3, 0, 0);
const GAP = READER_PAGE_GAP_MS + READER_PAGE_GAP_JITTER_MS + 1;
const TOKEN = {
  token: "jci_x",
  token_id: "t1",
  shop_id: "s1",
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

function setup(options: { token?: boolean; backfillBusy?: boolean } = {}) {
  const storage = new MemoryStorage();
  const tabs = new FakeTabs();
  const alarms = new FakeAlarms();
  const posted: { job: ReaderJob; responses: ReaderResponse[] }[] = [];
  const clock = { now: T0 };
  const flags = { backfillBusy: options.backfillBusy ?? false };
  const scheduler = new ReaderScheduler({
    storage,
    tabs,
    alarms,
    origin: SC,
    version: "0.3.0",
    now: () => clock.now,
    random: () => 0.5,
    backfillBusy: async () => flags.backfillBusy,
    sink: {
      async postReader(job, responses) {
        posted.push({ job, responses });
        return { [job.id]: "posted" };
      },
    },
  });
  if (options.token !== false) storage.data.token = TOKEN;
  const read = async () => (await loadState(storage)).readers;
  return { scheduler, storage, tabs, alarms, posted, clock, flags, read };
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
  expect(await ctx.scheduler.onResult(tab.id, { job: job?.id, status, responses })).toBe(true);
}

describe("planJobs", () => {
  const base = { shopId: "s1", nowMs: T0, stopped: new Set<never>(), adsDone: [] as string[] };

  it("opens only pages with a postable dataset: health waits while its table is reserved", () => {
    const ids = planJobs(base).map((j) => j.id);
    expect(ids).toEqual(["products", "vouchers", "ads"]);
    expect(planJobs({ ...base, held: new Set<ReaderDataset>() }).map((j) => j.id)).toEqual([
      "products",
      "vouchers",
      "ads",
      "health",
    ]);
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
    ]);
  });

  it("a dataset stopped after drift (this version) takes its page off the plan; no shop = nothing", () => {
    expect(planJobs({ ...base, stopped: new Set(["voucher_settings" as const]) }).map((j) => j.id)).toEqual(["products", "ads"]);
    expect(planJobs({ ...base, shopId: undefined })).toEqual([]);
  });
});

describe("a daily run", () => {
  it("opens one background tab per page, one at a time, with a gap, and closes each", async () => {
    const ctx = setup();
    expect(await ctx.scheduler.tick()).toBe("opened");
    expect(ctx.tabs.opened.map((t) => t.url)).toEqual([`${SC}/portal/product/list/all`]);
    expect(ctx.alarms.active.has(READER_WATCHDOG_ALARM)).toBe(true);
    expect(await ctx.scheduler.isBusy()).toBe(true);
    expect(await ctx.scheduler.activeTabIds()).toEqual([ctx.tabs.current.id]);

    // tab ready -> the job is sent to that tab
    const first = ctx.tabs.current;
    expect(await ctx.scheduler.onTabReady(first.id, first.url)).toBe(true);
    expect(ctx.tabs.sent).toEqual([{ tabId: first.id, message: { type: "reader-job", job: { id: "products" } } }]);
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

    // the run is over: watchdog cleared, today recorded, no more pages today
    const state = await ctx.read();
    expect(state?.run).toBeUndefined();
    expect(state?.lastRunDay).toBe("2026-11-03");
    expect(state?.lastRun?.outcomes).toEqual({
      products: "done:products=posted",
      vouchers: "done:vouchers=posted",
      ads: "done:ads=posted",
    });
    expect(ctx.alarms.active.has(READER_WATCHDOG_ALARM)).toBe(false);
    expect(ctx.tabs.closed).toHaveLength(3);
    expect(await ctx.scheduler.isBusy()).toBe(false);
    ctx.clock.now += 3_600_000;
    expect(await ctx.scheduler.tick()).toBe("done_today");
    expect(ctx.tabs.opened).toHaveLength(3);
  });

  it("the ads job carries its days; a read ads day is not planned again tomorrow", async () => {
    const ctx = setup();
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
      job: { id: "ads", days: ["2026-11-02", "2026-11-01", "2026-10-31", "2026-10-30"] },
    });
    await ctx.scheduler.onResult(tab.id, { job: "ads", status: "done", responses: [] });
    expect((await ctx.read())?.adsDone).toEqual(["2026-11-02", "2026-11-01", "2026-10-31", "2026-10-30"]);
    // tomorrow: only the new finished day
    ctx.clock.now += 24 * 3_600_000;
    await ctx.scheduler.tick();
    expect(ctx.tabs.current.url).toContain("/portal/product/list/all");
    expect((await ctx.read())?.run?.jobs.find((j) => j.id === "ads")?.days).toEqual(["2026-11-03"]);
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
