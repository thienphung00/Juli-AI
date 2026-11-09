// Connector 0.3.11: each ad campaign's settings (the Quảng cáo list) and the edit-page limits of
// the ongoing / scheduled ones, so the builder can offer "Chiến dịch đang chạy" with Shopee's own
// limits. Read-only: the detail reader replays only read endpoints of the page it opened.
import { describe, expect, it } from "vitest";
import { isReadOnlyPasPath, readerPageUrl } from "../src/shopee/endpoints";
import {
  type FetchedReaderResponse,
  pollingWaitFor,
  type ReaderEnv,
  type ReaderRequest,
  type ReaderResponse,
  runReaderJob,
  type Template,
} from "../src/shopee/reader";
import { mapAdsDetail, mapAdsSettings, mapReaderJob, ongoingAdsCampaigns } from "../src/shopee/reader-map";
import { Pacer } from "../src/shopee/runner";
import type { ReaderEndpoint } from "../src/shopee/endpoints";
import { planJobs } from "../src/background/scheduler";

const SC = "https://banhang.shopee.vn";
// 2026-11-06 10:00 GMT+7
const NOW = Date.UTC(2026, 10, 6, 3, 0, 0);
const TODAY = "2026-11-06";
const PILOT = "d73a240b-a00a-4306-9b3e-9fdf75d72aaf";

// Shapes from the ORY recon (2026-11-06); money and ROAS targets x100 000 like the daily rows.
const entry = (id: number | string, over: Record<string, unknown> = {}) => ({
  title: `Chiến dịch ${id}`,
  image: "vn-11134207-xxx",
  type: "product_manual",
  state: "ongoing",
  editable_list: ["status", "budget", "time", "roi_two_target"],
  campaign: { campaign_id: id, daily_budget: 18_609_000_000, total_budget: 0, start_time: 1_790_000_000, end_time: 0, roi_two_target: 530_000 },
  manual_product_ads: { item_id: 27933768174, product_placement: "all", bidding_strategy: "roi_two", enhanced_bid_price: 0 },
  report: { impression: 10, cost: 100_000_000 },
  ...over,
});
const home = (entries: unknown[], total: number) => ({ code: 0, msg: "OK", data: { total, entry_list: entries } });

function reply(endpoint: ReaderEndpoint, body: unknown, extra: Partial<ReaderResponse> = {}): ReaderResponse {
  return { endpoint, url: `${SC}/x`, status: 200, body, capturedAt: NOW, source: "replay", ...extra };
}

