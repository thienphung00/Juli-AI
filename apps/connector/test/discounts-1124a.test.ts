// @vitest-environment jsdom
// batch-1124-a Track S (S1): order lines carry the discounts the order used.
//   row 1: get_one_order states no combo amount; the old gap Σ (order_price x amount) − total_price
//          is vouchers / coins, not the combo's: never posted (owner Q4, batch-1124-b CONN);
//   row 2: the order page's buyer-payment block ("Thanh toán của Người Mua": Shopee Voucher, Mã
//          giảm giá của Shop) is read apart from the income block and posted as buyer_* fields;
//          the buyer-side shop voucher is never the seller's cost (P-S3 capture, 24/11);
//   row 4: Mua Kèm Deal Sốc from add_on_deal_id or is_add_on_sub_item.
// Structure and labels follow the read-only captures; every amount, id and SKU is synthetic.
import { describe, expect, it } from "vitest";
import { RAW_ORDER_ID } from "../src/platforms/shopee/affiliate-map";
import { buyerItemsIn, incomeItemsIn } from "../src/platforms/shopee/order-page-dom";
import { incomeReadIds, mapOrderIncome, mapOrderLines, trimOrderDetail } from "../src/platforms/shopee/orders-map";
import type { ReaderResponse } from "../src/platforms/shopee/reader";
import { gmt7DateStart } from "../src/core/time";
import { orderBackfillSinceDay, ordersSinceDay, planJobs } from "../src/platforms/shopee/background/scheduler";

const NOW = Date.UTC(2026, 10, 24, 3, 0, 0);
const CREATED = gmt7DateStart("2026-11-20") + 9 * 3600;

const detail = (order: Record<string, unknown>): ReaderResponse => ({
  endpoint: "order_detail",
  url: "u",
  status: 200,
  body: trimOrderDetail({ code: 0, data: { order_id: 7001, order_sn: "261120SYN001", create_time: CREATED, status_info: { status: "Hoàn thành" }, complete_time: CREATED + 86400, ...order } }),
  capturedAt: NOW,
  source: "replay",
  orderId: "7001",
});

/** A combo group of two bottles, listed 100.000 + 90.000 = 190.000, the buyer pays 148.000. */
const comboGroup = {
  amount: 1,
  order_price: "190000",
  bundle_deal_id: 77,
  bundle_deal_model: [
    { item_id: 9001, model_id: 9101, amount: 1, order_price: "100000", item_model: { sku: "SKU-A1", model_id: 9101 } },
    { item_id: 9003, model_id: 9301, amount: 1, order_price: "90000", item_model: { sku: "SKU-C1", model_id: 9301 } },
  ],
};

describe("S1 row 1: combo discount from get_one_order (replaced by owner Q4, batch-1124-b CONN)", () => {
  it("the order's gap (Σ order_price x amount − total_price: vouchers / coins) is never posted as the combo's", () => {
    const rows = mapOrderLines([detail({ total_price: "148000", price_before_discount: "148000", order_items: [comboGroup] })], NOW).rows;
    expect(rows.map((r) => [r.variation_sku, r.promo_kind, r.original_price, r.deal_price, r.seller_subsidy, r.bundle_discount])).toEqual([
      ["SKU-A1", "bundle", 100000, 100000, 0, undefined],
      ["SKU-C1", "bundle", 90000, 90000, 0, undefined],
    ]);
  });

  it("a plain line beside the combo keeps its own price and no combo amount", () => {
    const plain = { item_id: 9002, model_id: 9202, amount: 2, order_price: "50000", item_model: { sku: "SKU-B", model_id: 9202 } };
    const rows = mapOrderLines([detail({ total_price: "248000", order_items: [comboGroup, plain] })], NOW).rows;
    const by = Object.fromEntries(rows.map((r) => [r.variation_sku as string, r]));
    expect(by["SKU-B"]!.bundle_discount).toBeUndefined();
    expect(by["SKU-B"]!.promo_kind).toBeUndefined();
    expect(by["SKU-A1"]!.bundle_discount).toBeUndefined();
  });

  it("no gap, no total, or a gap larger than the combo lines: no amount is guessed", () => {
    for (const order of [
      { total_price: "190000", order_items: [comboGroup] },
      { order_items: [comboGroup] },
      { total_price: "1000", order_items: [comboGroup, { item_id: 9002, amount: 5, order_price: "50000", item_model: { sku: "SKU-B" } }] },
    ]) {
      const rows = mapOrderLines([detail(order)], NOW).rows;
      expect(rows.every((r) => r.bundle_discount === undefined)).toBe(true);
    }
  });

  it("an order without a combo gets no combo amount (a programme price is already the line's price)", () => {
    const rows = mapOrderLines([detail({ total_price: "80000", order_items: [{ item_id: 9002, amount: 1, order_price: "80000", item_model: { sku: "SKU-B" } }] })], NOW).rows;
    expect(rows[0]!.bundle_discount).toBeUndefined();
  });
});

