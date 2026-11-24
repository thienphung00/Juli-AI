// @vitest-environment jsdom
// batch-1124-b CONN (owner #56): a combo (Combo Khuyến Mãi) order line carries its item's real SKU.
// The get_one_order answer and the order page DOM below follow the read-only P-CONN capture of
// 24/11 (key and class names only; every id, SKU, name and amount is made up):
// - the combo is ONE `order_items` parent (placeholder item id, model id 0, empty SKUs, the combo
//   price after the combo discount); its sub-lines `item_list[]` carry ids + quantity, no price,
//   no SKU; `bundle_deal_model[]` carries {model_id, sku, name}; `bundle_deal_product[]` the
//   product-level SKU (empty here);
// - the order page shows `.order-payment-item.is-bundle > .bundle-deal-items > .bundle-deal-item`
//   (`.product-item` meta, `.price` unit list price, `.qty`), no `.product-item.product`.
import { describe, expect, it } from "vitest";
import { pageItemsIn } from "../src/platforms/shopee/order-page-dom";
import { mapOrderLines, skuLessOrders, trimOrderDetail, withPageSkus } from "../src/platforms/shopee/orders-map";
import { mapReaderJob } from "../src/platforms/shopee/reader-map";
import { pollingWaitFor, type ReaderEnv, type ReaderResponse, runReaderJob } from "../src/platforms/shopee/reader";
import { Pacer } from "../src/platforms/shopee/runner";

const SC = "https://banhang.shopee.vn";
const NOW = Date.UTC(2026, 10, 24, 3, 0, 0);
const CREATED = Math.floor(NOW / 1000) - 3_600;

const comboParent = (models: { modelId: number; sku: string; name: string }[], productSku = "") => ({
  add_on_deal_id: 0,
  amount: 1,
  bundle_deal: { bundle_deal_id: 88, status: 1, labels: ["Mua 2 giảm 5%"] },
  bundle_deal_id: 88,
  item_id: 1,
  model_id: 0,
  item_model: { model_id: 0, item_id: 0, name: "", sku: "" },
  product: { name: "Tên sản phẩm mẫu", images: ["img"], item_id: 0, model_id: 0, sku: "" },
  order_price: "190000",
  line_item_id: 1,
  is_add_on_sub_item: false,
  item_list: models.map((m, i) => ({ item_id: 7001, index: i, line_item_id: 10 + i, model_id: m.modelId, amount: 1, is_virtual_sku: false })),
  bundle_deal_model: models.map((m) => ({ model_id: m.modelId, item_id: 7001, name: m.name, status: 1, sku: m.sku, weight: 100 })),
  bundle_deal_product: models.map((m) => ({ name: "Tên sản phẩm mẫu", images: ["img"], is_pre_order: false, item_id: 7001, model_id: m.modelId, status: 1, sku: productSku, weight: 100 })),
});

const MODELS = [
  { modelId: 8001, sku: "SKU-A01", name: "Vị A" },
  { modelId: 8002, sku: "SKU-A02", name: "Vị B" },
];

function answer(items: unknown[], id = 6001): unknown {
  return trimOrderDetail({
    code: 0,
    data: {
      order_id: id,
      order_sn: `261124COMBO${id}`,
      status_info: { status: "Đang giao" },
      create_time: CREATED,
      complete_time: 0,
      total_price: "171000",
      price_before_discount: "171000",
      order_items: items,
      buyer_address_name: "Nguoi Mua Gia",
    },
  });
}

const plainItem = { item_id: 7100, model_id: 8100, amount: 1, order_price: "50000", item_model: { model_id: 8100, name: "Size M", sku: "SKU-P01" }, product: { name: "x", sku: "" } };

const bundleLine = (variation: string, sku: string | null, price = "100.000", qty = "1") => `
  <div class="bundle-deal-item">
    <div class="product-item">
      <div class="product-image"></div>
      <div class="product-detail">
        <div class="product-name">Tên sản phẩm mẫu</div>
        <div class="product-labels"></div>
        <div class="product-meta"><div>Phân loại: ${variation}</div>${sku ? `<div>SKU phân loại: ${sku}</div>` : ""}</div>
      </div>
    </div>
    <div class="price">${price}</div><div class="qty">${qty}</div>
  </div>`;
const comboBlock = (lines: string) => `
  <div class="order-payment-item is-bundle">
    <div class="no">1</div>
    <div class="bundle-deal-items">${lines}</div>
    <div class="subtotal"><div>190.000</div><div>200.000</div></div>
  </div>`;
const plainLine = `
  <div class="product-item product">
    <div class="product-detail"><div class="product-meta"><div>Phân loại: Size M</div><div>SKU phân loại: SKU-P01</div></div></div>
    <div class="price">₫50.000</div><div class="qty">1</div><div class="subtotal">₫50.000</div>
  </div>`;

