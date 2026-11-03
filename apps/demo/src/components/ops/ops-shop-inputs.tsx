"use client";

import { useMemo } from "react";

import { createShopInputsApi } from "../../lib/shop-inputs/api";
import type { ShopInputsApi } from "../../lib/shop-inputs/types";
import { readAuthSession } from "../../lib/supabase-auth";
import { ShopInputsPanel } from "../shop-inputs/shop-inputs-panel";
import { C, card } from "./ops-shell";

/**
 * "Thông số shop" in Cài đặt shop (P90 step 4): the Juli team fills a shop's cost,
 * packaging, stock and targets in from the same template the seller uses, as the team.
 * Vận hành+ uploads and applies (audited); Xem downloads the template and reads versions.
 */
export function OpsShopInputs({
  shopId,
  canEdit,
  baseFetch,
  api,
}: {
  readonly shopId: string;
  readonly canEdit: boolean;
  readonly baseFetch?: typeof fetch;
  readonly api?: ShopInputsApi;
}) {
  const client = useMemo(
    () =>
      api ??
      createShopInputsApi({
        base: `/v1/ops/shops/${encodeURIComponent(shopId)}/inputs`,
        token: readAuthSession()?.accessToken ?? "",
        fetchImpl: baseFetch,
      }),
    [api, shopId, baseFetch],
  );
  return (
    <div data-testid="ops-shop-inputs" style={card}>
      <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>Thông số shop</h2>
      <span style={{ fontSize: 12, color: C.muted2 }}>
        Giá vốn, đóng gói, tồn kho và mục tiêu theo tháng. Mỗi lần áp dụng là một phiên bản ghi tên đội ngũ, lý do và tệp, khôi phục được, và được ghi nhật ký.
      </span>
      <ShopInputsPanel api={client} canEdit={canEdit} writerLabel="Đội ngũ Juli" />
    </div>
  );
}
