// @vitest-environment jsdom
// Connector 0.3.32 (batch-1123-a C1 + C3): the order page (/portal/sale/order/<id>) read as shown.
// The fixture DOM follows the read-only capture of 2026-11-23 (class names and labels only; every
// value below is made up, no buyer data).
import { describe, expect, it } from "vitest";
import { withSkuFixes, orderPageJob } from "../src/platforms/shopee/background/scheduler";
import { incomeItemsIn, moneyOf, pageItemsIn } from "../src/platforms/shopee/order-page-dom";
import { incomeReadIds, mapOrderIncome, mapOrderLines, skuLessOrders, trimOrderDetail, withPageSkus } from "../src/platforms/shopee/orders-map";
import { mapReaderJob } from "../src/platforms/shopee/reader-map";
import { pollingWaitFor, type ReaderEnv, type ReaderResponse, runReaderJob } from "../src/platforms/shopee/reader";
import { Pacer } from "../src/platforms/shopee/runner";

const SC = "https://banhang.shopee.vn";
const NOW = Date.UTC(2026, 10, 23, 3, 0, 0);

const productLine = (variation: string, sku: string, total: string, qty = "1") => `
  <div class="product-item product">
    <div class="product-detail">
      <div class="product-name">Sản phẩm mẫu</div>
      <div class="product-meta"><div>Phân loại: ${variation}</div><div>SKU phân loại: ${sku}</div></div>
    </div>
    <div class="price">₫50.000</div><div class="qty">${qty}</div><div class="subtotal">${total}</div>
  </div>`;
const incomeRow = (label: string, value: string) =>
  `<div class="income-item"><div class="income-label"><div class="income-label-text">${label}</div></div><div class="income-value">${value}</div></div>`;
const INCOME_HTML = `
  <div class="income-container">
    <div class="income-item income-subtotal strong"><div class="income-label"><div class="income-label-text">Tổng tiền sản phẩm</div></div><div class="income-value">₫100.000</div></div>
    <div class="income-group">${incomeRow("Giá sản phẩm", "₫100.000")}</div>
    <div class="income-item income-subtotal strong"><div class="income-label"><div class="income-label-text">Tổng phí vận chuyển</div></div><div class="income-value">₫0</div></div>
    <div class="income-group">
      ${incomeRow("Phí vận chuyển Người mua trả", "₫6.000")}
      ${incomeRow("Phí vận chuyển thực tế", "-₫35.700")}
      ${incomeRow("Phí vận chuyển được trợ giá từ Shopee", "₫29.700")}
    </div>
    <div class="income-group">
      ${incomeRow("Phí cố định", "-₫16.000")}
      ${incomeRow("Phí dịch vụ PiShip", "-₫2.700")}
      ${incomeRow("Phí Dịch Vụ", "-₫8.500")}
      ${incomeRow("Phí xử lý giao dịch", "-₫6.360")}
      ${incomeRow("Phí hoa hồng Tiếp thị liên kết", "-₫705")}
    </div>
    ${incomeRow("Doanh Thu Đơn Hàng", "₫65.735")}
  </div>`;

function page(html: string): Document {
  document.body.innerHTML = html;
  return document;
}

/** A trimmed get_one_order answer whose only line is a combo parent with no SKU (as ORY's). */
function comboAnswer(id = "5001", sn = "261123AAAAAAAA"): unknown {
  return trimOrderDetail({
    code: 0,
    data: {
      order_id: Number(id),
      order_sn: sn,
      status_info: { status: "Hoàn thành" },
      create_time: Math.floor(NOW / 1000) - 86_400,
      complete_time: Math.floor(NOW / 1000),
      order_items: [{ amount: 1, order_price: "190000", bundle_deal_id: 77, item_list: [{ amount: 1 }, { amount: 1 }] }],
    },
  });
}
const detailReply = (body: unknown, orderId?: string): ReaderResponse => ({ endpoint: "order_detail", url: "u", status: 200, body, capturedAt: NOW, source: "page", ...(orderId ? { orderId } : {}) });

