// Connector 0.3.11 (P97 T1): shop totals, order lines, per-order income, and the shared request
// budget / rate-limit stop. Fixtures are SYNTHETIC and use the recon's field names; the shapes the
// recon did not record (order cards, income components) are marked TODO(first capture) in the
// mappers and pinned here only as far as the mappers promise.
import { describe, expect, it } from "vitest";
import { ingestBody } from "../src/ingest/client";
import { RAW_ORDER_ID } from "../src/shopee/affiliate-map";
import { completedOrders, mapOrderIncome, mapOrderLines, orderStatusOf, trimOrderCards, trimOrderIndex } from "../src/shopee/orders-map";
import { mapReaderJob } from "../src/shopee/reader-map";
import {
  type FetchedReaderResponse,
  pollingWaitFor,
  type ReaderEnv,
  type ReaderRequest,
  type ReaderResponse,
  runReaderJob,
  type Template,
  trimCaptured,
  withListPage,
  withOrderIds,
} from "../src/shopee/reader";
import type { ReaderEndpoint } from "../src/shopee/endpoints";
import { Pacer } from "../src/shopee/runner";
import { mapShopTotals } from "../src/shopee/totals-map";
import { gmt7DateStart } from "../src/shopee/time";

const SC = "https://banhang.shopee.vn";
// 2026-11-09 10:00 GMT+7
const NOW = Date.UTC(2026, 10, 9, 3, 0, 0);

function harness(
  templates: Partial<Record<ReaderEndpoint, Template>>,
  handler: (request: ReaderRequest) => { status?: number; body?: unknown },
  options: { budget?: number } = {},
): { env: ReaderEnv; sent: ReaderRequest[]; pauses: number[] } {
  let clock = NOW;
  const sent: ReaderRequest[] = [];
  const pauses: number[] = [];
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
    pathname: () => "/datacenter/overview",
    pause: async (ms) => {
      pauses.push(ms);
    },
    random: () => 0,
    ...(options.budget !== undefined ? { budget: { left: options.budget } } : {}),
  };
  return { env, sent, pauses };
}

const ts = (day: string) => gmt7DateStart(day) + 12 * 3600;
const points = (days: Record<string, number>) => Object.entries(days).map(([day, value]) => ({ timestamp: ts(day), value }));
const metric = (days: Record<string, number>) => ({ value: Object.values(days).at(-1), chain_ratio: 0.1, points: points(days) });

const DAYS = ["2026-11-06", "2026-11-07", "2026-11-08"];
const KEY_METRICS = {
  code: 0,
  data: {
    place_gmv: metric({ "2026-11-06": 1_000_000, "2026-11-07": 2_000_000, "2026-11-08": 1_500_000 }),
    place_orders: metric({ "2026-11-06": 5, "2026-11-07": 8, "2026-11-08": 6 }),
    place_sales_per_order: metric({ "2026-11-06": 200_000, "2026-11-07": 250_000, "2026-11-08": 250_000 }),
    paid_gmv: metric({ "2026-11-06": 900_000, "2026-11-07": 1_900_000, "2026-11-08": 1_400_000 }),
    paid_orders: metric({ "2026-11-06": 4, "2026-11-07": 7, "2026-11-08": 6 }),
    confirmed_gmv: metric({ "2026-11-06": 800_000, "2026-11-07": 1_800_000, "2026-11-08": 1_300_000 }),
    confirmed_orders: metric({ "2026-11-06": 4, "2026-11-07": 7, "2026-11-08": 5 }),
    confirmed_gmv_without_shopee_rebate: metric({ "2026-11-06": 780_000, "2026-11-07": 1_750_000, "2026-11-08": 1_250_000 }),
    shop_pv: metric({ "2026-11-06": 300, "2026-11-07": 400, "2026-11-08": 350 }),
    shop_uv: metric({ "2026-11-06": 120, "2026-11-07": 150, "2026-11-08": 140 }),
    product_clicks: metric({ "2026-11-06": 90, "2026-11-07": 110, "2026-11-08": 100 }),
    some_future_metric: { value: 1 },
  },
};
const ORDER_PERFORMANCE = {
  code: 0,
  data: {
    cancelled_sales: metric({ "2026-11-06": 50_000, "2026-11-07": 0, "2026-11-08": 20_000 }),
    return_refund_sales: metric({ "2026-11-06": 0, "2026-11-07": 10_000, "2026-11-08": 0 }),
    cancelled_orders: metric({ "2026-11-06": 1, "2026-11-07": 0, "2026-11-08": 1 }),
    return_refund_orders: metric({ "2026-11-06": 0, "2026-11-07": 1, "2026-11-08": 0 }),
  },
};

