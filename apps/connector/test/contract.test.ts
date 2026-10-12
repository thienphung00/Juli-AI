// The posts the mapper produces for the recon-shaped fixtures are pinned in
// test/fixtures/contract/*.body.json; the backend test
// tests/unit/test_ingest_connector_contract.py posts the SAME files through the
// gateway, so a field the extension sends and the gateway refuses fails one side.
import { describe, expect, it } from "vitest";
import { ingestBody } from "../src/ingest/client";
import { mapCaptured } from "../src/shopee/map";
import shopTrafficBody from "./fixtures/contract/shop_traffic.body.json";
import overviewBody from "./fixtures/contract/traffic_overview.body.json";
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
});
