// Connector 0.3.11 (P97 T1) in the service worker: new datasets are hashed and posted, the daily
// sync and the backfill share the request budget, a stop is told to Juli as a connector event.
import { describe, expect, it } from "vitest";
import { Connector, type Tabs } from "../src/background/connector";
import { addRequests, loadState, requestsLeft } from "../src/background/state";
import { DAILY_REQUEST_BUDGET, TODAY_REQUEST_RESERVE } from "../src/config";
import { GatewayClient, GatewayError, type IngestBody, type TokenInfo } from "../src/ingest/client";
import { importOrderRefKey, orderRef } from "../src/ingest/order-ref";
import type { ReaderResponse } from "../src/shopee/reader";
import { gmt7DateStart } from "../src/shopee/time";

// 2026-11-09 10:00 GMT+7
const NOW = Date.UTC(2026, 10, 9, 3, 0, 0);
const KEY = "ab".repeat(32);
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
  events: Record<string, unknown>[] = [];
  eventFails = false;
  async orderRefKey() {
    return { order_ref_key: KEY, algorithm: "HMAC-SHA256", key_version: 1 };
  }
  async post(_token: string, dataset: string, body: IngestBody) {
    this.posts.push({ dataset, body });
    return { rows: body.rows.length, duplicate: false };
  }
  async connectorEvent(_token: string, event: Record<string, unknown>, version: string) {
    if (this.eventFails) throw new GatewayError(500, "boom");
    this.events.push({ ...event, version });
    return {};
  }
}

function setup(tabIds: number[] = [7]) {
  const storage = new MemoryStorage();
  storage.data.token = TOKEN;
  const client = new FakeClient(async () => new Response("{}"));
  const sent: unknown[] = [];
  const tabs: Tabs = {
    sellerCentreTabs: async () => tabIds,
    send: async (_id, message) => {
      sent.push(message);
      return undefined;
    },
  };
  const connector = new Connector({ storage, client, tabs, version: "0.3.11", now: () => NOW });
  return { storage, client, connector, sent };
}

const ts = (day: string) => gmt7DateStart(day) + 12 * 3600;
const series = (values: Record<string, number>) => ({ points: Object.entries(values).map(([d, value]) => ({ timestamp: ts(d), value })) });

describe("new datasets through the service worker", () => {
  it("shop totals post one shop_overview per order type, keyed by order type", async () => {
    const { client, connector } = setup();
    const response: ReaderResponse = {
      endpoint: "shop_key_metrics",
      url: "u",
      status: 200,
      capturedAt: NOW,
      source: "replay",
      period: { start: "2026-11-07", end: "2026-11-08" },
      body: { code: 0, data: { confirmed_gmv: series({ "2026-11-07": 10, "2026-11-08": 20 }), confirmed_orders: series({ "2026-11-07": 1, "2026-11-08": 2 }), place_gmv: series({ "2026-11-07": 11, "2026-11-08": 21 }) } },
    };
    const outcomes = await connector.postReader({ id: "shop_totals", days: ["2026-11-08", "2026-11-07"] }, [response]);
    expect(outcomes).toEqual({ "shop_overview:confirmed": "posted", "shop_overview:placed": "posted" });
    expect(client.posts.map((p) => [p.dataset, p.body.order_type])).toEqual([["shop_overview", "confirmed"], ["shop_overview", "placed"]]);
    expect(client.posts[0]!.body.period).toEqual({ start: "2026-11-07", end: "2026-11-08", granularity: "day" });
  });

  it("order lines: the order number is hashed with the shop key; no raw id, buyer or address is posted", async () => {
    const { client, connector } = setup();
    const response: ReaderResponse = {
      endpoint: "order_cards",
      url: "u",
      status: 200,
      capturedAt: NOW,
      source: "page",
      body: {
        code: 0,
        data: {
          list: [
            {
              order_sn: "2611091SNAAAA",
              order_id: 5551234567890,
              status: "completed",
              create_time: ts("2026-11-08"),
              items: [{ item_id: 1, quantity: 1, original_price: 90_000, order_price: 90_000 }],
            },
          ],
        },
      },
    };
    const outcomes = await connector.postReader({ id: "orders" }, [response]);
    expect(outcomes).toEqual({ order_lines: "posted" });
    const expected = await orderRef("2611091SNAAAA", await importOrderRefKey(KEY));
    expect(client.posts[0]!.body.rows[0]).toMatchObject({ order_ref: expected, status: "delivered", qty: 1, deal_price: 90_000 });
    const text = JSON.stringify(client.posts[0]!.body);
    expect(text).not.toContain("2611091SNAAAA");
    expect(text).not.toContain("5551234567890");
    expect(text).not.toContain("__order_id__");
  });

  it("per-order income is hashed the same way (it joins the lines)", async () => {
    const { client, connector } = setup();
    const response: ReaderResponse = {
      endpoint: "order_income_components",
      url: "u",
      status: 200,
      capturedAt: NOW,
      source: "page",
      orderId: "5551234567890",
      orderSn: "2611091SNAAAA",
      body: { code: 0, data: { items: [{ name: "Số tiền cuối cùng", amount: 88_000 }, { name: "Phí Dịch Vụ", amount: -4_000 }] } },
    };
    const outcomes = await connector.postReader({ id: "order_income", orderIds: ["5551234567890"], orderSns: ["2611091SNAAAA"] }, [response]);
    expect(outcomes).toEqual({ order_income: "posted" });
    const expected = await orderRef("2611091SNAAAA", await importOrderRefKey(KEY));
    expect(client.posts[0]!.body.rows[0]).toEqual({ order_ref: expected, payout: 88_000, fee_service: 4_000 });
  });
});