function reply(endpoint: ReaderEndpoint, body: unknown, extra: Partial<ReaderResponse> = {}): ReaderResponse {
  return { endpoint, url: "u", status: 200, body, capturedAt: NOW, source: "replay", ...extra };
}

describe("shop totals -> shop_overview", () => {
  const period = { start: "2026-11-06", end: "2026-11-08" };

  it("posts placed, paid and confirmed days from one answer; unknown extra metrics are ignored", () => {
    const posts = mapShopTotals([reply("shop_key_metrics", KEY_METRICS, { period }), reply("shop_order_performance", ORDER_PERFORMANCE, { period })], NOW);
    expect(posts.map((p) => p.orderType)).toEqual(["confirmed", "placed", "paid"]);
    const confirmed = posts[0]!;
    expect(confirmed).toMatchObject({ dataset: "shop_overview", granularity: "day", periodStart: "2026-11-06", date: "2026-11-08", drift: null });
    expect(confirmed.rows).toHaveLength(3);
    expect(confirmed.rows[1]).toEqual({
      date: "2026-11-07",
      sales: 1_800_000,
      orders: 7,
      sales_per_order: 257142.86,
      sales_excl_shopee_subsidy: 1_750_000,
      product_clicks: 110,
      visitors: 150,
      extra: { shop_pv: 400 },
      cancelled_orders: 0,
      cancelled_sales: 0,
      returned_orders: 1,
      returned_sales: 10_000,
    });
    // placed carries the placed numbers and its own AOV; cancels / returns are a confirmed-basis split
    const placed = posts[1]!;
    expect(placed.rows[0]).toMatchObject({ date: "2026-11-06", sales: 1_000_000, orders: 5, sales_per_order: 200_000 });
    expect(placed.rows[0]).not.toHaveProperty("cancelled_orders");
    const body = ingestBody(placed, "0.3.11", NOW);
    expect(body.period).toEqual({ start: "2026-11-06", end: "2026-11-08", granularity: "day" });
    expect(body.order_type).toBe("placed");
  });

  it("never posts a day outside the asked range (a partial today)", () => {
    const withToday = JSON.parse(JSON.stringify(KEY_METRICS));
    withToday.data.confirmed_gmv.points.push({ timestamp: ts("2026-11-09"), value: 5 });
    const [confirmed] = mapShopTotals([reply("shop_key_metrics", withToday, { period })], NOW);
    expect(confirmed!.rows.map((r) => r.date)).toEqual(DAYS);
  });

  it("a one-day answer without points uses its headline value", () => {
    const one = { code: 0, data: { confirmed_gmv: { value: 123_000 }, confirmed_orders: { value: 3 } } };
    const [confirmed] = mapShopTotals([reply("shop_key_metrics", one, { period: { start: "2026-11-08", end: "2026-11-08" } })], NOW);
    expect(confirmed!.rows).toEqual([{ date: "2026-11-08", sales: 123_000, orders: 3, sales_per_order: 41_000 }]);
  });

  it("no GMV metric, or no daily points, is drift (nothing posted); an error answer maps to nothing", () => {
    const [noGmv] = mapShopTotals([reply("shop_key_metrics", { code: 0, data: { shop_uv: metric({ "2026-11-06": 1 }) } }, { period })], NOW);
    expect(noGmv!.drift).toEqual({ unexpected: [], missing: ["key_metrics.confirmed_gmv"] });
    expect(noGmv!.rows).toEqual([]);
    const [noPoints] = mapShopTotals([reply("shop_key_metrics", { code: 0, data: { confirmed_gmv: { value: 1 } } }, { period })], NOW);
    expect(noPoints!.drift?.missing).toEqual(["key_metrics.points"]);
    expect(mapShopTotals([reply("shop_key_metrics", { code: 5, msg: "x" }, { period })], NOW)).toEqual([]);
    expect(mapShopTotals([], NOW)).toEqual([]);
  });

  it("the reader replays key-metrics once for the range, then order-performance (2 requests)", async () => {
    const h = harness(
      { shop_key_metrics: { query: { period: "yesterday" } }, shop_order_performance: { query: { order_type: "confirmed" } } },
      (request) => ({ body: request.endpoint === "shop_key_metrics" ? KEY_METRICS : ORDER_PERFORMANCE }),
    );
    const outcome = await runReaderJob({ id: "shop_totals", days: [...DAYS].reverse() }, h.env);
    expect(outcome.status).toBe("done");
    expect(h.sent).toHaveLength(2);
    const url = new URL(h.sent[0]!.url);
    expect(url.pathname).toBe("/api/mydata/v3/dashboard/key-metrics/");
    expect(url.searchParams.get("start_time")).toBe(String(gmt7DateStart("2026-11-06")));
    expect(url.searchParams.get("end_time")).toBe(String(gmt7DateStart("2026-11-08") + 86_399));
    expect(url.searchParams.get("period")).toBe("past7days");
    expect(new URL(h.sent[1]!.url).searchParams.get("order_type")).toBe("confirmed");
    expect(outcome.responses.every((r) => r.period?.start === "2026-11-06" && r.period.end === "2026-11-08")).toBe(true);
    const posts = mapReaderJob({ id: "shop_totals", days: DAYS }, outcome.responses, NOW);
    expect(posts.map((p) => p.orderType)).toEqual(["confirmed", "placed", "paid"]);
  });

  it("an order-performance answer that fails does not lose the key metrics", async () => {
    const h = harness({ shop_key_metrics: { query: {} } }, (request) =>
      request.endpoint === "shop_key_metrics" ? { body: KEY_METRICS } : { status: 500, body: null },
    );
    const outcome = await runReaderJob({ id: "shop_totals", days: DAYS }, h.env);
    expect(outcome.status).toBe("done");
    const [confirmed] = mapReaderJob({ id: "shop_totals", days: DAYS }, outcome.responses, NOW);
    expect(confirmed!.rows[0]).not.toHaveProperty("cancelled_orders");
    expect(confirmed!.rows[0]).toMatchObject({ sales: 800_000 });
  });
});

