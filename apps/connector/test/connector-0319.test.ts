// Connector 0.3.19 (P100 Part A): the traffic reader, its posts, the reviewer sample shop, the
// tick report, re-injection after an update, and the popup's last-tick / stock lines.

import { describe, expect, it } from "vitest";
import { Connector, type Tabs } from "../src/platforms/shopee/background/connector";
import { reinjectPlan, reinjectSellerCentreTabs } from "../src/core/reinject";
import type { ReaderSchedule } from "../src/platforms/shopee/background/state";
import { readerActive, schedulerActive } from "../src/platforms/shopee/config";
import { GatewayClient, type IngestBody, type TokenInfo } from "../src/platforms/shopee/ingest/client";
import { adsHistoryLine, stockLine, tickLine, tickResultLabel } from "../src/platforms/shopee/popup/guide";
import {
  type FetchedReaderResponse,
  pollingWaitFor,
  type ReaderEnv,
  type ReaderRequest,
  type ReaderResponse,
  runReaderJob,
} from "../src/platforms/shopee/reader";
import { mapTrafficJob } from "../src/platforms/shopee/reader-map";
import { Pacer } from "../src/platforms/shopee/runner";
import { gmt7DateStart } from "../src/core/time";
import shopTraffic from "./fixtures/shop_traffic.json";
import overview from "./fixtures/traffic_overview.json";

