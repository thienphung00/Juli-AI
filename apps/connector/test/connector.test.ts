import { describe, expect, it } from "vitest";
import { Connector, type Tabs } from "../src/background/connector";
import { GatewayClient, GatewayError, type IngestBody, type TokenInfo } from "../src/ingest/client";
import overview from "./fixtures/traffic_overview.json";

const NOW = Date.UTC(2026, 9, 12, 3, 0, 0);
const Y_START = Date.UTC(2026, 9, 10, 17, 0, 0) / 1000;
const URL_OK = `https://banhang.shopee.vn/api/mydata/v1/product/traffic/overview/?start_time=${Y_START}&end_time=${Y_START + 86399}&period=yesterday&order_type=confirmed`;

const TOKEN: TokenInfo = {
  token: "jci_x",
  token_id: "t1",
  shop_id: "s1",
  platform: "shopee",
  expires_at: "2027-01-10T00:00:00Z",
  rotate_after: "2026-11-11T00:00:00Z",
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
  drifts: unknown[] = [];
  failWith: Error | null = null;
  async post(_token: string, dataset: string, body: IngestBody) {
    if (this.failWith) throw this.failWith;
    this.posts.push({ dataset, body });
    return { rows: body.rows.length, duplicate: false };
  }
  async reportDrift(...args: unknown[]) {
    this.drifts.push(args);
    return {};
  }
  async rotate() {
    return { ...TOKEN, token: "jci_y" };
  }
}

function setup(tabIds: number[] = []) {
  const storage = new MemoryStorage();
  const client = new FakeClient(async () => new Response("{}"));
  const sent: unknown[] = [];
  const tabs: Tabs = {
    sellerCentreTabs: async () => tabIds,
    send: async (_id, message) => {
      sent.push(message);
      return undefined;
    },
  };
  const connector = new Connector({ storage, client, tabs, version: "0.1.0", now: () => NOW });
  return { storage, client, sent, connector };
}

describe("captured responses", () => {
  it("does nothing before pairing", async () => {
    const { connector, client } = setup();
    expect(await connector.handleCapture({ url: URL_OK, body: overview, capturedAt: NOW })).toBe("unpaired");
    expect(client.posts).toEqual([]);
  });

  it("posts the mapped day with the extension's version", async () => {
    const { connector, client, storage } = setup();
    storage.data.token = TOKEN;
    expect(await connector.handleCapture({ url: URL_OK, body: overview, capturedAt: NOW })).toBe("posted");
    const post = client.posts[0]!;
    expect(post.dataset).toBe("traffic_overview");
    expect(post.body).toMatchObject({
      source: "extension",
      source_version: "0.1.0",
      period: { start: "2026-10-11", end: "2026-10-11", granularity: "day" },
      order_type: "confirmed",
    });
    expect(post.body.rows).toHaveLength(5);
    expect(JSON.stringify(post.body)).not.toContain("SPC_CDS");
  });

  it("reports drift once, then stops that dataset for this version", async () => {
    const { connector, client, storage } = setup();
    storage.data.token = TOKEN;
    const drifted = JSON.parse(JSON.stringify(overview));
    drifted.result.product_card.total.brand_new = 1;
    expect(await connector.handleCapture({ url: URL_OK, body: drifted, capturedAt: NOW })).toBe("drift");
    expect(client.drifts).toHaveLength(1);
    expect(await connector.handleCapture({ url: URL_OK, body: overview, capturedAt: NOW })).toBe("stopped");
    expect(client.posts).toEqual([]);
  });

  it("forgets a token the gateway no longer accepts", async () => {
    const { connector, client, storage } = setup();
    storage.data.token = TOKEN;
    client.failWith = new GatewayError(401, "invalid_token");
    expect(await connector.handleCapture({ url: URL_OK, body: overview, capturedAt: NOW })).toBe("unpaired");
    expect(storage.data.token).toBeNull();
  });

  it("queues a post that failed on the network, and stops on dataset_in_drift", async () => {
    const { connector, client, storage } = setup();
    storage.data.token = TOKEN;
    client.failWith = new TypeError("Failed to fetch");
    expect(await connector.handleCapture({ url: URL_OK, body: overview, capturedAt: NOW })).toBe("queued");
    expect((storage.data.queue as unknown[]).length).toBe(1);
    client.failWith = null;
    await connector.flushQueue();
    expect(storage.data.queue).toEqual([]);
    expect(client.posts).toHaveLength(1);
    client.failWith = new GatewayError(409, "dataset_in_drift");
    expect(await connector.handleCapture({ url: URL_OK, body: overview, capturedAt: NOW })).toBe("stopped");
  });
});

describe("daily sync", () => {
  it("waits for a Seller Centre tab, then asks it for yesterday", async () => {
    const none = setup([]);
    none.storage.data.token = TOKEN;
    expect(await none.connector.dailySync()).toBe("no_tab");
    expect(none.storage.data.pendingSync).toBe(true);

    const open = setup([7]);
    open.storage.data.token = TOKEN;
    open.storage.data.pendingSync = true;
    expect(await open.connector.tabReady()).toBe("requested");
    expect((open.sent[0] as { type: string }).type).toBe("sync");
    await open.connector.syncResult("done");
    expect(await open.connector.dailySync()).toBe("already_synced");
  });

  it("rotates the token once it is due", async () => {
    const { connector, storage } = setup();
    storage.data.token = { ...TOKEN, rotate_after: "2026-10-01T00:00:00Z" };
    await connector.rotateIfDue();
    expect((storage.data.token as TokenInfo).token).toBe("jci_y");
  });
});
