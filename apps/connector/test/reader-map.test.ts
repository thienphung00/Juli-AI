import { describe, expect, it } from "vitest";
import { ingestBody } from "../src/ingest/client";
import type { ReaderResponse } from "../src/shopee/reader";
import {
  activeItemIds,
  campaignCounts,
  completedTrafficDays,
  mapAdsDaily,
  mapItemTraffic,
  mapProductList,
  mapReaderJob,
  mapShopHealth,
  mapVoucherList,
  numberIn,
  passedOf,
  roasTarget,
} from "../src/shopee/reader-map";
import adsHome from "./fixtures/readers/ads_homepage.json";
import adsGraph from "./fixtures/readers/ads_time_graph.json";
import campaignInfo from "./fixtures/readers/campaign_info.json";
import healthConfigs from "./fixtures/readers/health_metric_configs.json";
import healthList from "./fixtures/readers/health_metric_list.json";
import healthOverview from "./fixtures/readers/health_overview.json";
import products1 from "./fixtures/readers/product_list.json";
import products2 from "./fixtures/readers/product_list_page2.json";
import trafficDetails from "./fixtures/readers/traffic_details.json";
import vouchers from "./fixtures/readers/voucher_list.json";

// 2026-11-03 10:00 in GMT+7
const NOW = Date.UTC(2026, 10, 3, 3, 0, 0);
const TODAY = "2026-11-03";

function response(endpoint: ReaderResponse["endpoint"], body: unknown, extra: Partial<ReaderResponse> = {}): ReaderResponse {
  return { endpoint, url: `https://banhang.shopee.vn/x/${endpoint}`, status: 200, body, capturedAt: NOW, source: "replay", ...extra };
}

describe("product list", () => {
  const responses = [
    response("product_list", products1, { page: 1 }),
    response("product_list", products2, { page: 2 }),
    response("campaign_info", campaignInfo, { source: "page" }),
  ];

  it("maps items and models to item_catalog (platform_items fields)", () => {
    const { catalog } = mapProductList(responses, NOW);
    expect(catalog).toMatchObject({ dataset: "item_catalog", date: TODAY, orderType: null, granularity: "period", drift: null });
    expect(catalog.rows).toEqual([
      { item_id: "1001", item_name: "Sản phẩm mẫu A", seller_sku: "SKU-A", status: "1" },
      { item_id: "1001", variation_id: "5001", variation_name: "Hồng", seller_sku: "A-HONG" },
      { item_id: "1001", variation_id: "5002", variation_name: "Xanh", seller_sku: "A-XANH" },
      { item_id: "1002", item_name: "Sản phẩm mẫu B", seller_sku: "SKU-B", status: "1" },
      { item_id: "1003", item_name: "Sản phẩm mẫu C", seller_sku: "SKU-C", status: "1" },
    ]);
  });

  it("maps the snapshot: price, stock per model, counts, images, times, promo tags, campaigns", () => {
    const { snapshot } = mapProductList(responses, NOW);
    expect(snapshot.dataset).toBe("item_snapshot");
    const [item, hong, xanh, b] = snapshot.rows;
    expect(item).toEqual({
      item_id: "1001",
      image: "vn-sample-cover-a",
      create_time: new Date(1777600000 * 1000).toISOString(),
      modify_time: new Date(1790000000 * 1000).toISOString(),
      price_min: 100000,
      price_max: 150000,
      selling_price_min: 90000,
      selling_price_max: 135000,
      has_discount: true,
      discount_percent: 10,
      max_discount: 15000,
      total_available_stock: 30,
      total_seller_stock: 25,
      total_shopee_stock: 5,
      low_stock_status: 0,
      sellable_stock: 25,
      in_transit_stock: 5,
      view_count: 400,
      liked_count: 12,
      sold_count: 33,
      promo_has_discount: true,
      promo_has_bundle_deal: true,
      promo_has_add_on_deal: false,
      promo_has_ams_commission: true,
      promo_wholesale: false,
      unlisted: false,
      campaign_count: 2,
    });
    expect(hong).toEqual({
      item_id: "1001",
      model_id: "5001",
      image: "vn-sample-model-a1",
      origin_price: 100000,
      promotion_price: 90000,
      total_available_stock: 10,
      sellable_stock: 8,
      in_transit_stock: 2,
      sold_count: 20,
      is_default: true,
      tier_index: "0",
    });
    expect(xanh).toMatchObject({ model_id: "5002", sellable_stock: 17, tier_index: "1" });
    expect(b).toMatchObject({ item_id: "1002", unlisted: true, campaign_count: 0, low_stock_status: 2 });
  });

  it("dedupes an item that moved between pages and ignores error pages", () => {
    const again = [...responses, response("product_list", products1, { page: 3 }), response("product_list", { code: 5, msg: "x" }, { page: 4, status: 200 })];
    expect(mapProductList(again, NOW).catalog.rows).toHaveLength(5);
  });

  it("an item without an id, or a first page without any list, is drift (nothing posted)", () => {
    const bad = { code: 0, data: { products: [{ name: "no id", price_detail: {}, model_list: [] }] } };
    const noId = mapProductList([response("product_list", bad, { page: 1 })], NOW);
    expect(noId.catalog.drift?.missing).toContain("products[].id");
    expect(noId.catalog.rows).toEqual([]);
    const reshaped = mapProductList([response("product_list", { code: 0, data: { something: 1 } }, { page: 1 })], NOW);
    expect(reshaped.catalog.drift?.missing).toEqual(["products"]);
    const empty = mapProductList([response("product_list", { code: 0, data: { products: [], total: 0 } }, { page: 1 })], NOW);
    expect(empty.catalog.drift).toBeNull();
    expect(empty.catalog.rows).toEqual([]);
  });

  it("a x100 000 money scale is drift, not a wrong price", () => {
    const scaled = JSON.parse(JSON.stringify(products1));
    scaled.data.products[0].price_detail.price_max = 15_000_000_000;
    const mapped = mapProductList([response("product_list", scaled, { page: 1 })], NOW);
    expect(mapped.snapshot.drift?.unexpected).toEqual(["price_detail.price_max:money_scale"]);
    expect(mapped.snapshot.rows).toEqual([]);
  });

  it("reads campaign counts from the page's own answer", () => {
    expect([...campaignCounts(campaignInfo)]).toEqual([
      ["1001", 2],
      ["1002", 0],
    ]);
    expect(campaignCounts({ code: 0, data: "nope" }).size).toBe(0);
  });
});

