import { describe, expect, it } from "vitest";
import { isPageMessage } from "../src/content/messages";
import { buildSyncPlan, gapBefore, requestUrl } from "../src/shopee/sync";

const NOW = Date.UTC(2026, 9, 12, 3, 0, 0);
const Y_START = Date.UTC(2026, 9, 10, 17, 0, 0) / 1000;

describe("daily sync plan", () => {
  it("asks for yesterday's shop-level calls; item readers wait for D31.6", () => {
    const plan = buildSyncPlan(NOW, new Set());
    expect(plan.map((p) => p.dataset)).toEqual(["traffic_overview", "shop_traffic"]);
    expect(plan[0]?.params).toEqual({
      start_time: String(Y_START),
      end_time: String(Y_START + 86399),
      period: "yesterday",
      order_type: "confirmed",
    });
    expect(plan[1]?.useTemplate).toBe(true);
  });

  it("skips stopped datasets and adds item pages when enabled", () => {
    const plan = buildSyncPlan(NOW, new Set(["traffic_overview"] as const), true);
    expect(plan.some((p) => p.dataset === "traffic_overview")).toBe(false);
    expect(plan.filter((p) => p.dataset === "item_by_source")).toHaveLength(5);
    expect(plan.filter((p) => p.dataset === "item_performance")).toHaveLength(5);
  });

  it("spaces requests at least 2 s apart with jitter", () => {
    expect(gapBefore(0)).toBe(0);
    expect(gapBefore(1, () => 0)).toBe(2000);
    expect(gapBefore(3, () => 0.999)).toBeLessThan(3500);
    expect(gapBefore(3, () => 0.999)).toBeGreaterThanOrEqual(2000);
  });

  it("adds the session params the page uses; a template must be 'yesterday'", () => {
    const [overview, traffic] = buildSyncPlan(NOW, new Set());
    const url = requestUrl("https://banhang.shopee.vn", overview!, { SPC_CDS: "s", SPC_CDS_VER: "2" });
    expect(url).toContain("/api/mydata/v1/product/traffic/overview/?start_time=");
    expect(url).toContain("SPC_CDS=s&SPC_CDS_VER=2");
    expect(requestUrl("https://banhang.shopee.vn", traffic!, {}, undefined)).toBeNull();
    expect(requestUrl("https://banhang.shopee.vn", traffic!, {}, { period: "real_time" })).toBeNull();
    expect(requestUrl("https://banhang.shopee.vn", traffic!, {}, { period: "yesterday", dt: "x" })).toContain(
      "period=yesterday&dt=x",
    );
  });
});

describe("page → content-script messages", () => {
  const self = {};
  const ok = { source: self, origin: "https://banhang.shopee.vn", data: { channel: "c", kind: "capture" } };
  it("accepts only this window, Seller Centre's origin and our channel", () => {
    expect(isPageMessage(ok, self, "https://banhang.shopee.vn", "c")).toBe(true);
    expect(isPageMessage({ ...ok, source: {} }, self, "https://banhang.shopee.vn", "c")).toBe(false);
    expect(isPageMessage({ ...ok, origin: "https://evil.example" }, self, "https://banhang.shopee.vn", "c")).toBe(false);
    expect(isPageMessage({ ...ok, data: { channel: "x", kind: "capture" } }, self, "https://banhang.shopee.vn", "c")).toBe(
      false,
    );
    expect(isPageMessage({ ...ok, data: { channel: "c", kind: "sync" } }, self, "https://banhang.shopee.vn", "c")).toBe(
      false,
    );
  });
});
