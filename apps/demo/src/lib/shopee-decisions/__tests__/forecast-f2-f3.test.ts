import { describe, expect, it } from "vitest";

import { staleText } from "../../../components/shopee-decisions/builder-p92/results";
import { basisTone } from "../../../components/shopee-decisions/builder-p92/results";
import { expectedRows } from "../model";
import { voucherCard } from "./fixtures";

/** Forecast grill F2 (stale data), F3 (noise band), pooled basis, and F4 `shown` from S1. Synthetic data. */
describe("forecast grill F2 · F3 on screen", () => {
  it("names the dataset and the last day when the shop's data is behind", () => {
    expect(staleText({ dataset: "orders", through: "2026-11-12" })).toBe("Đơn hàng đến 12/11");
    expect(staleText({ dataset: "traffic", through: "2026-11-09" })).toBe("Lượt truy cập đến 09/11");
    expect(staleText(null)).toBeNull();
  });

  it("a pooled estimate reads like a shop-level one", () => {
    expect(basisTone("pooled")).toBe(basisTone("shop"));
  });

  it("Dự kiến uses `shown`; a metric inside the noise band is —", () => {
    const card = voucherCard();
    const pm = { ...card.predicted.money_per_month, shown: { dgmv: 450_000, dorders: null, dprofit: 57_000 }, within_noise: ["orders" as const] };
    const rows = expectedRows({ ...card, predicted: { ...card.predicted, money_per_month: pm } });
    expect(rows[1]!.dv).toBe("+450.000đ GMV");
    expect(rows[2]!.dv).toMatch(/^\+57\.000đ trong \d+ ngày$/);
    expect(rows[3]!.dv).toBe("—");
    expect(rows[3]!.after).toBe("—");
  });
});