describe("S1 row 4: Mua Kèm Deal Sốc", () => {
  it("is_add_on_sub_item passes the in-page allowlist and marks the line add_on, as add_on_deal_id does", () => {
    const body = trimOrderDetail({
      code: 0,
      data: {
        order_id: 7002,
        order_sn: "261120SYN002",
        create_time: CREATED,
        total_price: "150000",
        order_items: [
          { item_id: 9010, amount: 1, order_price: "120000", item_model: { sku: "SKU-MAIN" }, add_on_deal_id: 0, is_add_on_sub_item: false },
          { item_id: 9011, amount: 1, order_price: "30000", item_model: { sku: "SKU-ADD" }, is_add_on_sub_item: true },
          { item_id: 9012, amount: 1, order_price: "0", item_model: { sku: "SKU-DEAL" }, add_on_deal_id: 55 },
        ],
      },
    }) as { data: { items: Record<string, unknown>[] } };
    expect(body.data.items[1]!.is_add_on_sub_item).toBe(true);
    const response: ReaderResponse = { endpoint: "order_detail", url: "u", status: 200, body, capturedAt: NOW, source: "replay" };
    const rows = mapOrderLines([response], NOW).rows;
    expect(rows.map((r) => [r.variation_sku, r.promo_kind])).toEqual([
      ["SKU-MAIN", undefined],
      ["SKU-ADD", "add_on"],
      ["SKU-DEAL", "add_on"],
    ]);
  });
});

/** The order page as the P-S3 capture lists it: the income block, then the buyer-payment block. */
function orderPage(buyerRows: [string, string][]): Document {
  document.body.innerHTML = `
    <div class="income-container">
      <div class="income-item"><div class="income-label"><div class="income-label-text">Giá sản phẩm</div></div><div class="income-value">₫100.000</div></div>
      <div class="income-item"><div class="income-label"><div class="income-label-text">Mã giảm giá của Shop</div></div><div class="income-value">-₫10.000</div></div>
      <div class="income-item income-subtotal strong highlighted"><div class="income-label"><div class="income-label-text">Doanh Thu Đơn Hàng <div class="eds-popover payment-tooltip"><svg><style>.cls-1{fill-rule:evenodd;}</style></svg></div></div></div><div class="income-value">₫70.000</div></div>
    </div>
    <div class="buyer-payment">
      <div class="title"><span>Thanh toán của Người Mua</span></div>
      <div class="row"><span>Tổng tiền sản phẩm</span><span>₫100.000</span></div>
      <div class="row"><span>Phí vận chuyển</span><span>₫15.000</span></div>
      ${buyerRows.map(([label, value]) => `<div class="row"><span>${label}</span><span>${value}</span></div>`).join("")}
      <div class="row"><span>Tổng tiền Thanh toán</span><span>₫55.000</span></div>
    </div>
    <div class="other"><span>Mã giảm giá của Shop</span><span>-₫999</span></div>`;
  return document;
}