describe("ads", () => {
  const DAY = "2026-11-02";
  const responses = [
    response("ads_homepage", adsHome, { day: DAY, page: 1, usePaidGmv: false }),
    response("ads_time_graph", adsGraph, { day: DAY }),
  ];

  it("maps one finished day: a row per campaign plus the day's ROAS target", () => {
    const [post] = mapAdsDaily(responses);
    expect(post).toMatchObject({ dataset: "ads_campaign_daily", date: DAY, orderType: "placed", granularity: "day", drift: null });
    const [first, second, target] = post!.rows;
    expect(first).toEqual({
      date: DAY,
      campaign_id: "7001",
      campaign_name: "Chiến dịch mẫu 1",
      ad_type: "product",
      ad_subtype: "gmv_max",
      state: "ongoing",
      daily_budget: 200000,
      total_budget: 0,
      roi_two_target: 5.5,
      impression: 1000,
      click: 40,
      product_impression: 900,
      product_click: 35,
      reach: 800,
      page_views: 60,
      unique_visitors: 50,
      checkout: 6,
      atc: 9,
      broad_order: 4,
      direct_order: 3,
      ctr: 0.04,
      broad_roi: 8,
      broad_cir: 0.125,
      direct_roi: 6,
      direct_cir: 0.1667,
      product_ctr: 0.0389,
      avg_rank: 2.5,
      sov: 0.31,
      cost: 50000,
      cpc: 1250,
      cpm: 50000,
      broad_gmv: 400000,
      direct_gmv: 300000,
      voucher_amount: 1000,
      voucher_sales: 20000,
      extra: { new_metric_x: 7 },
    });
    expect(second).toMatchObject({ campaign_id: "7002", state: "paused", impression: 10 });
    expect(target).toEqual({ date: DAY, roi_target: 6, roi_target_cold_start: false });
  });

  it("a paid-orders request posts order type paid; one post per day", () => {
    const paid = [
      response("ads_homepage", adsHome, { day: "2026-11-01", usePaidGmv: true }),
      response("ads_homepage", adsHome, { day: DAY, usePaidGmv: true }),
    ];
    const posts = mapAdsDaily(paid);
    expect(posts.map((p) => [p.date, p.orderType])).toEqual([
      ["2026-11-01", "paid"],
      [DAY, "paid"],
    ]);
  });

  it("ROAS target: the last non-empty setting of the day, none when unset", () => {
    expect(roasTarget(adsGraph)).toEqual({ value: 6, coldStart: false });
    expect(roasTarget({ code: 0, data: { report_by_time: [{ roi_target_setting: { value: 0 } }] } })).toBeNull();
  });

  it("an entry without a campaign id is drift; an implausible budget is a money-scale stop", () => {
    const noId = { code: 0, data: { entry_list: [{ title: "x", campaign: {}, report: {} }] } };
    expect(mapAdsDaily([response("ads_homepage", noId, { day: DAY })])[0]!.drift?.missing).toEqual([
      "entry.campaign.campaign_id",
    ]);
    const scaled = JSON.parse(JSON.stringify(adsHome));
    scaled.data.entry_list[0].campaign.daily_budget = 20_000_000_000_000_000;
    const [post] = mapAdsDaily([response("ads_homepage", scaled, { day: DAY })]);
    expect(post!.drift?.unexpected).toEqual(["ads:money_scale"]);
    expect(post!.rows).toEqual([]);
  });

  it("negative or non-numeric report values are dropped, not posted", () => {
    const odd = { code: 0, data: { entry_list: [{ campaign: { campaign_id: 1 }, report: { impression: -1, click: "x", cost: "120000000" } }] } };
    const [post] = mapAdsDaily([response("ads_homepage", odd, { day: DAY })]);
    expect(post!.rows[0]).toEqual({ date: DAY, campaign_id: "1", cost: 1200 });
  });

  it("produces the exact post body the gateway contract pins", () => {
    const [post] = mapAdsDaily(responses);
    const body = ingestBody(post!, "0.3.0", NOW);
    expect(body.period).toEqual({ start: DAY, end: DAY, granularity: "day" });
    expect(body.order_type).toBe("placed");
  });
});