const SC = "https://banhang.shopee.vn";
const NOW = Date.UTC(2026, 10, 14, 3, 0, 0); // 14/11 10:00 GMT+7
const TOKEN: TokenInfo = {
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

class FakeClient extends GatewayClient {
  posts: { dataset: string; body: IngestBody }[] = [];
  ticks: { body: unknown; version: string }[] = [];
  pairedAs = TOKEN;
  async post(_token: string, dataset: string, body: IngestBody) {
    this.posts.push({ dataset, body });
    return { rows: body.rows.length, duplicate: false };
  }
  async pair() {
    return this.pairedAs;
  }
  async connectorTick(_token: string, report: never, version: string) {
    this.ticks.push({ body: report, version });
    return {};
  }
}

function connectorSetup() {
  const storage = new MemoryStorage();
  const client = new FakeClient(async () => new Response("{}"));
  const tabs: Tabs = { sellerCentreTabs: async () => [], send: async () => undefined };
  const connector = new Connector({ storage, client, tabs, version: "0.3.19", now: () => NOW });
  return { storage, client, connector };
}

function readerHarness(handler: (request: ReaderRequest) => { status?: number; body?: unknown }, session = true) {
  let clock = NOW;
  const sent: ReaderRequest[] = [];
  const sleep = async (ms: number) => {
    clock += ms;
  };
  const now = () => clock;
  const env: ReaderEnv = {
    origin: SC,
    pacer: new Pacer({ sleep, now, random: () => 0 }),
    now,
    session: () => ({ SPC_CDS: "s", SPC_CDS_VER: "2" }),
    hasSession: () => session,
    template: () => undefined,
    waitFor: pollingWaitFor(sleep, now),
    mydataHeaders: () => ({ "x-sap-ri": "r" }),
    fetch: async (request): Promise<FetchedReaderResponse> => {
      sent.push(request);
      const answer = handler(request);
      return { status: answer.status ?? 200, text: async () => JSON.stringify(answer.body ?? null) };
    },
    pathname: () => "/datacenter/traffic/overview",
  };
  return { env, sent };
}

const FLAT = { uv: { value: 10, ratio: 0 }, pv: { value: 12, ratio: 0 }, placed_buyers: { value: 2, ratio: 0 } };
const bodyFor = (request: ReaderRequest) =>
  request.url.includes("/traffic/dashboard/") ? shopTraffic : request.url.includes("/product/overview/") ? FLAT : overview;

describe("the traffic reader (Truy cập in the scheduler's own tab)", () => {
  it("reads each day's overview on both order bases and the shop traffic dashboard, GET only", async () => {
    const h = readerHarness((request) => ({ body: bodyFor(request) }));
    const outcome = await runReaderJob({ id: "traffic", days: ["2026-11-13", "2026-11-12"] }, h.env);
    expect(outcome.status).toBe("done");
    expect(h.sent).toHaveLength(8); // per day: overview x 2 order bases, shop traffic, product overview (F4.8)
    expect(h.sent.every((r) => r.method === "GET")).toBe(true);
    const first = new URL(h.sent[0]!.url).searchParams;
    expect(Object.fromEntries(first)).toMatchObject({
      start_time: String(gmt7DateStart("2026-11-13")),
      end_time: String(gmt7DateStart("2026-11-13") + 86_399),
      period: "yesterday",
      order_type: "confirmed",
      SPC_CDS: "s",
    });
    expect(new URL(h.sent[2]!.url).pathname).toBe("/api/mydata/traffic/dashboard/overview/");
    expect(Object.fromEntries(new URL(h.sent[6]!.url).searchParams)).toMatchObject({ period: "day", dt: "20261112" });
    expect(new URL(h.sent[3]!.url).pathname).toBe("/api/mydata/v2/product/overview/");
    expect(h.sent[0]!.headers["x-sap-ri"]).toBe("r");
    // the session params never reach what is posted
    expect(outcome.responses.every((r) => !r.url.includes("SPC_CDS"))).toBe(true);
  });

  it("a page that never loaded data is needs_data_page; a Shopee error code is kept and the job goes on", async () => {
    const empty = readerHarness(() => ({ body: overview }), false);
    expect((await runReaderJob({ id: "traffic", days: ["2026-11-13"] }, empty.env)).status).toBe("needs_data_page");
    expect(empty.sent).toHaveLength(0);
    const odd = readerHarness((request) => (request.url.includes("placed") ? { body: { code: 10006, msg: "err:invalid param" } } : { body: bodyFor(request) }));
    const outcome = await runReaderJob({ id: "traffic", days: ["2026-11-13"] }, odd.env);
    expect(outcome.status).toBe("done");
    expect(odd.sent).toHaveLength(4);
    // and a rate answer stops it like every reader
    const rate = readerHarness(() => ({ status: 429, body: { error: 429 } }));
    expect((await runReaderJob({ id: "traffic", days: ["2026-11-13"] }, rate.env)).status).toBe("blocked_rate");
  });

  it("maps through the mydata mapper and posts one body per day and order type", async () => {
    const h = readerHarness((request) => ({ body: bodyFor(request) }));
    const outcome = await runReaderJob({ id: "traffic", days: ["2026-11-13"] }, h.env);
    const mapped = mapTrafficJob(outcome.responses);
    expect(mapped.map((m) => [m.dataset, m.date, m.orderType])).toEqual([
      ["traffic_overview", "2026-11-13", "confirmed"],
      ["traffic_overview", "2026-11-13", "placed"],
      ["shop_traffic", "2026-11-13", null],
      ["product_overview", "2026-11-13", "placed"],
      ["product_overview", "2026-11-13", "confirmed"],
    ]);
    const { storage, client, connector } = connectorSetup();
    storage.data.token = TOKEN;
    const posted = await connector.postReader({ id: "traffic", days: ["2026-11-13"] }, outcome.responses);
    expect(posted).toEqual({
      "traffic_overview:2026-11-13:confirmed": "posted",
      "traffic_overview:2026-11-13:placed": "posted",
      "shop_traffic:2026-11-13": "posted",
      "product_overview:2026-11-13:placed": "posted",
      "product_overview:2026-11-13:confirmed": "posted",
    });
    expect(client.posts.map((p) => p.dataset)).toEqual([
      "traffic_overview",
      "traffic_overview",
      "shop_traffic",
      "product_overview",
      "product_overview",
    ]);
    // an error answer is left out
    expect(mapTrafficJob([{ ...(outcome.responses[0] as ReaderResponse), body: { code: 10006 } }])).toEqual([]);
  });
});

describe("T11: no shop list in the Connector", () => {
  it("reads and schedules for the paired shop, whichever it is", () => {
    expect(readerActive("products", "any-paired-shop")).toBe(true);
    expect(schedulerActive("any-paired-shop")).toBe(true);
    expect(schedulerActive(undefined)).toBe(false);
  });

  it("keeps the token Juli issues (Juli never issues a code for the reviewer sample shop)", async () => {
    const { storage, client, connector } = connectorSetup();
    client.pairedAs = { ...TOKEN, shop_id: "any-paired-shop" };
    await connector.pair("ABCDE-FGHJK");
    expect((storage.data.token as { shop_id: string }).shop_id).toBe("any-paired-shop");
  });
});

describe("the tick report", () => {
  it("is sent with the token and the version; nothing before pairing", async () => {
    const { storage, client, connector } = connectorSetup();
    const report = { kind: "skip" as const, trigger: "boot", result: "backfill_busy", day: "2026-11-14", at: "2026-11-14T03:00:00.000Z" };
    await connector.reportTick(report);
    expect(client.ticks).toHaveLength(0);
    storage.data.token = TOKEN;
    await connector.reportTick(report);
    expect(client.ticks).toEqual([{ body: report, version: "0.3.19" }]);
  });

  it("the client trims what it sends and posts to /v1/ingest/connector-ticks", async () => {
    const calls: { url: string; body: Record<string, unknown> }[] = [];
    const client = new GatewayClient(async (url, init) => {
      calls.push({ url, body: JSON.parse(String(init?.body)) });
      return new Response("{}", { status: 202 });
    }, "https://api.example");
    await client.connectorTick(
      "t",
      { kind: "run", trigger: "daily", result: "finished", day: "2026-11-14", at: "x", outcomes: { orders: `done:${"x".repeat(400)}` } },
      "0.3.19",
    );
    expect(calls[0]!.url).toBe("https://api.example/v1/ingest/connector-ticks");
    expect(calls[0]!.body).toMatchObject({ platform: "shopee", kind: "run", trigger: "daily", day: "2026-11-14", source_version: "0.3.19" });
    expect(String((calls[0]!.body.outcomes as Record<string, string>).orders)).toHaveLength(160);
  });
});

describe("re-injection after an update", () => {
  it("the relay always; the hook only where fetch is still native (no hook left in the page)", () => {
    expect(reinjectPlan({ nativeFetch: false })).toEqual({ hook: false, relay: true });
    expect(reinjectPlan({ nativeFetch: true })).toEqual({ hook: true, relay: true });
    expect(reinjectPlan(undefined)).toEqual({ hook: false, relay: false });
  });

  it("skips discarded tabs and tabs that refuse, and goes on with the others", async () => {
    const done: string[] = [];
    const count = await reinjectSellerCentreTabs({
      sellerCentreTabs: async () => [{ id: 1 }, { id: 2, discarded: true }, { id: 3 }, { id: 4 }],
      probe: async (id) => {
        if (id === 3) throw new Error("cannot script");
        return { nativeFetch: id === 4 };
      },
      injectHook: async (id) => void done.push(`hook:${id}`),
      injectRelay: async (id) => void done.push(`relay:${id}`),
    });
    expect(count).toBe(2);
    expect(done).toEqual(["relay:1", "hook:4", "relay:4"]);
  });
});

describe("popup lines", () => {
  it("the last tick: when (GMT+7), what woke it, how it ended", () => {
    const readers = { adsDone: [], lastTick: { at: "2026-11-13T23:31:00.000Z", trigger: "stock_alarm", result: "stock:opened" } } as ReaderSchedule;
    expect(tickLine(readers)).toBe("Lượt gần nhất 14/11 06:31 (đọc tồn kho 06:30): bắt đầu đọc tồn kho");
    expect(tickLine({ adsDone: [] })).toBeNull();
    expect(tickResultLabel("backfill_busy")).toContain("thử lại");
  });

  it("the ads history line: progress, done, or where Seller Centre's history ends", () => {
    const days = ["2026-11-13", "2026-11-12", "2026-11-11"];
    const base = { shopId: "s1", createdAt: "x", days };
    expect(adsHistoryLine({ adsDone: [], adsHistory: { ...base, done: days.slice(0, 1), status: "running" } })).toBe("Quảng cáo 3 ngày trước: 1/3 ngày");
    expect(adsHistoryLine({ adsDone: [], adsHistory: { ...base, done: days, status: "done", earliest: "2026-11-11" } })).toBe("Quảng cáo 3 ngày trước: đã lấy đủ");
    expect(
      adsHistoryLine({ adsDone: [], adsHistory: { ...base, done: days.slice(0, 2), status: "done", earliest: "2026-11-12", limit: { day: "2026-11-11", code: "code_10006", at: "x" } } }),
    ).toBe("Quảng cáo các ngày trước: đã lấy đến 12/11/2026 (Seller Centre không giữ xa hơn)");
    expect(adsHistoryLine({ adsDone: [] })).toBeNull();
  });

  it("the stock line: when the product list with stock was last read", () => {
    expect(stockLine({ adsDone: [], productsAt: Date.parse("2026-11-13T23:31:00.000Z") })).toBe("Tồn kho đọc lúc 14/11 06:31 · mỗi ngày 06:30");
    expect(stockLine({ adsDone: [], stock: { day: "2026-11-14", attempts: 1, at: "2026-11-13T23:31:00.000Z", outcome: "needs_data_page" } })).toContain(
      "14/11 06:31",
    );
    expect(stockLine({ adsDone: [] })).toBe("Tồn kho: đọc mỗi ngày lúc 06:30");
  });
});
