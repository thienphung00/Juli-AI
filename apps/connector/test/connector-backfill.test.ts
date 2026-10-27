import { describe, expect, it } from "vitest";
import { Connector, type Tabs } from "../src/background/connector";
import type { Backfill } from "../src/background/state";
import { GatewayClient, GatewayError, type IngestBody, type TokenInfo } from "../src/ingest/client";
import { backfillLabel, CONSENT_REQUIRED_MESSAGE } from "../src/popup/labels";
import type { RequestResult } from "../src/shopee/runner";
import type { PlannedRequest } from "../src/shopee/sync";
import shopTraffic from "./fixtures/shop_traffic.json";
import overview from "./fixtures/traffic_overview.json";

const START = Date.UTC(2026, 9, 26, 3, 0, 0); // 2026-10-26 10:00 GMT+7
const SC = "https://banhang.shopee.vn";

const TOKEN: TokenInfo = {
  token: "jci_x",
  token_id: "t1",
  shop_id: "s1",
  platform: "shopee",
  expires_at: "2027-01-10T00:00:00Z",
  rotate_after: "2026-11-25T00:00:00Z",
};

class MemoryStorage {
  data: Record<string, unknown> = {};
  async get(keys?: string | string[] | null) {
    const list = keys == null ? Object.keys(this.data) : Array.isArray(keys) ? keys : [keys];
    return Object.fromEntries(list.filter((k) => this.data[k] != null).map((k) => [k, this.data[k]]));
  }
  async set(items: Record<string, unknown>) {
    Object.assign(this.data, JSON.parse(JSON.stringify(items)));
  }
}

class FakeClient extends GatewayClient {
  posts: { dataset: string; body: IngestBody }[] = [];
  failWith: Error | null = null;
  async post(_token: string, dataset: string, body: IngestBody) {
    if (this.failWith) throw this.failWith;
    this.posts.push({ dataset, body });
    return { rows: body.rows.length, duplicate: false };
  }
  async reportDrift() {
    return {};
  }
}

interface BackfillMessage {
  type: "backfill";
  day: string;
  plan: PlannedRequest[];
}

function setup(storage = new MemoryStorage(), version = "0.2.0") {
  const clock = { now: START };
  const client = new FakeClient(async () => new Response("{}"));
  const sent: BackfillMessage[] = [];
  const tabIds = [7];
  const tabs: Tabs = {
    sellerCentreTabs: async () => tabIds,
    send: async (_id, message) => {
      sent.push(message as BackfillMessage);
      return undefined;
    },
  };
  const connector = new Connector({ storage, client, tabs, version, now: () => clock.now });
  storage.data.token ??= TOKEN;
  return { storage, client, sent, connector, clock, tabIds };
}

const BODIES = { traffic_overview: overview, shop_traffic: shopTraffic } as Record<string, unknown>;

/** What the page hook would answer for a backfill message, with data for every call. */
function answer(message: BackfillMessage, capturedAt: number, override: Partial<Record<string, Partial<RequestResult>>> = {}) {
  return message.plan.map((request) => ({
    dataset: request.dataset,
    url: `${SC}${request.path}?${new URLSearchParams(request.params).toString()}`,
    status: 200,
    body: BODIES[request.dataset],
    capturedAt,
    ...override[request.dataset],
  })) as RequestResult[];
}

const backfillOf = (storage: MemoryStorage) => storage.data.backfill as Backfill;

/** Step, answer with data, repeat `days` times (or until nothing is sent). */
async function runDays(t: ReturnType<typeof setup>, days: number) {
  for (let i = 0; i < days; i += 1) {
    const before = t.sent.length;
    const step = await t.connector.backfillStep();
    if (step !== "requested" || t.sent.length === before) return step;
    const message = t.sent.at(-1)!;
    t.clock.now += 2 * 2_500; // two paced calls
    expect(await t.connector.backfillResult(message.day, "done", answer(message, t.clock.now))).toBe("accepted");
  }
  return "ran";
}