describe("vouchers", () => {
  const mapped = mapVoucherList([response("voucher_list", vouchers, { page: 1 })], NOW);

  it("maps settings and live usage; the platform wall clock is GMT+7", () => {
    expect(mapped).toMatchObject({ dataset: "voucher_settings", date: TODAY, orderType: null, granularity: "period", drift: null });
    expect(mapped.rows[0]).toEqual({
      voucher_id: "9001",
      program_name: "Giảm 15k đơn từ 200k",
      starts_at: new Date((1790000000 + 7 * 3600) * 1000).toISOString().slice(0, 19),
      voucher_code: "ABC15",
      ends_at: new Date((1792600000 + 7 * 3600) * 1000).toISOString().slice(0, 19),
      status: "ongoing",
      discount_amount: 15000,
      min_spend: 200000,
      usage_limit: 100,
      current_usage: 12,
      distributed_count: 40,
      usage_limit_per_user: 1,
      use_type: 1,
      reward_type: 1,
      purpose: 0,
      is_seller_absorbed: true,
      item_count: 0,
      item_scope: "shop",
    });
    expect(mapped.rows[1]).toMatchObject({
      voucher_id: "9002",
      discount_percent: 10,
      max_value: 30000,
      status: "upcoming",
      item_count: 2,
      item_scope: "items",
      is_seller_absorbed: false,
    });
    expect(mapped.rows[1]).not.toHaveProperty("discount_amount");
  });

  it("a voucher without id, name or start is drift", () => {
    const bad = { code: 0, data: { voucher_list: [{ voucher_id: 5, start_time: 1790000000 }] } };
    const result = mapVoucherList([response("voucher_list", bad)], NOW);
    expect(result.drift?.missing).toEqual(["vouchers[].name"]);
    expect(result.rows).toEqual([]);
  });

  it("an implausible min spend is a money-scale stop", () => {
    const scaled = JSON.parse(JSON.stringify(vouchers));
    scaled.data.voucher_list[0].min_price = 30_000_000_000;
    expect(mapVoucherList([response("voucher_list", scaled)], NOW).drift?.unexpected).toEqual(["vouchers:money_scale"]);
  });
});