describe("ads_campaign_settings (the Quảng cáo list)", () => {
  const page1 = home([entry(7001), entry(7002, { state: "paused", editable_list: ["status"], group_image: { image_list: ["a"] } })], 3);
  const page2 = home(
    [
      entry(7003, {
        type: "shop_manual",
        state: "ended",
        manual_product_ads: undefined,
        campaign: { campaign_id: 7003, daily_budget: 0, total_budget: 50_000_000_000, start_time: 1_788_000_000, end_time: 1_789_000_000 },
      }),
      entry(7001), // the same campaign on two pages is kept once
    ],
    3,
  );

  it("maps every campaign once, scaled: budget in VND, ROAS target a ratio, no end = no ends_at", () => {
    const post = mapAdsSettings([reply("ads_homepage", page1, { page: 1 }), reply("ads_homepage", page2, { page: 2 })], NOW);
    expect(post).toMatchObject({ dataset: "ads_campaign_settings", date: TODAY, orderType: null, granularity: "period", drift: null });
    expect(post!.rows.map((r) => r.campaign_id)).toEqual(["7001", "7002", "7003"]);
    expect(post!.rows[0]).toEqual({
      campaign_id: "7001",
      campaign_name: "Chiến dịch 7001",
      campaign_type: "product_manual",
      state: "ongoing",
      starts_at: "2026-09-21T21:13:20",
      daily_budget: 186090,
      total_budget: 0,
      roi_two_target: 5.3,
      item_id: "27933768174",
      product_placement: "all",
      bidding_strategy: "roi_two",
      enhanced_bid_price: 0,
      editable: ["status", "budget", "time", "roi_two_target"],
      is_group: false,
    });
    expect(post!.rows[1]).toMatchObject({ campaign_id: "7002", state: "paused", editable: ["status"], is_group: true });
    expect(post!.rows[2]).toMatchObject({ campaign_type: "shop_manual", total_budget: 500000, ends_at: "2026-09-10T07:26:40" });
    expect(post!.rows[2]).not.toHaveProperty("item_id");
    expect(JSON.stringify(post)).not.toContain("vn-11134207"); // no image ids leave the browser
  });

  it("a day-less read (settings only) maps too, and no daily post comes from it", () => {
    const posts = mapReaderJob({ id: "ads", days: [] }, [reply("ads_homepage", page1, { page: 1 })], NOW);
    expect(posts.map((p) => p.dataset)).toEqual(["ads_campaign_settings"]);
  });

  it("the ongoing / scheduled product campaigns are the detail reader's work list", () => {
    const responses = [
      reply("ads_homepage", page1),
      reply("ads_homepage", home([entry(7004, { state: "scheduled", type: "product_mpd" }), entry(7005, { type: "product_gms" })], 2)),
    ];
    expect(ongoingAdsCampaigns(responses)).toEqual([
      { id: "7001", kind: "manual", name: "Chiến dịch 7001" },
      { id: "7004", kind: "mpd", name: "Chiến dịch 7004" },
    ]);
  });
});

// -- the edit page of one ongoing campaign ---------------------------------------------------

const productGet = (id: number) => ({
  code: 0,
  data: {
    campaign: {
      campaign_id: id,
      name: `Chiến dịch ${id}`,
      product_selection: "manual",
      display_location: "all",
      rapid_boost: true,
      roi_two: { target: 530_000, rapid_boost: true, estimate: { lower_bound: 532_000, upper_bound: 844_000 } },
    },
    ads_list: [
      { item_id: 27933768174, stock: 82, price_lower_bound: 13_900_000_000, price_upper_bound: 13_900_000_000 },
      { item_id: "24008937848", stock: 0, price_lower_bound: 9_000_000_000, price_upper_bound: 12_000_000_000 },
    ],
  },
});
const roiRecommend = {
  code: 0,
  data: {
    exact: { value: 700_000, percentile: 50 },
    lower_bound: { value: 530_000, percentile: 20 },
    upper_bound: { value: 840_000, percentile: 80 },
    hard_lower_bound: 150_000,
    hard_upper_bound: 3_000_000,
    recommended_target_roi: 530_000,
    gmv_order_uplift: 12,
    roi_two_target_daily_edit_count: 1,
  },
};
const budgetEdit = {
  code: 0,
  data: {
    total_budget: { min: 0 },
    daily_budget: {
      recommended: 18_609_000_000,
      low_threshold: 11_165_400_000,
      min: 10_000_000_000,
      max: 10_000_000_000_000,
      multiple: 100_000_000,
      is_allow_decrease: true,
      previous_expense: 9_800_000_000,
    },
  },
};
const expense = { code: 0, data: { total_expense: 152_000_000_000, today_expense: 3_216_200_000, max_seven_day_expense: 21_000_000_000, avg_seven_day_expense: 9_800_000_000 } };

