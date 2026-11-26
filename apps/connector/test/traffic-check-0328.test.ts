// Connector 0.3.28 (batch-1119-f5 t1): F5.3 Shopee's traffic-check page is its own block reason
// ("traffic_check", contract R): a reader or fill tab that lands there stops, the fill job fails
// shopee_traffic_check, and ONE 6 h pause holds readers, fills and read-backs (no button, heartbeat
// or data call lifts it early). F5.4 never two Shopee automations at once. F5.V the version.
import { describe, expect, it } from "vitest";
import manifest from "../public/manifest.json";
import pkg from "../package.json";
import { READER_BLOCK_TRAFFIC_MS, READER_LOAD_GRACE_MS } from "../src/platforms/shopee/config";
import { FillJobs, readbackPages } from "../src/platforms/shopee/background/fill-jobs";
import { type BlockEvent, FILL_TAB_WAIT_MS, READER_KICK_ALARM, ReaderScheduler, type SchedulerTabs, type TickReport } from "../src/platforms/shopee/background/scheduler";
import { loadState } from "../src/platforms/shopee/background/state";
import { blockedPath } from "../src/platforms/shopee/reader";
import { readersLabel } from "../src/platforms/shopee/popup/labels";
import { outcomeStatus, runLine } from "../src/platforms/shopee/popup/guide";
import { JOB_ID, rawJob, voucherJob } from "./fill-job-helpers";

const SC = "https://banhang.shopee.vn";
const TRAFFIC = "https://shopee.vn/verify/traffic/error?home=x";
// 2026-11-19 10:00 GMT+7
const T0 = Date.UTC(2026, 10, 19, 3, 0, 0);
const TOKEN = { token: "jci_x", token_id: "t1", shop_id: "5b0c1d2e-3f40-4a51-8b62-7c83d94e0a15", platform: "shopee", expires_at: "2027-01-10T00:00:00Z", rotate_after: "2026-12-01T00:00:00Z" };

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
  inspection = new Map<number, { open: boolean; url?: string }>();
  async open(url: string) {
    const id = this.nextId++;
    this.opened.push({ id, url });
    return id;
  }
  async close(tabId: number) {
    this.closed.push(tabId);
  }
  async send() {
    return undefined;
  }
  async inspect(tabId: number) {
    return this.inspection.get(tabId) ?? { open: true, url: this.opened.find((t) => t.id === tabId)?.url };
  }
  get current() {
    return this.opened[this.opened.length - 1]!;
  }
}

/** The service worker's wiring, in small: one storage, the scheduler, the fill runner. */
function world(jobs: unknown[] = []) {
  const storage = new MemoryStorage();
  storage.data.token = TOKEN;
  const clock = { now: T0 };
  const tabs = new FakeTabs();
  const alarms = new Map<string, unknown>();
  const events: BlockEvent[] = [];
  const ticks: TickReport[] = [];
  const fillTab = { open: false, url: `${SC}/portal/marketing/vouchers/new` };
  const reports: { id: string; body: Record<string, unknown> }[] = [];
  const fillOpened: string[] = [];
  const asked: string[][] = [];
  let fillJobs: FillJobs;
  const scheduler = new ReaderScheduler({
    storage,
    tabs,
    alarms: {
      create: async (name, info) => void alarms.set(name, info),
      clear: async (name) => alarms.delete(name),
    },
    readers: ["products", "vouchers"],
    stockRun: false,
    origin: SC,
    version: "0.3.28",
    now: () => clock.now,
    random: () => 0.5,
    backfillBusy: async () => false,
    fillTabOpen: () => fillJobs.tabOpen(),
    sink: {
      reportBlock: async (e) => void events.push(e),
      reportTick: async (t) => void ticks.push(t),
      postReader: async (job) => ({ [job.id]: "posted" }),
    },
  });
  fillJobs = new FillJobs({
    storage,
    client: {
      fillJobs: async () => ({ enabled: true, jobs }),
      fillJobReport: async (_t: string, id: string, body: Record<string, unknown>) => {
        reports.push({ id, body });
        return {};
      },
    },
    now: () => clock.now,
    tabs: {
      openPage: async (url) => {
        fillOpened.push(url);
        fillTab.open = true;
        return 41;
      },
      inspect: async () => (fillTab.open ? { open: true, url: fillTab.url } : { open: false }),
      close: async () => undefined,
    },
    readback: { pages: readbackPages, start: async (pages) => void asked.push(pages), readSince: async () => false },
    busy: async () => await scheduler.isBusy(),
    halt: (reason, page, detail) => scheduler.haltFor(reason, page, detail),
  });
  const blocked = async () => (await loadState(storage)).readers?.blocked;
  return { storage, clock, tabs, alarms, events, ticks, fillTab, reports, fillOpened, asked, scheduler, fillJobs, blocked };
}

