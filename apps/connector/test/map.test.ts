import { describe, expect, it } from "vitest";
import { mapCaptured, toSeconds } from "../src/shopee/map";
import itemList from "./fixtures/item_list.json";
import performance from "./fixtures/product_performance.json";
import shopTraffic from "./fixtures/shop_traffic.json";
import overview from "./fixtures/traffic_overview.json";

const NOW = Date.UTC(2026, 9, 12, 3, 0, 0);
const Y_START = Date.UTC(2026, 9, 10, 17, 0, 0) / 1000;
const RANGE = `start_time=${Y_START}&end_time=${Y_START + 86399}&period=yesterday`;
const SC = "https://banhang.shopee.vn";

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function capture(path: string, query: string, body: unknown) {
  return mapCaptured({ url: `${SC}${path}?${query}`, body, capturedAt: NOW });
}

describe("traffic overview → shopee.traffic_overview", () => {
  const url = "/api/mydata/v1/product/traffic/overview/";

  it("maps one row per L1 source, ratios to extra, comparisons dropped", () => {
    const mapped = capture(url, `${RANGE}&order_type=confirmed`, overview);
    expect(mapped?.drift).toBeNull();
    expect(mapped?.dataset).toBe("traffic_overview");
    expect(mapped?.date).toBe("2026-10-11");
    expect(mapped?.orderType).toBe("confirmed");
    expect(mapped?.rows.map((r) => r.source)).toEqual([
      "psd_label_product_card",
      "psd_label_seller_live",
      "psd_label_seller_video",
      "psd_label_affiliate",
      "psd_label_shopee_ads",
    ]);
    const card = mapped!.rows[0]!;
    expect(card).toMatchObject({ date: "2026-10-11", sales: 1000000, orders: 3.5, product_impressions: 3000, ctr: 0.05 });
    expect(card.extra).toMatchObject({ sales_ratio: 0.2 });
    expect(Object.keys(card).some((k) => k.endsWith("_pct_diff"))).toBe(false);
    const ads = mapped!.rows[4]!;
    expect(ads).toMatchObject({ ads_expense: 50000, ads_roas: 4, conversion: 0.0167 });
  });

  it("reports an unexpected field as drift", () => {
    const body = clone(overview);
    (body.result.product_card.total as Record<string, unknown>).new_metric = 1;
    const mapped = capture(url, RANGE, body);
    expect(mapped?.drift?.unexpected).toEqual(["result.product_card.new_metric"]);
  });

  it("reports a missing field, a new source key and a renamed enum as drift", () => {
    const body = clone(overview) as unknown as { result: Record<string, { total: Record<string, unknown> }> };
    delete body.result.product_card!.total.product_impressions;
    body.result.live!.total.source = "psd_label_live_v2";
    (body.result as Record<string, unknown>).shop_tab = { total: {}, breakdown: [] };
    const drift = capture(url, RANGE, body)?.drift;
    expect(drift?.missing).toContain("result.product_card.product_impressions");
    expect(drift?.unexpected).toContain("result.live.source=psd_label_live_v2");
    expect(drift?.unexpected).toContain("result.shop_tab");
  });

  it("treats a percentage where a fraction is expected as drift", () => {
    const body = clone(overview);
    body.result.video.total.ctr = 5;
    expect(capture(url, RANGE, body)?.drift?.unexpected).toEqual(["result.video.ctr:not_a_fraction"]);
  });

  it("ignores errors, partial days, aggregates and other origins", () => {
    expect(capture(url, RANGE, { code: 1001, msg: "err", result: null })).toBeNull();
    expect(capture(url, "period=real_time", overview)).toBeNull();
    expect(capture(url, "period=past30days", overview)).toBeNull();
    expect(mapCaptured({ url: `https://evil.example${url}?${RANGE}`, body: overview, capturedAt: NOW })).toBeNull();
    expect(capture("/api/mydata/v2/product/overview/", RANGE, overview)).toBeNull();
  });

  it("flags a response without the {code,msg,result} wrapper", () => {
    expect(capture(url, RANGE, { overview: {} })?.drift?.missing).toEqual(["code", "result"]);
  });
});

describe("traffic dashboard → shopee.shop_traffic", () => {
  it("maps one row per device; hh:mm:ss to seconds; '-' dropped", () => {
    const mapped = capture("/api/mydata/traffic/dashboard/overview/", "period=yesterday", shopTraffic);
    expect(mapped?.drift).toBeNull();
    expect(mapped?.orderType).toBeNull();
    expect(mapped?.rows).toHaveLength(3);
    expect(mapped?.rows[0]).toMatchObject({ device: "all", visitors: 120, avg_stay_time: 90, new_followers: 5 });
    expect(mapped?.rows[1]).not.toHaveProperty("new_followers");
    expect(toSeconds("01:02:03")).toBe(3723);
  });

  it("maps nothing while Seller Centre says the data is not ready", () => {
    const body = clone(shopTraffic);
    body.result.data_ready = false;
    expect(capture("/api/mydata/traffic/dashboard/overview/", "period=yesterday", body)?.rows).toEqual([]);
  });
});

describe("item lists (provisional until D31.6)", () => {
  it("maps item × source rows with known metric names, the rest to extra", () => {
    const mapped = capture(
      "/api/mydata/v1/product/traffic/item-list/",
      `${RANGE}&l1_source=psd_label_product_card&page_num=1&page_size=10&order_type=confirmed`,
      itemList,
    );
    expect(mapped?.drift).toBeNull();
    expect(mapped?.rows[0]).toMatchObject({
      item_id: "111222333",
      item_name: "Sản phẩm mẫu A",
      source: "psd_label_product_card",
      sales: 300000,
      orders: 1.5,
    });
    expect(mapped?.rows[0]?.extra).toEqual({ sales_ratio: 0.3, image: "x.jpg" });
    expect(mapped?.rows[1]?.item_id).toBe("444555666");
  });

  it("strips the order-type prefix on item performance and keeps other order types aside", () => {
    const mapped = capture("/api/mydata/v4/product/performance/", `${RANGE}&order_type=confirmed`, performance);
    expect(mapped?.rows[0]).toMatchObject({
      item_id: "111222333",
      sales: 300000,
      orders: 1.5,
      units: 2,
      product_impressions: 900,
      product_clicks: 30,
      uv: 25,
      atc_uv: 4,
      atc_rate: 0.16,
    });
    expect(mapped?.rows[0]?.extra).toEqual({ placed_sales: 350000, status: 1 });
  });

  it("an item without an id is drift", () => {
    const body = clone(itemList) as unknown as { result: { item: Record<string, unknown>[] } };
    delete body.result.item[0]!.item_id;
    const mapped = capture(
      "/api/mydata/v1/product/traffic/item-list/",
      `${RANGE}&l1_source=psd_label_product_card`,
      body,
    );
    expect(mapped?.drift?.missing).toEqual(["result.item[].item_id"]);
  });
});