describe("ads_campaign_detail (the edit page's limits)", () => {
  it("maps one row per campaign, money in VND, ROAS ratios, stock and price ranges summarised", () => {
    const tag = (id: string) => ({ campaignId: id });
    const post = mapAdsDetail(
      [
        reply("ads_product_get", productGet(7001), tag("7001")),
        reply("ads_roi_recommend", roiRecommend, tag("7001")),
        reply("ads_budget_edit", budgetEdit, tag("7001")),
        reply("ads_expense_stats", expense, tag("7001")),
      ],
      NOW,
    );
    expect(post).toMatchObject({ dataset: "ads_campaign_detail", date: TODAY, granularity: "period", drift: null });
    expect(post.rows).toEqual([
      {
        campaign_id: "7001",
        product_selection: "manual",
        display_location: "all",
        rapid_boost: true,
        item_ids: ["27933768174", "24008937848"],
        item_count: 2,
        out_of_stock_count: 1,
        price_low: 90000,
        price_high: 139000,
        roas_estimate_low: 5.32,
        roas_estimate_high: 8.44,
        roas_recommended: 5.3,
        roas_exact: 7,
        roas_exact_percentile: 50,
        roas_low: 5.3,
        roas_low_percentile: 20,
        roas_high: 8.4,
        roas_high_percentile: 80,
        roas_min: 1.5,
        roas_max: 30,
        gmv_order_uplift: 12,
        roas_daily_edits: 1,
        budget_min: 100000,
        budget_max: 100000000,
        budget_recommended: 186090,
        budget_low_threshold: 111654,
        budget_multiple: 1000,
        budget_allow_decrease: true,
        budget_previous_expense: 98000,
        total_expense: 1520000,
        today_expense: 32162,
        max_7d_expense: 210000,
        avg_7d_expense: 98000,
      },
    ]);
  });
});

// -- the detail reader ---------------------------------------------------------------------

function harness(templates: Partial<Record<ReaderEndpoint, Template>>, answer: (r: ReaderRequest) => unknown) {
  let clock = 1_000_000;
  const sent: ReaderRequest[] = [];
  const sleep = async (ms: number) => {
    clock += ms;
  };
  const now = () => clock;
  const env: ReaderEnv = {
    origin: SC,
    pacer: new Pacer({ sleep, now, random: () => 0 }),
    now,
    session: () => ({ SPC_CDS: "s" }),
    hasSession: () => true,
    template: (endpoint) => templates[endpoint],
    waitFor: pollingWaitFor(sleep, now),
    fetch: async (request): Promise<FetchedReaderResponse> => {
      sent.push(request);
      return { status: 200, text: async () => JSON.stringify(answer(request)) };
    },
    pathname: () => "/portal/marketing/pas/product/manual/7001",
  };
  return { env, sent };
}

