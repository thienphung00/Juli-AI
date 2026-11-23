// @vitest-environment jsdom
// batch-1123-a2 C-A2: on the card-list path (the page's own card answer holds orders), a card
// whose line names no SKU (a combo's parent row: posted as `sku:unknown`, live 23/11) has its order
// read with get_one_order, budget-counted, so the posted lines carry the combo's item ids. A refused
// read keeps the card's lines and says so. Every value here is synthetic.
import { describe, expect, it } from "vitest";
import { RAW_ORDER_ID } from "../src/platforms/shopee/affiliate-map";
import { cardOrdersWithoutSku, mapOrderLines } from "../src/platforms/shopee/orders-map";
import {
  BUNDLE_DETAIL_REFUSED,
  type FetchedReaderResponse,
  pollingWaitFor,
  type ReaderEnv,
  type ReaderRequest,
  type ReaderResponse,
  runReaderJob,
} from "../src/platforms/shopee/reader";
import { Pacer } from "../src/platforms/shopee/runner";
import { gmt7DateStart } from "../src/core/time";

const SC = "https://banhang.shopee.vn";
const NOW = Date.UTC(2026, 10, 23, 3, 0, 0);
const CREATED = gmt7DateStart("2026-11-23") + 9 * 3600;

/** A card answer: order 5001 is a combo (parent row with no SKU), order 5002 a plain line. */
const CARDS = {
  code: 0,
  data: {
    list: [
      {
        order_id: 5001,
        order_sn: "261123COMBO01",
        create_time: CREATED,
        status: "Chờ lấy hàng",
        items: [{ amount: 1, order_price: 19_000_000_000, item_price: 19_000_000_000, bundle_deal_id: 77 }],
      },
      {
        order_id: 5002,
        order_sn: "261123PLAIN02",
        create_time: CREATED,
        status: "Chờ lấy hàng",
        items: [{ item_id: 9002, model_id: 9202, amount: 1, order_price: 10_000_000_000, item_price: 10_000_000_000, model_sku: "SKU-B" }],
      },
    ],
  },
};

/** get_one_order for the combo: its own lines with item ids (whole dong). */
function comboDetail() {
  return {
    code: 0,
    data: {
      order_id: 5001,
      order_sn: "261123COMBO01",
      status_info: { status: "Chờ lấy hàng" },
      create_time: CREATED,
      complete_time: 0,
      total_price: "190000",
      order_items: [
        {
          amount: 1,
          order_price: "190000",
          bundle_deal_id: 77,
          bundle_deal_model: [
            { item_id: 9001, model_id: 9101, amount: 1, order_price: "100000", item_model: { sku: "SKU-A1", model_id: 9101 } },
            { item_id: 9003, model_id: 9301, amount: 1, order_price: "90000", item_model: { sku: "SKU-C1", model_id: 9301 } },
          ],
        },
      ],
      shipping_address: { name: "Nguoi Mua Gia", phone: "0900000000" },
    },
  };
}

function cardsEnv(options: { budget?: number; refuse?: boolean } = {}) {
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
    template: (endpoint) =>
      endpoint === "order_cards"
        ? { query: {}, body: {}, lastResponse: CARDS }
        : endpoint === "order_search"
          ? { query: {}, body: { filter: {} }, lastResponse: { code: 0, data: { list: [{ order_id: 5001 }, { order_id: 5002 }] } } }
          : undefined,
    waitFor: pollingWaitFor(sleep, now),
    fetch: async (request): Promise<FetchedReaderResponse> => {
      sent.push(request);
      // a server error on that one order (a login / CAPTCHA / rate answer still stops the job, as on the links path)
      if (options.refuse) return { status: 500, text: async () => "{}" };
      return { status: 200, text: async () => JSON.stringify(comboDetail()) };
    },
    pathname: () => "/portal/sale/order",
    pause: async () => undefined,
    random: () => 0,
    orderLinks: () => [],
    orderListEmpty: () => false,
    moreOrderPages: () => false,
    ...(options.budget !== undefined ? { budget: { left: options.budget } } : {}),
  };
  return { env, sent };
}

describe("C-A2: combo orders on the card-list path", () => {
  it("cardOrdersWithoutSku names only the card orders with a SKU-less line and no detail yet", () => {
    const cards: ReaderResponse = { endpoint: "order_cards", url: "u", status: 200, body: CARDS, capturedAt: NOW, source: "page" };
    expect(cardOrdersWithoutSku([cards])).toEqual(["5001"]);
    const detail: ReaderResponse = { endpoint: "order_detail", url: "u", status: 200, body: comboDetail(), capturedAt: NOW, source: "replay" };
    expect(cardOrdersWithoutSku([cards, detail])).toEqual([]);
  });

  it("reads get_one_order for the combo only (GET, budget-counted); its lines carry item ids and SKUs, the plain card line stays", async () => {
    const h = cardsEnv({ budget: 10 });
    const outcome = await runReaderJob({ id: "orders", sinceDay: "2026-11-23" }, h.env);
    expect(outcome.status).toBe("done");
    expect(h.sent.map((r) => [r.method, new URL(r.url).pathname, new URL(r.url).searchParams.get("order_id")])).toEqual([["GET", "/api/v3/order/get_one_order", "5001"]]);
    expect(h.env.budget!.left).toBe(9);
    expect(JSON.stringify(outcome.responses)).not.toMatch(/Nguoi Mua|0900000000/);
    const rows = mapOrderLines(outcome.responses, NOW).rows;
    const combo = rows.filter((r) => r[RAW_ORDER_ID] === "261123COMBO01");
    expect(combo.map((r) => [r.variation_sku, (r.extra as Record<string, unknown>).item_id, r.promo_kind])).toEqual([
      ["SKU-A1", "9001", "bundle"],
      ["SKU-C1", "9003", "bundle"],
    ]);
    // no card row of the combo is posted beside its detail lines
    expect(combo.every((r) => r.variation_sku !== undefined)).toBe(true);
    expect(rows.filter((r) => r[RAW_ORDER_ID] === "261123PLAIN02").map((r) => r.variation_sku)).toEqual(["SKU-B"]);
  });

  it("a refused detail keeps the card's lines and ends with the outcome note", async () => {
    const h = cardsEnv({ refuse: true });
    const outcome = await runReaderJob({ id: "orders", sinceDay: "2026-11-23" }, h.env);
    expect(outcome.detail).toBe(BUNDLE_DETAIL_REFUSED);
    const rows = mapOrderLines(outcome.responses, NOW).rows;
    expect(rows.filter((r) => r[RAW_ORDER_ID] === "261123COMBO01")).toHaveLength(1);
  });

  it("an empty budget stops before the detail: partial:budget", async () => {
    const h = cardsEnv({ budget: 0 });
    const outcome = await runReaderJob({ id: "orders", sinceDay: "2026-11-23" }, h.env);
    expect(outcome.detail).toBe("partial:budget");
    expect(h.sent).toHaveLength(0);
  });
});
