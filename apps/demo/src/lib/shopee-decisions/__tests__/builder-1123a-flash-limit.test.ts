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
