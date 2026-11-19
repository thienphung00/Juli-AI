import { describe, expect, it } from "vitest";
import { mapCaptured } from "../src/platforms/shopee/map";
import overview from "./fixtures/traffic_overview.json";

const NOW = Date.UTC(2026, 9, 12, 3, 0, 0);
const Y_START = Date.UTC(2026, 9, 10, 17, 0, 0) / 1000;
const URL = `https://banhang.shopee.vn/api/mydata/v1/product/traffic/overview/?start_time=${Y_START}&end_time=${Y_START + 86399}&period=yesterday&order_type=confirmed`;

function body(): { result: Record<string, { total: Record<string, unknown>; breakdown: unknown[] }> } {
  return JSON.parse(JSON.stringify(overview));
}
const sub = (source: string, extra: Record<string, unknown> = {}) => ({
  source,
  sales: 12000,
  orders: 2,
  units: 3,
  buyers: 2,
  product_impressions: 400,
  product_clicks: 40,
  ctr: 0.1,
  sales_ratio: 0.1,
  ...extra,
});

describe("F4.1 traffic_overview breakdown rows (C1)", () => {
  it("posts one row per breakdown entry with sub_source, totals unchanged", () => {
    const plain = mapCaptured({ url: URL, body: overview, capturedAt: NOW })!;
    const b = body();
    b.result.product_card!.breakdown = [sub("psd_label_shop"), sub("psd_label_search"), sub("psd_label_others")];
    b.result.affiliate!.breakdown = [sub("psd_label_affiliate_video")];
    const mapped = mapCaptured({ url: URL, body: b, capturedAt: NOW })!;
    expect(mapped.drift).toBeNull();
    const subs = mapped.rows.filter((r) => r.sub_source !== undefined);
    expect(subs.map((r) => [r.source, r.sub_source])).toEqual([
      ["psd_label_product_card", "psd_label_shop"],
      ["psd_label_product_card", "psd_label_search"],
      ["psd_label_product_card", "psd_label_others"],
      ["psd_label_affiliate", "psd_label_affiliate_video"],
    ]);
    expect(subs[0]).toMatchObject({ date: "2026-10-11", sales: 12000, orders: 2, product_impressions: 400, ctr: 0.1 });
    expect(subs[0]!.extra).toEqual({ sales_ratio: 0.1 });
    expect(JSON.stringify(mapped.rows)).not.toContain("l2_breakdown_count");
    // the L1 totals are exactly what they were
    expect(mapped.rows.filter((r) => r.sub_source === undefined)).toEqual(plain.rows);
  });

  it("keeps an unknown code and omits the -1000000 sentinel", () => {
    const b = body();
    b.result.paid_ads!.breakdown = [
      { source: "psd_label_brand_new_ads", sales: 500, orders: 1, ads_expense: -1000000, ads_roas: -1000000 },
    ];
    const mapped = mapCaptured({ url: URL, body: b, capturedAt: NOW })!;
    const row = mapped.rows.find((r) => r.sub_source === "psd_label_brand_new_ads")!;
    expect(row.source).toBe("psd_label_shopee_ads");
    expect(row).toMatchObject({ sales: 500, orders: 1 });
    expect("ads_expense" in row).toBe(false);
    expect("ads_roas" in row).toBe(false);
  });

  it("flags an entry without a source as drift and posts nothing for it", () => {
    const b = body();
    b.result.live!.breakdown = [{ sales: 1 }];
    const mapped = mapCaptured({ url: URL, body: b, capturedAt: NOW })!;
    expect(mapped.drift?.unexpected).toContain("result.live.breakdown[0].source");
    expect(mapped.rows.filter((r) => r.sub_source !== undefined)).toHaveLength(0);
  });
});
