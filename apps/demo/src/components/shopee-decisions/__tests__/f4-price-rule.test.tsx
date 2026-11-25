import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MAX_DEAL_NAME, initialForms } from "../../../lib/shopee-decisions/builder-p92";
import { pickerProducts, variationList } from "../../../lib/shopee-decisions/__tests__/builder-fixtures";
import type { VariationRow } from "../../../lib/shopee-decisions/builder-api";
import { DealSocPanel, PriceFlashPanel, quoteVariationPrice } from "../builder-p92/panels-offers";
import type { PanelCtx } from "../builder-p92/shared";

const product = pickerProducts().products[0]!;
const base = variationList().variations[0]!;
const priced: VariationRow = { ...base, variation_id: "a", name: "Loại A", list_price: 150_900, selling_price: 126_360, paid_price: 126_360, min_discount_pct: 17 };
const unpriced: VariationRow = { ...base, variation_id: "b", name: "Loại B", list_price: null, selling_price: null, paid_price: null, min_discount_pct: null };
const ctx = { variations: [priced, unpriced], products: [product], product, outcome: null, market: null } as unknown as PanelCtx;

describe("F4: one price rule", () => {
  it("the typed percent is quoted from one place: the shown price is the quoted price", () => {
    const next = quoteVariationPrice(priced, { discount_pct: 5 }, "flash_sale");
    expect(next).toBe(143_300);
  });

  it("a value typed in Đổi giá niêm yết does not carry into Flash Sale", () => {
    const f = initialForms().price_flash;
    const set = vi.fn();
    render(<PriceFlashPanel ctx={ctx} form={{ ...f, what: "price", rows: [{ variationId: "a", value: "-5" }] }} set={set} />);
    fireEvent.click(screen.getByRole("radio", { name: "Flash Sale Của Shop" }));
    expect(set).toHaveBeenCalledWith({ what: "flash_sale", rows: [] });
  });

  it("a variation without a price takes no input", () => {
    const f = initialForms().price_flash;
    render(<PriceFlashPanel ctx={ctx} form={{ ...f, what: "price" }} set={() => undefined} />);
    expect(screen.getByLabelText(/Loại B/)).toBeDisabled();
    expect(screen.getByLabelText(/Loại A/)).not.toBeDisabled();
  });

  it("the Deal Sốc name counter shows the backend limit", () => {
    expect(MAX_DEAL_NAME).toBe(25);
    const f = initialForms().deal_soc;
    render(<DealSocPanel ctx={ctx} form={{ ...f, name: "abc" }} set={() => undefined} />);
    expect(screen.getByText(/3\/25 ký tự/)).toBeInTheDocument();
  });
});