describe("F5.3 the traffic-check page is its own reason (contract R)", () => {
  it("classifies /verify/traffic… as traffic_check, never login or captcha", () => {
    expect(blockedPath("/verify/traffic/error")).toBe("traffic_check");
    expect(blockedPath("/verify/traffic")).toBe("traffic_check");
    expect(blockedPath("/verify/captcha")).toBe("captcha");
    expect(blockedPath("/account/signin")).toBe("login");
  });

  it("a reader tab on the traffic check stops the run: outcome blocked:traffic_check (+ until), a 6 h pause, Ops told", async () => {
    const w = world();
    expect(await w.scheduler.tick()).toBe("opened");
    const tab = w.tabs.current;
    w.tabs.inspection.set(tab.id, { open: true, url: TRAFFIC });
    w.clock.now += READER_LOAD_GRACE_MS + 1;
    expect(await w.scheduler.tick()).toBe("blocked:traffic_check");
    const until = w.clock.now + READER_BLOCK_TRAFFIC_MS;
    expect(await w.blocked()).toMatchObject({ reason: "traffic_check", page: "products", until });
    const run = w.ticks.find((t) => t.kind === "run")!;
    expect(run.result).toBe("blocked:traffic_check");
    expect(run.outcomes!.products).toBe(`blocked:traffic_check|until=${new Date(until).toISOString()}`);
    expect(w.events).toEqual([expect.objectContaining({ reader: "products", status: "traffic_check" })]);
    expect(w.tabs.closed).toEqual([tab.id]);
    expect(w.tabs.opened).toHaveLength(1);
  });

  it("a reader tab that navigates there mid-run (tab URL change) stops at once", async () => {
    const w = world();
    await w.scheduler.tick();
    expect(await w.scheduler.onTabUrl(w.tabs.current.id, TRAFFIC)).toBe(true);
    expect((await w.blocked())?.reason).toBe("traffic_check");
    expect(await w.scheduler.onTabUrl(999, TRAFFIC)).toBe(false); // not the scheduler's tab
  });

  it("a fill tab there (poll): the job fails shopee_traffic_check, the ONE pause holds readers, fills and read-backs for 6 h", async () => {
    const w = world([voucherJob(), rawJob("readback", { mode: "readback", open_path: "/portal/marketing/vouchers/list", target: { voucher_id: "7700000000000001" }, datasets: ["voucher_list"] }, { id: "7f1c9a3e-1d2b-4c5d-8e7f-0a1b2c3d4e5f" })]);
    expect(await w.fillJobs.poll()).toBe("opened");
    w.asked.length = 0;
    w.fillTab.url = TRAFFIC;
    expect(await w.fillJobs.poll()).toBe("shopee_traffic_check");
    expect(w.reports.find((r) => r.id === JOB_ID && r.body.status === "failed")?.body).toEqual({ status: "failed", error: "shopee_traffic_check" });
    expect(await w.blocked()).toMatchObject({ reason: "traffic_check", until: T0 + READER_BLOCK_TRAFFIC_MS });
    expect(w.events).toEqual([expect.objectContaining({ reader: "fill", status: "traffic_check" })]);
    // F5.3b: told to Juli as a block too: a run tick the backend's validator takes (trigger [a-z_],
    // result [A-Za-z0-9_.:-], outcome key [a-z_]) and stores as a seller_centre block
    const until = new Date(T0 + READER_BLOCK_TRAFFIC_MS).toISOString();
    expect(w.ticks).toEqual([
      { kind: "run", trigger: "fill", result: "blocked:traffic_check", day: "2026-11-19", at: new Date(T0).toISOString(), outcomes: { fill: `blocked:traffic_check|until=${until}` } },
    ]);
    const tick = w.ticks[0]!;
    expect(tick.trigger).toMatch(/^[a-z_]{1,32}$/);
    expect(tick.result).toMatch(/^[A-Za-z0-9_.:\-]{1,80}$/);
    for (const [key, outcome] of Object.entries(tick.outcomes!)) {
      expect(key).toMatch(/^[a-z_]{1,48}$/);
      expect(outcome.length).toBeLessThanOrEqual(160);
    }
    // during the pause: no reader page, no fill page, no read-back
    w.fillTab.open = false;
    for (const later of [60_000, 3_600_000, READER_BLOCK_TRAFFIC_MS - 60_000]) {
      w.clock.now = T0 + later;
      expect(await w.scheduler.due()).toBe(false);
      expect(await w.scheduler.tick()).toBe("blocked");
      expect(await w.fillJobs.poll()).toBe("blocked");
    }
    expect(w.tabs.opened).toEqual([]);
    expect(w.fillOpened).toHaveLength(1);
    expect(w.asked).toEqual([]);
    // after the 6 h the readers may run again
    w.clock.now = T0 + READER_BLOCK_TRAFFIC_MS + 1;
    expect(await w.scheduler.due()).toBe(true);
  });

  it("a fill tab that navigates there (tab URL change) stops the job at once", async () => {
    const w = world([voucherJob()]);
    await w.fillJobs.poll();
    expect(await w.fillJobs.onTabUrl(41, TRAFFIC)).toBe("shopee_traffic_check");
    expect(w.reports.at(-1)?.body).toEqual({ status: "failed", error: "shopee_traffic_check" });
    expect((await w.blocked())?.reason).toBe("traffic_check");
    expect(await w.fillJobs.onTabUrl(41, `${SC}/portal/marketing/vouchers/new`)).toBeNull(); // no active job any more
    expect(await w.fillJobs.onTabUrl(7, TRAFFIC)).toBeNull(); // not a job tab
  });

  it("neither «Đồng bộ» / «Đối chiếu ngay» (clearBlock), a data call (sessionSeen) nor a login halt lifts it or arms a re-read before `until`", async () => {
    const w = world();
    await w.scheduler.tick();
    await w.scheduler.onTabUrl(w.tabs.current.id, TRAFFIC);
    const before = await w.blocked();
    w.alarms.clear();
    w.clock.now += 60_000;
    await w.scheduler.clearBlock();
    await w.scheduler.sessionSeen("datacenter");
    const ticks = w.ticks.length;
    await w.scheduler.haltFor("login", "/portal/product/1001", "password_prompt");
    await w.scheduler.haltFor("traffic_check", "/portal/product/1001", "shopee_traffic_check"); // already in force: kept, not told again
    expect(w.ticks).toHaveLength(ticks);
    expect(await w.blocked()).toEqual(before);
    expect((await loadState(w.storage)).readers?.reread).toBeUndefined();
    expect(w.alarms.has(READER_KICK_ALARM)).toBe(false);
    expect(await w.scheduler.tick({ manual: true })).toBe("blocked");
    // once `until` passed, the button lifts nothing that is not there and the day runs
    w.clock.now = before!.until + 1;
    await w.scheduler.clearBlock();
    expect(await w.scheduler.tick({ manual: true })).toBe("opened");
  });

  it("the popup says «Shopee tạm chặn truy cập tự động — Juli dừng đến HH:mm» (GMT+7)", async () => {
    const w = world();
    await w.scheduler.tick();
    await w.scheduler.onTabUrl(w.tabs.current.id, TRAFFIC);
    const readers = (await loadState(w.storage)).readers!;
    // T0 is 10:00 GMT+7; + 6 h
    expect(readersLabel(readers, w.clock.now)).toBe("Shopee tạm chặn truy cập tự động — Juli dừng đến 16:00");
    expect(runLine(readers, w.clock.now)).toBe("Shopee tạm chặn truy cập tự động — Juli dừng đến 16:00");
    expect(outcomeStatus(`blocked:traffic_check|until=${new Date(readers.blocked!.until).toISOString()}`).status).toBe("Shopee tạm chặn truy cập tự động");
  });
});

