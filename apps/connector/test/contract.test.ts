// The posts the mapper produces for the recon-shaped fixtures are pinned in
// test/fixtures/contract/*.body.json; the backend test
// tests/unit/test_ingest_connector_contract.py posts the SAME files through the
// gateway, so a field the extension sends and the gateway refuses fails one side.
import { describe, expect, it } from "vitest";
import { ingestBody } from "../src/platforms/shopee/ingest/client";
import { mapCaptured } from "../src/platforms/shopee/map";
import adsDailyBody from "./fixtures/contract/ads_campaign_daily.body.json";
import itemCatalogBody from "./fixtures/contract/item_catalog.body.json";
import itemTrafficBody from "./fixtures/contract/item_traffic_sources.body.json";
import itemSnapshotBody from "./fixtures/contract/item_snapshot.body.json";
import shopHealthBody from "./fixtures/contract/shop_health_daily.body.json";
import shopTrafficBody from "./fixtures/contract/shop_traffic.body.json";
import overviewBody from "./fixtures/contract/traffic_overview.body.json";
import voucherBody from "./fixtures/contract/voucher_settings.body.json";
import comboBody from "./fixtures/contract/combo_settings.body.json";
import orderLinesBody from "./fixtures/contract/order_lines.body.json";
import orderIncomeBody from "./fixtures/contract/order_income.body.json";
import { RAW_ORDER_ID } from "../src/platforms/shopee/affiliate-map";
import { mapOrderIncome, mapOrderLines, trimOrderDetail } from "../src/platforms/shopee/orders-map";
import type { Mapped } from "../src/platforms/shopee/map";
import type { ReaderResponse } from "../src/platforms/shopee/reader";
import { mapAdsDaily, mapComboList, mapItemTraffic, mapProductList, mapShopHealth, mapVoucherList } from "../src/platforms/shopee/reader-map";
import comboDetail from "./fixtures/readers/combo_detail.json";
import comboList from "./fixtures/readers/combo_list.json";
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
import shopTraffic from "./fixtures/shop_traffic.json";
import overview from "./fixtures/traffic_overview.json";

const NOW = Date.UTC(2026, 9, 12, 3, 0, 0);
const Y = Date.UTC(2026, 9, 10, 17, 0, 0) / 1000;
const SC = "https://banhang.shopee.vn";