// -- order lines --------------------------------------------------------------------------------

/** A synthetic card in the shape the mapper expects (TODO: replace by the first real capture). */
function card(id: string | number, status: string, items: Record<string, unknown>[], extra: Record<string, unknown> = {}) {
  return {
    order_id: id,
    status,
    create_time: ts("2026-11-07"),
    complete_time: status === "completed" ? ts("2026-11-08") : 0,
    pay_time: ts("2026-11-07"),
    buyer_username: "khach_hang_that",
    buyer_name: "Nguyen Van A",
    shipping_address: "12 Duong Gia, Quan 1",
    buyer_phone: "0900000000",
    note_to_seller: "giao gio hanh chinh",
    tracking_number: "SPXVN000",
    shop_voucher_amount: 2_000_000_000,
    items,
    ...extra,
  };
}
const LINE_A = { item_id: 111, model_id: 222, item_sku: "SKU-A", model_sku: "SKU-A-1", model_name: "Hồng", item_name: "Tên sản phẩm", quantity: 2, original_price: 15_000_000_000, order_price: 12_000_000_000 };
const LINE_B = { item_id: 112, model_id: 223, item_sku: "SKU-B", quantity: 1, original_price: 8_000_000_000, order_price: 8_000_000_000 };
const CARDS = { code: 0, data: { card_list: [{ order_card: card("2611071ABC", "completed", [LINE_A, LINE_B]) }, { order_card: card(2611072222222, "cancelled", [LINE_B]) }] } };

