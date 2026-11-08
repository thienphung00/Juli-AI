import { describe, expect, it } from "vitest";
import { AFFILIATE_READER_IDS, AFFILIATE_WINDOW_DAYS, READER_DATASETS, READER_IDS } from "../src/config";
import { ingestBody } from "../src/ingest/client";
import { importOrderRefKey, orderRef } from "../src/ingest/order-ref";
import {
  displayNumber,
  mapAffiliateBills,
  mapAffiliateCampaigns,
  mapAffiliateCommissions,
  mapAffiliateContent,
  mapAffiliateConversions,
  mapAffiliatePartners,
  mapAffiliateProducts,
  mapAffiliateShop,
  RAW_ORDER_ID,
  scaleFromPairs,
} from "../src/shopee/affiliate-map";
import { isCapturedEndpoint, READER_PAGES, readerEndpointOf, type ReaderEndpoint } from "../src/shopee/endpoints";
import {
  type FetchedReaderResponse,
  periodOfTemplate,
  pollingWaitFor,
  type ReaderEnv,
  type ReaderRequest,
  type ReaderResponse,
  runReaderJob,
  type Template,
  trimCaptured,
} from "../src/shopee/reader";
import { Pacer } from "../src/shopee/runner";
import { gmt7DateStart } from "../src/shopee/time";

const SC = "https://banhang.shopee.vn";
// 2026-11-06 09:00 GMT+7
const NOW = Date.UTC(2026, 10, 6, 2, 0, 0);
const GQL = "/api/v3/affiliateplatform/gql";

function harness(
  templates: Partial<Record<ReaderEndpoint, Template>>,
  handler: (request: ReaderRequest) => { status?: number; body?: unknown },
): { env: ReaderEnv; sent: ReaderRequest[] } {
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
    pathname: () => "/portal/web-seller-affiliate/x",
  };
  return { env, sent };
}

// Two real-shaped orders (recon 2026-11-06 key names; synthetic values). Money is VND x 100 000,
// as the display twins show.
function order(id: string, kol: string, items: Record<string, unknown>[]) {
  return {
    order_id: id,
    purchase_time: gmt7DateStart("2026-11-05") + 14 * 3600 + 56 * 60,
    conversion_complete_time: 0,
    order_complete_time: 0,
    order_status: "Đang xử lý",
    fraud_status: 1,
    shopee_username: kol,
    display_name: "Nguyen Van Kol",
    avatar: "https://cf.shopee.vn/avatar",
    user_id: "990011",
    buyer_status: 1,
    linked_mcn_name: "",
    traffic_type: 2,
    items,
  };
}
const ITEM = {
  item_id: "24334416779",
  model_id: "340525665541",
  item_name: "[Combo] 3,5,10 Hộp Găng Tay",
  item_price: 12_636_000_000,
  dis_item_price: "₫126.360",
  actual_amount: 12_636_000_000,
  dis_actual_amount: "₫126.360",
  refunded_amount: 0,
  dis_refunded_amount: "₫0",
  qty: 1,
  expense: "1010880000",
  campaign_type: 1,
  img_code: "abc",
};
const CONVERSION_PAGE = {
  code: 0,
  msg: "success",
  data: {
    page_num: 1,
    page_size: 20,
    total_count: 2,
    list: [
      order("261105GDSAEB5W", "anhkienhcm01", [ITEM]),
      order("261104ENT9FEDS", "nghithuy654", [{ ...ITEM, item_id: "26107129526", model_id: "420525740151", item_price: 8_262_000_000, dis_item_price: "₫82.620", actual_amount: 8_262_000_000, dis_actual_amount: "₫82.620" }]),
    ],
  },
};

describe("affiliate endpoints and pages", () => {
  it("every affiliate reader has a page and a dataset", () => {
    for (const id of AFFILIATE_READER_IDS) {
      expect(READER_IDS).toContain(id);
      expect(READER_PAGES[id].path.startsWith("/portal/web-seller-affiliate/")).toBe(true);
      expect(READER_DATASETS[id].length).toBe(1);
    }
  });

  it("a GraphQL call matches only its own query operation, and a mutation never matches", () => {
    expect(readerEndpointOf("POST", GQL, "GetShopCampaign")).toBe("affiliate_shop_campaign");
    expect(readerEndpointOf("POST", GQL, "QueryCommissionList")).toBe("affiliate_commission_list");
    expect(readerEndpointOf("POST", GQL, "AutoAddProductsMutation")).toBeNull();
    expect(readerEndpointOf("POST", GQL, "QuickCreateOpenCampaignsMutation")).toBeNull();
    expect(readerEndpointOf("POST", GQL, null)).toBeNull();
    expect(readerEndpointOf("POST", GQL, "SomethingElse")).toBeNull();
    expect(readerEndpointOf("GET", "/api/v3/affiliateplatform/conversion/report/list")).toBe("affiliate_conversion");
  });

  it("only the conversion report is replayed; every other affiliate answer is captured", () => {
    expect(isCapturedEndpoint("affiliate_conversion")).toBe(false);
    for (const e of ["affiliate_performance", "affiliate_seller_daily", "affiliate_item_detail", "affiliate_validation", "affiliate_shop_campaign", "affiliate_commission_list", "affiliate_content_summary", "affiliate_latest_date"] as const) {
      expect(isCapturedEndpoint(e)).toBe(true);
    }
  });
});

