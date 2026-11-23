import { describe, expect, it } from "vitest";

import { buildVersion, initialForms, type Forms } from "../builder-p92";
import { pickerProducts, variationList } from "./builder-fixtures";

/** batch-1123-a F4: the Flash Sale form's optional "Giới hạn đặt hàng" rides on the version as `purchase_limit`. */

const product = pickerProducts().products[0]!;
const ctx = { product, variations: variationList().variations.slice(0, 2) };
const f = initialForms();
const flash = (purchaseLimit: string): Forms => ({
  ...f,
  price_flash: { ...f.price_flash, what: "flash_sale", rows: [{ variationId: "v3", value: "10" }], purchaseLimit },
});

describe("Flash Sale · Giới hạn đặt hàng", () => {
  it("a limit 1-1000 is sent as purchase_limit; empty sends none (Không hạn mức)", () => {
    expect(buildVersion("price_flash", flash("3"), ctx).version).toMatchObject({ kind: "flash_sale", purchase_limit: 3 });
    expect(buildVersion("price_flash", flash(""), ctx).version).not.toHaveProperty("purchase_limit");
  });

  it("0, over 1000, a fraction or text is refused in Vietnamese", () => {
    for (const bad of ["0", "1001", "2.5", "abc"]) expect(buildVersion("price_flash", flash(bad), ctx).problem).toMatch(/Giới hạn đặt hàng/);
  });
});

describe("name limits per Shopee form (owner decision #13), worded like the server", () => {
  const deal = (name: string, type: "add_on" | "gift" = "add_on"): Forms => ({ ...f, deal_soc: { ...f.deal_soc, type, name } });
  it("Deal Sốc 25, Combo 25, Chương Trình Của Shop 150", () => {
    expect(buildVersion("deal_soc", deal("x".repeat(26)), ctx).problem).toBe("Tên Deal Sốc tối đa 25 ký tự.");
    expect(buildVersion("deal_soc", deal("x".repeat(26), "gift"), ctx).problem).toBe("Tên Deal Sốc tối đa 25 ký tự.");
    expect(buildVersion("deal_soc", deal("x".repeat(25)), ctx).problem).not.toMatch(/Tên Deal Sốc/);
    expect(buildVersion("combo", { ...f, combo: { ...f.combo, items: ["a", "b"], name: "x".repeat(26) } }, ctx).problem).toBe("Tên Combo Khuyến Mãi tối đa 25 ký tự.");
    expect(buildVersion("product_discount", { ...f, product_discount: { ...f.product_discount, name: "x".repeat(151) } }, ctx).problem).toBe("Tên chương trình khuyến mãi tối đa 150 ký tự.");
    expect(buildVersion("product_discount", { ...f, product_discount: { ...f.product_discount, name: "x".repeat(150) } }, ctx).problem).not.toMatch(/Tên chương trình/);
  });
});