describe("extension ↔ gateway contract", () => {
  it("traffic_overview", () => {
    const mapped = mapCaptured({
      url: `${SC}/api/mydata/v1/product/traffic/overview/?start_time=${Y}&end_time=${Y + 86399}&period=yesterday&order_type=confirmed`,
      body: overview,
      capturedAt: NOW,
    });
    expect(ingestBody(mapped!, "0.1.0", NOW)).toEqual(overviewBody);
  });

  it("shop_traffic", () => {
    const mapped = mapCaptured({
      url: `${SC}/api/mydata/traffic/dashboard/overview/?period=yesterday`,
      body: shopTraffic,
      capturedAt: NOW,
    });
    expect(ingestBody(mapped!, "0.1.0", NOW)).toEqual(shopTrafficBody);
  });

  // The page readers (ADR-120 d.14): tests/unit/test_ingest_connector_contract.py posts the same
  // files through the gateway (item_snapshot and shop_health_daily through their reserved models).
  describe("page readers", () => {
    const READ_AT = Date.UTC(2026, 10, 3, 3, 0, 0);
    const reply = (endpoint: ReaderResponse["endpoint"], body: unknown, extra: Partial<ReaderResponse> = {}): ReaderResponse => ({
      endpoint,
      url: "u",
      status: 200,
      body,
      capturedAt: READ_AT,
      source: "replay",
      ...extra,
    });
    const products = mapProductList(
      [
        reply("product_list", products1, { page: 1 }),
        reply("product_list", products2, { page: 2 }),
        reply("campaign_info", campaignInfo, { source: "page" }),
      ],
      READ_AT,
    );

    it("item_catalog", () => expect(ingestBody(products.catalog, "0.3.0", READ_AT)).toEqual(itemCatalogBody));
    it("item_snapshot (reserved until migration 112)", () =>
      expect(ingestBody(products.snapshot, "0.3.0", READ_AT)).toEqual(itemSnapshotBody));
    it("ads_campaign_daily", () => {
      const [post] = mapAdsDaily([
        reply("ads_homepage", adsHome, { day: "2026-11-02", usePaidGmv: false }),
        reply("ads_time_graph", adsGraph, { day: "2026-11-02" }),
      ]);
      expect(ingestBody(post!, "0.3.0", READ_AT)).toEqual(adsDailyBody);
    });
    it("item_traffic_sources", () => {
      const [post] = mapItemTraffic([reply("traffic_details", trafficDetails, { day: "2026-11-02", itemId: "1001" })]);
      expect(ingestBody(post!, "0.3.4", READ_AT)).toEqual(itemTrafficBody);
    });
    it("voucher_settings", () =>
      expect(ingestBody(mapVoucherList([reply("voucher_list", vouchers, { page: 1 })], READ_AT), "0.3.0", READ_AT)).toEqual(
        voucherBody,
      ));
    it("combo_settings (0.3.35)", () =>
      expect(ingestBody(mapComboList([reply("combo_list", comboList), reply("combo_detail", comboDetail)], READ_AT), "0.3.35", READ_AT)).toEqual(comboBody));
    // batch-1124-a S1: a combo + Mua Kèm order (get_one_order) and its order page income with the
    // buyer-payment vouchers. The raw order id is replaced by a fixed synthetic order_ref (the
    // service worker's keyed hash in the extension).
    const REF = "0123456789abcdef0123456789abcdef";
    const hashed = (mapped: Mapped): Mapped => ({
      ...mapped,
      rows: mapped.rows.map((row) => {
        const { [RAW_ORDER_ID]: _id, ...rest } = row;
        return { ...rest, order_ref: REF };
      }),
    });
    const S1_CREATED = Date.UTC(2026, 10, 2, 2, 0, 0) / 1000;
    const s1Detail = reply("order_detail", trimOrderDetail({
      code: 0,
      data: {
        order_id: 8001,
        order_sn: "261102SYN801",
        create_time: S1_CREATED,
        complete_time: S1_CREATED + 86400,
        status_info: { status: "Hoàn thành" },
        total_price: "178000",
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
          { item_id: 9011, model_id: 9211, amount: 1, order_price: "30000", item_model: { sku: "SKU-ADD", model_id: 9211 }, add_on_deal_id: 55, is_add_on_sub_item: true },
        ],
      },
    }));
    const s1Income = reply(
      "order_income_components",
      {
        code: 0,
        data: {
          items: [
            { name: "Giá sản phẩm", amount: 178000 },
            { name: "Phí cố định", amount: -26700 },
            { name: "Voucher Xtra", amount: -5500 },
            { name: "Doanh Thu Đơn Hàng", amount: 145800 },
          ],
          buyer_items: [
            { name: "Shopee Voucher", amount: -20000 },
            { name: "Mã giảm giá của Shop", amount: -10000 },
          ],
        },
      },
      { source: "page", orderId: "8001", orderSn: "261102SYN801" },
    );
    it("order_lines (S1: combo amount, Mua Kèm)", () =>
      expect(ingestBody(hashed(mapOrderLines([s1Detail], READ_AT)), "0.3.35", READ_AT)).toEqual(orderLinesBody));
    it("order_income (S1: buyer-payment vouchers apart from the seller's costs)", () =>
      expect(ingestBody(hashed(mapOrderIncome([s1Income], READ_AT)), "0.3.35", READ_AT)).toEqual(orderIncomeBody));
    it("shop_health_daily (reserved until its table exists)", () =>
      expect(
        ingestBody(
          mapShopHealth(
            [
              reply("health_overview", healthOverview),
              reply("health_metric_list", healthList),
              reply("health_metric_configs", healthConfigs),
            ],
            READ_AT,
          ),
          "0.3.0",
          READ_AT,
        ),
      ).toEqual(shopHealthBody));
  });
});