describe("F5.4 never two Shopee automations at once", () => {
  it("the scheduler opens no reader page while a fill tab is open: it waits and kicks a retry", async () => {
    const w = world([voucherJob()]);
    expect(await w.fillJobs.poll()).toBe("opened");
    expect(await w.fillJobs.tabOpen()).toBe(true);
    expect(await w.scheduler.tick()).toBe("fill_busy");
    expect(w.tabs.opened).toEqual([]);
    expect(w.alarms.has(READER_KICK_ALARM)).toBe(true);
    w.fillTab.open = false; // the person closed the fill page
    expect(await w.fillJobs.tabOpen()).toBe(false);
    expect(await w.scheduler.tick({ trigger: "kick" })).toBe("opened");
    expect(w.tabs.opened).toHaveLength(1);
  });

  it("a run in progress does not open its next page while a fill tab is open; it goes on once the tab is gone", async () => {
    const w = world([voucherJob()]);
    expect(await w.scheduler.tick()).toBe("opened"); // products
    // the products page answers; meanwhile a fill page was opened by the person from Juli
    await w.scheduler.onResult(w.tabs.current.id, { job: "products", status: "done", responses: [] });
    w.fillTab.open = true;
    await w.storage.set({ fill: { active: { id: JOB_ID, tabId: 41, openedAt: w.clock.now, counted: true }, autoOpened: [JOB_ID] } });
    w.clock.now += 120_000;
    expect(await w.scheduler.tick()).toBe("fill_busy");
    expect(w.tabs.opened).toHaveLength(1);
    w.fillTab.open = false;
    w.clock.now += FILL_TAB_WAIT_MS + 1;
    expect(await w.scheduler.tick()).toBe("opened"); // vouchers
    expect(w.tabs.opened).toHaveLength(2);
  });

  it("the fill poll opens no job page while a reader run is going, and starts no read-back while a fill tab is open", async () => {
    const w = world([voucherJob()]);
    await w.scheduler.tick();
    expect(await w.fillJobs.poll()).toBe("busy");
    expect(w.fillOpened).toEqual([]);
    const rb = world([rawJob("readback", { mode: "readback", open_path: "/portal/marketing/vouchers/list", target: { voucher_id: "7700000000000001" }, datasets: ["voucher_list"] })]);
    rb.fillTab.open = true;
    await rb.storage.set({ fill: { active: { id: "other", tabId: 41, openedAt: rb.clock.now, counted: true }, autoOpened: [] } });
    expect(await rb.fillJobs.poll()).toBe("job_open");
    expect(rb.asked).toEqual([]); // the read-back waits for the fill tab
    rb.fillTab.open = false;
    await rb.fillJobs.poll();
    expect(rb.asked).toEqual([["vouchers"]]);
  });
});

describe("F5.V the version", () => {
  it("is 0.3.37 in package.json and the manifest", () => {
    expect(pkg.version).toBe("0.3.37");
    expect(manifest.version).toBe("0.3.37");
  });
});