describe("order list: PII stays in the page", () => {
  it("the trimmer keeps an allowlist: no username, name, address, phone, note, tracking or product name", () => {
    const trimmed = JSON.stringify(trimOrderCards(CARDS));
    for (const leak of ["khach_hang_that", "Nguyen Van A", "Duong Gia", "0900000000", "giao gio", "SPXVN000", "Tên sản phẩm"]) {
      expect(trimmed).not.toContain(leak);
    }
    expect(trimmed).toContain("SKU-A");
    expect(trimOrderCards(CARDS)).toEqual(trimCaptured("order_cards", CARDS));
    const index = { code: 0, data: { order_list: [{ order_id: 1, buyer_username: "x" }, { order_id: 2 }] } };
    expect(trimOrderIndex(index)).toEqual({ code: 0, data: { list: [{ order_id: 1 }, { order_id: 2 }] } });
  });

  it("maps lines with the order id only as the raw-id key, order-level amounts split by line value", () => {
    const body = trimOrderCards(CARDS);
    const mapped = mapOrderLines([reply("order_cards", body)], NOW);
    expect(mapped).toMatchObject({ dataset: "order_lines", granularity: "period", periodStart: "2026-11-07", date: "2026-11-07", drift: null });
    expect(mapped.rows).toHaveLength(3);
    const first = mapped.rows[0]!;
    expect(first).toMatchObject({ [RAW_ORDER_ID]: "2611071ABC", line_no: 0, status: "delivered", qty: 2, original_price: 150_000, deal_price: 120_000, sku: "SKU-A", variation_sku: "SKU-A-1", variation_name: "Hồng" });
    expect(first.seller_subsidy).toBe(60_000);
    // shop voucher 20 000 split by line value: A = 240 000 of 320 000
    expect(first.shop_voucher_share).toBe(15_000);
    expect(mapped.rows[1]!.shop_voucher_share).toBe(5_000);
    expect(mapped.rows[2]).toMatchObject({ [RAW_ORDER_ID]: "2611072222222", status: "cancelled" });
    // no buyer field of any kind, and no raw name of a person
    expect(JSON.stringify(mapped.rows)).not.toMatch(/khach|Nguyen|0900|Duong/);
    expect(mapped.rows.every((row) => !("order_ref" in row))).toBe(true); // hashed by the service worker
  });

  it("the money scale comes from the amounts: plain VND is read as VND", () => {
    const plain = { code: 0, data: { list: [card("2611073AAA", "completed", [{ ...LINE_B, original_price: 80_000, order_price: 80_000 }], { shop_voucher_amount: 0 })] } };
    const mapped = mapOrderLines([reply("order_cards", plain)], NOW);
    expect(mapped.rows[0]).toMatchObject({ original_price: 80_000, deal_price: 80_000 });
  });

  it("an order missing its time or items is skipped; nothing mapped at all is drift; unknown extras are fine", () => {
    const odd = { code: 0, data: { list: [{ ...card("2611074BBB", "completed", [LINE_B]), create_time: undefined, brand_new_field: 7 }, card("2611075CCC", "completed", [LINE_B])] } };
    const mapped = mapOrderLines([reply("order_cards", odd)], NOW);
    expect(mapped.drift).toBeNull();
    expect(mapped.rows).toHaveLength(1);
    const broken = { code: 0, data: { list: [{ ...card("2611076DDD", "completed", [LINE_B]), create_time: undefined }] } };
    expect(mapOrderLines([reply("order_cards", broken)], NOW).drift?.missing).toEqual(["orders[].create_time"]);
    expect(mapOrderLines([], NOW).rows).toEqual([]);
  });

  it("status words map to the contract values; unknown is in_transit, never delivered", () => {
    expect(orderStatusOf("completed")).toBe("delivered");
    expect(orderStatusOf("Đã hủy")).toBe("cancelled");
    expect(orderStatusOf("cancelled")).toBe("cancelled");
    expect(orderStatusOf("return_refund")).toBe("refunded_not_received");
    expect(orderStatusOf("shipping")).toBe("in_transit");
    expect(orderStatusOf(3)).toBe("in_transit");
  });

  it("the hashed id is the order number (order_sn) when the card has both; the API id is kept for the income call", () => {
    const both = { code: 0, data: { list: [card(5551234567890, "completed", [LINE_B], { order_sn: "2611091SNAAAA" })] } };
    const trimmed = trimOrderCards(both);
    const mapped = mapOrderLines([reply("order_cards", trimmed)], NOW);
    expect(mapped.rows[0]![RAW_ORDER_ID]).toBe("2611091SNAAAA");
    expect(completedOrders([reply("order_cards", trimmed)])).toEqual([{ id: "5551234567890", sn: "2611091SNAAAA", completedAt: ts("2026-11-08") * 1000 }]);
  });

  it("completedOrders lists the delivered orders with their completion time", () => {
    const done = completedOrders([reply("order_cards", trimOrderCards(CARDS))]);
    expect(done).toEqual([{ id: "2611071ABC", completedAt: ts("2026-11-08") * 1000 }]);
  });
});

