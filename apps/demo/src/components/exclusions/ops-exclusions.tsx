"use client";

import { useCallback, useMemo } from "react";

import { readAuthSession } from "../../lib/supabase-auth";
import { createShopeeApi, opsShopeeBase } from "../../lib/shopee-analytics/client";
import { createBuilderApi, opsBuilderBase } from "../../lib/shopee-decisions/builder-api";
import { C, card } from "../ops/ops-shell";
import { EXCLUSIONS_LEDE, EXCLUSIONS_TITLE, ExclusionsPanel, type ExclusionPreview, type ExclusionsApi } from "./exclusions-panel";

/**
 * "Loại trừ sản phẩm" in Ops' Cài đặt shop (P92 B-1) and in "Xem như shop" (`readOnly`): the same
 * list the seller has. Vận hành+ adds, changes a reason and undoes (audited `exclusion_add` /
 * `exclusion_undo`); Xem and "Xem như shop" only read.
 */
export function OpsExclusions({
  shopId,
  canEdit,
  baseFetch,
  api,
  loadPreview,
  bare = false,
}: {
  readonly shopId: string;
  readonly canEdit: boolean;
  readonly baseFetch?: typeof fetch;
  readonly api?: ExclusionsApi;
  readonly loadPreview?: () => Promise<ExclusionPreview>;
  /** No card and title: "Xem như shop" draws its own. */
  readonly bare?: boolean;
}) {
  const token = readAuthSession()?.accessToken ?? "";
  const client = useMemo(
    () => api ?? createBuilderApi({ base: opsBuilderBase(shopId), token, fetchImpl: baseFetch }),
    [api, shopId, token, baseFetch],
  );
  const overview = useMemo(() => createShopeeApi({ base: opsShopeeBase(shopId), token, fetchImpl: baseFetch }), [shopId, token, baseFetch]);
  const preview = useCallback(async () => {
    const ov = await overview.overview({ period: "30d" });
    return { gmv: ov.kpi_strip.gmv.value, excludedGmv: ov.gmv.excluded_gmv ?? null };
  }, [overview]);
  const panel = <ExclusionsPanel api={client} loadPreview={loadPreview ?? preview} readOnly={!canEdit} />;
  if (bare) return panel;
  return (
    <div data-testid="ops-exclusions" id="loai-tru-san-pham" style={card}>
      <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>{EXCLUSIONS_TITLE}</h2>
      <span style={{ fontSize: 12, color: C.muted2 }}>{EXCLUSIONS_LEDE}</span>
      {panel}
    </div>
  );
}
