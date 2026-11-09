import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ShopeeHostProvider } from "../../../lib/shopee-analytics/context";
import { sellerLinks } from "../../../lib/shopee-analytics/links";
import { fakeApi, product } from "../../../lib/shopee-analytics/__tests__/fixtures";
import type { ProductPage, SkuCost } from "../../../lib/shopee-analytics/types";
import { fakeBuilder, variationList } from "../../../lib/shopee-decisions/__tests__/builder-fixtures";
import { VariationCompare } from "../../shopee-decisions/builder-p92/variations";
import { ProductPageView } from "../product-page";
import { params, renderWith } from "./harness";

/** ADR-122 d.12 on Sản phẩm › Phiên bản sản phẩm: both margins, Đơn = orders, pack-key SKU chip, no 1/3 footer. */

function withSkus(extra: Record<string, Record<string, unknown>>): ProductPage {
  const base = product();
  const skus = base.cost_and_floor.skus.map((s) => ({ ...s, ...(extra[s.sku] ?? {}) }) as SkuCost);
  return { ...base, cost_and_floor: { ...base.cost_and_floor, skus } };
}

const page = (p: ProductPage) => renderWith(<ProductPageView id="BEP-S5" params={params("tab=ng")} />, fakeApi({ product: p }));

describe("Sản phẩm: Phiên bản sản phẩm (ADR-122 d.12)", () => {
  it("shows Biên ở giá bán (chắc chắn) and Biên cuối (ước tính) from the backend", async () => {
    page(withSkus({ "BEP-S5-CB": { orders: 12, price_margin_pct: 22.5, final_margin_pct: 14.1, final_margin_basis: "variation" } }));
    const row = within(await screen.findByTestId("sa-variations")).getByTestId("sa-var-BEP-S5-CB");
    expect(within(row).getByTestId("sa-margin-price")).toHaveTextContent("22,5%");
    expect(within(row).getByTestId("sa-margin-price")).toHaveTextContent("Biên ở giá bán · chắc chắn");
    expect(within(row).getByTestId("sa-margin-final")).toHaveTextContent("14,1%");
    expect(within(row).getByTestId("sa-margin-final")).toHaveTextContent("Biên cuối · ước tính");
    expect(within(row).getByTestId("sa-margin-final")).not.toHaveTextContent("theo tỉ lệ của sản phẩm");
  });

  it("a variation on its product's rates says so; a missing giá vốn reads chưa tính", async () => {
    page(
      withSkus({
        "BEP-S5-CB": { price_margin_pct: 20, final_margin_pct: 11, final_margin_basis: "product", final_margin_note: "theo tỉ lệ của sản phẩm" },
        "BEP-S5-QT": { price_margin_pct: null, final_margin_pct: null, final_margin_basis: "variation" },
      }),
    );
    const table = await screen.findByTestId("sa-variations");
    expect(within(within(table).getByTestId("sa-var-BEP-S5-CB")).getByTestId("sa-margin-final")).toHaveTextContent("theo tỉ lệ của sản phẩm");
    const qt = within(table).getByTestId("sa-var-BEP-S5-QT");
    expect(within(qt).getByTestId("sa-margin-price")).toHaveTextContent("chưa tính");
    expect(within(qt).getByTestId("sa-margin-final")).toHaveTextContent("chưa tính");
  });

  it("Đơn counts distinct orders and the units move to the hint", async () => {
    page(withSkus({ "BEP-S5-CB": { orders: 12, units: 30 } }));
    const row = within(await screen.findByTestId("sa-variations")).getByTestId("sa-var-BEP-S5-CB");
    const cell = within(row).getByTestId("sa-var-orders");
    expect(cell).toHaveTextContent(/^12/);
    expect(cell).toHaveTextContent("30 sản phẩm");
  });

  it("the SKU chip shows the cost key with its pack when it differs from the plain SKU", async () => {
    page(withSkus({ "BEP-S5-CB": { sku: "BEP-S5-CB×3", variation_id: "v1", base_sku: "BEP-S5-CB" } }));
    const table = await screen.findByTestId("sa-variations");
    expect(within(table).getByTestId("sa-var-BEP-S5-CB")).toHaveTextContent("BEP-S5-CB×3");
  });

  it("the footer no longer offers the 1/3 assumed cost", async () => {
    page(product());
    const table = await screen.findByTestId("sa-variations");
    expect(table).not.toHaveTextContent("giả định 1/3 giá, có ghi rõ");
    expect(table).toHaveTextContent("chưa tính");
  });
});

describe("So sánh phân loại: Biên cuối (W2-G's final_margin_pct)", () => {
  it("renders final_margin_pct next to margin_pct when present", () => {
    const data = variationList();
    const rows = data.variations.map((v, i) => ({ ...v, final_margin_pct: i === 0 ? 9.5 : null, final_margin_basis: i === 1 ? ("product" as const) : ("variation" as const) }));
    render(<VariationCompare costLink="/x" data={{ ...data, variations: rows }} />);
    const v3 = screen.getByTestId("p2-vcmp-v3");
    expect(v3).toHaveTextContent("16,0%");
    expect(v3).toHaveTextContent("Biên ở giá bán · chắc chắn");
    expect(within(v3).getByTestId("p2-vcmp-final")).toHaveTextContent("9,5%");
    expect(within(screen.getByTestId("p2-vcmp-v5")).getByTestId("p2-vcmp-final")).toHaveTextContent("chưa tính");
    expect(within(screen.getByTestId("p2-vcmp-v5")).getByTestId("p2-vcmp-final")).toHaveTextContent("theo tỉ lệ của sản phẩm");
  });

  it("is null-safe: without the field only today's margin shows", async () => {
    render(
      <ShopeeHostProvider host={{ api: fakeApi({ product: product() }), links: sellerLinks, shopKey: "shop-1", builder: fakeBuilder() }}>
        <ProductPageView id="BEP-S5" params={new URLSearchParams("tab=ng&cmp=1")} />
      </ShopeeHostProvider>,
    );
    const table = await screen.findByTestId("p2-vcmp");
    expect(within(table).queryByTestId("p2-vcmp-final")).toBeNull();
    expect(within(table).getByTestId("p2-vcmp-v3")).not.toHaveTextContent("Biên cuối");
  });
});
