// Connector 0.3.27 (batch-1118g t1), service-worker side: read-back jobs (contract C) handed to the
// readers and reported captured once the page posted; 0.3.35: a combo list read-back is the combos reader's;
// a product read-back's tab is closed once captured; Shopee's anti-bot page stops the job and pauses
// the job pages; the page's current values (contract D) are posted as item_catalog rows.
import { describe, expect, it } from "vitest";
import { FillJobs, readbackPages } from "../src/platforms/shopee/background/fill-jobs";
import { Connector, currentRowsOf } from "../src/platforms/shopee/background/connector";
import { loadState } from "../src/platforms/shopee/background/state";
import { parseFillJob } from "../src/platforms/shopee/fill/job-types";
import { GatewayClient, type IngestBody, type TokenInfo } from "../src/platforms/shopee/ingest/client";
import { JOB_ID, rawJob, voucherJob } from "./fill-job-helpers";

const NOW = Date.UTC(2026, 10, 18, 3, 0, 0);
const TOKEN: TokenInfo = { token: "jci_x", token_id: "t1", shop_id: "s1", platform: "shopee", expires_at: "2027-01-10T00:00:00Z", rotate_after: "2026-12-01T00:00:00Z" };

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

const voucherReadback = (over: Record<string, unknown> = {}) =>
  rawJob("readback", { mode: "readback", open_path: "/portal/marketing/vouchers/list", target: { voucher_id: "7700000000000001" }, datasets: ["voucher_list"], ...over });

function setup(jobs: unknown[], tab: { open: boolean; url?: string } = { open: true }) {
  const storage = new MemoryStorage();
  storage.data.token = TOKEN;
  const reports: { id: string; body: Record<string, unknown> }[] = [];
  const opened: string[] = [];
  const closed: number[] = [];
  const asked: string[][] = [];
  const read = { done: false };
  const clock = { t: NOW };
  const runner = new FillJobs({
    storage,
    client: {
      fillJobs: async () => ({ enabled: true, jobs }),
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
      inspect: async () => tab,
      close: async (id) => void closed.push(id),
    },
    readback: {
      pages: readbackPages,
      start: async (pages) => void asked.push(pages),
      readSince: async () => read.done,
    },
    busy: async () => false,
    halt: async () => undefined,
  });
  return { runner, storage, reports, opened, closed, asked, read, clock };
}

describe("F3.2 read-backs the readers do", () => {
  it("maps datasets to reader pages; a product read-back opens its own page; the combo list has no reader", () => {
    expect(readbackPages(parseFillJob(voucherReadback())!)).toEqual(["vouchers"]);
    expect(readbackPages(parseFillJob(voucherReadback({ open_path: "/portal/product/list/all", target: { item_id: "1001" }, datasets: ["item_catalog"] }))!)).toEqual(["products"]);
    expect(readbackPages(parseFillJob(rawJob("readback", { mode: "readback", open_path: "/portal/product/1001", target: { item_id: "1001" }, datasets: ["item_catalog"] }))!)).toBeNull();
    expect(readbackPages(parseFillJob(voucherReadback({ open_path: "/portal/marketing/bundle/list", target: { combo_id: "77" }, datasets: ["combo_list"] }))!)).toEqual(["combos"]);
    expect(readbackPages(parseFillJob(voucherJob())!)).toBeNull();
  });

  it("hands the pages to the readers (opened), asks again each poll, reports captured once they posted, opens no job page", async () => {
    const s = setup([voucherReadback()]);
    expect(await s.runner.poll()).toBe("nothing_queued");
    expect(s.asked).toEqual([["vouchers"]]);
    expect(s.reports.map((r) => r.body.status)).toEqual(["opened"]);
    await s.runner.poll();
    expect(s.asked).toHaveLength(2);
    s.read.done = true;
    await s.runner.poll();
    expect(s.reports.map((r) => r.body.status)).toEqual(["opened", "captured"]);
    expect(s.opened).toEqual([]);
    expect((await loadState(s.storage)).fill?.readbacks).toEqual({});
  });

  it("0.3.35: hands a combo list read-back to the combos reader (no longer unsupported)", async () => {
    const s = setup([voucherReadback({ open_path: "/portal/marketing/bundle/list", target: { combo_id: "77" }, datasets: ["combo_list"] })]);
    await s.runner.poll();
    expect(s.reports).toEqual([{ id: JOB_ID, body: { status: "opened" } }]);
    expect(s.asked).toEqual([["combos"]]);
  });

  it("opens a product read-back's page like a job and closes that tab once it reported captured", async () => {
    const s = setup([rawJob("readback", { mode: "readback", open_path: "/portal/product/1001", target: { item_id: "1001" }, datasets: ["item_catalog"] })]);
    expect(await s.runner.poll()).toBe("opened");
    expect(s.opened[0]).toContain("/portal/product/1001#juli-fill=");
    await s.runner.report(JOB_ID, "captured");
    expect(s.closed).toEqual([41]);
  });

  it("never closes the person's own fill tab", async () => {
    const s = setup([voucherJob()]);
    await s.runner.poll();
    await s.runner.report(JOB_ID, "captured", { capturedRef: "7700000000000001" });
    expect(s.closed).toEqual([]);
  });
});

