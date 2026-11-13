// The service worker's fill-job runner (P97 D85.6): polls Juli for the token's shop's jobs, opens
// one queued page at a time within the shared request budget, serves the job only to the page that
// is exactly its page, passes progress on, and stops for the shop on a password prompt.
import { describe, expect, it } from "vitest";
import { FillJobs, jobUrl, senderMatchesJob } from "../src/background/fill-jobs";
import { addRequests, loadState, requestsLeft } from "../src/background/state";
import { DAILY_REQUEST_BUDGET, READER_PAGE_LOAD_COST } from "../src/config";
import { GatewayError } from "../src/ingest/client";
import { bundleIdFrom, savedBundlePath, savedVoucherPath, voucherIdFrom } from "../src/fill/saved";
import { gmt7Date } from "../src/shopee/time";
import { JOB_ID, voucherJob } from "./fill-job-helpers";

const NOW = Date.UTC(2026, 10, 9, 3, 0, 0);
const TOKEN = { token: "jci_x", token_id: "t1", shop_id: "s1", platform: "shopee", expires_at: "2027-01-10T00:00:00Z", rotate_after: "2026-12-01T00:00:00Z" };
const DAY = gmt7Date(Math.floor(NOW / 1000));

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

function setup(over: { jobs?: unknown[]; enabled?: boolean; busy?: boolean; listError?: number; tabOpen?: boolean } = {}) {
  const storage = new MemoryStorage();
  storage.data.token = TOKEN;
  const opened: string[] = [];
  const reports: { id: string; body: Record<string, unknown> }[] = [];
  const halts: unknown[][] = [];
  const clock = { t: NOW };
  const state = { jobs: over.jobs ?? [voucherJob()], enabled: over.enabled ?? true, tabOpen: over.tabOpen ?? true };
  const jobs = new FillJobs({
    storage,
    client: {
      fillJobs: async () => {
        if (over.listError) throw new GatewayError(over.listError, "x");
        return { enabled: state.enabled, jobs: state.jobs };
      },
      fillJobReport: async (_t: string, id: string, body: Record<string, unknown>) => {
        reports.push({ id, body });
        return {};
      },
    },
    now: () => clock.t,
    tabs: {
      openPage: async (url) => {
        opened.push(url);
        return 41;
      },
      inspect: async () => ({ open: state.tabOpen }),
    },
    busy: async () => over.busy === true,
    halt: async (...args) => {
      halts.push(args);
    },
  });
  return { jobs, storage, opened, reports, halts, clock, state };
}

describe("the poll", () => {
  it("opens the next queued job's page with the job id in the address and counts the page load", async () => {
    const s = setup();
    expect(await s.jobs.poll()).toBe("opened");
    expect(s.opened).toEqual([`https://banhang.shopee.vn/portal/marketing/vouchers/new?usecase=1#juli-fill=${JOB_ID}`]);
    const state = await loadState(s.storage);
    expect(requestsLeft(state, DAY)).toBe(DAILY_REQUEST_BUDGET - READER_PAGE_LOAD_COST);
    expect(state.fill?.active).toMatchObject({ id: JOB_ID, tabId: 41 });
  });

  it("opens one page at a time, and never the same job twice by itself", async () => {
    const s = setup();
    await s.jobs.poll();
    expect(await s.jobs.poll()).toBe("job_open");
    s.state.tabOpen = false; // the person closed the tab
    expect(await s.jobs.poll()).toBe("nothing_queued");
    expect(s.opened).toHaveLength(1);
  });

  it("only opens queued jobs: one the person is working on is left alone", async () => {
    const s = setup({ jobs: [voucherJob({}), { ...voucherJob(), id: "7f1c9a3e-1d2b-4c5d-8e7f-0a1b2c3d4e5f", status: "filled" }].slice(1) });
    expect(await s.jobs.poll()).toBe("nothing_queued");
    expect(s.opened).toEqual([]);
  });

  it("drops a job whose address is not an allowed page", async () => {
    const s = setup({ jobs: [voucherJob({ open_path: "/portal/marketing/vouchers/list" })] });
    expect(await s.jobs.poll()).toBe("nothing_queued");
  });

  it("opens nothing while Juli's kill switch is off", async () => {
    const s = setup({ enabled: false });
    expect(await s.jobs.poll()).toBe("disabled");
    expect(s.opened).toEqual([]);
  });

  it("opens nothing when unpaired, when Juli says 401, while another run holds the pace, or after a stop", async () => {
    const none = setup();
    delete none.storage.data.token;
    expect(await none.jobs.poll()).toBe("inactive");
    expect(await setup({ listError: 401 }).jobs.poll()).toBe("unpaired");
    expect(await setup({ busy: true }).jobs.poll()).toBe("busy");
    const stopped = setup();
    stopped.storage.data.readers = { adsDone: [], trafficDone: [], blocked: { at: "x", reason: "login", page: "products", until: NOW + 3_600_000 } };
    expect(await stopped.jobs.poll()).toBe("blocked");
    expect(stopped.opened).toEqual([]);
  });

  it("opens nothing once the day's request budget cannot pay a page load", async () => {
    const s = setup();
    await addRequests(s.storage, DAY, DAILY_REQUEST_BUDGET - READER_PAGE_LOAD_COST + 1);
    expect(await s.jobs.poll()).toBe("budget_spent");
    expect(s.opened).toEqual([]);
  });
});

