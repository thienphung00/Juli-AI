// @vitest-environment jsdom
// Connector 0.3.20: the order list page no longer calls the list endpoints (Shopee's DRM bundle
// loads it), so order_lines were never posted. The reader now takes the order ids from the list
// page's links, pages with the page's own pager, and reads each order with GET get_one_order,
// trimmed IN THE PAGE. Field names as captured on 2026-11-15; every value here is fake.
import { describe, expect, it } from "vitest";
import { ORDER_LIST_MAX_PAGES_PER_RUN } from "../src/platforms/shopee/config";
import { ingestBody } from "../src/platforms/shopee/ingest/client";
import { jobOutcome } from "../src/platforms/shopee/background/scheduler";
import { outcomeStatus } from "../src/platforms/shopee/popup/guide";
import { RAW_ORDER_ID } from "../src/platforms/shopee/affiliate-map";
import { goToNextOrderPage, orderLinksIn, orderListEmptyIn, pagerNextIn } from "../src/platforms/shopee/order-dom";
import { completedOrders, mapOrderLines, orderStatusOf, trimOrderDetail } from "../src/platforms/shopee/orders-map";
import {
  type FetchedReaderResponse,
  type OrderLink,
  orderSnDay,
  pollingWaitFor,
  type ReaderEnv,
  type ReaderRequest,
  type ReaderResponse,
  runReaderJob,
  type Template,
} from "../src/platforms/shopee/reader";
import type { ReaderEndpoint } from "../src/platforms/shopee/endpoints";
import { Pacer } from "../src/platforms/shopee/runner";
import { gmt7DateStart } from "../src/core/time";

const SC = "https://banhang.shopee.vn";
// 2026-11-15 10:00 GMT+7
const NOW = Date.UTC(2026, 10, 15, 3, 0, 0);
const ts = (day: string, hour = 12) => gmt7DateStart(day) + hour * 3600;

/** A get_one_order answer with the captured field names (and the PII it carries, all fake). */
function detail(id: number, sn: string, over: Record<string, unknown> = {}, items?: Record<string, unknown>[]) {
  const day = `20${sn.slice(0, 2)}-${sn.slice(2, 4)}-${sn.slice(4, 6)}`;
  return {
    code: 0,
    data: {
      order_id: id,
      order_sn: sn,
      status: 2,
      status_info: { status: "Đã giao cho ĐVVC", description: "x" },
      status_info_v2: { status: "Đã giao cho ĐVVC" },
      create_time: ts(day),
      complete_time: 0,
      total_price: "78000",
      price_before_discount: "120000",
      shipping_fee: "15000",
      escrow_release_time: 0,
      shipping_address: { name: "Tran Thi Mau", phone: "0911111111", full_address: "99 Pho Gia, Ha Noi" },
      buyer_user: { user_name: "nguoi_mua_gia", user_id: 77, portrait: "p.jpg" },
      remark: "goi truoc khi giao",
      actual_carrier: "SPX",
      tracking_number: "SPXVN999",
      order_items: items ?? [
        {
          item_id: 9001,
          model_id: 9101,
          amount: 1,
          order_price: "100000",
          status: 1,
          line_item_id: "L1",
          item_model: { sku: "G600024", model_id: 9101, name: "Xanh, M", price: 999 },
          product: { sku: "", name: "Ten san pham that", images: ["a.jpg"] },
          bundle_deal_model: [],
          bundle_deal_product: [],
          item_list: [],
          add_on_deal_id: 0,
          bundle_deal_id: 0,
        },
      ],
      ...over,
    },
  };
}
const PII = /Tran Thi|0911111111|Pho Gia|nguoi_mua_gia|goi truoc|SPXVN999|Ten san pham|portrait|p\.jpg/;

const reply = (body: unknown): ReaderResponse => ({ endpoint: "order_detail", url: "u", status: 200, body, capturedAt: NOW, source: "replay" });