describe("pagination helpers and the order reader", () => {
  it("withListPage sets the page number or offset wherever the body keeps it, else null", () => {
    expect(withListPage({ pagination: { page_number: 1, page_size: 40 }, filter: {} }, 3, 40)).toEqual({ pagination: { page_number: 3, page_size: 40 }, filter: {} });
    expect(withListPage({ offset: 0, limit: 40 }, 2, 40)).toEqual({ offset: 40, limit: 40 });
    expect(withListPage({ filter: { status: 1 } }, 2, 40)).toBeNull();
  });

  it("withOrderIds swaps the id list of the cards request, keeping its element shape", () => {
    expect(withOrderIds({ order_param_list: [{ order_id: 1 }, { order_id: 2 }], x: 1 }, ["1", "2"], ["7", "8", "9"])).toEqual({
      order_param_list: [{ order_id: 7 }, { order_id: 8 }, { order_id: 9 }],
      x: 1,
    });
    expect(withOrderIds({ ids: [1, 2] }, ["1", "2"], ["5"])).toEqual({ ids: [5] });
    expect(withOrderIds({ ids: [99] }, ["1", "2"], ["5"])).toBeNull();
    expect(withOrderIds({ ids: [1] }, [], ["5"])).toBeNull();
  });

  const search = (page: number) => ({ code: 0, data: { order_list: [{ order_id: page * 10 + 1 }, { order_id: page * 10 + 2 }] } });
  const templates = (): Partial<Record<ReaderEndpoint, Template>> => ({
    order_search: { query: {}, body: { pagination: { page_number: 1, page_size: 2 } }, lastResponse: search(1) },
    order_cards: { query: {}, body: { order_param_list: [{ order_id: 11 }, { order_id: 12 }] }, lastResponse: CARDS },
  });

  it("keeps the page's own first answers (trimmed) and replays at most 5 pages, 20-45 s apart", async () => {
    const h = harness(templates(), (request) => {
      if (request.endpoint === "order_search") {
        const page = JSON.parse(request.body!).pagination.page_number as number;
        return { body: search(page) };
      }
      return { body: CARDS };
    });
    const outcome = await runReaderJob({ id: "orders" }, h.env);
    expect(outcome.status).toBe("done");
    // page 1 from the page itself + pages 2..5: 4 index calls + 4 card calls
    expect(h.sent).toHaveLength(8);
    expect(h.pauses).toHaveLength(4);
    expect(h.pauses.every((ms) => ms >= 20_000 && ms <= 45_000)).toBe(true);
    expect(outcome.responses.filter((r) => r.source === "page").map((r) => r.endpoint)).toEqual(["order_search", "order_cards"]);
    // the replayed card request carries the NEW ids
    expect(JSON.parse(h.sent[1]!.body!).order_param_list).toEqual([{ order_id: 21 }, { order_id: 22 }]);
    expect(JSON.stringify(outcome.responses)).not.toMatch(/khach_hang_that|Duong Gia|0900000000/);
  });

  it("a failed replay of page 2+ still returns done with the answers already read, plus a partial note", async () => {
    const h = harness(templates(), (request) => {
      if (request.endpoint === "order_search") {
        const page = JSON.parse(request.body!).pagination.page_number as number;
        if (page === 3) return { status: 500, body: { error: 1 } };
        return { body: search(page) };
      }
      return { body: CARDS };
    });
    const outcome = await runReaderJob({ id: "orders" }, h.env);
    expect(outcome.status).toBe("done");
    expect(outcome.detail).toBe("partial:order_search:http_500");
    // page 1 (the page's own) and the complete page 2 stay; the failed page 3 is dropped
    expect(outcome.responses.map((r) => r.page)).toEqual([1, 1, 2, 2]);
  });

  it("a CAPTCHA while replaying page 2 still stops everything", async () => {
    const h = harness(templates(), () => ({ status: 403, body: { error: "captcha" } }));
    const outcome = await runReaderJob({ id: "orders" }, h.env);
    expect(outcome.status).not.toBe("done");
  });

  it("without a recognisable page number it reads only what the page loaded", async () => {
    const t = templates();
    t.order_search = { query: {}, body: { filter: { status: 1 } }, lastResponse: search(1) };
    const h = harness(t, () => ({ body: CARDS }));
    const outcome = await runReaderJob({ id: "orders" }, h.env);
    expect(outcome.status).toBe("done");
    expect(h.sent).toHaveLength(0);
    expect(outcome.responses).toHaveLength(2);
  });

  it("the page's own answers are never replayed beyond the read-only order list / search paths", async () => {
    const h = harness(templates(), (request) => ({ body: request.endpoint === "order_search" ? search(2) : CARDS }));
    await runReaderJob({ id: "orders" }, h.env);
    for (const request of h.sent) {
      expect(new URL(request.url).pathname).toMatch(/^\/api\/v3\/order\/(search_order_list_index|get_order_list_card_list)$/);
    }
  });
});

