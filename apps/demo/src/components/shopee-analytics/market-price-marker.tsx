"use client";

import { DASH, pp, vnd } from "../../lib/shopee-analytics/format";
import { MARKET_REASON_COPY, useMarketPrice, type MarketPosition, type MarketScope } from "../../lib/shopee-analytics/market-price";
import { MarketBar } from "./market-price-block";

const COPY: Readonly<Record<MarketPosition, string>> = {
  below_p25: "dưới khoảng phổ biến",
  within: "trong khoảng phổ biến",
  above_p75: "trên khoảng phổ biến",
};

/**
 * Builder price / discount / flash-sale panel: a live marker of the drafted price inside the
 * market's P25–P75 range (per unit). Uses the lightweight `market-range` call. Export only: the
 * builder mounts it, e.g. `<MarketPriceMarker scope={{ base, token, shopId }} itemId={id} variationId={v} draftPrice={price} />`.
 */
export function MarketPriceMarker({
  scope,
  itemId,
  variationId,
  draftPrice,
}: {
  readonly scope: MarketScope | null;
  readonly itemId: string;
  readonly variationId?: string;
  readonly draftPrice: number | null;
}) {
  const state = useMarketPrice(scope, itemId, { range: true, variationId, price: draftPrice });
  if (state.status === "idle" || state.status === "loading") return null;
  if (state.status === "error") return null;
  const d = state.data;
  if (!d.available || !d.market) {
    return (
      <p className="sa-hint" data-testid="market-marker-absent">
        {d.reason ? MARKET_REASON_COPY[d.reason] : "Chưa có giá thị trường."}
      </p>
    );
  }
  const m = d.marker;
  return (
    <div data-testid="market-marker">
      <MarketBar median={d.market.median} own={m?.price_per_unit ?? null} p25={d.market.p25} p75={d.market.p75} />
      <p className="sa-hint">
        Giá thị trường {d.unit?.per_label ?? "giá / đơn vị"}: {vnd(d.market.p25)} – {vnd(d.market.p75)} (trung vị {vnd(d.market.median)})
        {d.stale ? " · cũ" : ""}
        {m && m.price_per_unit !== null ? ` · bản nháp ${vnd(m.price_per_unit)}${m.position ? `, ${COPY[m.position]}` : ""}${m.vs_median_pct !== null ? ` (${m.vs_median_pct > 0 ? "+" : ""}${pp(m.vs_median_pct)} so với trung vị)` : ""}` : draftPrice ? ` · bản nháp ${DASH}` : ""}
      </p>
    </div>
  );
}
