import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { buildVersion, initialForms } from "../../../lib/shopee-decisions/builder-p92";
import { pickerProducts, variationList } from "../../../lib/shopee-decisions/__tests__/builder-fixtures";
import type { VariationRow } from "../../../lib/shopee-decisions/builder-api";
import { DiscountPanel } from "../builder-p92/panels-offers";
import type { PanelCtx } from "../builder-p92/shared";

/** ORY 2026-11-14: Chương Trình Của Shop at 10 % was refused only after a round trip (the product already sells at 82.620đ, needs ≥ 17 %). */
const product = pickerProducts().products[0]!;
const base = variationList().variations[0]!;
const variation: VariationRow = { ...base, list_price: 99_000, selling_price: 82_620, paid_price: 82_620, min_discount_pct: 17 };
const buildCtx = { product, variations: [variation] };

function forms(mode: "pct" | "final_price", value: string) {
  const f = initialForms();
  return { ...f, product_discount: { ...f.product_discount, mode, rows: [{ variationId: variation.variation_id, value }] } };
}

function panel(mode: "pct" | "final_price", value: string) {
  const f = forms(mode, value).product_discount;
  const ctx = { variations: [variation], product, outcome: null, market: null } as unknown as PanelCtx;
  return render(<DiscountPanel ctx={ctx} form={f} set={() => undefined} />);
}

describe("giá thấp nhất của chương trình giảm giá", () => {
  it("shows the minimum and the price buyers pay under the row", () => {
    panel("pct", "");
    expect(screen.getByTestId("p2-min-1")).toHaveTextContent("Tối thiểu 17 % · đang bán 82.620đ");
    expect(screen.queryByTestId("p2-under-1")).toBeNull();
  });

  it("flags a value below the minimum, and nothing at or above it", () => {
    const { unmount } = panel("pct", "10");
    expect(screen.getByTestId("p2-under-1")).toHaveTextContent("Thấp hơn giá đang bán: nhập từ 17 % trở lên");
    unmount();
    panel("pct", "17");
    expect(screen.queryByTestId("p2-under-1")).toBeNull();
  });

  it("flags a price after the discount that is not under the price buyers pay", () => {
    panel("final_price", "85000");
    expect(screen.getByTestId("p2-under-1")).toHaveTextContent("nhập dưới 82.620đ");
  });

  it("shows nothing when the minimum is unknown", () => {
    const f = forms("pct", "5").product_discount;
    const open: VariationRow = { ...variation, paid_price: null, min_discount_pct: null };
    const ctx = { variations: [open], product, outcome: null, market: null } as unknown as PanelCtx;
    render(<DiscountPanel ctx={ctx} form={f} set={() => undefined} />);
    expect(screen.queryByTestId("p2-min-1")).toBeNull();
    expect(screen.queryByTestId("p2-under-1")).toBeNull();
  });

  it("does not build the version below the minimum, so no call is made", () => {
    const low = buildVersion("product_discount", forms("pct", "10"), buildCtx);
    expect(low.version).toBeNull();
    expect(low.problem).toBe("Thấp hơn giá đang bán: nhập từ 17 % trở lên");
    expect(buildVersion("product_discount", forms("pct", "17"), buildCtx).version).not.toBeNull();
    expect(buildVersion("product_discount", forms("final_price", "85000"), buildCtx).version).toBeNull();
    expect(buildVersion("product_discount", forms("final_price", "80000"), buildCtx).version).not.toBeNull();
  });

  it("applies to the flash sale of the shop as well, not to a list-price change", () => {
    const f = initialForms();
    const flash = { ...f, price_flash: { ...f.price_flash, what: "flash_sale" as const, mode: "pct" as const, units: "10", rows: [{ variationId: variation.variation_id, value: "10" }] } };
    expect(buildVersion("price_flash", flash, buildCtx).problem).toMatch(/nhập từ 17 %/);
    const price = { ...f, price_flash: { ...f.price_flash, what: "price" as const, mode: "pct" as const, rows: [{ variationId: variation.variation_id, value: "-10" }] } };
    expect(buildVersion("price_flash", price, buildCtx).problem).toBeNull();
  });
});
