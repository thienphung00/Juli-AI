import { describe, expect, it } from "vitest";

import { lossChip } from "../../../components/shopee-decisions/builder-p92/results";
import { roiText, roundHalfAway } from "../../metrics";
import { actualText, baselineLine, changeText, deltaText, forecastOfResult, dataThroughText, finalVerdict, measuredWithText, metricView, newestDataThrough, isNoisy } from "../forecast-display";

describe("forecast display (F7.8)", () => {
  it("headline with the days for profit, the grey line with sign and percent", () => {
    const v = metricView("profit", { hien_tai: 162572, du_kien: 153500, delta: -9072, delta_pct: -5.6, days: 30 });
    expect(v.label).toBe("Lợi nhuận đóng góp dự kiến (30 ngày)");
    expect(v.value).toBe("153.500 đ");
    expect(v.sub).toBe("hiện tại: 162.572 đ · −9.072 đ (−5,6 %)");
    expect(v.loss).toBe(false);
  });

  it("a positive change carries +; orders have no đ; AOV and GMV use đ", () => {
    expect(baselineLine("orders", { hien_tai: 10, du_kien: 12, delta: 2, delta_pct: 20 })).toBe("hiện tại: 10 đơn · +2 (+20,0 %)");
    expect(metricView("gmv", { hien_tai: 1000, du_kien: 1100, delta: 100, delta_pct: 10 }).label).toBe("GMV dự kiến");
    expect(metricView("aov", { hien_tai: 100000, du_kien: 91667, delta: -8333, delta_pct: -8.3 }).value).toBe("91.667 đ");
  });

  it("Lỗ only when du_kien < 0, never because the change is negative", () => {
    expect(metricView("profit", { hien_tai: 100, du_kien: 50, delta: -50, delta_pct: -50 }).loss).toBe(false);
    const loss = metricView("profit", { hien_tai: 100, du_kien: -20, delta: -120, delta_pct: -120 });
    expect(loss.loss).toBe(true);
    expect(loss.value).toBe("Lỗ 20 đ");
    expect(metricView("gmv", { hien_tai: 100, du_kien: -20, delta: -120, delta_pct: null }).loss).toBe(false);
  });

  it("no estimate is a dash with the reason as the hover; low / high never appear", () => {
    const v = metricView("profit", { hien_tai: null, du_kien: null, delta: null, delta_pct: null }, { why: "Chưa đủ dữ liệu" });
    expect(v).toMatchObject({ value: "—", sub: null, why: "Chưa đủ dữ liệu" });
    const withBand = metricView("profit", { hien_tai: 10, du_kien: 20, delta: 10, delta_pct: 100, low: 1234, high: 5678 });
    expect(JSON.stringify(withBand)).not.toMatch(/1\.234|5\.678|1234|5678/);
  });

  it("Số liệu đến dd/mm, the newest of a list", () => {
    expect(dataThroughText("2026-11-18")).toBe("Số liệu đến 18/11");
    expect(dataThroughText(null)).toBeNull();
    expect(newestDataThrough([{ data_through: "2026-11-17" }, { forecast: { data_through: "2026-11-19" } }, {}])).toBe("2026-11-19");
  });

  it("Thực tế against hiện tại, the final verdict only when final, đo chung with codes", () => {
    expect(actualText("profit", { thuc_te: 40000, hien_tai: 58000, delta: -18000, delta_pct: -31 })).toBe("Thực tế: 40.000 đ · hiện tại: 58.000 đ · −18.000 đ (−31,0 %)");
    expect(finalVerdict({ final: true, verdict: { label: "Vượt khoảng" } })).toBe("Vượt khoảng");
    expect(finalVerdict({ final: false, verdict: { label: "Vượt khoảng" } })).toBeNull();
    expect(measuredWithText(["GIA-1", "DS-01b"])).toBe("đo chung với GIA-1, DS-01b");
    expect(measuredWithText([])).toBeNull();
  });

  it("D1: the change is the difference of the SHOWN figures (52 → 53 reads +1, never +2)", () => {
    expect(baselineLine("orders", { hien_tai: 52.4, du_kien: 52.6, delta: 0.2, delta_pct: 0.4 })).toBe("hiện tại: 52 đơn · +1 (+0,4 %)");
    expect(baselineLine("orders", { hien_tai: 52.4, du_kien: 53.6, delta: 1.2, delta_pct: 2.3 })).toContain("· +2 ");
    expect(metricView("gmv", { hien_tai: 100.4, du_kien: 100.6, delta: 0.2, delta_pct: 0 }).sub).toContain("+1 đ");
  });

  it("D1: rounding is half away from zero, like the server (−1,5 → −2)", () => {
    expect(roundHalfAway(-1.5)).toBe(-2);
    expect(roundHalfAway(2.5)).toBe(3);
    expect(deltaText("orders", -1.5)).toBe("−2");
    expect(changeText("gmv", -2.5, null)).toBe("−3 đ");
    const f = forecastOfResult({ estimable: true, days: 7, after: { days: 7 }, detail: { before: { gmv: 100, orders: 51.5, profit: 10, views: null, ctr: null, ctor: null, aov: null, by_source: {} }, likely: { gmv: 100, orders: 50, profit: 10, views: null, ctr: null, ctor: null, aov: null, by_source: {} }, low: null, high: null } } as never);
    // shown 52 → 50 is −2, not the unrounded −1,5
    expect(f?.metrics?.orders?.delta).toBe(-2);
  });

  it("D2: the card profit line is the registry's Lợi nhuận đóng góp, and ROI has one decimal", () => {
    expect(metricView("profit", { hien_tai: 1, du_kien: 2, delta: 1, delta_pct: 1, days: 14 }).label).toBe("Lợi nhuận đóng góp dự kiến (14 ngày)");
    expect(roiText(1.95)).toBe("2,0");
    expect(roiText(5.44)).toBe("5,4");
  });

  it("D4: a profit inside the noise carries the tag (the F5 design), a gmv does not", () => {
    const noisy = metricView("profit", { hien_tai: 100, du_kien: 112, delta: 12, delta_pct: 12 }, { days: 30, noise: true });
    expect(noisy.value).toBe("112 đ · trong dao động");
    expect(metricView("profit", { hien_tai: 100, du_kien: 112, delta: 12, delta_pct: 12 }, { days: 30 }).value).toBe("112 đ");
    const f = forecastOfResult({ estimable: true, days: 7, after: { days: 7 }, within_noise: ["gmv", "profit"], detail: { before: { gmv: 1, orders: 1, profit: 1, views: null, ctr: null, ctor: null, aov: null, by_source: {} }, likely: { gmv: 2, orders: 2, profit: 2, views: null, ctr: null, ctor: null, aov: null, by_source: {} }, low: null, high: null } } as never);
    expect(isNoisy(f, "profit")).toBe(true);
    expect(isNoisy(f, "gmv")).toBe(false);
  });

  it("F2: the server's block is the forecast; the field is within_noise; a loss is never only \"trong dao động\"", () => {
    const block = { days: 30, within_noise: ["profit"], metrics: { profit: { hien_tai: 100, du_kien: 92, delta: -8, delta_pct: -8 } } };
    expect(forecastOfResult({ estimable: true, forecast: block } as never)).toBe(block);
    expect(isNoisy(block, "profit")).toBe(false);
    expect(isNoisy({ ...block, metrics: { profit: { hien_tai: 100, du_kien: 108, delta: 8, delta_pct: 8 } } }, "profit")).toBe(true);
    const under = { ...block, metrics: { profit: { hien_tai: -20, du_kien: -12, delta: 8, delta_pct: null } } };
    expect(isNoisy(under, "profit")).toBe(false);
    expect(lossChip(under, { estimable: true } as never)).toEqual({ text: "Lỗ", tone: "down" });
  });
});