describe("conversion report reader", () => {
  it("replays the page's GET over the last 30 finished days, page by page, and trims personal fields", async () => {
    const template: Template = { query: { page_num: "1", page_size: "20", purchase_time_s: "1", purchase_time_e: "2" } };
    const { env, sent } = harness({ affiliate_conversion: template }, () => ({ body: CONVERSION_PAGE }));
    const outcome = await runReaderJob({ id: "affiliate" }, env);
    expect(outcome.status).toBe("done");
    expect(sent).toHaveLength(1); // 2 rows < page size 20
    const url = new URL(sent[0]!.url);
    expect(url.pathname).toBe("/api/v3/affiliateplatform/conversion/report/list");
    expect(sent[0]!.method).toBe("GET");
    expect(url.searchParams.get("page_num")).toBe("1");
    expect(Number(url.searchParams.get("purchase_time_s"))).toBe(gmt7DateStart("2026-10-07"));
    expect(Number(url.searchParams.get("purchase_time_e"))).toBe(gmt7DateStart("2026-11-05") + 86_399);
    const text = JSON.stringify(outcome.responses[0]!.body);
    for (const leaked of ["Nguyen Van Kol", "avatar", "990011", "buyer_status", "item_name", "img_code"]) {
      expect(text).not.toContain(leaked);
    }
    expect(outcome.responses[0]!.period).toEqual({ start: "2026-10-07", end: "2026-11-05" });
    expect(AFFILIATE_WINDOW_DAYS).toBeLessThanOrEqual(31);
  });

  it("maps each order line; the order id stays a raw marker until the service worker hashes it", () => {
    const response: ReaderResponse = {
      endpoint: "affiliate_conversion",
      url: `${SC}/x`,
      status: 200,
      body: trimCaptured("affiliate_conversion", CONVERSION_PAGE),
      capturedAt: NOW,
      source: "replay",
      period: { start: "2026-10-06", end: "2026-11-05" },
    };
    const mapped = mapAffiliateConversions([response], NOW);
    expect(mapped.drift).toBeNull();
    expect(mapped.dataset).toBe("affiliate_order_lines");
    expect(mapped.rows).toHaveLength(2);
    const first = mapped.rows[0]!;
    expect(first).toMatchObject({
      [RAW_ORDER_ID]: "261105GDSAEB5W",
      line_no: 0,
      affiliate: true,
      item_id: "24334416779",
      model_id: "340525665541",
      price: 126360,
      order_value: 126360,
      refund_amount: 0,
      cost: 10108.8,
      qty: 1,
      ordered_at: "2026-11-05T14:56:00",
      affiliate_account: "anhkienhcm01",
      campaign_type: "1",
      channel: "2",
    });
    expect(JSON.stringify(mapped.rows)).not.toContain("Nguyen Van Kol");
    const body = ingestBody(mapped, "0.3.6", NOW);
    expect(body.period).toEqual({ start: "2026-10-06", end: "2026-11-05", granularity: "period" });
  });

  it("a money scale the display twins contradict still posts the order and drops the odd amount", () => {
    const bad = structuredClone(CONVERSION_PAGE);
    (bad.data.list[0]!.items[0] as Record<string, unknown>).item_price = 999;
    const mapped = mapAffiliateConversions(
      [{ endpoint: "affiliate_conversion", url: "x", status: 200, body: bad, capturedAt: NOW, source: "replay", period: { start: "2026-10-06", end: "2026-11-05" } }],
      NOW,
    );
    expect(mapped.drift).toBeNull();
    expect(mapped.rows.length).toBeGreaterThan(0);
  });
});

