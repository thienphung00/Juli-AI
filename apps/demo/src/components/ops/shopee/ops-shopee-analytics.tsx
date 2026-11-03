"use client";

import { Suspense } from "react";

import type { OpsMe } from "../../../lib/ops/types";
import { OpsShopeeAnalyticsBody } from "../../shopee-analytics/hosts";
import { OpsHeader, OpsPage } from "../ops-shell";
import { PageTitle } from "./shopee-ui";

/**
 * Shopee · Phân tích shop (Juli Ops, step 9): the shop's Tổng quan, Phân tích, Sản phẩm and Xếp hạng,
 * the same screens the seller sees, read through the Ops API (`/v1/ops/shops/{id}/shopee/analytics/*`).
 * Reading only; the numbers are the seller's own.
 */
export function OpsShopeeAnalytics({ me, shopId, fetchImpl }: { readonly me: OpsMe; readonly shopId: string; readonly fetchImpl?: typeof fetch }) {
  return (
    <OpsPage>
      <OpsHeader me={me} shopId={shopId} />
      <main style={{ padding: "22px 28px 40px", display: "flex", flexDirection: "column", gap: 16 }}>
        <PageTitle active="phan-tich" shopId={shopId} title="Shopee · Phân tích shop" />
        <Suspense fallback={<p role="status">Đang tải…</p>}>
          <OpsShopeeAnalyticsBody fetchImpl={fetchImpl} shopId={shopId} />
        </Suspense>
      </main>
    </OpsPage>
  );
}
