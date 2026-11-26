import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { PickerProduct } from "../../../lib/shopee-decisions/builder-api";
import { initialForms } from "../../../lib/shopee-decisions/builder-p92";
import { VoucherPanel } from "../builder-p92/panels-offers";
import type { PanelCtx } from "../builder-p92/shared";

type Scope = ReturnType<typeof initialForms>["voucher"]["scope"];

const product = { item_id: "sample-1", name: "Áo mẫu" } as unknown as PickerProduct;

function suggestion(scope: Scope, over: Partial<PanelCtx> = {}): string {
  const ctx = { api: {}, product, variations: [], products: [product], shopAov: 198_000, productAov: 246_000, outcome: null, narrow: false, costLink: "/c", market: null, ...over } as unknown as PanelCtx;
  render(<VoucherPanel ctx={ctx} form={{ ...initialForms().voucher, scope }} set={vi.fn()} />);
  return screen.getByText(/^Gợi ý từ AOV/).textContent ?? "";
}

describe("voucher AOV label (owner #87)", () => {
  it("a product voucher names the product's AOV", () => {
    expect(suggestion("product")).toBe("Gợi ý từ AOV của sản phẩm (246.000đ)");
  });

  it.each<Scope>(["shop", "follower", "livestream"])("a %s voucher names the shop's AOV", (scope) => {
    expect(suggestion(scope)).toBe("Gợi ý từ AOV của shop (198.000đ)");
  });

  it.each<[Scope, Partial<PanelCtx>]>([
    ["product", { productAov: null }],
    ["shop", { shopAov: null }],
  ])("without its own AOV a %s voucher shows no figure and no owner", (scope, over) => {
    expect(suggestion(scope, over)).toBe("Gợi ý từ AOV");
  });

  it("the chips stand on the AOV the label shows", () => {
    suggestion("product");
    expect(screen.getByRole("button", { name: "5k / 200k" })).toBeInTheDocument();
  });
});