describe("30-day backfill", () => {
  it("fetches 30 days newest → oldest, one day per round trip, then stops for good", async () => {
    const t = setup();
    await runDays(t, 40);
    const days = t.sent.map((m) => m.day);
    expect(days).toHaveLength(30);
    expect(days[0]).toBe("2026-10-25");
    expect(days[29]).toBe("2026-09-26");
    expect(new Set(days).size).toBe(30);
    // yesterday as "Hôm qua", older days as "Theo ngày"; shop traffic by dt.
    expect(t.sent[0]!.plan[0]!.params.period).toBe("yesterday");
    expect(t.sent[1]!.plan[0]!.params).toMatchObject({ period: "day" });
    expect(Number(t.sent[1]!.plan[0]!.params.end_time) - Number(t.sent[1]!.plan[0]!.params.start_time)).toBe(86400);
    expect(t.sent[5]!.plan[1]!.params).toEqual({ period: "day", dt: days[5]!.replaceAll("-", "") });
    // 2 datasets × 30 days, each post for its own day.
    expect(t.client.posts).toHaveLength(60);
    expect(t.client.posts.filter((p) => p.dataset === "shop_traffic").map((p) => p.body.period.start)).toEqual(days);
    expect(backfillOf(t.storage).status).toBe("done");
    expect(await t.connector.backfillStep()).toBe("done");
    expect(t.sent).toHaveLength(30);
    expect(backfillLabel(backfillOf(t.storage))).toBe("Đã lấy đủ số liệu 30 ngày trước");
  });

  it("resumes after the browser closed mid-way and never re-sends an accepted day", async () => {
    const storage = new MemoryStorage();
    const first = setup(storage);
    await runDays(first, 10);
    expect(await first.connector.backfillStep()).toBe("requested"); // day 11 sent, then the browser closes
    const lost = first.sent.at(-1)!.day;
    expect(backfillLabel(backfillOf(storage))).toBe("Đang lấy số liệu 30 ngày trước: 10/30 ngày · cần mở Seller Centre");

    // A new service worker, same chrome.storage, the next morning.
    const second = setup(storage);
    second.clock.now = START + 20 * 3600_000;
    expect(await second.connector.backfillStep()).toBe("requested");
    expect(second.sent[0]!.day).toBe(lost);
    // A stale answer for a day that is no longer in flight is ignored.
    expect(await second.connector.backfillResult("2026-10-25", "done", answer(first.sent[0]!, second.clock.now))).toBe(
      "stale",
    );
    await second.connector.backfillResult(lost, "done", answer(second.sent[0]!, second.clock.now));
    await runDays(second, 40);
    const all = [...first.sent.slice(0, 10), ...second.sent].map((m) => m.day);
    expect(new Set(all).size).toBe(30);
    expect(all).toHaveLength(30);
    expect(first.client.posts.length + second.client.posts.length).toBe(60);
  });

  it("does not send a second day while one is in flight; re-sends after the timeout", async () => {
    const t = setup();
    expect(await t.connector.backfillStep()).toBe("requested");
    expect(await t.connector.backfillStep()).toBe("in_flight");
    expect(t.sent).toHaveLength(1);
    t.clock.now += 3 * 60_000 + 1;
    expect(await t.connector.backfillStep()).toBe("requested");
    expect(t.sent.map((m) => m.day)).toEqual(["2026-10-25", "2026-10-25"]);
  });

  it("waits for a Seller Centre tab and for the page's first data call", async () => {
    const t = setup();
    t.tabIds.length = 0;
    expect(await t.connector.backfillStep()).toBe("no_tab");
    t.tabIds.push(7);
    expect(await t.connector.backfillStep()).toBe("requested");
    expect(await t.connector.backfillResult(t.sent[0]!.day, "needs_data_page", [])).toBe("needs_data_page");
    expect(await t.connector.backfillStep()).toBe("needs_data_page"); // no message loop
    expect(t.sent).toHaveLength(1);
    const url = `${SC}/api/mydata/v1/product/traffic/overview/?start_time=1790787600&end_time=1790874000&period=day&order_type=confirmed`;
    await t.connector.pageCapture({ url, body: overview, capturedAt: t.clock.now });
    expect(await t.connector.backfillStep()).toBe("requested");
  });

  it("stops on code 10006 for a day, records it, and does not loop; a new version retries", async () => {
    const storage = new MemoryStorage();
    const t = setup(storage);
    await runDays(t, 2);
    await t.connector.backfillStep();
    const message = t.sent.at(-1)!;
    const results = answer(message, t.clock.now, {
      traffic_overview: { body: { code: 10006, msg: "err:invalid param, detail:unknown error" } },
    }).slice(0, 1); // the hook stops at the first non-data answer
    expect(await t.connector.backfillResult(message.day, "done", results)).toBe("stopped:invalid_param");
    expect(backfillOf(storage).stop).toMatchObject({ reason: "invalid_param", day: message.day, code: "10006" });
    expect(storage.data.lastError).toMatchObject({ code: "shopee_10006" });
    expect(await t.connector.backfillStep()).toBe("stopped");
    t.clock.now += 24 * 3600_000;
    expect(await t.connector.backfillStep()).toBe("stopped");
    expect(t.sent).toHaveLength(3);
    expect(backfillLabel(backfillOf(storage))).toContain("Seller Centre đã thay đổi");

    const upgraded = setup(storage, "0.2.1");
    expect(await upgraded.connector.backfillStep()).toBe("requested");
    expect(upgraded.sent[0]!.day).toBe(message.day);
  });

  it("stops on a Seller Centre session error until the page loads data again", async () => {
    const t = setup();
    await t.connector.backfillStep();
    const message = t.sent[0]!;
    const results = answer(message, t.clock.now, { traffic_overview: { status: 403, body: null } }).slice(0, 1);
    expect(await t.connector.backfillResult(message.day, "done", results)).toBe("stopped:session");
    expect(await t.connector.backfillStep()).toBe("stopped");
    expect(backfillLabel(backfillOf(t.storage))).toContain("đăng nhập lại Seller Centre");
    // A login page (HTML, not JSON) is a session error too.
    const url = `${SC}/api/mydata/traffic/dashboard/overview/?period=day&dt=20261001`;
    await t.connector.pageCapture({ url, body: { code: 0, msg: "ok", result: shopTraffic.result }, capturedAt: t.clock.now });
    expect(await t.connector.backfillStep()).toBe("requested");
    const login = answer(t.sent[1]!, t.clock.now, { traffic_overview: { status: 200, body: null } }).slice(0, 1);
    expect(await t.connector.backfillResult(t.sent[1]!.day, "done", login)).toBe("stopped:session");
  });

  it("stops on a Juli 401 (token gone) and resumes the same shop after pairing again", async () => {
    const t = setup();
    await runDays(t, 1);
    await t.connector.backfillStep();
    t.client.failWith = new GatewayError(401, "invalid_token");
    const message = t.sent.at(-1)!;
    expect(await t.connector.backfillResult(message.day, "done", answer(message, t.clock.now))).toBe("stopped:unpaired");
    expect(t.storage.data.token).toBeNull();
    t.client.failWith = null;
    t.client.pair = async () => TOKEN;
    await t.connector.pair("ABCDE-FGHJK");
    expect(await t.connector.backfillStep()).toBe("requested");
    expect(t.sent.at(-1)!.day).toBe(message.day);
    expect(backfillOf(t.storage).done).toEqual(["2026-10-25"]);
  });

  it("retries a day after transient Seller Centre failures, then stops after 3", async () => {
    const t = setup();
    for (let attempt = 1; attempt <= 3; attempt += 1) {
      expect(await t.connector.backfillStep()).toBe("requested");
      const message = t.sent.at(-1)!;
      const results = answer(message, t.clock.now, { traffic_overview: { status: 502, body: null } }).slice(0, 1);
      const outcome = await t.connector.backfillResult(message.day, "done", results);
      expect(outcome).toBe(attempt < 3 ? "retry_later" : "stopped:shopee_error");
      if (attempt < 3) {
        expect(await t.connector.backfillStep()).toBe("waiting");
        t.clock.now += 10 * 60_000;
      }
    }
    expect(t.sent).toHaveLength(3);
    expect(await t.connector.backfillStep()).toBe("stopped");
  });
});