describe("Shopee's anti-bot page on a job tab", () => {
  it("reports failed / shopee_traffic_check, opens no job page for a while, never retries the page", async () => {
    const s = setup([voucherJob()]);
    await s.runner.poll();
    const tab = { open: true, url: "https://shopee.vn/verify/traffic/error?home=x" };
    // the same storage; the job's tab now shows the bot check
    const runner = new FillJobs({
      storage: s.storage,
      client: {
        fillJobs: async () => ({ enabled: true, jobs: [voucherJob()] }),
        fillJobReport: async (_t: string, id: string, body: Record<string, unknown>) => {
          s.reports.push({ id, body });
          return {};
        },
      },
      now: () => s.clock.t,
      tabs: {
        openPage: async (url) => {
          s.opened.push(url);
          return 42;
        },
        inspect: async () => tab,
      },
      busy: async () => false,
      halt: async () => undefined,
    });
    expect(await runner.poll()).toBe("shopee_traffic_check");
    expect(s.reports.at(-1)).toEqual({ id: JOB_ID, body: { status: "failed", error: "shopee_traffic_check" } });
    expect(await runner.poll()).toBe("paused");
    s.clock.t += 7 * 3_600_000;
    expect(await runner.poll()).not.toBe("paused");
    expect(s.opened).toHaveLength(1); // the job is never opened again by itself
  });
});

describe("contract D: current values posted as item_catalog rows", () => {
  class FakeClient extends GatewayClient {
    posts: { dataset: string; body: IngestBody }[] = [];
    async post(_token: string, dataset: string, body: IngestBody) {
      this.posts.push({ dataset, body });
      return { rows: body.rows.length, duplicate: false };
    }
  }

  it("keeps only well-formed fields", () => {
    expect(
      currentRowsOf([
        { item_id: "1001", description_first_line: "Dòng đầu\nmới", item_name: "  Tên  ", extra: "x" },
        { item_id: "1002", commission_pct: 13 },
        { item_id: "abc", commission_pct: 5 },
        { item_id: "1003", commission_pct: 140 },
        { item_id: "1004" },
        "junk",
      ]),
    ).toEqual([
      { item_id: "1001", item_name: "Tên", description_first_line: "Dòng đầu mới" },
      { item_id: "1002", commission_pct: 13 },
    ]);
    expect(currentRowsOf("x")).toEqual([]);
  });

  it("posts them as one item_catalog snapshot with the Connector's version", async () => {
    const storage = new MemoryStorage();
    storage.data.token = TOKEN;
    const client = new FakeClient(async () => new Response("{}"));
    const connector = new Connector({ storage, client, tabs: { sellerCentreTabs: async () => [], send: async () => undefined }, version: "0.3.27", now: () => NOW });
    expect(await connector.postCurrent([{ item_id: "2002", commission_pct: 9 }])).toBe("posted");
    expect(client.posts).toHaveLength(1);
    expect(client.posts[0]!.dataset).toBe("item_catalog");
    expect(client.posts[0]!.body).toMatchObject({ source_version: "0.3.27", period: { granularity: "period" }, rows: [{ item_id: "2002", commission_pct: 9 }] });
    expect(await connector.postCurrent([])).toBe("ignored");
  });
});

describe("t2's read-back shapes", () => {
  it("an affiliate read-back opens the open campaign as a job page; a voucher one goes to the vouchers reader", () => {
    const aff = parseFillJob(rawJob("readback", { mode: "readback", open_path: "/portal/web-seller-affiliate/open_campaign", target: { product_ids: ["2002"] }, datasets: ["item_catalog"] }))!;
    expect(readbackPages(aff)).toBeNull();
    expect(readbackPages(parseFillJob(voucherReadback())!)).toEqual(["vouchers"]);
  });

  it("the fill-job poll carries X-Connector-Version (the backend keeps it per computer)", async () => {
    const { configureClientIdentity, IngestClient } = await import("../src/core/ingest/client");
    const seen: Record<string, string>[] = [];
    configureClientIdentity({ version: "0.3.27" });
    try {
      const client = new IngestClient("shopee", async (_url, init) => {
        seen.push((init?.headers ?? {}) as Record<string, string>);
        return new Response(JSON.stringify({ enabled: true, jobs: [] }), { status: 200, headers: { "Content-Type": "application/json" } });
      });
      await client.fillJobs("jci_x", { scOpen: true });
      await client.fillJobReport("jci_x", JOB_ID, { status: "captured" });
    } finally {
      configureClientIdentity({});
    }
    expect(seen.map((h) => h["X-Connector-Version"])).toEqual(["0.3.27", "0.3.27"]);
  });
});
