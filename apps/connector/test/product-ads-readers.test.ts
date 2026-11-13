// Connector 0.3.12 (P97 T3): the 30-day product table (`product_period`) and the group campaigns'
// per-product ads (`ads_campaign_period`). Fixtures are SYNTHETIC and use the field names of the
// 2026-11-09 recordings (fasttrack/contracts/p97-recon-2026-11-09.md); shapes the recording did not
// capture are marked TODO(first capture) in the mappers and pinned here only as far as they promise.
import { describe, expect, it } from "vitest";
import { ingestBody } from "../src/ingest/client";
import {
  ADS_PRODUCTS_MAX_CAMPAIGNS,
  PRODUCT_PERIOD_MAX_PAGES,
  READER_PAGE_LOAD_COST,
  READER_DATASETS,
  READERS_ACTIVE,
} from "../src/config";
import { isReadOnlyPasPath, READER_ENDPOINTS, type ReaderEndpoint, readerEndpointOf, readerPageUrl, READER_PAGES } from "../src/shopee/endpoints";
import { mapAdsProducts } from "../src/shopee/ads-products-map";
import { mapProductPeriod } from "../src/shopee/product-period-map";
import { campaignTitle, mapReaderJob } from "../src/shopee/reader-map";
import {
  type FetchedReaderResponse,
  pollingWaitFor,
  type ReaderEnv,
  type ReaderRequest,
  type ReaderResponse,
  runReaderJob,
  campaignNameFromGet,
  type Template,
} from "../src/shopee/reader";
import { Pacer } from "../src/shopee/runner";
import { gmt7DateStart } from "../src/shopee/time";
import { planJobs } from "../src/background/scheduler";

const SC = "https://banhang.shopee.vn";
const NOW = Date.UTC(2026, 10, 9, 3, 0, 0); // 2026-11-09 10:00 GMT+7

function harness(templates: Partial<Record<ReaderEndpoint, Template>>, handler: (request: ReaderRequest) => { status?: number; body?: unknown }, pathname = "/datacenter/product/performance") {
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
    hasSession: () => true,
    template: (endpoint) => templates[endpoint],
    waitFor: pollingWaitFor(sleep, now),
    fetch: async (request): Promise<FetchedReaderResponse> => {
      sent.push(request);
      const answer = handler(request);
      return { status: answer.status ?? 200, text: async () => JSON.stringify(answer.body ?? null) };
    },
    pathname: () => pathname,
    random: () => 0,
  };
  return { env, sent };
}

function reply(endpoint: ReaderEndpoint, body: unknown, extra: Partial<ReaderResponse> = {}): ReaderResponse {
  return { endpoint, url: "u", status: 200, body, capturedAt: NOW, source: "replay", ...extra };
}

// -- product table -------------------------------------------------------------------------------

const item = (id: number, over: Record<string, unknown> = {}) => ({
  id,
  name: `Sản phẩm mẫu ${id}`,
  image: "abc123",
  status: 1,
  display_tag_label: "",
  product_card_impressions: 1000,
  unique_product_card_impressions: 800,
  product_card_clicks: 50,
  unique_product_card_clicks: 40,
  ctr: 0.05,
  pv: 60,
  uv: 45,
  likes: 3,
  bounce_visitors: 20,
  bounce_rate: 0.44,
  search_clicks: 12,
  add_to_cart_units: 9,
  add_to_cart_buyers: 7,
  placed_sales: 900_000,
  placed_units: 12,
  placed_buyers: 9,
  placed_orders: 10,
  placed_sales_per_order: 90_000,
  paid_sales: 800_000,
  confirmed_sales: 700_000,
  confirmed_units: 9,
  confirmed_buyers: 7,
  confirmed_orders: 8,
  confirmed_sales_per_order: 87_500,
  placed_order_conversion_rate: 0.22,
  confirmed_order_conversion_rate: 0.18,
  models: [
    { id: 5001, name: "Hộp 5", status: 1, add_to_cart_units: 4, placed_sales: 500_000, placed_units: 6, placed_orders: 5, confirmed_sales: 400_000, confirmed_units: 5, confirmed_orders: 4 },
  ],
  ...over,
});
const page = (items: unknown[], total = items.length) => ({ code: 0, result: { total, items, need_upload_item: false } });
const period = { start: "2026-10-10", end: "2026-11-08" };

