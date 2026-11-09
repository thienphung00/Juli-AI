import { describe, expect, it } from "vitest";
import { Connector, type Tabs } from "../src/background/connector";
import { loadState, saveState } from "../src/background/state";
import { MAX_ROWS_PER_POST } from "../src/config";
import { GatewayClient, GatewayError, type IngestBody, type TokenInfo } from "../src/ingest/client";
import type { ReaderResponse } from "../src/shopee/reader";
import adsHome from "./fixtures/readers/ads_homepage.json";
import products1 from "./fixtures/readers/product_list.json";
import trafficDetails from "./fixtures/readers/traffic_details.json";
import vouchers from "./fixtures/readers/voucher_list.json";

const NOW = Date.UTC(2026, 10, 3, 3, 0, 0);
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
  drifts: { dataset: string; endpoint: string }[] = [];
  failWith: Error | null = null;
  async post(_token: string, dataset: string, body: IngestBody) {
    if (this.failWith) throw this.failWith;
    this.posts.push({ dataset, body });
    return { rows: body.rows.length, duplicate: false };
  }
  async reportDrift(_t: string, dataset: string, _v: string, endpoint: string) {
    this.drifts.push({ dataset, endpoint });
    return {};
  }
}

function setup(busy = false) {
  const storage = new MemoryStorage();
  storage.data.token = TOKEN;
  const client = new FakeClient(async () => new Response("{}"));
  const sent: unknown[] = [];
  const tabs: Tabs = {
    sellerCentreTabs: async () => [7],
    send: async (_id, message) => {
      sent.push(message);
      return undefined;
    },
  };
  const connector = new Connector({ storage, client, tabs, version: "0.3.4", now: () => NOW, busy: async () => busy });
  return { storage, client, connector, sent };
}

function response(endpoint: ReaderResponse["endpoint"], body: unknown, extra: Partial<ReaderResponse> = {}): ReaderResponse {
  return { endpoint, url: "u", status: 200, body, capturedAt: NOW, source: "replay", ...extra };
}

