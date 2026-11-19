import { describe, expect, it } from "vitest";
import { mapCaptured, mapCapturedAll } from "../src/platforms/shopee/map";
import { isDataAnswer } from "../src/platforms/shopee/runner";
import { buildBackfillDayPlan, buildSyncPlan } from "../src/platforms/shopee/sync";
import { mapTrafficJob } from "../src/platforms/shopee/reader-map";
import { gmt7DateStart } from "../src/core/time";

const NOW = Date.UTC(2026, 10, 19, 3, 0, 0);
const START = gmt7DateStart("2026-11-18");
const URL = `https://banhang.shopee.vn/api/mydata/v2/product/overview/?start_time=${START}&end_time=${START + 86400}&period=day`;
const m = (value: number) => ({ value, ratio: 0.1 });

// Made-up numbers in the captured flat shape.
const body = () => ({
  uv: m(1200),
  pv: m(1500),
  iv: m(90),
  bounce_rate: m(0.4),
  bounce_visitors: m(480),
  search_clicks: m(300),
  like_unit_num: m(12),
  atc_uv: m(100),
  atc_unit_num: m(130),
  atc_rate: m(0.083),
  placed_buyers: m(40),
  placed_gmv: m(8_000_000),
  placed_items: m(35),
  placed_orders: m(41),
  placed_unit_num: m(55),
  confirmed_buyers: m(30),
  confirmed_gmv: m(6_000_000),
  confirmed_items: m(28),
  confirmed_unit_num: m(44),
  uv_to_placed_buyers_rate: m(0.033),
  uv_to_confirmed_buyers_rate: m(0.025),
  placed_buyers_to_confirmed_buyers_rate: m(0.75),
  paid_buyers: m(10),
});

describe("F4.8 product_overview (flat answer, file-import field names)", () => {
  it("posts one post per order type with the file fields; ratio is not stored", () => {
    const [placed, confirmed] = mapCapturedAll({ url: URL, body: body(), capturedAt: NOW });
    expect([placed!.orderType, confirmed!.orderType]).toEqual(["placed", "confirmed"]);
    expect(placed).toMatchObject({ dataset: "product_overview", date: "2026-11-18", drift: null });
    expect(placed!.rows).toEqual([
      {
        date: "2026-11-18",
        product_visitors: 1200,
        product_page_views: 1500,
        products_visited: 90,
        bounced_visitors: 480,
        bounce_rate: 0.4,
        search_clicks: 300,
        likes: 12,
        atc_visitors: 100,
        atc_units: 130,
        atc_rate: 0.083,
        buyers: 40,
        units: 55,
        products_sold: 35,
        sales: 8_000_000,
        conversion_rate: 0.033,
      },
    ]);
    expect(confirmed!.rows[0]).toMatchObject({
      buyers: 30,
      units: 44,
      products_sold: 28,
      sales: 6_000_000,
      conversion_rate: 0.025,
      product_visitors: 1200,
      extra: { placed_to_confirmed_rate: 0.75 },
    });
    expect(JSON.stringify(placed)).not.toContain("ratio");
    expect(mapCaptured({ url: URL, body: body(), capturedAt: NOW })?.orderType).toBe("placed");
  });

  it("omits the -1000000 sentinel and an out-of-range rate", () => {
    const b = { ...body(), placed_gmv: m(-1_000_000), atc_rate: m(7) };
    const [placed] = mapCapturedAll({ url: URL, body: b, capturedAt: NOW });
    expect("sales" in placed!.rows[0]!).toBe(false);
    expect("atc_rate" in placed!.rows[0]!).toBe(false);
    expect(placed!.rows[0]).toMatchObject({ buyers: 40 });
  });

  it("ignores today's real_time page call and error answers; reports an unknown shape as drift", () => {
    const rt = `https://banhang.shopee.vn/api/mydata/v2/product/overview/?start_time=${START}&end_time=${START + 86400}&period=real_time`;
    expect(mapCapturedAll({ url: rt, body: body(), capturedAt: NOW })).toEqual([]);
    expect(mapCapturedAll({ url: URL, body: { code: 10006, msg: "x" }, capturedAt: NOW })).toEqual([]);
    const drift = mapCapturedAll({ url: URL, body: { something: { value: 1 } }, capturedAt: NOW });
    expect(drift[0]!.drift?.missing).toEqual(["uv"]);
    expect(drift[0]!.rows).toEqual([]);
  });

  it("is in the daily plan and the backfill day plan, one request, the page's own day shape", () => {
    for (const plan of [buildSyncPlan(NOW, new Set()), buildBackfillDayPlan("2026-11-10", NOW, new Set())]) {
      const reqs = plan.filter((p) => p.dataset === "product_overview");
      expect(reqs).toHaveLength(1);
      const start = Number(reqs[0]!.params.start_time);
      expect(reqs[0]!.path).toBe("/api/mydata/v2/product/overview/");
      expect(reqs[0]!.params).toMatchObject({ period: "day", end_time: String(start + 86400) });
    }
    expect(buildBackfillDayPlan("2026-11-10", NOW, new Set(["product_overview"] as const)).some((p) => p.dataset === "product_overview")).toBe(false);
  });

  it("the day runner counts a flat answer as data (it must not stop the day)", () => {
    expect(isDataAnswer(200, body())).toBe(true);
    expect(isDataAnswer(200, { code: 10006 })).toBe(false);
    expect(isDataAnswer(200, {})).toBe(false);
  });

  it("the traffic reader job maps it too", () => {
    const posts = mapTrafficJob([
      { endpoint: "product_overview", url: URL, status: 200, body: body(), capturedAt: NOW, day: "2026-11-18", source: "replay" },
    ]);
    expect(posts.map((p) => [p.dataset, p.orderType])).toEqual([
      ["product_overview", "placed"],
      ["product_overview", "confirmed"],
    ]);
  });
});