function page(html: string): Document {
  document.body.innerHTML = html;
  return document;
}

const detail = (body: unknown): ReaderResponse => ({ endpoint: "order_detail", url: "u", status: 200, body, capturedAt: NOW, source: "page" });

describe("a combo's get_one_order answer (P-CONN shape)", () => {
  it("keeps item_list as the sub-lines, each with its variation SKU from bundle_deal_model by model id", () => {
    const trimmed = answer([comboParent(MODELS)]) as { data: { items: { sub_items: Record<string, unknown>[] }[] } };
    expect(trimmed.data.items[0]!.sub_items).toEqual([
      { item_id: 7001, line_item_id: 10, model_id: 8001, amount: 1, model_sku: "SKU-A01", model_name: "Vị A" },
      { item_id: 7001, line_item_id: 11, model_id: 8002, amount: 1, model_sku: "SKU-A02", model_name: "Vị B" },
    ]);
    // no buyer data and no product name leave the page
    expect(JSON.stringify(trimmed)).not.toMatch(/Nguoi Mua|Tên sản phẩm/);
  });

  it("the product-level SKU comes from bundle_deal_product when it is set", () => {
    const trimmed = answer([comboParent(MODELS, "SP-01")]) as { data: { items: { sub_items: Record<string, unknown>[] }[] } };
    expect(trimmed.data.items[0]!.sub_items.map((s) => s.item_sku)).toEqual(["SP-01", "SP-01"]);
  });

  it("the sub-lines have no price, so the order goes to its order page (no line is priced by a guess)", () => {
    const body = answer([comboParent(MODELS)]);
    const rows = mapOrderLines([detail(body)], NOW).rows;
    expect(rows).toHaveLength(1);
    expect(rows[0]!.sku).toBeUndefined();
    expect(rows[0]!.variation_sku).toBeUndefined();
    expect(skuLessOrders([detail(body)]).map((o) => o.id)).toEqual(["6001"]);
  });
});

describe("a combo on the order page (P-CONN DOM)", () => {
  it("reads one line per .bundle-deal-item: SKU phân loại, quantity, unit list price x quantity", () => {
    const doc = page(comboBlock(bundleLine("Vị A", "SKU-A01") + bundleLine("Vị B", "SKU-A02", "100.000", "2")));
    expect(pageItemsIn(doc)).toEqual([
      { variationName: "Vị A", sku: "SKU-A01", qty: 1, listPrice: 100_000, lineTotal: 100_000 },
      { variationName: "Vị B", sku: "SKU-A02", qty: 2, listPrice: 100_000, lineTotal: 200_000 },
    ]);
  });

  it("a plain line and a combo on one page keep page order", () => {
    const doc = page(plainLine + comboBlock(bundleLine("Vị A", "SKU-A01") + bundleLine("Vị B", "SKU-A02")));
    expect(pageItemsIn(doc).map((p) => p.sku)).toEqual(["SKU-P01", "SKU-A01", "SKU-A02"]);
  });
});