// -- per-order income ---------------------------------------------------------------------------

const INCOME = (id: string, final: number | null) => ({
  code: 0,
  data: {
    order_id: id,
    sections: [
      { title: "Tổng quan", items: [{ name: "Giá sản phẩm", amount: 150_000 }, { name: "Doanh thu đơn hàng ước tính", amount: 120_000 }] },
      {
        title: "Phụ phí",
        items: [
          { name: "Phí cố định", amount: -9_000 },
          { name: "Phí Dịch Vụ", amount: -7_500 },
          { name: "Phí xử lý giao dịch", amount: -3_000 },
          { name: "Phí dịch vụ PiShip", amount: -1_000 },
          { name: "Mã giảm giá của Shop", amount: -2_000 },
        ],
      },
      ...(final === null ? [] : [{ title: "Tổng kết", items: [{ name: "Số tiền cuối cùng", amount: final }] }]),
    ],
  },
});

describe("per-order income", () => {
  it("maps Vietnamese component labels; costs are positive, the payout is signed; extras are ignored", () => {
    const mapped = mapOrderIncome([reply("order_income_components", INCOME("2611071ABC", 118_500), { orderId: "2611071ABC" })], NOW);
    expect(mapped).toMatchObject({ dataset: "order_income", granularity: "period", drift: null });
    expect(mapped.rows).toEqual([
      {
        [RAW_ORDER_ID]: "2611071ABC",
        product_price: 150_000,
        fee_fixed: 9_000,
        fee_service: 7_500,
        fee_payment: 3_000,
        fee_piship: 1_000,
        seller_voucher_borne: 2_000,
        payout: 118_500,
      },
    ]);
  });

  it("an order without its final amount yet is skipped (estimate only); all skipped = drift", () => {
    const answers = [reply("order_income_components", INCOME("1AAAAAA", 100), { orderId: "1AAAAAA" }), reply("order_income_components", INCOME("2BBBBBB", null), { orderId: "2BBBBBB" })];
    expect(mapOrderIncome(answers, NOW).rows).toHaveLength(1);
    const none = mapOrderIncome([answers[1]!], NOW);
    expect(none.rows).toEqual([]);
    expect(none.drift?.missing).toEqual(["components.final_amount"]);
    expect(mapOrderIncome([], NOW).rows).toEqual([]);
  });

  it("amounts sent x100 000 are read from their size", () => {
    const scaled = JSON.parse(JSON.stringify(INCOME("1CCCCCC", 11_850_000_000)));
    scaled.data.sections[0].items[0].amount = 15_000_000_000;
    const mapped = mapOrderIncome([reply("order_income_components", scaled, { orderId: "1CCCCCC" })], NOW);
    expect(mapped.rows[0]).toMatchObject({ product_price: 150_000, payout: 118_500 });
  });

  it("the reader keeps the opened order's own answer and replays the others with only the order id changed", async () => {
    const template: Template = { query: { order_id: "2611071ABC", region: "VN" }, lastResponse: INCOME("2611071ABC", 118_500) };
    const h = harness({ order_income_components: template }, (request) => {
      const id = new URL(request.url).searchParams.get("order_id")!;
      return { body: INCOME(id, 90_000) };
    });
    const outcome = await runReaderJob({ id: "order_income", orderIds: ["2611071ABC", "2611072DEF", "2611073GHI"] }, h.env);
    expect(outcome.status).toBe("done");
    expect(h.sent).toHaveLength(2);
    expect(h.sent.map((r) => new URL(r.url).searchParams.get("order_id"))).toEqual(["2611072DEF", "2611073GHI"]);
    expect(h.sent.every((r) => new URL(r.url).searchParams.get("region") === "VN")).toBe(true);
    const posts = mapReaderJob({ id: "order_income" }, outcome.responses, NOW);
    expect(posts[0]!.rows.map((row) => row[RAW_ORDER_ID])).toEqual(["2611071ABC", "2611072DEF", "2611073GHI"]);
  });

  it("the hashed id of an income answer is the order number the queue knew", async () => {
    const template: Template = { query: { order_id: "5551" }, lastResponse: INCOME("5551", 118_500) };
    const h = harness({ order_income_components: template }, (request) => ({ body: INCOME(new URL(request.url).searchParams.get("order_id")!, 90_000) }));
    const outcome = await runReaderJob({ id: "order_income", orderIds: ["5551", "5552"], orderSns: ["SN1AAAAAA", ""] }, h.env);
    const rows = mapReaderJob({ id: "order_income" }, outcome.responses, NOW)[0]!.rows;
    expect(rows.map((row) => row[RAW_ORDER_ID])).toEqual(["SN1AAAAAA", "5552"]);
  });

  it("without the order id in the page's own request nothing is replayed", async () => {
    const h = harness({ order_income_components: { query: { x: "1" }, lastResponse: INCOME("2611071ABC", 1) } }, () => ({ body: INCOME("z", 1) }));
    const outcome = await runReaderJob({ id: "order_income", orderIds: ["2611071ABC", "2611072DEF"] }, h.env);
    expect(h.sent).toHaveLength(0);
    expect(outcome.status).toBe("done");
  });
});

