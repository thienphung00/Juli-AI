"use client";

import { useMemo, type ReactNode } from "react";

import { createShopInputsApi } from "../../lib/shop-inputs/api";
import type { ShopInputsApi } from "../../lib/shop-inputs/types";
import { AppPageHeader } from "../app-shell/page-header";
import { ShopInputsPanel } from "./shop-inputs-panel";

export const SHOP_INPUTS_TAB_LABEL = "Thông số shop";

/**
 * /settings › Thông số shop (P90 step 4, ADR-120 d.12): the shop's owner downloads the
 * pre-filled template, uploads it and applies it as a version. Signed-in sellers only.
 */
export function ShopInputsSettings({
  auth,
  shopName,
  tabs,
  api,
}: {
  readonly auth: { readonly token: string; readonly shopId: string; readonly fetchImpl?: typeof fetch };
  readonly shopName: string;
  readonly tabs?: ReactNode;
  /** Tests inject a fake; the page builds the real client. */
  readonly api?: ShopInputsApi;
}) {
  const client = useMemo(
    () =>
      api ??
      createShopInputsApi({
        base: "/v1/demo/shop-inputs",
        token: auth.token,
        shopId: auth.shopId,
        fetchImpl: auth.fetchImpl,
      }),
    [api, auth.token, auth.shopId, auth.fetchImpl],
  );
  return (
    <section aria-labelledby="shop-inputs-title" className="qd-page">
      <AppPageHeader
        eyebrow="Cài đặt"
        lede={
          <>
            Giá vốn, đóng gói, tồn kho và mục tiêu của <strong>{shopName}</strong>. Juli dùng các số này để tính giá sàn, biên lợi nhuận và đề xuất.
          </>
        }
        title="Giá vốn, tồn kho và mục tiêu"
        titleId="shop-inputs-title"
      />
      {tabs}
      <ShopInputsPanel api={client} />
    </section>
  );
}