describe("the order page DOM (0.3.32)", () => {
  it("reads money with its sign", () => {
    expect(moneyOf("₫65.735")).toBe(65_735);
    expect(moneyOf("-₫35.700")).toBe(-35_700);
    expect(moneyOf("− 16.000 ₫")).toBe(-16_000);
    expect(moneyOf("—")).toBeUndefined();
  });

  it("reads each product line's Phân loại, SKU phân loại and line total", () => {
    const doc = page(productLine("Xanh, M", "G600024", "₫120.000", "2") + productLine("Đỏ, L", "G600025", "₫70.000"));
    expect(pageItemsIn(doc)).toEqual([
      { variationName: "Xanh, M", sku: "G600024", lineTotal: 120_000, qty: 2 },
      { variationName: "Đỏ, L", sku: "G600025", lineTotal: 70_000, qty: 1 },
    ]);
  });

  it("maps the Doanh thu block to the order_income fields of the income file", () => {
    const items = incomeItemsIn(page(INCOME_HTML));
    expect(items.map((i) => i.name)).toContain("Phí dịch vụ PiShip");
    const answer: ReaderResponse = { endpoint: "order_income_components", url: "u", status: 200, body: { code: 0, data: { items } }, capturedAt: NOW, source: "page", orderId: "5001", orderSn: "261123AAAAAAAA" };
    const mapped = mapOrderIncome([answer], NOW);
    expect(mapped.drift).toBeNull();
    expect(mapped.rows).toHaveLength(1);
    expect(mapped.rows[0]).toMatchObject({
      product_price: 100_000,
      ship_buyer_paid: 6_000,
      ship_actual_cost: 35_700,
      ship_shopee_subsidy: 29_700,
      fee_fixed: 16_000,
      fee_piship: 2_700,
      fee_service: 8_500,
      fee_payment: 6_360,
      affiliate_commission: 705,
      payout: 65_735,
    });
    expect(incomeReadIds([answer])).toEqual(new Set(["5001"]));
  });
});

describe("SKUs from the order page (C1)", () => {
  it("finds the orders whose answer has a line with no SKU", () => {
    const plain = trimOrderDetail({ code: 0, data: { order_id: 5002, order_sn: "261123BBBBBBBB", order_items: [{ amount: 1, order_price: "1000", item_model: { sku: "A-1" } }] } });
    expect(skuLessOrders([detailReply(comboAnswer()), detailReply(plain)]).map((o) => [o.id, o.sn])).toEqual([["5001", "261123AAAAAAAA"]]);
  });

  it("a combo parent becomes one line per page line, priced by the page totals, the order total kept", () => {
    const fixed = withPageSkus(comboAnswer(), [
      { variationName: "Xanh, M", sku: "G600024", lineTotal: 120_000, qty: 1 },
      { variationName: "Đỏ, L", sku: "G600025", lineTotal: 70_000, qty: 1 },
    ]);
    const rows = mapOrderLines([detailReply(fixed)], NOW).rows;
    expect(rows.map((r) => [r.variation_sku, r.deal_price, r.qty, r.line_no, r.promo_kind])).toEqual([
      ["G600024", 120_000, 1, 0, "bundle"],
      ["G600025", 70_000, 1, 1, "bundle"],
    ]);
  });

  it("each split line takes its page quantity, and the money adds up to the parent's exactly", () => {
    // a combo of 1 x 190.001đ (not divisible evenly) shown as 2 + 1 items on the page
    const parentAnswer = trimOrderDetail({
      code: 0,
      data: {
        order_id: 5004,
        order_sn: "261123DDDDDDDD",
        create_time: Math.floor(NOW / 1000),
        order_items: [{ amount: 1, order_price: "190001", item_price: "200001", bundle_deal_id: 77, item_list: [{ amount: 1 }, { amount: 1 }] }],
      },
    });
    const pageLines = [
      { variationName: "Xanh, M", sku: "G600024", lineTotal: 126_000, qty: 2 },
      { variationName: "Đỏ, L", sku: "G600025", lineTotal: 64_000, qty: 1 },
    ];
    const rows = mapOrderLines([detailReply(withPageSkus(parentAnswer, pageLines))], NOW).rows;
    expect(rows.map((r) => r.qty)).toEqual(pageLines.map((p) => p.qty));
    const total = (field: "deal_price" | "original_price") => rows.reduce((a, r) => a + Math.round((r[field] as number) * (r.qty as number) * 100), 0);
    expect(total("deal_price")).toBe(190_001 * 100);
    expect(total("original_price")).toBe(200_001 * 100);
  });

  it("a page line without a quantity: the combo is not split (nothing guessed)", () => {
    expect(withPageSkus(comboAnswer(), [{ sku: "A", lineTotal: 1 }, { sku: "B", qty: 1 }])).toBeNull();
  });

  it("as many page lines as order lines: each SKU-less line takes its page line; else nothing is guessed", () => {
    const one = trimOrderDetail({ code: 0, data: { order_id: 5003, order_sn: "261123CCCCCCCC", create_time: Math.floor(NOW / 1000), order_items: [{ amount: 2, order_price: "50000" }] } });
    const rows = mapOrderLines([detailReply(withPageSkus(one, [{ sku: "G1", variationName: "Size S" }]))], NOW).rows;
    expect(rows.map((r) => [r.variation_sku, r.variation_name, r.qty, r.deal_price])).toEqual([["G1", "Size S", 2, 50_000]]);
    expect(withPageSkus(comboAnswer(), [])).toBeNull();
    expect(withPageSkus(comboAnswer(), [{ variationName: "no sku" }, { variationName: "no sku" }])).toBeNull();
  });

  it("the order page job posts the order's income and its lines with the page's SKUs", async () => {
    const doc = page(productLine("Xanh, M", "G600024", "₫120.000") + productLine("Đỏ, L", "G600025", "₫70.000") + INCOME_HTML);
    let clock = NOW;
    const sleep = async (ms: number) => {
      clock += ms;
    };
    const env: ReaderEnv = {
      origin: SC,
      pacer: new Pacer({ sleep, now: () => clock, random: () => 0 }),
      now: () => clock,
      session: () => ({}),
      hasSession: () => true,
      template: () => undefined,
      waitFor: pollingWaitFor(sleep, () => clock),
      fetch: async () => {
        throw new Error("nothing is requested");
      },
      orderPageIncome: () => incomeItemsIn(doc),
      orderPageItems: () => pageItemsIn(doc),
    };
    const job = { id: "order_income" as const, orderIds: ["5001"], orderSns: ["261123AAAAAAAA"], incomeFor: [true], fixBodies: [comboAnswer()] };
    const outcome = await runReaderJob(job, env);
    expect(outcome.status).toBe("done");
    const mapped = mapReaderJob(job, outcome.responses, NOW);
    expect(mapped.map((m) => [m.dataset, m.rows.length])).toEqual([
      ["order_income", 1],
      ["order_lines", 2],
    ]);
    // not completed yet: only the lines, no income estimate
    const linesOnly = await runReaderJob({ ...job, incomeFor: [false] }, env);
    expect(linesOnly.responses.map((r) => r.endpoint)).toEqual(["order_detail"]);
  });
});