describe("the product table -> product_period", () => {
  it("posts confirmed and placed from one answer, with variations and no image", () => {
    const posts = mapProductPeriod([reply("product_performance", page([item(1001), item(1002)]), { period })], NOW);
    expect(posts.map((p) => p.orderType)).toEqual(["confirmed", "placed"]);
    const confirmed = posts[0]!;
    expect(confirmed).toMatchObject({ dataset: "product_period", granularity: "period", periodStart: "2026-10-10", date: "2026-11-08", drift: null });
    expect(confirmed.rows).toHaveLength(4); // 2 items + 2 variations
    expect(confirmed.rows[0]).toEqual({
      item_id: "1001",
      item_name: "Sản phẩm mẫu 1001",
      item_status: "1",
      sales: 700_000,
      orders: 8,
      units: 9,
      buyers: 7,
      sales_per_order: 87_500,
      conversion_rate: 0.18,
      product_impressions: 1000,
      unique_product_impressions: 800,
      product_clicks: 50,
      unique_product_clicks: 40,
      ctr: 0.05,
      product_visitors: 45,
      product_page_views: 60,
      bounced_visitors: 20,
      bounce_rate: 0.44,
      search_clicks: 12,
      likes: 3,
      atc_visitors: 7,
      atc_units: 9,
    });
    expect(confirmed.rows[1]).toMatchObject({ item_id: "1001", variation_id: "5001", variation_name: "Hộp 5", sales: 400_000, orders: 4, atc_units: 4 });
    const placed = posts[1]!;
    expect(placed.rows[0]).toMatchObject({ sales: 900_000, orders: 10, units: 12, sales_per_order: 90_000, conversion_rate: 0.22 });
    expect(JSON.stringify(posts)).not.toContain("abc123"); // the image reference never leaves
    const body = ingestBody(placed, "0.3.12", NOW);
    expect(body.period).toEqual({ start: "2026-10-10", end: "2026-11-08", granularity: "period" });
    expect(body.order_type).toBe("placed");
  });

  it("reads percents as fractions when any rate is above 1, for the whole answer", () => {
    const [confirmed] = mapProductPeriod([reply("product_performance", page([item(1, { ctr: 5, bounce_rate: 44, confirmed_order_conversion_rate: 18 })]), { period })], NOW);
    expect(confirmed!.rows[0]).toMatchObject({ ctr: 0.05, bounce_rate: 0.44, conversion_rate: 0.18 });
  });

  it("joins pages without repeating an item; an item with no id, or no sales at all, is drift", () => {
    const joined = mapProductPeriod(
      [reply("product_performance", page([item(1), item(2)], 3), { period, page: 1 }), reply("product_performance", page([item(2), item(3)], 3), { period, page: 2 })],
      NOW,
    );
    expect(joined[0]!.rows.map((r) => r.item_id).filter((_, i, a) => a.indexOf(_) === i)).toEqual(["1", "2", "3"]);
    const noId = mapProductPeriod([reply("product_performance", page([item(1), { name: "x" }]), { period })], NOW);
    expect(noId[0]!.drift?.missing).toEqual(["items[].id"]);
    expect(noId[0]!.rows).toEqual([]);
    const noSales = mapProductPeriod([reply("product_performance", page([{ id: 1, name: "x", uv: 3 }]), { period })], NOW);
    expect(noSales[0]!.drift?.missing).toEqual(["items[].confirmed_sales"]);
  });

  it("an empty page is no post and no drift; an error or a missing result maps to nothing / drift", () => {
    const empty = mapProductPeriod([reply("product_performance", { code: 0, result: { total: 0, items: null, need_upload_item: true } }, { period })], NOW);
    expect(empty.every((p) => p.rows.length === 0 && p.drift === null)).toBe(true);
    expect(mapProductPeriod([reply("product_performance", { code: 5, msg: "x" }, { period })], NOW)).toEqual([]);
    expect(mapProductPeriod([], NOW)).toEqual([]);
    const noResult = mapProductPeriod([reply("product_performance", { code: 0 }, { period })], NOW);
    expect(noResult[0]!.drift?.missing).toContain("result.items");
  });

  it("goes through mapReaderJob", () => {
    expect(mapReaderJob({ id: "product_period" }, [reply("product_performance", page([item(1)]), { period })], NOW).map((p) => p.dataset)).toEqual(["product_period", "product_period"]);
  });
});