describe("postReader", () => {
  it("posts item_catalog (period, platform_items fields) and item_snapshot (the backend accepts it)", async () => {
    const { client, connector } = setup();
    const outcomes = await connector.postReader({ id: "products" }, [response("product_list", products1, { page: 1 })]);
    expect(outcomes).toEqual({ item_catalog: "posted", item_snapshot: "posted" });
    expect(client.posts.map((p) => p.dataset)).toEqual(["item_catalog", "item_snapshot"]);
    const body = client.posts[0]!.body;
    expect(body).toMatchObject({
      source: "extension",
      source_version: "0.3.4",
      period: { start: "2026-11-03", end: "2026-11-03", granularity: "period" },
      order_type: null,
    });
    expect(body.rows).toHaveLength(4);
  });

  it("item_traffic: one post per finished day, order_type confirmed, granularity day", async () => {
    const { client, connector } = setup();
    const answer = (day: string) => response("traffic_details", trafficDetails, { day, itemId: "1001" });
    const outcomes = await connector.postReader({ id: "item_traffic", days: ["2026-11-02", "2026-11-01"], itemIds: ["1001"] }, [
      answer("2026-11-02"),
      answer("2026-11-01"),
    ]);
    expect(outcomes).toEqual({ "item_traffic_sources:2026-11-01": "posted", "item_traffic_sources:2026-11-02": "posted" });
    expect(client.posts.map((p) => p.dataset)).toEqual(["item_traffic_sources", "item_traffic_sources"]);
    expect(client.posts[0]!.body).toMatchObject({
      period: { start: "2026-11-01", end: "2026-11-01", granularity: "day" },
      order_type: "confirmed",
    });
  });

  it("ads: one post per finished day with the order type; vouchers: a one-day snapshot period", async () => {
    const { client, connector } = setup();
    const outcomes = await connector.postReader({ id: "ads", days: ["2026-11-02"] }, [
      response("ads_homepage", adsHome, { day: "2026-11-02", usePaidGmv: false }),
    ]);
    // Connector 0.3.11: the same list answer also posts the campaigns' settings (capture day).
    expect(outcomes).toEqual({ "ads_campaign_daily:2026-11-02": "posted", "ads_campaign_settings:2026-11-03": "posted" });
    expect(client.posts[0]!.body).toMatchObject({
      period: { start: "2026-11-02", end: "2026-11-02", granularity: "day" },
      order_type: "placed",
    });
    await connector.postReader({ id: "vouchers" }, [response("voucher_list", vouchers, { page: 1 })]);
    const voucherPost = client.posts.find((p) => p.dataset === "voucher_settings");
    expect(voucherPost).toMatchObject({ dataset: "voucher_settings" });
    expect(voucherPost!.body.period.granularity).toBe("period");
  });

  it("splits a big list into posts of at most MAX_ROWS_PER_POST rows", async () => {
    const { client, connector } = setup();
    const many = {
      code: 0,
      data: {
        products: Array.from({ length: MAX_ROWS_PER_POST + 50 }, (_, i) => ({ id: 2000 + i, name: `p${i}`, price_detail: {}, model_list: [] })),
        total: MAX_ROWS_PER_POST + 50,
      },
    };
    await connector.postReader({ id: "products" }, [response("product_list", many, { page: 1 })]);
    expect(client.posts.map((p) => p.body.rows.length)).toEqual([MAX_ROWS_PER_POST, 50, MAX_ROWS_PER_POST, 50]);
  });

  it("drift stops that dataset (reported, nothing posted); a later run is 'stopped'", async () => {
    const { client, connector, storage } = setup();
    const bad = { code: 0, data: { voucher_list: [{ voucher_id: 5, start_time: 1790000000 }] } };
    expect(await connector.postReader({ id: "vouchers" }, [response("voucher_list", bad)])).toEqual({ voucher_settings: "drift" });
    expect(client.drifts).toEqual([{ dataset: "voucher_settings", endpoint: "voucher/list" }]);
    expect(client.posts).toEqual([]);
    expect((await loadState(storage)).stopped.voucher_settings?.missing).toEqual(["vouchers[].name"]);
    expect(await connector.postReader({ id: "vouchers" }, [response("voucher_list", vouchers)])).toEqual({ voucher_settings: "stopped" });
  });

  it("a network failure queues the chunk; a consent refusal stops; an unpaired shop sends nothing", async () => {
    const queued = setup();
    queued.client.failWith = new GatewayError(503, "unavailable");
    expect(await queued.connector.postReader({ id: "vouchers" }, [response("voucher_list", vouchers)])).toEqual({ voucher_settings: "queued" });
    expect((await loadState(queued.storage)).queue).toHaveLength(1);

    const refused = setup();
    refused.client.failWith = new GatewayError(403, "consent_required");
    expect(await refused.connector.postReader({ id: "vouchers" }, [response("voucher_list", vouchers)])).toEqual({ voucher_settings: "refused" });
    expect((await loadState(refused.storage)).consentBlocked).toBeTruthy();

    const unpaired = setup();
    await saveState(unpaired.storage, { token: undefined });
    expect(await unpaired.connector.postReader({ id: "vouchers" }, [response("voucher_list", vouchers)])).toEqual({ voucher_settings: "unpaired" });
  });
});

describe("a scheduled run holds the pace budget", () => {
  it("the daily sync and the backfill wait while a reader run is active", async () => {
    const busy = setup(true);
    expect(await busy.connector.dailySync()).toBe("busy");
    expect(await busy.connector.backfillStep()).toBe("busy");
    expect(busy.sent).toEqual([]);
    const free = setup(false);
    expect(await free.connector.dailySync()).toBe("requested");
  });

  it("reports a backfill day in flight to the scheduler", async () => {
    const { connector, storage } = setup();
    expect(await connector.backfillInFlight()).toBe(false);
    await connector.backfillStep();
    expect(await connector.backfillInFlight()).toBe(true);
    storage.data.backfill = { ...(storage.data.backfill as object), inFlight: { day: "x", at: NOW - 10 * 60_000 } };
    expect(await connector.backfillInFlight()).toBe(false); // timed out
  });
});
