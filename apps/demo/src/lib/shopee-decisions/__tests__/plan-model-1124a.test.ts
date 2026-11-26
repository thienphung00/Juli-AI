import { describe, expect, it } from "vitest";

import { aggRows, kolRows, splitRows } from "../plan-model";
import { plan } from "./plan-fixtures";

describe("Track D (batch-1124-a): plan model", () => {
  it("D1: ④ Δ đơn, ⑤ Δ AOV and GMV Δ come from the shown rounded figures", () => {
    const p = plan();
    const a = p.aggregate!;
    const rows = aggRows({
      ...p,
      aggregate: { ...a, today: { ...a.today!, orders_30d: 205.4, gmv_30d: 25_750_400, aov: 125_400 }, after: { ...a.after!, aov: 125_600 }, dorders_month: { p10: 0, p50: 0.2, p90: 1 }, dgmv_month: { total: { p10: 0, p50: 200, p90: 1 } } },
    });
    // 205,4 → 205 and 205,6 → 206 on screen: "+1", not "+0,2" / "+0"
    expect(rows.find((r) => r.key === "orders")!.d).toBe("+1 đơn");
    // AOV is shown to nghìn: 125.000đ → 126.000đ is +1.000đ
    expect(rows.find((r) => r.key === "aov")!.d).toContain("+1.000đ");
  });

  it("D2/D3: ③ is the registry's Biên lợi nhuận from the server margin; no dead chắc chắn row", () => {
    const p = plan();
    const rows = aggRows({ ...p, aggregate: { ...p.aggregate!, margin: { metric_id: "margin", before_pct: 10, after_pct: 9.5 }, dprofit_month: { ...p.aggregate!.dprofit_month!, certain: null } } });
    expect(rows.find((r) => r.key === "bien")).toMatchObject({ label: "③ Biên lợi nhuận", today: "10,0%", after: "9,5%" });
    expect(rows.find((r) => r.key === "sure")).toBeUndefined();
  });

  it("D3: the KOL sample-cost row is dropped unless the server gives the certain cost", () => {
    const base = { samples: 1, invites: 1, profit: { p10: 0, p50: 1, p90: 2 } };
    expect(kolRows({ ...base, sampleCost: null }).map((r) => r.k)).toEqual(["Số thẻ", "Lợi nhuận ròng sau mẫu"]);
    expect(kolRows({ ...base, sampleCost: 190_000 }).map((r) => r.k)).toContain("Tổng chi phí mẫu (chắc chắn, chi một lần)");
  });

  it("D5: the per-channel Δ rows add up to the total row", () => {
    const rows = splitRows({ delta_p50: { organic: { dgmv: 10, dorders: 2, dprofit: 5_000 }, ads: { dgmv: 20, dorders: 1, dprofit: -2_000 }, affiliate: { dgmv: 30, dorders: 1, dprofit: 1_000 } } });
    expect(rows.map((r) => r.label)).toEqual(["Organic", "Quảng cáo", "TTLK", "Tổng"]);
    expect(rows.at(-1)!.dprofit).toBe("+4.000đ");
    expect(rows.at(-1)!.dorders).toBe("+4 đơn");
    expect(splitRows(null)).toEqual([]);
  });
});