describe("S1 row 2: the buyer-payment block", () => {
  it("reads only the two voucher rows of the block (bounded by its total), never the income block's", () => {
    const doc = orderPage([
      ["Shopee Voucher", "-₫50.000"],
      ["Mã giảm giá của Shop", "-₫10.000"],
    ]);
    expect(buyerItemsIn(doc)).toEqual([
      { name: "Shopee Voucher", amount: -50000 },
      { name: "Mã giảm giá của Shop", amount: -10000 },
    ]);
    // the income block is unchanged
    expect(incomeItemsIn(doc).map((i) => i.name)).toEqual(["Giá sản phẩm", "Mã giảm giá của Shop", "Doanh Thu Đơn Hàng"]);
  });

  it("a page without the block, or a block without vouchers, gives nothing", () => {
    document.body.innerHTML = `<div class="income-container"></div>`;
    expect(buyerItemsIn(document)).toEqual([]);
    expect(buyerItemsIn(orderPage([]))).toEqual([]);
  });

  const income = (items: unknown, buyer?: unknown): ReaderResponse => ({
    endpoint: "order_income_components",
    url: "u",
    status: 200,
    body: { code: 0, data: { items, ...(buyer !== undefined ? { buyer_items: buyer } : {}) } },
    capturedAt: NOW,
    source: "page",
    orderId: "7001",
    orderSn: "261120SYN001",
  });

  it("the buyer-payment vouchers post as order_*_voucher amounts; the seller's cost stays the income block's own row", () => {
    const [row] = mapOrderIncome(
      [
        income(
          [
            { name: "Giá sản phẩm", amount: 100000 },
            { name: "Mã giảm giá của Shop", amount: -10000 },
            { name: "Doanh Thu Đơn Hàng", amount: 70000 },
          ],
          [
            { name: "Shopee Voucher", amount: -50000 },
            { name: "Mã giảm giá của Shop", amount: -34680 },
          ],
        ),
      ],
      NOW,
    ).rows;
    expect(row).toMatchObject({ [RAW_ORDER_ID]: "261120SYN001", payout: 70000, seller_voucher_borne: 10000, order_shop_voucher: 34680, order_platform_voucher: 50000 });
  });

  it("a shop voucher the buyer used with no seller deduction (Voucher Xtra) never becomes a seller cost", () => {
    const [row] = mapOrderIncome(
      [income([{ name: "Giá sản phẩm", amount: 100000 }, { name: "Voucher Xtra", amount: -5500 }, { name: "Doanh Thu Đơn Hàng", amount: 80000 }], [{ name: "Mã giảm giá của Shop", amount: -34680 }])],
      NOW,
    ).rows;
    expect(row!.seller_voucher_borne).toBeUndefined();
    expect(row!.order_shop_voucher).toBe(34680);
    expect(row!.fee_voucher_xtra).toBe(5500);
  });

  it("buyer rows never count as the income's final amount", () => {
    const buyerOnly = income([{ name: "Giá sản phẩm", amount: 100000 }], [{ name: "Doanh Thu Đơn Hàng", amount: 1 }]);
    expect(incomeReadIds([buyerOnly]).size).toBe(0);
    expect(mapOrderIncome([buyerOnly], NOW).rows).toEqual([]);
  });
});

describe("S1 #48: the one re-read of the order days an older Connector read", () => {
  const TODAY = "2026-11-24";
  const holes = { order_lines_backfill: ["2026-10-26", "2026-11-01", "2026-11-10", "2026-11-18"] };
  const since = ordersSinceDay(TODAY, "2026-11-23"); // the usual catch-up: 3 days of overlap

  it("reads back to the oldest backfill day the backfill's budget affords", () => {
    expect(orderBackfillSinceDay(TODAY, since, holes, 550)).toBe("2026-10-26"); // 36 days of room, capped at 30
    expect(orderBackfillSinceDay(TODAY, since, holes, 300)).toBe("2026-11-10"); // 20 days of room
    expect(orderBackfillSinceDay(TODAY, since, holes, 100)).toBe("2026-11-18"); // 6 days
  });

  it("no backfill day, no budget room, or only days the usual read covers: the usual read", () => {
    expect(orderBackfillSinceDay(TODAY, since, undefined, 550)).toBeUndefined();
    expect(orderBackfillSinceDay(TODAY, since, holes, 0)).toBeUndefined();
    expect(orderBackfillSinceDay(TODAY, since, holes, 14)).toBeUndefined();
    expect(orderBackfillSinceDay(TODAY, "2026-10-20", holes, 550)).toBeUndefined();
  });

  const plan = (extra: Record<string, unknown>) =>
    planJobs({ shopId: "s1", nowMs: NOW, stopped: new Set(), adsDone: [], readers: ["orders"], ordersCoveredDay: "2026-11-23", ...extra }).find((j) => j.id === "orders");

  it("the orders job carries the backfill (once a day: a job already run today waits for tomorrow)", () => {
    expect(plan({ holes, holeRoom: 300 })).toEqual({ id: "orders", sinceDay: "2026-11-10", orderBackfill: true });
    expect(plan({ holeRoom: 300 })).toEqual({ id: "orders", sinceDay: since });
    expect(plan({ holes, holeRoom: 0 })).toEqual({ id: "orders", sinceDay: since });
    expect(plan({ holes, holeRoom: 300, ordersDay: TODAY })).toBeUndefined();
  });
});