describe("account health", () => {
  const responses = [
    response("health_overview", healthOverview),
    response("health_metric_list", healthList),
    response("health_metric_configs", healthConfigs),
  ];

  it("joins the metric list with the config names and the overview row", () => {
    const mapped = mapShopHealth(responses, NOW);
    expect(mapped).toMatchObject({ dataset: "shop_health_daily", date: TODAY, granularity: "day", drift: null });
    expect(mapped.rows).toEqual([
      { date: TODAY, failed_metric_count: 1, penalty_point: 0, performance_rating: 2 },
      {
        date: TODAY,
        metric_id: "11",
        label: "Tỷ lệ phản hồi chat",
        display_value: "92,5%",
        value: 92.5,
        target_display: "≥ 90%",
        target: 90,
        compare_result: 1,
        metric_tag: 3,
      },
      {
        date: TODAY,
        metric_id: "12",
        label: "Đánh giá sao",
        display_value: "3.4",
        value: 3.4,
        target_display: "4",
        target: 4,
        compare_result: "not_met",
        passed: false,
        metric_tag: "service",
      },
      { date: TODAY, metric_id: "13", display_value: "-" },
    ]);
  });

  it("parses display numbers and pass / fail words", () => {
    expect(numberIn("92,5%")).toBe(92.5);
    expect(numberIn("-")).toBeUndefined();
    expect(numberIn("≥ 3 ngày")).toBe(3);
    expect(passedOf("PASS")).toBe(true);
    expect(passedOf("below_target")).toBe(false);
    expect(passedOf(1)).toBeUndefined();
  });

  it("a metric list without ids is drift", () => {
    const bad = response("health_metric_list", { code: 0, data: { metrics: [{ metric_id: "abc" }] } });
    expect(mapShopHealth([bad], NOW).drift?.missing).toEqual(["metric_list[].metric_id"]);
  });
});

describe("mapReaderJob", () => {
  it("dispatches by reader and keeps the dataset names the gateway knows", () => {
    const products = mapReaderJob({ id: "products" }, [response("product_list", products1, { page: 1 })], NOW);
    expect(products.map((m) => m.dataset)).toEqual(["item_catalog", "item_snapshot"]);
    expect(mapReaderJob({ id: "vouchers" }, [], NOW).map((m) => m.dataset)).toEqual(["voucher_settings"]);
    expect(mapReaderJob({ id: "health" }, [], NOW).map((m) => m.dataset)).toEqual(["shop_health_daily"]);
    expect(mapReaderJob({ id: "ads", days: ["2026-11-02"] }, [], NOW)).toEqual([]);
  });

  it("holds no buyer data: no mapped field name is buyer-shaped", () => {
    const all = [
      ...mapReaderJob({ id: "products" }, [response("product_list", products1, { page: 1 })], NOW),
      ...mapAdsDaily([response("ads_homepage", adsHome, { day: "2026-11-02" })]),
      mapVoucherList([response("voucher_list", vouchers)], NOW),
      mapShopHealth([response("health_metric_list", healthList)], NOW),
    ];
    const keys = new Set(all.flatMap((m) => m.rows.flatMap((r) => Object.keys(r))));
    for (const key of keys) expect(key).not.toMatch(/buyer|phone|address|email|recipient|user_id|nickname/i);
  });
});

