// The posts the mapper produces for the recon-shaped fixtures are pinned in
// test/fixtures/contract/*.body.json; the backend test
// tests/unit/test_ingest_connector_contract.py posts the SAME files through the
// gateway, so a field the extension sends and the gateway refuses fails one side.
import { describe, expect, it } from "vitest";
import { ingestBody } from "../src/ingest/client";
import { mapCaptured } from "../src/shopee/map";
import adsDailyBody from "./fixtures/contract/ads_campaign_daily.body.json";
import itemCatalogBody from "./fixtures/contract/item_catalog.body.json";
import itemTrafficBody from "./fixtures/contract/item_traffic_sources.body.json";
import itemSnapshotBody from "./fixtures/contract/item_snapshot.body.json";
import shopHealthBody from "./fixtures/contract/shop_health_daily.body.json";
import shopTrafficBody from "./fixtures/contract/shop_traffic.body.json";
import overviewBody from "./fixtures/contract/traffic_overview.body.json";
import voucherBody from "./fixtures/contract/voucher_settings.body.json";
import type { ReaderResponse } from "../src/shopee/reader";
import { mapAdsDaily, mapItemTraffic, mapProductList, mapShopHealth, mapVoucherList } from "../src/shopee/reader-map";
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