describe("the order page queue (0.3.32)", () => {
  it("a SKU-less order joins the queue for its lines only; one already queued gets its answer", () => {
    const queue = withSkuFixes([{ id: "5001", completedAt: 1 }], [
      { id: "5001", sn: "261123AAAAAAAA", body: { a: 1 } },
      { id: "5009", body: { b: 2 } },
    ], 99);
    expect(queue).toEqual([
      { id: "5001", completedAt: 1, fix: { a: 1 } },
      { id: "5009", completedAt: 99, income: false, fix: { b: 2 } },
    ]);
    expect(orderPageJob({ id: "order_income" }, queue[1]!)).toEqual({ id: "order_income", orderIds: ["5009"], orderSns: [""], incomeFor: [false], fixBodies: [{ b: 2 }], fixLast: [false] });
  });
});

describe("a line the order page cannot name (0.3.32, verifier)", () => {
  const envFor = (doc: Document): ReaderEnv => {
    let clock = NOW;
    const sleep = async (ms: number) => {
      clock += ms;
    };
    return {
      origin: SC,
      pacer: new Pacer({ sleep, now: () => clock, random: () => 0 }),
      now: () => clock,
      session: () => ({}),
      hasSession: () => true,
      template: () => undefined,
      waitFor: pollingWaitFor(sleep, () => clock),
      fetch: async () => {
        throw new Error("nothing is requested");
      },
      orderPageIncome: () => incomeItemsIn(doc),
      orderPageItems: () => pageItemsIn(doc),
    };
  };
  // three page lines for a one-line order without SKU, no quantities: cannot be matched
  const unmatchedPage = () => page(`<div class="product-item product"><div class="product-meta"><div>Phân loại: A</div></div></div>`.repeat(3));

  it("before the last read: nothing posted, 'page_lines_unmatched'", async () => {
    const env = envFor(unmatchedPage());
    const job = { id: "order_income" as const, orderIds: ["5001"], orderSns: [""], incomeFor: [false], fixBodies: [comboAnswer()], fixLast: [false] };
    const outcome = await runReaderJob(job, env);
    expect(outcome.responses).toEqual([]);
    // 0.3.34 C-H5: page lines vs the answer's lines (the combo parent + its 2 children)
    expect(outcome.detail).toBe("page_lines_unmatched:page_3:answer_1+2");
  });

  it("the last read posts the lines as unresolved_item", async () => {
    const env = envFor(unmatchedPage());
    const job = { id: "order_income" as const, orderIds: ["5001"], orderSns: [""], incomeFor: [false], fixBodies: [comboAnswer()], fixLast: [true] };
    const outcome = await runReaderJob(job, env);
    expect(outcome.detail).toBe("unresolved_item");
    const rows = mapOrderLines(outcome.responses, NOW).rows;
    expect(rows.map((r) => r.variation_sku)).toEqual(["unresolved_item"]);
  });
});