// -- the shared budget and the rate-limit stop, at reader level --------------------------------

describe("request budget and rate-limit stop (reader level)", () => {
  const incomeTemplate = (): Template => ({ query: { order_id: "2611071ABC" }, lastResponse: INCOME("2611071ABC", 1) });

  it("the budget is checked before EVERY replay: when it is spent the job stops with budget_spent", async () => {
    const h = harness({ order_income_components: incomeTemplate() }, (request) => ({ body: INCOME(new URL(request.url).searchParams.get("order_id")!, 1) }), { budget: 2 });
    const outcome = await runReaderJob({ id: "order_income", orderIds: ["2611071ABC", "A1", "A2", "A3", "A4"] }, h.env);
    expect(outcome.status).toBe("budget_spent");
    expect(h.sent).toHaveLength(2);
  });

  it("no budget granted (0) sends nothing at all", async () => {
    const h = harness({ order_income_components: incomeTemplate() }, () => ({ body: INCOME("x", 1) }), { budget: 0 });
    const outcome = await runReaderJob({ id: "order_income", orderIds: ["2611071ABC", "A1"] }, h.env);
    expect(outcome.status).toBe("budget_spent");
    expect(h.sent).toHaveLength(0);
  });

  it.each([
    ["HTTP 429", { status: 429, body: {} }],
    ["HTTP 403 (not the anti-fraud page)", { status: 403, body: { error: 5 } }],
    ["a Shopee message that says too many requests", { status: 200, body: { code: 9, msg: "Too many requests" } }],
  ])("%s stops the job as blocked_rate (all readers, no tolerance)", async (_name, answer) => {
    const h = harness({ order_income_components: incomeTemplate() }, () => answer);
    const outcome = await runReaderJob({ id: "order_income", orderIds: ["2611071ABC", "A1", "A2"] }, h.env);
    expect(outcome.status).toBe("blocked_rate");
    expect(h.sent).toHaveLength(1);
  });
});
