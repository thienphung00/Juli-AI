"use client";

import { Suspense } from "react";

import type { OpsMe } from "../../../lib/ops/types";
import { OpsShopeeRecoBody } from "../../shopee-decisions/hosts";
import { useQueryParams } from "../../shopee-analytics/hosts";
import { OpsHeader, OpsPage } from "../ops-shell";
import { PageTitle } from "./shopee-ui";

/**
 * Shopee · Đề xuất (Juli Ops, step 9b): the shop's recommendation cards - drafts included - with
 * the staff actions (generate, publish to the shop, withdraw, re-run stale cards, "Đã làm" by
 * staff). The same card screens the seller sees, read through `/v1/ops/shops/{id}/shopee/recommendations`;
 * what-if here records nothing. The seller's decision (duyệt / yêu cầu chỉnh / bỏ qua) stays the seller's.
 */
function Body({ shopId, fetchImpl }: { readonly shopId: string; readonly fetchImpl?: typeof fetch }) {
  const params = useQueryParams();
  return <OpsShopeeRecoBody fetchImpl={fetchImpl} params={params} shopId={shopId} />;
}

export function OpsShopeeReco({ me, shopId, fetchImpl }: { readonly me: OpsMe; readonly shopId: string; readonly fetchImpl?: typeof fetch }) {
  return (
    <OpsPage>
      <OpsHeader me={me} shopId={shopId} />
      <main style={{ padding: "22px 28px 40px", display: "flex", flexDirection: "column", gap: 16 }}>
        <PageTitle active="de-xuat" shopId={shopId} title="Shopee · Đề xuất" />
        <Suspense fallback={<p role="status">Đang tải…</p>}>
          <Body fetchImpl={fetchImpl} shopId={shopId} />
        </Suspense>
      </main>
    </OpsPage>
  );
}
