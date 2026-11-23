import { render } from "@testing-library/react";
import type { ReactElement } from "react";

import type { NavPlatform } from "../../../lib/app-navigation";
import type { ShopeeApi } from "../../../lib/shopee-analytics/client";
import { ShopeeHostProvider } from "../../../lib/shopee-analytics/context";
import { sellerLinks } from "../../../lib/shopee-analytics/links";

export function renderWith(ui: ReactElement, api: ShopeeApi, opts: { readOnly?: boolean; links?: typeof sellerLinks; platform?: NavPlatform } = {}) {
  return render(
    <ShopeeHostProvider host={{ api, links: opts.links ?? sellerLinks, shopKey: "shop-1", shopName: "Shop gia dụng", readOnly: opts.readOnly, platform: opts.platform }}>{ui}</ShopeeHostProvider>,
  );
}

export const params = (q = "") => new URLSearchParams(q);

/** No buyer data is ever drawn: nothing in the page says buyer. */
export function textOf(container: HTMLElement): string {
  return container.textContent ?? "";
}