describe("the product table reader", () => {
  const template: Template = { query: { period: "past7days", page_size: "10", page_num: "1", order_type: "confirmed" }, headers: { "x-test": "1" } };

  it("replays the page's call for the last 30 finished days, 10 a page, confirmed sales descending", async () => {
    const h = harness({ product_performance: template }, (request) => {
      const n = Number(new URL(request.url).searchParams.get("page_num"));
      return { body: page(Array.from({ length: 10 }, (_, i) => item(n * 100 + i)), 43) };
    });
    const outcome = await runReaderJob({ id: "product_period" }, h.env);
    expect(outcome.status).toBe("done");
    expect(h.sent).toHaveLength(PRODUCT_PERIOD_MAX_PAGES);
    const q = new URL(h.sent[0]!.url).searchParams;
    expect(Object.fromEntries(q)).toMatchObject({
      period: "past30days",
      page_size: "10",
      page_num: "1",
      order_type: "confirmed",
      order_by: "confirmed_sales.desc",
      category_type: "shopee",
      category_id: "-1",
      keyword: "",
      SPC_CDS: "s",
    });
    expect(Number(q.get("start_time"))).toBe(gmt7DateStart("2026-10-10"));
    expect(Number(q.get("end_time"))).toBe(gmt7DateStart("2026-11-08") + 86_399);
    expect(h.sent.every((r) => r.method === "GET")).toBe(true);
    expect(outcome.responses[0]!.period).toEqual({ start: "2026-10-10", end: "2026-11-08" });
  });

  it("stops at the last page the answer's total names, and on a short page", async () => {
    const h = harness({ product_performance: template }, (request) => {
      const n = Number(new URL(request.url).searchParams.get("page_num"));
      return { body: page(n === 1 ? Array.from({ length: 10 }, (_, i) => item(i + 1)) : [item(11), item(12), item(13)], 13) };
    });
    await runReaderJob({ id: "product_period" }, h.env);
    expect(h.sent).toHaveLength(2);
  });

  it("stops the shop on a rate answer and never posts a half page past it", async () => {
    const h = harness({ product_performance: template }, () => ({ status: 429, body: { error: 429 } }));
    const outcome = await runReaderJob({ id: "product_period" }, h.env);
    expect(outcome.status).toBe("blocked_rate");
    expect(h.sent).toHaveLength(1);
  });

  it("stops on the Shopee password prompt before any request", async () => {
    const h = harness({ product_performance: template }, () => ({ body: page([]) }));
    h.env.passwordModalVisible = () => true;
    const outcome = await runReaderJob({ id: "product_period" }, h.env);
    expect(outcome).toMatchObject({ status: "blocked_login", detail: "password_modal" });
    expect(h.sent).toEqual([]);
  });

  it("is planned once a day, after the shop totals, on the product performance page", () => {
    const base = { shopId: "s", nowMs: NOW, stopped: new Set<never>(), adsDone: [] as string[], readers: ["shop_totals", "product_period"] as const };
    expect(planJobs({ ...base, totalsDay: "2026-11-09" }).map((j) => j.id)).toEqual(["product_period"]);
    expect(planJobs({ ...base, totalsDay: "2026-11-09", productPeriodDay: "2026-11-09" })).toEqual([]);
    expect(READER_PAGES.product_period.path).toBe("/datacenter/product/performance");
    expect(readerPageUrl({ id: "product_period" })).toBe("/datacenter/product/performance");
    expect(READERS_ACTIVE.product_period).toBe(true);
    expect(READER_DATASETS.product_period).toEqual(["product_period"]);
    expect(readerEndpointOf("GET", "/api/mydata/v4/product/performance/")).toBe("product_performance");
  });
});

// -- group campaigns' per-product ads ---------------------------------------------------------