describe("gateway refusal: 403 consent_required (PR #2199)", () => {
  const URL_OK = `${SC}/api/mydata/v1/product/traffic/overview/?start_time=1790787600&end_time=1790874000&period=day&order_type=confirmed`;

  it("stops the backfill and every post, without retrying, until the seller retries", async () => {
    const t = setup();
    await t.connector.backfillStep();
    const message = t.sent[0]!;
    t.client.failWith = new GatewayError(403, "consent_required");
    expect(await t.connector.backfillResult(message.day, "done", answer(message, t.clock.now))).toBe(
      "stopped:consent_required",
    );
    expect(t.storage.data.consentBlocked).toBeTruthy();
    expect(t.storage.data.queue ?? []).toEqual([]); // not queued for retry
    expect(backfillLabel(backfillOf(t.storage))).toContain("shop chưa được cấp quyền đồng bộ");
    expect(CONSENT_REQUIRED_MESSAGE).toContain("chưa được cấp quyền đồng bộ");

    // Nothing else is sent while refused: passive captures, the daily sync, the backfill.
    t.client.failWith = null;
    expect(await t.connector.handleCapture({ url: URL_OK, body: overview, capturedAt: t.clock.now })).toBe("refused");
    expect(await t.connector.dailySync()).toBe("consent_required");
    expect(await t.connector.backfillStep()).toBe("consent_required");
    expect(t.client.posts).toEqual([]);
    expect(t.sent).toHaveLength(1);

    // The seller presses "Đồng bộ hôm qua" once the shop has consent.
    await t.connector.syncNow();
    expect(t.storage.data.consentBlocked).toBeNull();
    expect(await t.connector.backfillStep()).toBe("requested");
    expect(t.sent.at(-1)!.day).toBe(message.day);
  });

  it("a refused passive capture is a stop, not a queued retry", async () => {
    const t = setup();
    t.client.failWith = new GatewayError(403, "consent_required");
    expect(await t.connector.handleCapture({ url: URL_OK, body: overview, capturedAt: t.clock.now })).toBe("refused");
    expect(t.storage.data.queue ?? []).toEqual([]);
    expect(t.storage.data.lastError).toMatchObject({ code: "consent_required" });
    // Other 403s stay plain rejections.
    const other = setup();
    other.client.failWith = new GatewayError(403, "platform_not_allowed");
    expect(await other.connector.handleCapture({ url: URL_OK, body: overview, capturedAt: other.clock.now })).toBe(
      "rejected",
    );
    expect(other.storage.data.consentBlocked).toBeUndefined();
  });
});