describe("item traffic sources (traffic/details)", () => {
  const day = "2026-11-02";
  const ok = (itemId: string, body: unknown = trafficDetails, d = day) =>
    response("traffic_details", body, { day: d, itemId });

  it("maps one post per day: a total + the seven product_card sources per item, numbers only", () => {
    const [post] = mapItemTraffic([ok("1001")]);
    expect(post).toMatchObject({
      dataset: "item_traffic_sources",
      date: day,
      orderType: "confirmed",
      granularity: "day",
      drift: null,
    });
    const card = post!.rows.filter((r) => r.l1 === "product_card");
    expect(card.map((r) => r.l2)).toEqual([
      "total",
      "search",
      "recommendation",
      "my_purchase",
      "shopping_cart",
      "shop",
      "promotion",
      "others",
    ]);
    expect(card[0]).toEqual({
      date: day,
      item_id: "1001",
      l1: "product_card",
      l2: "total",
      sales: 1_000_000,
      orders: 20,
      units: 30,
      buyers: 10,
      product_impressions: 1000,
      unique_product_impressions: 800,
      product_clicks: 100,
      unique_product_clicks: 90,
    });
    // ratios, pct_diff, ctr and the source label never leave the browser
    for (const r of post!.rows) {
      expect(Object.keys(r).every((k) => !/ratio|pct_diff|ctr|source|per_order|rate/.test(k))).toBe(true);
    }
  });

  it("skips all-zero live / video / affiliate rows and level-2 labels the contract does not name", () => {
    const [post] = mapItemTraffic([ok("1001")]);
    expect(post!.rows.filter((r) => r.l1 === "live" || r.l1 === "affiliate")).toEqual([]);
    expect(post!.rows.filter((r) => r.l1 === "video").map((r) => r.l2)).toEqual(["total", "recommendation"]);
  });

  it("splits days and items; an unread (error) answer is not mapped; a missing product_card is drift", () => {
    const posts = mapItemTraffic([
      ok("1001"),
      ok("1002"),
      ok("1001", trafficDetails, "2026-11-01"),
      response("traffic_details", { code: 90309999 }, { day: "2026-10-31", itemId: "1001", status: 500 }),
    ]);
    expect(posts.map((p) => p.date)).toEqual(["2026-10-31", "2026-11-01", "2026-11-02"]);
    expect(posts[0]!.rows).toEqual([]);
    expect(new Set(posts[2]!.rows.map((r) => r.item_id))).toEqual(new Set(["1001", "1002"]));
    const [bad] = mapItemTraffic([ok("1001", { code: 0, result: { live: {} } })]);
    expect(bad!.drift).toEqual({ unexpected: [], missing: ["result.product_card.total"] });
    expect(bad!.rows).toEqual([]);
  });

  it("goes through mapReaderJob and ingestBody as a day post (order_type confirmed)", () => {
    const [post] = mapReaderJob({ id: "item_traffic", days: [day], itemIds: ["1001"] }, [ok("1001")], NOW);
    const body = ingestBody(post!, "0.3.4", NOW);
    expect(body).toMatchObject({ period: { start: day, end: day, granularity: "day" }, order_type: "confirmed" });
  });

  it("completedTrafficDays: a day counts as read only when every item answered", () => {
    const job = { id: "item_traffic" as const, days: [day, "2026-11-01"], itemIds: ["1001", "1002"] };
    expect(completedTrafficDays(job, [ok("1001"), ok("1002"), ok("1001", trafficDetails, "2026-11-01")])).toEqual([day]);
    expect(completedTrafficDays(job, [])).toEqual([]);
  });

  it("activeItemIds: skips unlisted items, keeps normal ones (all of them if no status looks normal)", () => {
    const list = (products: unknown[]) => response("product_list", { code: 0, data: { products } }, { page: 1 });
    expect(
      activeItemIds([
        list([
          { id: 1, status: 1, stock_detail: {} },
          { id: 2, status: 1, stock_detail: {}, tag: { unlist: true } },
          { id: 3, status: 7, stock_detail: {} },
          { id: 4, stock_detail: {} },
        ]),
      ]),
    ).toEqual(["1", "4"]);
    expect(activeItemIds([list([{ id: 5, status: 9, stock_detail: {} }])])).toEqual(["5"]);
  });
});

describe("assisted-execution read-back: the fields the backend verifies", () => {
  it("item_snapshot carries cover + model image, list/selling price and stock; item_catalog the title", () => {
    const { catalog, snapshot } = mapProductList([response("product_list", products1, { page: 1 })], NOW);
    const item = snapshot.rows.find((r) => r.item_id === "1001" && r.model_id === undefined)!;
    const model = snapshot.rows.find((r) => r.model_id === "5001")!;
    expect(item).toHaveProperty("image");
    expect(item).toHaveProperty("price_min");
    expect(item).toHaveProperty("price_max");
    expect(item).toHaveProperty("selling_price_min");
    expect(item).toHaveProperty("selling_price_max");
    expect(item).toHaveProperty("total_available_stock");
    expect(model).toHaveProperty("image");
    expect(model).toHaveProperty("origin_price");
    expect(model).toHaveProperty("promotion_price");
    expect(model).toHaveProperty("total_available_stock");
    expect(catalog.rows[0]).toHaveProperty("item_name");
  });

  it("ads daily carries daily_budget and roi_two_target; vouchers carry value, min spend, usage limit, dates", () => {
    const [ads] = mapAdsDaily([response("ads_homepage", adsHome, { day: "2026-11-02", usePaidGmv: false })]);
    expect(ads!.rows.some((r) => "daily_budget" in r && "roi_two_target" in r)).toBe(true);
    const voucher = mapVoucherList([response("voucher_list", vouchers, { page: 1 })], NOW);
    const row = voucher.rows.find((r) => "min_spend" in r && "usage_limit" in r)!;
    expect(row).toHaveProperty("starts_at");
    expect(row).toHaveProperty("ends_at");
    expect(row.discount_amount !== undefined || row.discount_percent !== undefined).toBe(true);
  });
});
