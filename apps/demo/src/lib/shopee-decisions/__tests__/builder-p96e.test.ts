import { describe, expect, it } from "vitest";

import { buildVersion, comboPriceOf, initialForms, marginText, refusalText } from "../builder-p92";
import { pickerProducts, variationList } from "./builder-fixtures";

/** P96e (ORY, 2026-11-06): a combo "Giá cố định" of 10đ gave −7.404.531.027đ and "Biên −1.404.170,0%". */

const product = pickerProducts().products[0]!;
const ctx = { product, variations: variationList().variations.slice(0, 2) };
const f = initialForms();
const two = ["a", "b"];

describe("P96e · combo price and margin", () => {
  it("a special price under 1.000đ is refused with a hint that a percent was meant", () => {
    const special = (value: string) => ({ ...f, combo: { ...f.combo, items: two, dtype: "special_price" as const, tiers: [{ qty: "2", value }] } });
    const p = buildVersion("combo", special("10"), ctx).problem;
    expect(p).toMatch(/quá thấp/);
    expect(p).toMatch(/% giảm/);
    expect(buildVersion("combo", special("120000"), ctx).problem).toBeNull();
  });

  it("the server's new combo refusals read in Vietnamese", () => {
    expect(refusalText({ refusal: { code: "combo_discount_over_max", message: "combo_discount_over_max" } })).toMatch(/90%/);
    expect(refusalText({ refusal: { code: "combo_price_too_low", message: "combo_price_too_low" } })).toMatch(/% giảm/);
  });

  it("the combo price comes from the unmasked field (Ops masks buyer_* keys as •••)", () => {
    expect(comboPriceOf({ buyer_pays: "•••", combo_price: 120000 })).toBe(120000);
    expect(comboPriceOf({ buyer_pays: 99000 })).toBe(99000);
    expect(comboPriceOf({})).toBeNull();
  });

  it("a margin below −100 % reads as a loss, not −1.404.170,0%", () => {
    expect(marginText(-1404170)).toBe("lỗ (bán dưới giá vốn)");
    expect(marginText(-12.5)).toBe("−12,5%");
    expect(marginText(31.6)).toBe("31,6%");
    expect(marginText(null)).toBe("—");
  });
});