describe("order numbers and the list page DOM", () => {
  it("the order number's first six characters are its GMT+7 day", () => {
    expect(orderSnDay("261114ABCDEF12")).toBe("2026-11-14");
    expect(orderSnDay("261399ABC")).toBeUndefined();
    expect(orderSnDay(undefined)).toBeUndefined();
  });

  const card = (id: string, sn: string) => `
    <div class="order-card">
      <div class="header"><span class="buyer">nguoi_mua_gia</span><span>Mã đơn hàng ${sn}</span></div>
      <div class="body"><a href="/portal/sale/order/${id}">Xem chi tiết</a><span>Tran Thi Mau</span></div>
      <a class="footer" href="/portal/sale/order/${id}?tab=1">Chi tiết</a>
    </div>`;
  const page = (cards: string, pager = "") => {
    document.body.innerHTML = `<div class="list">${cards}</div>${pager}`;
  };

  it("reads each card's order id from its link and its order number from its text, nothing else", () => {
    page(card("248286575283352", "261114AAAAAAAA") + card("248286575283353", "261113BBBBBBBB") + `<a href="/portal/sale/order">Tất cả</a>`);
    const links = orderLinksIn(document);
    expect(links).toEqual([
      { id: "248286575283352", sn: "261114AAAAAAAA" },
      { id: "248286575283353", sn: "261113BBBBBBBB" },
    ]);
    expect(JSON.stringify(links)).not.toMatch(PII);
    expect(orderListEmptyIn(document)).toBe(false);
  });

  it("an order link with a trailing space still gives its id (ORY 2026-11-16)", () => {
    page(card("248286575283352", "261114AAAAAAAA").replace(/(\/portal\/sale\/order\/\d+)(\?tab=1)?"/g, '$1 "'));
    expect(orderLinksIn(document)).toEqual([{ id: "248286575283352", sn: "261114AAAAAAAA" }]);
  });

  it("the empty state is seen only without order cards", () => {
    page(`<div class="empty">Không tìm thấy đơn hàng</div>`);
    expect(orderLinksIn(document)).toEqual([]);
    expect(orderListEmptyIn(document)).toBe(true);
  });

  it("the pager's next control: enabled and inside a pager, else nothing", () => {
    let clicks = 0;
    page(card("1000001", "261114CCCCCCCC"), `<div class="eds-pager"><button class="eds-pager__button-prev">‹</button><button class="eds-pager__button-next"><i class="icon"></i></button></div>`);
    const next = pagerNextIn(document)!;
    next.addEventListener("click", () => (clicks += 1));
    expect(goToNextOrderPage(document)).toBe(true);
    expect(clicks).toBe(1);
    page(card("1000001", "261114CCCCCCCC"), `<div class="eds-pager"><button class="eds-pager__button-next" disabled>›</button></div>`);
    expect(goToNextOrderPage(document)).toBe(false);
    page(card("1000001", "261114CCCCCCCC"), `<button class="eds-pager__button-next">not in a pager</button>`);
    expect(pagerNextIn(document)).toBeNull();
  });
});

describe("get_one_order: trimmed in the page", () => {
  it("keeps the allowlist only: no address, buyer, remark, tracking or product name", () => {
    const trimmed = trimOrderDetail(detail(5001, "261114AAAAAAAA"));
    expect(JSON.stringify(trimmed)).not.toMatch(PII);
    expect(trimmed).toEqual({
      code: 0,
      data: {
        order_id: 5001,
        order_sn: "261114AAAAAAAA",
        status: 2,
        status_text: "Đã giao cho ĐVVC",
        create_time: ts("2026-11-14"),
        complete_time: 0,
        total_price: "78000",
        price_before_discount: "120000",
        items: [
          {
            item_id: 9001,
            model_id: 9101,
            amount: 1,
            order_price: "100000",
            line_item_id: "L1",
            add_on_deal_id: 0,
            bundle_deal_id: 0,
            model_sku: "G600024",
            model_name: "Xanh, M",
            item_sku: "",
          },
        ],
      },
    });
  });

  it("an answer without an order keeps nothing", () => {
    expect(trimOrderDetail({ code: 0, data: { shipping_address: { name: "Tran Thi Mau" } } })).toEqual({ code: 0, data: null });
  });
});

describe("get_one_order -> order_lines", () => {
  it("no pay time on get_one_order: a placed order is confirmed at its creation, an unpaid one is not", () => {
    const placed = mapOrderLines([reply(trimOrderDetail(detail(5101, "261114DDDDDDDD")))], NOW).rows[0]!;
    expect(placed.paid_at).toBe(placed.ordered_at);
    const unpaid = mapOrderLines(
      [reply(trimOrderDetail(detail(5102, "261114EEEEEEEE", { status: 1, status_info: { status: "Chờ thanh toán" }, status_info_v2: { status: "Chờ thanh toán" } })))],
      NOW,
    ).rows[0]!;
    expect(unpaid.paid_at).toBeUndefined();
  });

  it("maps one line per item: whole dong, the order number as the hashed id, the variation SKU", () => {
    const mapped = mapOrderLines([reply(trimOrderDetail(detail(5001, "261114AAAAAAAA")))], NOW);
    expect(mapped).toMatchObject({ dataset: "order_lines", endpoint: "order/get_one_order", periodStart: "2026-11-14", date: "2026-11-14", drift: null });
    expect(mapped.rows).toEqual([
      {
        [RAW_ORDER_ID]: "261114AAAAAAAA",
        line_no: 0,
        ordered_at: "2026-11-14T12:00:00",
        status: "in_transit",
        qty: 1,
        // a one-line order: its own price before discount is the line's original price
        original_price: 120_000,
        deal_price: 100_000,
        seller_subsidy: 20_000,
        variation_sku: "G600024",
        variation_name: "Xanh, M",
        extra: { item_id: "9001", model_id: "9101" },
        // no pay time on get_one_order: a placed (not "Chờ thanh toán") order is confirmed at creation
        paid_at: "2026-11-14T12:00:00",
      },
    ]);
    const body = ingestBody(mapped, "0.3.20", NOW);
    expect(body.period).toEqual({ start: "2026-11-14", end: "2026-11-14", granularity: "period" });
  });

  it("the shown status text decides; the code is a fallback; a completion time means delivered", () => {
    const status = (over: Record<string, unknown>) =>
      mapOrderLines([reply(trimOrderDetail(detail(5002, "261110BBBBBBBB", over)))], NOW).rows[0]!.status;
    expect(status({ status_info: { status: "Hoàn thành" }, status_info_v2: undefined, complete_time: ts("2026-11-12") })).toBe("delivered");
    expect(status({ status_info: { status: "Đã hủy" }, status_info_v2: undefined })).toBe("cancelled");
    expect(status({ status_info: { status: "Trả hàng/Hoàn tiền" }, status_info_v2: undefined })).toBe("refunded_not_received");
    expect(status({ status_info: { status: "Đang giao" }, status_info_v2: undefined })).toBe("in_transit");
    expect(status({ status_info: undefined, status_info_v2: undefined, complete_time: ts("2026-11-12") })).toBe("delivered");
    expect(status({ status_info: undefined, status_info_v2: undefined })).toBe("in_transit");
    expect(orderStatusOf("Đã giao cho ĐVVC")).toBe("in_transit");
    expect(orderStatusOf("Đã giao")).toBe("delivered");
    expect(orderStatusOf("Hoàn thành")).toBe("delivered");
    expect(orderStatusOf("Đã hoàn tiền")).toBe("refunded_accepted");
  });

  it("a combo with priced sub-lines is posted as those lines; without prices, as the parent line", () => {
    const parent = { item_id: 9001, model_id: 9101, amount: 1, order_price: "150000", bundle_deal_id: 55, item_model: { sku: "COMBO-1" } };
    const subs = [
      { item_id: 9002, model_id: 9102, amount: 1, order_price: "90000", item_model: { sku: "SUB-A", name: "A" } },
      { item_id: 9003, model_id: 9103, amount: 2, order_price: "30000", item_model: { sku: "SUB-B" } },
    ];
    const combo = mapOrderLines([reply(trimOrderDetail(detail(5003, "261112CCCCCCCC", {}, [{ ...parent, bundle_deal_model: subs }])))], NOW);
    expect(combo.rows.map((r) => [r.variation_sku, r.qty, r.deal_price, r.line_no, r.promo_kind])).toEqual([
      ["SUB-A", 1, 90_000, 0, "bundle"],
      ["SUB-B", 2, 30_000, 1, "bundle"],
    ]);
    const unpriced = subs.map(({ order_price: _p, ...rest }) => rest);
    const whole = mapOrderLines([reply(trimOrderDetail(detail(5004, "261112DDDDDDDD", {}, [{ ...parent, item_list: unpriced }])))], NOW);
    expect(whole.rows.map((r) => [r.variation_sku, r.qty, r.deal_price, r.promo_kind])).toEqual([["COMBO-1", 1, 150_000, "bundle"]]);
  });

  it("completed orders feed the income queue with the numeric id and the order number", () => {
    const done = detail(5005, "261108EEEEEEEE", { status_info: { status: "Hoàn thành" }, complete_time: ts("2026-11-11") });
    const cancelled = detail(5006, "261108FFFFFFFF", { status_info: { status: "Đã hủy" }, complete_time: ts("2026-11-11") });
    const open = detail(5007, "261108GGGGGGGG");
    expect(completedOrders([done, cancelled, open].map((b) => reply(trimOrderDetail(b))))).toEqual([
      { id: "5005", sn: "261108EEEEEEEE", completedAt: ts("2026-11-11") * 1000 },
    ]);
  });

  it("answers that hold no order map to nothing (the scheduler then reports 0 rows)", () => {
    const mapped = mapOrderLines([reply({ code: 0, data: null })], NOW);
    expect(mapped.rows).toEqual([]);
  });
});

// -- the reader -----------------------------------------------------------------------------------

/** A list page of `pages` (newest first); the pager moves to the next one. */
function listEnv(
  pages: OrderLink[][],
  options: { budget?: number; templates?: Partial<Record<ReaderEndpoint, Template>>; empty?: boolean; pagerStuck?: boolean } = {},
) {
  let clock = NOW;
  let at = 0;
  const sent: ReaderRequest[] = [];
  const pauses: number[] = [];
  const nexts: number[] = [];
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
    template: (endpoint) => options.templates?.[endpoint],
    waitFor: pollingWaitFor(sleep, now),
    fetch: async (request): Promise<FetchedReaderResponse> => {
      sent.push(request);
      const id = Number(new URL(request.url).searchParams.get("order_id"));
      const link = pages.flat().find((l) => Number(l.id) === id)!;
      return { status: 200, text: async () => JSON.stringify(detail(id, link.sn!)) };
    },
    pathname: () => "/portal/sale/order",
    pause: async (ms) => {
      pauses.push(ms);
    },
    random: () => 0,
    orderLinks: () => pages[at] ?? [],
    orderListEmpty: () => options.empty === true,
    nextOrderPage: () => {
      if (at + 1 >= pages.length) return false;
      nexts.push(at);
      if (!options.pagerStuck) at += 1;
      return true;
    },
    ...(options.budget !== undefined ? { budget: { left: options.budget } } : {}),
  };
  return { env, sent, pauses, nexts };
}

const link = (id: number, day: string): OrderLink => ({ id: String(id), sn: `${day.slice(2, 4)}${day.slice(5, 7)}${day.slice(8, 10)}X${id}` });

describe("the orders reader on the list page (0.3.20)", () => {
  const PAGES = [
    [link(101, "2026-11-14"), link(102, "2026-11-12"), link(103, "2026-11-10")],
    [link(201, "2026-11-09"), link(202, "2026-11-06"), link(203, "2026-11-05")],
    [link(301, "2026-11-03"), link(302, "2026-11-02")], // every order older than sinceDay: the last page read
    [link(401, "2026-11-01")],
  ];

  it("pages with the page's own pager until a page is older than sinceDay, then reads each order since then", async () => {
    const h = listEnv(PAGES);
    const outcome = await runReaderJob({ id: "orders", sinceDay: "2026-11-05" }, h.env);
    expect(outcome.status).toBe("done");
    expect(outcome.detail).toBeUndefined();
    expect(h.nexts).toEqual([0, 1]); // pages 1 -> 2 -> 3, never page 4
    expect(h.pauses).toHaveLength(2);
    expect(h.pauses.every((ms) => ms >= 20_000 && ms <= 45_000)).toBe(true);
    // only the orders placed since 05/11, one GET get_one_order each, with the session params
    const ids = h.sent.map((r) => new URL(r.url).searchParams.get("order_id"));
    expect(ids).toEqual(["101", "102", "103", "201", "202", "203"]);
    for (const request of h.sent) {
      const url = new URL(request.url);
      expect(request.method).toBe("GET");
      expect(url.pathname).toBe("/api/v3/order/get_one_order");
      expect(url.searchParams.get("SPC_CDS")).toBe("s");
      expect(url.searchParams.get("SPC_CDS_VER")).toBe("2");
      expect(request.publicUrl).not.toContain("SPC_CDS");
    }
    // trimmed in the page: nothing personal leaves it
    expect(JSON.stringify(outcome.responses)).not.toMatch(PII);
    const mapped = mapOrderLines(outcome.responses, NOW);
    expect(mapped.rows).toHaveLength(6);
    expect(mapped.rows.map((r) => r[RAW_ORDER_ID])).toContain(PAGES[0]![0]!.sn);
  });

  it("orders are paced like every replay and counted against the budget; an empty budget ends it as partial", async () => {
    const h = listEnv(PAGES, { budget: 4 });
    const outcome = await runReaderJob({ id: "orders", sinceDay: "2026-11-05" }, h.env);
    expect(outcome.status).toBe("done");
    expect(outcome.detail).toBe("partial:budget");
    expect(h.sent).toHaveLength(4);
    expect(mapOrderLines(outcome.responses, NOW).rows).toHaveLength(4);
  });

  it("stops at the page cap and says so; a pager that does not move ends it as partial", async () => {
    const many = Array.from({ length: ORDER_LIST_MAX_PAGES_PER_RUN + 5 }, (_, i) => [link(1000 + i, "2026-11-14")]);
    const capped = listEnv(many);
    expect((await runReaderJob({ id: "orders", sinceDay: "2026-11-05" }, capped.env)).detail).toBe("partial:page_cap");
    expect(capped.nexts).toHaveLength(ORDER_LIST_MAX_PAGES_PER_RUN - 1);
    const stuck = listEnv(PAGES, { pagerStuck: true });
    const outcome = await runReaderJob({ id: "orders", sinceDay: "2026-11-05" }, stuck.env);
    expect(outcome.detail).toBe("partial:pager");
    expect(stuck.sent).toHaveLength(3); // what page 1 showed is still read
  });

  it("no order since sinceDay: no request at all, 'no_new_orders'; an empty list page: 'no_orders'", async () => {
    const old = listEnv([[link(1, "2026-10-01")]]);
    expect((await runReaderJob({ id: "orders", sinceDay: "2026-11-05" }, old.env)).detail).toBe("no_new_orders");
    expect(old.sent).toHaveLength(0);
    const empty = listEnv([], { empty: true });
    const outcome = await runReaderJob({ id: "orders", sinceDay: "2026-11-05" }, empty.env);
    expect(outcome).toMatchObject({ status: "done", detail: "no_orders" });
  });

  it("a page that shows neither cards nor its empty state is not 'read'", async () => {
    const h = listEnv([]);
    const outcome = await runReaderJob({ id: "orders", sinceDay: "2026-11-05" }, h.env);
    expect(outcome.status).toBe("needs_template");
  });

  it("the old list endpoints still win when the page calls them again", async () => {
    const cards = { code: 0, data: { list: [{ order_id: 1, order_sn: "261114OLDPATH1", create_time: ts("2026-11-14"), status: "completed", items: [] }] } };
    const h = listEnv(PAGES, {
      templates: {
        order_search: { query: {}, body: { filter: {} }, lastResponse: { code: 0, data: { list: [{ order_id: 1 }] } } },
        order_cards: { query: {}, body: {}, lastResponse: cards },
      },
    });
    const outcome = await runReaderJob({ id: "orders", sinceDay: "2026-11-05" }, h.env);
    expect(outcome.responses.map((r) => r.endpoint)).toEqual(["order_search", "order_cards"]);
    expect(h.sent).toHaveLength(0);
  });
});

describe("truthful status (0.3.20)", () => {
  it("an orders job that produced no order line is an error, never 'Đã đọc và gửi'", () => {
    expect(jobOutcome("orders", { order_lines: "ignored" }, "order_lines=ignored", "")).toBe("error:orders:0_rows:ignored");
    expect(jobOutcome("orders", {}, "", "")).toBe("error:orders:0_rows");
    expect(jobOutcome("orders", { order_lines: "drift" }, "order_lines=drift", "")).toBe("error:orders:0_rows:drift");
    expect(jobOutcome("orders", {}, "", "no_orders")).toBe("no_orders");
    expect(jobOutcome("orders", { order_lines: "ignored" }, "order_lines=ignored", "no_new_orders")).toBe("no_orders");
    expect(jobOutcome("orders", { order_lines: "posted" }, "order_lines=posted", "partial:budget")).toBe("done:order_lines=posted|partial:budget");
    expect(outcomeStatus(jobOutcome("orders", { order_lines: "ignored" }, "order_lines=ignored", "")).status).not.toBe("Đã đọc và gửi");
    expect(outcomeStatus("no_orders").status).toContain("Không có gì");
  });

  it("any reader: 'Đã đọc và gửi' only when something was sent", () => {
    expect(outcomeStatus("done:item_catalog=posted").status).toBe("Đã đọc và gửi");
    expect(outcomeStatus("done:order_income=queued").status).toBe("Đã đọc và gửi");
    expect(outcomeStatus("done:order_lines=ignored")).toMatchObject({ tone: "warn" });
    expect(outcomeStatus("done:order_lines=ignored").status).not.toBe("Đã đọc và gửi");
    expect(outcomeStatus("done")).toMatchObject({ tone: "warn" });
    expect(outcomeStatus("done:affiliate_bill_period:2026-11-14=empty")).toMatchObject({ tone: "muted" });
  });
});
