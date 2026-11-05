"use client";

import { useCallback, useMemo, type ReactNode } from "react";

import { createShopeeApi, DEMO_SHOPEE_BASE } from "../../lib/shopee-analytics/client";
import { DEMO_BUILDER_BASE, createBuilderApi } from "../../lib/shopee-decisions/builder-api";
import { AppPageHeader } from "../app-shell/page-header";
import { EXCLUSIONS_LEDE, EXCLUSIONS_TITLE, ExclusionsPanel, type ExclusionsApi, type ExclusionPreview } from "./exclusions-panel";

export const EXCLUSIONS_TAB_LABEL = EXCLUSIONS_TITLE;

/** `/settings › Loại trừ sản phẩm` (P92 B-1): the seller's own list of listings kept out of the optimisation. */
export function ExclusionsSettings({
  auth,
  shopName,
  tabs,
  api,
  loadPreview,
}: {
  readonly auth: { readonly token: string; readonly shopId: string; readonly fetchImpl?: typeof fetch };
  readonly shopName: string;
  readonly tabs?: ReactNode;
  /** Tests inject fakes; the page builds the real clients. */
  readonly api?: ExclusionsApi;
  readonly loadPreview?: () => Promise<ExclusionPreview>;
}) {
  const client = useMemo(
    () => api ?? createBuilderApi({ base: DEMO_BUILDER_BASE, token: auth.token, shopId: auth.shopId, fetchImpl: auth.fetchImpl }),
    [api, auth.token, auth.shopId, auth.fetchImpl],
  );
  const overview = useMemo(
    () => createShopeeApi({ base: DEMO_SHOPEE_BASE, token: auth.token, shopId: auth.shopId, fetchImpl: auth.fetchImpl }),
    [auth.token, auth.shopId, auth.fetchImpl],
  );
  const preview = useCallback(
    async () => {
      const ov = await overview.overview({ period: "30d" });
      return { gmv: ov.kpi_strip.gmv.value, excludedGmv: ov.gmv.excluded_gmv ?? null };
    },
    [overview],
  );
  return (
    <section aria-labelledby="exclusions-title" className="qd-page">
      <AppPageHeader
        eyebrow="Cài đặt › Loại trừ sản phẩm"
        lede={EXCLUSIONS_LEDE}
        title={
          <>
            {EXCLUSIONS_TITLE} <span className="sx-shop">Shopee · {shopName}</span>
          </>
        }
        titleId="exclusions-title"
      />
      {tabs}
      <ExclusionsPanel api={client} loadPreview={loadPreview ?? preview} />
    </section>
  );
}