describe("one request budget for every Seller Centre request", () => {
  it("requests are counted per GMT+7 day and reset with it", async () => {
    const storage = new MemoryStorage();
    await addRequests(storage, "2026-11-09", 30);
    await addRequests(storage, "2026-11-09", 12);
    const state = await loadState(storage);
    expect(requestsLeft(state, "2026-11-09")).toBe(DAILY_REQUEST_BUDGET - 42);
    expect(requestsLeft(state, "2026-11-10")).toBe(DAILY_REQUEST_BUDGET);
  });

  it("the daily sync counts what the page sent; with the budget spent it is not sent at all", async () => {
    const { storage, connector, sent } = setup();
    expect(await connector.dailySync()).toBe("requested");
    await connector.syncResult("done", 2);
    expect((await loadState(storage)).budget).toEqual({ day: "2026-11-09", used: 2 });
    await addRequests(storage, "2026-11-09", DAILY_REQUEST_BUDGET);
    storage.data.lastSync = { day: "2026-11-07", at: "x", status: "done" };
    sent.length = 0;
    expect(await connector.dailySync()).toBe("budget_spent");
    expect(sent).toEqual([]);
  });

  it("the backfill waits for tomorrow once today's budget is spent", async () => {
    const { storage, connector, sent } = setup();
    await addRequests(storage, "2026-11-09", DAILY_REQUEST_BUDGET - 1);
    expect(await connector.backfillStep()).toBe("budget_spent");
    expect(sent).toEqual([]);
  });
});

describe("0.3.15: today's traffic keeps a reserved share of the budget", () => {
  it("the backfill cannot spend the share reserved for today's readers", async () => {
    const { storage, connector, sent } = setup();
    // 400 - 150 reserved = 250 for the backfill; spend all of it, then the next day waits.
    await addRequests(storage, "2026-11-09", DAILY_REQUEST_BUDGET - TODAY_REQUEST_RESERVE - 1);
    expect(await connector.backfillStep()).toBe("budget_spent");
    expect(sent).toEqual([]);
    expect(requestsLeft(await loadState(storage), "2026-11-09")).toBe(TODAY_REQUEST_RESERVE + 1);
  });

  it("the daily sync (today) can still use the reserved share", async () => {
    const { storage, connector } = setup();
    await addRequests(storage, "2026-11-09", DAILY_REQUEST_BUDGET - TODAY_REQUEST_RESERVE);
    expect(await connector.dailySync()).toBe("requested");
  });

  it("a backfill with budget in its share still progresses", async () => {
    const { storage, connector, sent } = setup();
    await addRequests(storage, "2026-11-09", 100);
    expect(await connector.backfillStep()).not.toBe("budget_spent");
    expect(sent.length).toBeGreaterThan(0);
  });
});

describe("stops are told to Juli", () => {
  const block = { at: "x", reason: "rate_limit", page: "orders", until: NOW + 3_600_000 };

  it("while the readers are blocked neither the daily sync nor the backfill sends anything", async () => {
    const { storage, connector, sent } = setup();
    storage.data.readers = { adsDone: [], trafficDone: [], blocked: block };
    expect(await connector.dailySync()).toBe("blocked");
    expect(await connector.backfillStep()).toBe("blocked");
    expect(sent).toEqual([]);
    storage.data.readers = { adsDone: [], trafficDone: [], blocked: { ...block, until: NOW - 1 } };
    expect(await connector.dailySync()).toBe("requested");
  });

  it("reportBlock posts reader, page, status and time with the version; a failed post is swallowed", async () => {
    const { client, connector } = setup();
    await connector.reportBlock({ reader: "orders", page: "/portal/sale/order", status: "rate_limit", code: "http_429", at: "2026-11-09T03:00:00.000Z" });
    expect(client.events).toEqual([
      { reader: "orders", page: "/portal/sale/order", status: "rate_limit", code: "http_429", at: "2026-11-09T03:00:00.000Z", version: "0.3.11" },
    ]);
    client.eventFails = true;
    await expect(connector.reportBlock({ reader: "orders", page: "p", status: "captcha", at: "x" })).resolves.toBeUndefined();
  });

  it("the client sends the event to /v1/ingest/connector-events with the token and no body data", async () => {
    const calls: { url: string; init: RequestInit }[] = [];
    const client = new GatewayClient(async (url, init) => {
      calls.push({ url, init: init ?? {} });
      return new Response("{}", { status: 200 });
    }, "https://api.example");
    await client.connectorEvent("jci_x", { reader: "orders", page: "/portal/sale/order", status: "rate_limit", code: "http_429", at: "2026-11-09T03:00:00.000Z" }, "0.3.11");
    expect(calls[0]!.url).toBe("https://api.example/v1/ingest/connector-events");
    expect((calls[0]!.init.headers as Record<string, string>).Authorization).toBe("Bearer jci_x");
    expect(JSON.parse(calls[0]!.init.body as string)).toEqual({
      platform: "shopee",
      reader: "orders",
      page: "/portal/sale/order",
      status: "rate_limit",
      code: "http_429",
      occurred_at: "2026-11-09T03:00:00.000Z",
      source_version: "0.3.11",
    });
  });
});