describe("captured affiliate pages", () => {
  const latest = { code: 0, data: { latest_report_date: "2026-11-04" } };

  it("reads the page's own answer (no request sent) and dates it from the page's request", async () => {
    const perf = {
      code: 0,
      data: {
        list: [
          { affiliate_id: 777001, user_id: "123", shopee_username: "kol_one", avatar: "x", clicks: 40, orders: 3, gmv: 30_000_000_000, dis_gmv: "₫300.000", est_commission: 2_400_000_000, dis_est_commission: "₫24.000", actual_commission: 2_400_000_000, roi: 12.5, item_sold: 4, total_buyers: 3, new_buyers: 2, conversion_rate: 7.5 },
        ],
        sum_key_metrics: { sum_orders: 3 },
      },
    };
    const templates: Partial<Record<ReaderEndpoint, Template>> = {
      affiliate_performance: { query: { start_time: String(gmt7DateStart("2026-11-04")), end_time: String(gmt7DateStart("2026-11-04") + 86_399) }, lastResponse: trimCaptured("affiliate_performance", perf) },
      affiliate_latest_date: { query: {}, lastResponse: latest },
    };
    const { env, sent } = harness(templates, () => ({ body: {} }));
    const outcome = await runReaderJob({ id: "affiliate_kols" }, env);
    expect(outcome.status).toBe("done");
    expect(sent).toHaveLength(0);
    const response = outcome.responses.find((r) => r.endpoint === "affiliate_performance")!;
    expect(response.source).toBe("page");
    expect(response.period).toEqual({ start: "2026-11-04", end: "2026-11-04" });
    expect(JSON.stringify(response.body)).not.toContain("avatar");
    expect(JSON.stringify(response.body)).not.toContain('"user_id"');
    const mapped = mapAffiliatePartners(outcome.responses, NOW);
    expect(mapped.drift).toBeNull();
    expect(mapped.rows[0]).toEqual({
      affiliate_id: "777001",
      account: "kol_one",
      sales: 300000,
      orders: 3,
      units: 4,
      clicks: 40,
      buyers: 3,
      new_buyers: 2,
      est_commission: 24000,
      roi: 12.5,
      extra: { actual_commission: 24000, conversion_rate: 0.075 },
    });
    expect(ingestBody(mapped, "0.3.6", NOW).period).toEqual({ start: "2026-11-04", end: "2026-11-04", granularity: "period" });
  });

  it("without the page's own request period the latest report day is used; a page that loaded nothing is needs_template", async () => {
    const detail = { code: 0, data: { list: [{ item_id: 24334416779, price: 12_636_000_000, gmv: 25_272_000_000, dis_gmv: "₫252.720", sale: 2, spend: 2_021_760_000, roi: 12.5, orders: 2, total_buyers: 2, new_buyers: 1, clicks: 30 }] } };
    const { env } = harness({ affiliate_item_detail: { query: {}, lastResponse: detail }, affiliate_latest_date: { query: {}, lastResponse: latest } }, () => ({ body: {} }));
    const outcome = await runReaderJob({ id: "affiliate_products" }, env);
    const mapped = mapAffiliateProducts(outcome.responses, NOW);
    expect(mapped.drift).toBeNull();
    expect(mapped.date).toBe("2026-11-04");
    expect(mapped.rows[0]).toMatchObject({ item_id: "24334416779", price: 126360, sales: 252720, units: 2, est_commission: 20217.6 });
    const empty = harness({}, () => ({ body: {} }));
    expect((await runReaderJob({ id: "affiliate_bills" }, empty.env)).status).toBe("needs_template");
  });

  it("GraphQL variables give the period; mutations are never part of a job", () => {
    const template: Template = { query: { q: "QueryCommissionList" }, body: { operationName: "QueryCommissionList", variables: { startTime: gmt7DateStart("2026-10-06"), endTime: gmt7DateStart("2026-11-04") + 86_399, pageNum: 1 } } };
    expect(periodOfTemplate(template)).toEqual({ start: "2026-10-06", end: "2026-11-04" });
  });

  it("seller_daily: one post per day plus the direct / indirect split of the page's period", () => {
    const daily = {
      code: 0,
      data: {
        list: [
          { ymd: "20261103", actual_amount: 50_000_000_000, order_count: 4, seller_gross_commission: 4_000_000_000, roi: 12.5, gross_item_sold: 5, total_buyers: 4, new_buyers: 2, actual_commission: 3_900_000_000, clicks: 120 },
          { ymd: "20261104", actual_amount: 30_000_000_000, order_count: 2, seller_gross_commission: 2_400_000_000, roi: 12.5, gross_item_sold: 2, total_buyers: 2, new_buyers: 1, actual_commission: 2_400_000_000, clicks: 80 },
        ],
        seller_attribution_breakdown: { direct_orders: 5, indirect_orders: 1, direct_order_amount: 70_000_000_000, indirect_order_amount: 10_000_000_000 },
        total_order_count: 6,
      },
    };
    // No display twins here: the fallback scale (x 100 000) is used and passes the plausibility check.
    const posts = mapAffiliateShop(
      [{ endpoint: "affiliate_seller_daily", url: "x", status: 200, body: daily, capturedAt: NOW, source: "page", period: { start: "2026-11-03", end: "2026-11-04" } }],
      NOW,
    );
    expect(posts.map((p) => [p.periodStart, p.date])).toEqual([
      ["2026-11-03", "2026-11-03"],
      ["2026-11-04", "2026-11-04"],
      ["2026-11-03", "2026-11-04"],
    ]);
    expect(posts[0]!.rows[0]).toMatchObject({ sales: 500000, orders: 4, units: 5, clicks: 120, est_commission: 40000, actual_commission: 39000 });
    expect(posts[2]!.rows[0]).toEqual({ direct_orders: 5, indirect_orders: 1, direct_sales: 700000, indirect_sales: 100000 });
  });

  it("campaign terms, commission list, content summary and bills", () => {
    const at = (endpoint: ReaderEndpoint, body: unknown, period?: { start: string; end: string }): ReaderResponse => ({ endpoint, url: "x", status: 200, body, capturedAt: NOW, source: "page", ...(period ? { period } : {}) });
    const camp = mapAffiliateCampaigns([at("affiliate_shop_campaign", { data: { shopCampaigns: [{ commissionId: "5001", commissionName: "Chiến dịch mở rộng", commissionRate: 8, commissionStatus: 1, periodStartTime: gmt7DateStart("2026-01-03"), periodEndTime: 0, budget: 200_000_000_000 }] } })], NOW);
    expect(camp.rows[0]).toEqual({ campaign_id: "5001", campaign_name: "Chiến dịch mở rộng", commission_rate: 0.08, status: "1", starts_on: "2026-01-03", budget: 2000000 });
    expect(camp.date).toBe("2026-11-06");
    const period = { start: "2026-10-06", end: "2026-11-04" };
    const comm = mapAffiliateCommissions([at("affiliate_commission_list", { data: { commissionList: { pagination: { totalCount: 1 }, list: [{ commissionId: 5001, affiliates: 3, itemSold: 4, orderAmount: 48_000_000_000, estCommission: 3_840_000_000, itemId: "24334416779" }] } } }, period)], NOW);
    expect(comm.rows[0]).toEqual({ campaign_id: "5001", item_id: "24334416779", kols: 3, units: 4, sales: 480000, est_commission: 38400 });
    const content = mapAffiliateContent([at("affiliate_content_summary", { data: { sellerContentSummary: { itemSold: 3, gmv: 30_000_000_000, comments: 6, gpm: 25_000_000, orders: 2, contentsCount: 4, views: 1200, likes: 40 } } }, period)], NOW);
    expect(content.rows[0]).toEqual({ sales: 300000, units: 3, orders: 2, contents: 4, views: 1200, likes: 40, comments: 6, gpm: 250 });
    const bills = mapAffiliateBills([at("affiliate_validation", { data: { list: [{ validation_id: 88001, validation_month: "2026-10", online_bill: { commission_amount: 1_200_000_000_000, deducted_amount: 1_200_000_000_000, pending_amount: 0 } }, { validation_id: 88002, validation_month: "2026-11", online_bill: { commission_amount: 300_000_000_000 } }] } })], NOW);
    expect(bills.map((b) => [b.periodStart, b.date])).toEqual([
      ["2026-10-01", "2026-10-31"],
      ["2026-11-01", "2026-11-06"],
    ]);
    expect(bills[0]!.rows[0]).toEqual({ bill_code: "88001", commission: 12000000, total_deduction: 12000000, pending_amount: 0 });
  });

  it("a captured answer with no period is drift, not a guess", () => {
    const mapped = mapAffiliatePartners([{ endpoint: "affiliate_performance", url: "x", status: 200, body: { data: { list: [] } }, capturedAt: NOW, source: "page" }], NOW);
    expect(mapped.drift?.missing).toEqual(["period"]);
  });
});

describe("money scale helpers", () => {
  it("reads Vietnamese display numbers and the scale from pairs", () => {
    expect(displayNumber("₫126.360")).toBe(126360);
    expect(displayNumber("1.234,5")).toBe(1234.5);
    expect(scaleFromPairs([{ gmv: 12_636_000_000, dis_gmv: "₫126.360" }], ["gmv"])).toBe(100_000);
    expect(scaleFromPairs([{ gmv: 126360, dis_gmv: "₫126.360" }], ["gmv"])).toBe(1);
    expect(scaleFromPairs([{ gmv: 5, dis_gmv: "₫126.360" }], ["gmv"])).toBeNull();
    expect(scaleFromPairs([{ gmv: 5 }], ["gmv"])).toBeUndefined();
  });

  it("order_ref matches the Ops upload page's function (same key, same id)", async () => {
    const key = await importOrderRefKey("00112233445566778899aabbccddeeff");
    const a = await orderRef(" 261105gdsaeb5w ", key);
    expect(a).toMatch(/^[0-9a-f]{32}$/);
    expect(await orderRef("261105GDSAEB5W", key)).toBe(a);
  });
});