const adsRow = (id: number, over: Record<string, unknown> = {}) => ({
  item_id: id,
  report: { impression: 2000, click: 80, ctr: 0.04, cost: 150_000 * 100_000, broad_gmv: 900_000 * 100_000, direct_gmv: 600_000 * 100_000, broad_order: 9, direct_order: 6, ...over },
});
const startTime = gmt7DateStart("2026-11-02");
const endTime = gmt7DateStart("2026-11-08") + 86_399;
const pageBody = (campaign: number, extra: Record<string, unknown> = {}) => ({ campaign_id: campaign, start_time: startTime, end_time: endTime, ...extra });
const mpd = (rows: unknown[]) => ({ code: 0, data: { list: rows, total: rows.length } });
const win = { period: { start: "2026-11-02", end: "2026-11-08" } };

describe("group campaigns' products -> ads_campaign_period", () => {
  it("is a list read (replayable) and its page is the campaign's manual-mpd page", () => {
    expect(isReadOnlyPasPath(READER_ENDPOINTS.ads_mpd_products.path)).toBe(true);
    expect(readerEndpointOf("POST", "/api/pas/v1/product/mpd/list_item_product_performance/")).toBe("ads_mpd_products");
    expect(readerPageUrl({ id: "ads_products", campaignIds: ["188757809", "2"] })).toBe("/portal/marketing/pas/product/manual-mpd/188757809");
  });

  it("posts per-product views, clicks, cost and GMV as placed-order period rows with the ads money scale", () => {
    const [post] = mapAdsProducts(
      [reply("ads_mpd_products", mpd([adsRow(1001), adsRow(1002, { cost: 0 })]), { campaignId: "188757809", campaignName: "Chiến dịch nhóm A", source: "page", ...win })],
      NOW,
    );
    expect(post).toMatchObject({ dataset: "ads_campaign_period", granularity: "period", orderType: "placed", periodStart: "2026-11-02", date: "2026-11-08", drift: null });
    expect(post!.rows[0]).toEqual({
      campaign_name: "Chiến dịch nhóm A",
      item_id: "1001",
      ordinal: 0,
      ads_impressions: 2000,
      ad_clicks: 80,
      ctr: 0.04,
      ads_expense: 150_000,
      sales: 900_000,
      direct_sales: 600_000,
      conversions: 9,
      direct_conversions: 6,
    });
    expect(post!.rows[1]).toMatchObject({ item_id: "1002", ordinal: 1, ads_expense: 0 });
    expect(ingestBody(post!, "0.3.12", NOW).order_type).toBe("placed");
  });

  it("0.3.15: a missing list title is not drift when the campaign id (or the answer's own name) is known", () => {
    const byId = mapAdsProducts([reply("ads_mpd_products", mpd([adsRow(1001)]), { campaignId: "188757809", source: "page", ...win })], NOW);
    expect(byId[0]!.drift).toBeNull();
    expect(byId[0]!.rows[0]).toMatchObject({ campaign_name: "Chiến dịch 188757809", item_id: "1001", ads_expense: 150_000 });
    const own = mapAdsProducts(
      [reply("ads_mpd_products", { code: 0, data: { campaign: { name: "Nhóm B" }, list: [adsRow(1001)] } }, { campaignId: "5", source: "page", ...win })],
      NOW,
    );
    expect(own[0]!.drift).toBeNull();
    expect(own[0]!.rows[0]).toMatchObject({ campaign_name: "Nhóm B" });
  });

  it("0.3.15: the campaign title is found wherever the ads list now keeps it", () => {
    const entry = (extra: Record<string, unknown>) => ({ type: "product_mpd", state: "ongoing", campaign: { campaign_id: 77, ...(extra.campaign as object) }, ...Object.fromEntries(Object.entries(extra).filter(([k]) => k !== "campaign")) });
    expect(campaignTitle(entry({ title: "Cũ" }))).toBe("Cũ");
    expect(campaignTitle(entry({ campaign: { name: "Lồng" } }))).toBe("Lồng");
    expect(campaignTitle(entry({ campaign_info: { name: "Info" } }))).toBe("Info");
    expect(campaignTitle(entry({ ad_name: "Ad" }))).toBe("Ad");
    expect(campaignTitle(entry({}))).toBeUndefined();
  });

  it("is drift (nothing posted) without a window, a campaign title or a recognisable list", () => {
    const noWindow = mapAdsProducts([reply("ads_mpd_products", mpd([adsRow(1)]), { campaignName: "A" })], NOW);
    expect(noWindow[0]!.drift?.missing).toEqual(["request.window"]);
    expect(noWindow[0]!.rows).toEqual([]);
    // neither a title nor a campaign id: nothing to key the rows by
    const noName = mapAdsProducts([reply("ads_mpd_products", mpd([adsRow(1)]), win)], NOW);
    expect(noName[0]!.drift?.missing).toEqual(["campaign_name"]);
    const noList = mapAdsProducts([reply("ads_mpd_products", { code: 0, data: { rows: [{ x: 1 }] } }, { campaignName: "A", ...win })], NOW);
    expect(noList[0]!.drift?.missing).toEqual(["list[].item_id+report"]);
    expect(mapAdsProducts([], NOW)).toEqual([]);
  });

  it("keeps the page's own answer for the opened campaign and replays only campaign_id for the others", async () => {
    const own = mpd([adsRow(1001)]);
    const h = harness(
      { ads_mpd_products: { query: {}, body: pageBody(188757809, { page_size: 20 }), lastResponse: own, headers: { "x-test": "1" } } },
      () => ({ body: mpd([adsRow(2002)]) }),
      "/portal/marketing/pas/product/manual-mpd/188757809",
    );
    const outcome = await runReaderJob({ id: "ads_products", campaignIds: ["188757809", "188757810"], campaignNames: ["A", "B"] }, h.env);
    expect(outcome.status).toBe("done");
    expect(h.sent).toHaveLength(1);
    expect(h.sent[0]!.method).toBe("POST");
    expect(JSON.parse(h.sent[0]!.body!)).toMatchObject({ campaign_id: 188757810, page_size: 20, start_time: startTime });
    expect(outcome.responses.map((r) => [r.campaignId, r.campaignName, r.source])).toEqual([
      ["188757809", "A", "page"],
      ["188757810", "B", "replay"],
    ]);
    expect(outcome.responses.every((r) => r.period?.start === "2026-11-02" && r.period.end === "2026-11-08")).toBe(true);
    const posts = mapReaderJob({ id: "ads_products", campaignIds: ["188757809", "188757810"], campaignNames: ["A", "B"] }, outcome.responses, NOW);
    expect(posts).toHaveLength(1);
    expect(posts[0]!.rows.map((r) => [r.campaign_name, r.item_id])).toEqual([
      ["A", "1001"],
      ["B", "2002"],
    ]);
  });

  it("stops on the password prompt before it replays anything", async () => {
    const h = harness({ ads_mpd_products: { query: {}, body: pageBody(1), lastResponse: mpd([]) } }, () => ({ body: mpd([]) }), "/portal/marketing/pas/product/manual-mpd/1");
    h.env.passwordModalVisible = () => true;
    const outcome = await runReaderJob({ id: "ads_products", campaignIds: ["1", "2"], campaignNames: ["A", "B"] }, h.env);
    expect(outcome).toMatchObject({ status: "blocked_login", detail: "password_modal" });
    expect(h.sent).toEqual([]);
  });

  it("needs a template when the page never loaded the table", async () => {
    const h = harness({}, () => ({ body: mpd([]) }), "/portal/marketing/pas/product/manual-mpd/1");
    h.env.hasSession = () => true;
    const outcome = await runReaderJob({ id: "ads_products", campaignIds: ["1"], campaignNames: ["A"] }, h.env);
    expect(["needs_template", "needs_data_page"]).toContain(outcome.status);
  });

  // Recorded shapes, 2026-11-10 (synthetic values).
  const realMpd = (rows: number[]) => ({
    code: 0,
    data: {
      result_list: rows.map((id) => ({
        item_id: id,
        name: `Tên sản phẩm ${id}`,
        image: "abc",
        trait_list: [],
        report: { broad_gmv: 900_000 * 100_000, broad_order: 9, click: 80, cost: 150_000 * 100_000, ctr: 0.04, impression: 2000, product_click: 30, product_impression: 500, page_views: 40, direct_gmv: 600_000 * 100_000, direct_order: 6 },
      })),
    },
  });
  const realGet = (id: number, name: string) => ({
    code: 0,
    data: { campaign: { campaign_id: id, name, type: "product_mpd", state: "ongoing", daily_budget: 1, start_time: 1, end_time: 2, total_budget: 0, bidding_strategy: "roi_two", product_placement: "all", product_selection: "manual", roi_two: { target: 5 }, target_broad_roi: 5 } },
  });

  it("names the opened campaign from the page's product/get (numeric id), not from a product name", async () => {
    const h = harness(
      {
        ads_mpd_products: { query: {}, body: { reference_id: "r", ...pageBody(188757809) }, lastResponse: realMpd([1001]) },
        ads_product_get: { query: {}, body: { campaign_id: 188757809, reference_id: "r" }, lastResponse: realGet(188757809, "Nhóm Mùa Sale") },
      },
      () => ({ body: realMpd([2002]) }),
      "/portal/marketing/pas/product/manual-mpd/188757809",
    );
    const ids = ["188757809", "188757810"];
    const outcome = await runReaderJob({ id: "ads_products", campaignIds: ids, campaignNames: ["Tiêu đề danh sách A", "Tiêu đề danh sách B"] }, h.env);
    expect(outcome.responses.map((r) => r.campaignName)).toEqual(["Nhóm Mùa Sale", "Tiêu đề danh sách B"]);
    const posts = mapReaderJob({ id: "ads_products", campaignIds: ids }, outcome.responses, NOW);
    expect(posts[0]!.drift).toBeNull();
    expect(posts[0]!.rows.map((r) => [r.campaign_name, r.item_id])).toEqual([
      ["Nhóm Mùa Sale", "1001"],
      ["Tiêu đề danh sách B", "2002"],
    ]);
  });

  it("ignores a product/get for another campaign and falls back to the list title, then the id", async () => {
    const h = harness(
      {
        ads_mpd_products: { query: {}, body: pageBody(5), lastResponse: realMpd([1]) },
        ads_product_get: { query: {}, body: { campaign_id: 9 }, lastResponse: realGet(9, "Khác") },
      },
      () => ({ body: realMpd([2]) }),
      "/portal/marketing/pas/product/manual-mpd/5",
    );
    const withTitle = await runReaderJob({ id: "ads_products", campaignIds: ["5"], campaignNames: ["Từ danh sách"] }, h.env);
    expect(withTitle.responses[0]!.campaignName).toBe("Từ danh sách");
    const none = await runReaderJob({ id: "ads_products", campaignIds: ["5"], campaignNames: [""] }, h.env);
    expect(none.responses[0]!.campaignName).toBeUndefined();
    const posts = mapAdsProducts(none.responses, NOW);
    expect(posts[0]!.drift).toBeNull();
    expect(posts[0]!.rows[0]!.campaign_name).toBe("Chiến dịch 5");
  });

  it("campaignNameFromGet accepts a string campaign id and rejects a missing name", () => {
    expect(campaignNameFromGet({ code: 0, data: { campaign: { campaign_id: "7", name: " X " } } }, "7")).toBe("X");
    expect(campaignNameFromGet({ code: 0, data: { campaign: { campaign_id: 7, name: "" } } }, "7")).toBeUndefined();
  });

  it("maps the recorded result_list shape and never uses the product name as the campaign name", () => {
    const posts = mapAdsProducts([reply("ads_mpd_products", realMpd([11, 12]), { campaignId: "3", ...win })], NOW);
    expect(posts[0]!.drift).toBeNull();
    expect(posts[0]!.rows.map((r) => [r.campaign_name, r.item_id])).toEqual([
      ["Chiến dịch 3", "11"],
      ["Chiến dịch 3", "12"],
    ]);
  });

  it("never reads more group campaigns than the cap", () => {
    expect(ADS_PRODUCTS_MAX_CAMPAIGNS).toBeLessThanOrEqual(10);
    expect(READER_PAGE_LOAD_COST).toBe(10);
  });
});
