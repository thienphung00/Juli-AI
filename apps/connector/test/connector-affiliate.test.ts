import { describe, expect, it } from "vitest";
import { Connector, type Tabs } from "../src/background/connector";
import { loadState } from "../src/background/state";
import { GatewayClient, GatewayError, type IngestBody, type TokenInfo } from "../src/ingest/client";
import { importOrderRefKey, orderRef } from "../src/ingest/order-ref";
import type { ReaderResponse } from "../src/shopee/reader";
import { gmt7DateStart } from "../src/shopee/time";

// 2026-11-06 09:00 GMT+7
const NOW = Date.UTC(2026, 10, 6, 2, 0, 0);
// A synthetic test key (not a secret): low entropy on purpose so secret scanners leave it alone.
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
  keyAnswer: () => Promise<unknown> = async () => ({ order_ref_key: KEY, algorithm: "HMAC-SHA256", key_version: 1 });
  async orderRefKey() {
    return this.keyAnswer();
  }
  async post(_token: string, dataset: string, body: IngestBody) {
    this.posts.push({ dataset, body });
    return { rows: body.rows.length, duplicate: false };
  }
}

const tabs: Tabs = { sellerCentreTabs: async () => [], send: async () => undefined };

function conversion(): ReaderResponse {
  return {
    endpoint: "affiliate_conversion",
    url: "https://banhang.shopee.vn/api/v3/affiliateplatform/conversion/report/list",
    status: 200,
    capturedAt: NOW,
    source: "replay",
    period: { start: "2026-10-07", end: "2026-11-05" },
    body: {
      code: 0,
      data: {
        total_count: 1,
        list: [
          {
            order_id: "261105GDSAEB5W",
            purchase_time: gmt7DateStart("2026-11-05") + 3600,
            shopee_username: "anhkienhcm01",
            items: [{ item_id: "24334416779", model_id: "340525665541", item_price: 12_636_000_000, dis_item_price: "₫126.360", qty: 1 }],
          },
        ],
      },
    },
  };
}

function setup() {
  const storage = new MemoryStorage();
  storage.data.token = TOKEN;
  const client = new FakeClient(async () => new Response("{}"));
  const connector = new Connector({ storage, client, tabs, version: "0.3.6", now: () => NOW });
  return { storage, client, connector };
}

describe("affiliate order lines in the service worker", () => {
  it("the order id is replaced by order_ref with the shop's key before the post; the raw id never leaves", async () => {
    const { client, connector } = setup();
    const outcomes = await connector.postReader({ id: "affiliate" }, [conversion()]);
    expect(outcomes).toEqual({ affiliate_order_lines: "posted" });
    expect(client.posts).toHaveLength(1);
    const body = client.posts[0]!.body;
    expect(body.period).toEqual({ start: "2026-10-07", end: "2026-11-05", granularity: "period" });
    const expected = await orderRef("261105GDSAEB5W", await importOrderRefKey(KEY));
    expect(body.rows[0]).toMatchObject({ order_ref: expected, item_id: "24334416779", price: 126360, affiliate_account: "anhkienhcm01" });
    const text = JSON.stringify(body);
    expect(text).not.toContain("261105GDSAEB5W");
    expect(text).not.toContain("__order_id__");
  });

  it("no key (503 / network): nothing is posted and the reason is recorded", async () => {
    const { storage, client, connector } = setup();
    client.keyAnswer = async () => {
      throw new GatewayError(503, "order_ref_key_not_configured");
    };
    const outcomes = await connector.postReader({ id: "affiliate" }, [conversion()]);
    expect(outcomes).toEqual({ affiliate_order_lines: "rejected" });
    expect(client.posts).toEqual([]);
    expect((await loadState(storage)).lastError?.code).toBe("order_ref_key_unavailable");
  });

  it("a row still carrying a raw order id is never submitted", async () => {
    const { client, connector } = setup();
    const outcome = await connector.submit(
      { dataset: "affiliate_order_lines", endpoint: "x", date: "2026-11-05", orderType: null, granularity: "period", rows: [{ __order_id__: "X1", item_id: "1" }], drift: null },
      NOW,
    );
    expect(outcome).toBe("rejected");
    expect(client.posts).toEqual([]);
  });
});