describe("the ads_detail reader", () => {
  const templates: Partial<Record<ReaderEndpoint, Template>> = {
    ads_product_get: { query: {}, body: { campaign_id: 7001, reference_id: "r1" }, lastResponse: productGet(7001) },
    ads_roi_recommend: { query: {}, body: { campaign_id: 7001, reference_id: "r1" }, lastResponse: roiRecommend },
    ads_budget_edit: { query: {}, body: { campaign_id: 7001 }, lastResponse: budgetEdit },
    ads_expense_stats: { query: {}, body: { campaign_id: 7001 }, lastResponse: expense },
  };

  it("keeps the opened campaign's own answers and replays only the four read calls for the others", async () => {
    const { env, sent } = harness(templates, (r) => {
      const id = Number(JSON.parse(r.body ?? "{}").campaign_id);
      if (r.endpoint === "ads_product_get") return productGet(id);
      if (r.endpoint === "ads_roi_recommend") return roiRecommend;
      if (r.endpoint === "ads_budget_edit") return budgetEdit;
      return expense;
    });
    const outcome = await runReaderJob({ id: "ads_detail", campaignIds: ["7001", "7004"] }, env);
    expect(outcome.status).toBe("done");
    // the opened page's campaign is not asked again; the other one is, once per read endpoint
    expect(sent.map((r) => [r.endpoint, JSON.parse(r.body ?? "{}").campaign_id])).toEqual([
      ["ads_product_get", 7004],
      ["ads_roi_recommend", 7004],
      ["ads_budget_edit", 7004],
      ["ads_expense_stats", 7004],
    ]);
    expect(sent.every((r) => isReadOnlyPasPath(new URL(r.url).pathname))).toBe(true);
    const ids = outcome.responses.filter((r) => r.endpoint === "ads_product_get").map((r) => r.campaignId);
    expect(ids).toEqual(["7001", "7004"]);
    const post = mapReaderJob({ id: "ads_detail", campaignIds: ["7001", "7004"] }, outcome.responses, NOW)[0]!;
    expect(post.rows.map((r) => r.campaign_id)).toEqual(["7001", "7004"]);
  });

  it("only read endpoints are ever replayed", () => {
    expect(isReadOnlyPasPath("/api/pas/v1/product/get/")).toBe(true);
    expect(isReadOnlyPasPath("/api/pas/v1/setup_helper/get_budget_data_for_edit/")).toBe(true);
    expect(isReadOnlyPasPath("/api/pas/v1/setup_helper/get_campaign_expense_statistics/")).toBe(true);
    for (const write of ["/api/pas/v1/product/edit/", "/api/pas/v1/product/update/", "/api/pas/v1/banner/modify/", "/api/pas/v1/product/create/", "/api/pas/v1/campaign/delete/"]) {
      expect(isReadOnlyPasPath(write)).toBe(false);
    }
  });

  it("opens the opened campaign's own edit page (manual or mpd)", () => {
    expect(readerPageUrl({ id: "ads_detail", campaignIds: ["7001"], campaignKinds: ["manual"] })).toBe("/portal/marketing/pas/product/manual/7001");
    expect(readerPageUrl({ id: "ads_detail", campaignIds: ["7004"], campaignKinds: ["mpd"] })).toBe("/portal/marketing/pas/product/manual-mpd/7004");
    expect(readerPageUrl({ id: "ads" })).toBe("/portal/marketing/pas/index");
  });
});

describe("planning", () => {
  const base = { shopId: PILOT, nowMs: NOW, stopped: new Set<never>(), adsDone: [] as string[], readers: ["ads", "ads_detail"] as const };
  const allRead = ["2026-11-05", "2026-11-04", "2026-11-03", "2026-11-02"];

  it("the list is re-read once a day for its settings even when every ads day is posted", () => {
    expect(planJobs({ ...base, adsDone: allRead, adsSettingsDay: "2026-11-05" }).find((j) => j.id === "ads")).toEqual({ id: "ads", days: [] });
    expect(planJobs({ ...base, adsDone: allRead, adsSettingsDay: TODAY }).find((j) => j.id === "ads")).toBeUndefined();
  });

  it("the detail page job is planned after the list", () => {
    expect(planJobs(base).map((j) => j.id)).toEqual(["ads", "ads_detail"]);
  });
});

// F3 (0.3.11): which ads days count as read.
describe("an ads day is read only when campaigns posted or Shopee answered zero campaigns", async () => {
  const { adsDayRead } = await import("../src/background/scheduler");
  const DAY = "2026-11-02";
  const answer = (body: unknown) => [{ ...reply("ads_homepage", body, { day: DAY }) }];
  const shopOnly = { code: 0, data: { entry_list: [{ title: "GMV Max shop", campaign: {}, report: { cost: 1 } }] } };
  const zero = { code: 0, data: { entry_list: [] } };

  it("only the ROAS-target row came back: not read", () => {
    expect(adsDayRead("posted", [], DAY)).toBe(false);
  });
  it("a GMV Max shop-level entry alone is skipped (not drift) and the day is read", () => {
    expect(adsDayRead("posted", answer(shopOnly), DAY)).toBe(true);
    expect(adsDayRead("ignored", answer(shopOnly), DAY)).toBe(true);
  });
  it("Shopee answered an empty list: read; an unfinished day (nothing) is not", () => {
    expect(adsDayRead("ignored", answer(zero), DAY)).toBe(true);
    expect(adsDayRead("ignored", [], DAY)).toBe(false);
    expect(adsDayRead("rejected", answer(zero), DAY)).toBe(false);
  });
});