describe("combo lines posted with the real SKU", () => {
  it("each sub-line becomes a line with its own ids and SKUs, the combo price split by the page's list prices", () => {
    const doc = page(comboBlock(bundleLine("Vị A", "SKU-A01") + bundleLine("Vị B", "SKU-A02")));
    const rows = mapOrderLines([detail(withPageSkus(answer([comboParent(MODELS)]), pageItemsIn(doc)))], NOW).rows;
    expect(rows.map((r) => [r.line_no, r.sku, r.variation_sku, r.variation_name, r.qty, r.deal_price, r.promo_kind, r.extra])).toEqual([
      [0, undefined, "SKU-A01", "Vị A", 1, 95_000, "bundle", { item_id: "7001", model_id: "8001", bundle_deal_id: 88, list_price: 100_000 }],
      [1, undefined, "SKU-A02", "Vị B", 1, 95_000, "bundle", { item_id: "7001", model_id: "8002", bundle_deal_id: 88, list_price: 100_000 }],
    ]);
  });

  it("owner Q4: bundle_discount = (list price − combo price share) x qty; original = deal, no seller subsidy", () => {
    // the P-CONN order: list 100.000 x 2 -> combo 190.000 -> lines 95.000 / 95.000, 5.000 each
    const doc = page(comboBlock(bundleLine("Vị A", "SKU-A01") + bundleLine("Vị B", "SKU-A02")));
    const rows = mapOrderLines([detail(withPageSkus(answer([comboParent(MODELS)]), pageItemsIn(doc)))], NOW).rows;
    expect(rows.map((r) => [r.original_price, r.deal_price, r.seller_subsidy, r.bundle_discount])).toEqual([
      [95_000, 95_000, 0, 5_000],
      [95_000, 95_000, 0, 5_000],
    ]);
    // the order's total_price (171.000: vouchers / coins below the combo price) is not the combo's
    expect(rows.reduce((a, r) => a + (r.bundle_discount as number), 0)).toBe(10_000);
  });

  it("owner Q4: with quantities, Σ bundle_discount = Σ list x qty − the combo price, exactly", () => {
    const parent = { ...comboParent(MODELS), order_price: "250000", item_list: [
      { item_id: 7001, model_id: 8001, amount: 1 },
      { item_id: 7001, model_id: 8002, amount: 2 },
    ] };
    const doc = page(comboBlock(bundleLine("Vị A", "SKU-A01", "100.000", "1") + bundleLine("Vị B", "SKU-A02", "90.000", "2")));
    const rows = mapOrderLines([detail(withPageSkus(answer([parent]), pageItemsIn(doc)))], NOW).rows;
    const cents = (f: string) => rows.reduce((a, r) => a + Math.round((r[f] as number) * 100), 0);
    expect(cents("bundle_discount")).toBe((100_000 + 2 * 90_000 - 250_000) * 100);
    expect(rows.reduce((a, r) => a + Math.round((r.deal_price as number) * (r.qty as number) * 100), 0)).toBe(250_000 * 100);
    expect(rows.every((r) => r.seller_subsidy === 0 && r.original_price === r.deal_price)).toBe(true);
  });

  it("owner Q4: before the page is read the combo line posts no bundle_discount (never the old gap)", () => {
    const rows = mapOrderLines([detail(answer([comboParent(MODELS)]))], NOW).rows;
    expect(rows.map((r) => [r.promo_kind, r.original_price, r.deal_price, r.seller_subsidy, r.bundle_discount])).toEqual([["bundle", 190_000, 190_000, 0, undefined]]);
  });

  it("a combo line carries its SKU in the same fields as a plain line of the same reader", () => {
    const plain = mapOrderLines([detail(answer([plainItem], 6002))], NOW).rows[0]!;
    const doc = page(comboBlock(bundleLine("Vị A", "SKU-A01") + bundleLine("Vị B", "SKU-A02")));
    const combo = mapOrderLines([detail(withPageSkus(answer([comboParent(MODELS)]), pageItemsIn(doc)))], NOW).rows[0]!;
    const skuKeys = (row: Record<string, unknown>) => Object.keys(row).filter((k) => /sku|variation|extra/.test(k)).sort();
    expect(skuKeys(combo)).toEqual(skuKeys(plain));
    expect(plain.variation_sku).toBe("SKU-P01");
  });

  it("the answer's SKU names the line when the page shows no SKU phân loại", () => {
    const doc = page(comboBlock(bundleLine("Vị A", null) + bundleLine("Vị B", null)));
    const rows = mapOrderLines([detail(withPageSkus(answer([comboParent(MODELS)]), pageItemsIn(doc)))], NOW).rows;
    expect(rows.map((r) => r.variation_sku)).toEqual(["SKU-A01", "SKU-A02"]);
  });

  it("a plain line and a combo in one order: 1 + 2 lines, the plain line unchanged", () => {
    const doc = page(plainLine + comboBlock(bundleLine("Vị A", "SKU-A01") + bundleLine("Vị B", "SKU-A02")));
    const rows = mapOrderLines([detail(withPageSkus(answer([plainItem, comboParent(MODELS)]), pageItemsIn(doc)))], NOW).rows;
    expect(rows.map((r) => [r.variation_sku, r.deal_price, r.promo_kind])).toEqual([
      ["SKU-P01", 50_000, undefined],
      ["SKU-A01", 95_000, "bundle"],
      ["SKU-A02", 95_000, "bundle"],
    ]);
  });

  it("a sub-line no list and no page names stays unknown: never the combo's name, never a guess", () => {
    const models = [MODELS[0]!, { modelId: 8009, sku: "", name: "Vị C" }];
    const doc = page(comboBlock(bundleLine("Vị A", null) + bundleLine("Vị C", null)));
    expect(withPageSkus(answer([comboParent(models)]), pageItemsIn(doc))).toBeNull();
  });

  it("the order page job posts the combo's lines with their SKUs (no more page_lines_unmatched:page_0)", async () => {
    const doc = page(comboBlock(bundleLine("Vị A", "SKU-A01") + bundleLine("Vị B", "SKU-A02")));
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
      orderPageIncome: () => [],
      orderPageItems: () => pageItemsIn(doc),
    };
    const job = { id: "order_income" as const, orderIds: ["6001"], orderSns: [""], incomeFor: [false], fixBodies: [answer([comboParent(MODELS)])], fixLast: [false] };
    const outcome = await runReaderJob(job, env);
    expect(outcome.detail ?? "").not.toMatch(/page_lines_unmatched/);
    const lines = mapReaderJob(job, outcome.responses, NOW).find((m) => m.dataset === "order_lines");
    expect(lines?.rows.map((r) => r.variation_sku)).toEqual(["SKU-A01", "SKU-A02"]);
  });
});