describe("serving the job to the page", () => {
  const url = `https://banhang.shopee.vn/portal/marketing/vouchers/new?usecase=1#juli-fill=${JOB_ID}`;

  it("serves a job to the exact page it names", async () => {
    const s = setup();
    const reply = await s.jobs.jobFor(url, JOB_ID);
    expect(reply).toMatchObject({ ok: true, value: { id: JOB_ID, kind: "voucher" } });
  });

  it("serves it to no other page, and not an unknown job", async () => {
    const s = setup();
    expect(await s.jobs.jobFor("https://banhang.shopee.vn/portal/marketing/vouchers/new?usecase=2#juli-fill=" + JOB_ID, JOB_ID)).toEqual({ ok: false, reason: "wrong_page" });
    expect(await s.jobs.jobFor(`https://banhang.shopee.vn/portal/product/1#juli-fill=${JOB_ID}`, JOB_ID)).toEqual({ ok: false, reason: "wrong_page" });
    expect(await s.jobs.jobFor(url, "11111111-1111-4111-8111-111111111111")).toEqual({ ok: false, reason: "unknown_job" });
    expect(await s.jobs.jobFor(undefined, JOB_ID)).toEqual({ ok: false, reason: "wrong_page" });
  });

  it("is invisible without a switch, and counts a page the person opened with the button", async () => {
    expect(await setup({ enabled: false }).jobs.jobFor(url, JOB_ID)).toEqual({ ok: false, reason: "inactive" });
    const s = setup();
    await s.jobs.jobFor(url, JOB_ID);
    expect(requestsLeft(await loadState(s.storage), DAY)).toBe(DAILY_REQUEST_BUDGET - READER_PAGE_LOAD_COST);
    await s.jobs.jobFor(url, JOB_ID); // the same page again is not counted twice
    expect(requestsLeft(await loadState(s.storage), DAY)).toBe(DAILY_REQUEST_BUDGET - READER_PAGE_LOAD_COST);
  });

  it("refuses with the budget reason when the day's budget is spent", async () => {
    const s = setup();
    await addRequests(s.storage, DAY, DAILY_REQUEST_BUDGET);
    expect(await s.jobs.jobFor(url, JOB_ID)).toEqual({ ok: false, reason: "budget" });
  });

  it("matches the address exactly", () => {
    const job = { id: JOB_ID, openPath: "/portal/marketing/pas/product/manual/160675212" };
    expect(jobUrl(job)).toBe(`https://banhang.shopee.vn/portal/marketing/pas/product/manual/160675212#juli-fill=${JOB_ID}`);
    expect(senderMatchesJob(jobUrl(job), job)).toBe(true);
    expect(senderMatchesJob(`https://evil.example/portal/marketing/pas/product/manual/160675212#juli-fill=${JOB_ID}`, job)).toBe(false);
    expect(senderMatchesJob(`https://banhang.shopee.vn/portal/marketing/pas/product/manual/1#juli-fill=${JOB_ID}`, job)).toBe(false);
  });
});

describe("progress and the password prompt", () => {
  it("passes progress on and frees the slot when the id is captured", async () => {
    const s = setup();
    await s.jobs.poll();
    await s.jobs.report(JOB_ID, "filled");
    expect((await loadState(s.storage)).fill?.active?.id).toBe(JOB_ID);
    await s.jobs.report(JOB_ID, "captured", { capturedRef: "88001" });
    expect(s.reports.map((r) => r.body)).toEqual([{ status: "filled" }, { status: "captured", captured_ref: "88001" }]);
    expect((await loadState(s.storage)).fill?.active).toBeUndefined();
  });

  it("stops everything for the shop on a password prompt: job failed, shop halted, slot freed", async () => {
    const s = setup();
    await s.jobs.poll();
    await s.jobs.halt(JOB_ID, "/portal/marketing/vouchers/new");
    expect(s.reports).toEqual([{ id: JOB_ID, body: { status: "failed", error: "password_prompt" } }]);
    expect(s.halts).toEqual([["login", "/portal/marketing/vouchers/new", "password_prompt"]]);
    expect((await loadState(s.storage)).fill?.active).toBeUndefined();
  });
});

describe("noticing a saved voucher", () => {
  it("knows a create endpoint and reads only digits from its answer", () => {
    expect(savedVoucherPath("/api/marketing/v3/voucher/create/")).toBe(true);
    expect(savedVoucherPath("/api/marketing/v3/voucher/list/")).toBe(false);
    expect(savedVoucherPath("/api/pas/v1/product/edit")).toBe(false);
    expect(voucherIdFrom({ code: 0, data: { voucher_id: 123456789012 } })).toBe("123456789012");
    expect(voucherIdFrom({ voucher_id: "42" })).toBe("42");
    expect(voucherIdFrom({ voucher_id: "4 2; drop" })).toBeNull();
    expect(voucherIdFrom({ data: { list: [] } })).toBeNull();
  });

  it("knows a combo create endpoint and reads only digits of its id; nothing else is captured", () => {
    expect(savedBundlePath("/api/marketing/v3/bundle_deal/create/")).toBe(true);
    expect(savedBundlePath("/api/marketing/v3/bundle_deal/list/")).toBe(false);
    expect(savedBundlePath("/api/marketing/v3/voucher/create/")).toBe(false);
    expect(bundleIdFrom({ code: 0, data: { bundle_deal_id: 555000111 } })).toBe("555000111");
    expect(bundleIdFrom({ bundle_id: "77" })).toBe("77");
    expect(bundleIdFrom({ bundle_id: "7 7; x" })).toBeNull();
    expect(bundleIdFrom({ data: { list: [] } })).toBeNull();
  });
});
