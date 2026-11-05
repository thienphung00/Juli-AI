import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ShopeeHostProvider } from "../../../lib/shopee-analytics/context";
import { sellerLinks } from "../../../lib/shopee-analytics/links";
import { fakeApi, product } from "../../../lib/shopee-analytics/__tests__/fixtures";
import { fakeBuilder } from "../../../lib/shopee-decisions/__tests__/builder-fixtures";
import { ProductPageView } from "../product-page";

/** Sản phẩm · "So sánh phân loại" (P92 B-2, artboard SanPham `#cmp=1`): price and margin only, same endpoint as the builder. */

function page(qs: string, builder = fakeBuilder()) {
  render(
    <ShopeeHostProvider host={{ api: fakeApi({ product: product() }), links: sellerLinks, shopKey: "shop-1", builder }}>
      <ProductPageView id="BEP-S5" params={new URLSearchParams(qs)} />
    </ShopeeHostProvider>,
  );
  return builder;
}

describe("Sản phẩm: So sánh phân loại", () => {
  it("is collapsed, opens on click and reads the builder's variations endpoint", async () => {
    const builder = page("tab=ng");
    const expand = await screen.findByTestId("p2-expand");
    expect(within(expand).queryByTestId("p2-vcmp")).toBeNull();
    expect(builder.calls.filter((c) => c.name === "variations")).toHaveLength(0);
    await userEvent.setup().click(within(expand).getByRole("button", { name: /So sánh phân loại/ }));
    const table = await screen.findByTestId("p2-vcmp");
    expect(builder.calls.find((c) => c.name === "variations")!.args[0]).toBe("BEP-S5");
    expect(table).toHaveTextContent("Combo 5 hộp");
    expect(table).toHaveTextContent("27.800đ/đơn vị");
    expect(within(table).getByTestId("p2-vcmp-v10")).toHaveTextContent("chưa tính");
  });

  it("?cmp=1 opens it (artboard #cmp=1)", async () => {
    page("tab=ng&cmp=1");
    expect(await screen.findByTestId("p2-vcmp")).toBeInTheDocument();
  });

  it("is not shown while the builder API is off", async () => {
    render(
      <ShopeeHostProvider host={{ api: fakeApi({ product: product() }), links: sellerLinks, shopKey: "shop-1" }}>
        <ProductPageView id="BEP-S5" params={new URLSearchParams("tab=ng")} />
      </ShopeeHostProvider>,
    );
    await screen.findByTestId("sa-variations");
    await waitFor(() => expect(screen.queryByTestId("p2-expand")).toBeNull());
  });
});
