import { describe, expect, it } from "vitest";

import { actualText, baselineLine, dataThroughText, finalVerdict, measuredWithText, metricView, newestDataThrough } from "../forecast-display";

describe("forecast display (F7.8)", () => {
  it("headline with the days for profit, the grey line with sign and percent", () => {
    const v = metricView("profit", { hien_tai: 162572, du_kien: 153500, delta: -9072, delta_pct: -5.6, days: 30 });
    expect(v.label).toBe("Lợi nhuận dự kiến (30 ngày)");
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
});
