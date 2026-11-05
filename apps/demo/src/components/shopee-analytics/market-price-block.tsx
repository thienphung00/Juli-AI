"use client";

import type { CSSProperties } from "react";

import { count, DASH, pp, vnd } from "../../lib/shopee-analytics/format";
import {
  barPercent,
  MARKET_REASON_COPY,
  useMarketPrice,
  type MarketPosition,
  type MarketPrice,
  type MarketScope,
} from "../../lib/shopee-analytics/market-price";
import { Section, TextChip } from "./ui";

/**
 * P92 B-10 "Giá thị trường" (Sản phẩm, Demo and Ops): the product's price per unit against the
 * page-1 search listings of its main keyword, pack-normalised. Absent data says why and shows
 * no number; data older than the server's limit shows its date and a "cũ" chip.
 */

const POSITION_COPY: Readonly<Record<MarketPosition, string>> = {
  below_p25: "Thấp hơn 25% sản phẩm tương tự",
  within: "Nằm trong khoảng giá phổ biến (P25–P75)",
  above_p75: "Cao hơn 75% sản phẩm tương tự",
};

const dateOf = (iso: string | null | undefined): string => {
  if (!iso) return DASH;
  const [y, m, d] = iso.slice(0, 10).split("-");
  return y && m && d ? `${d}/${m}/${y}` : iso;
};

const barStyle: CSSProperties = { position: "relative", height: 10, borderRadius: 5, background: "rgba(128,128,128,0.18)", margin: "10px 0 4px" };

/** The P25–P75 bar with the median tick and the own / drafted price marker. */
export function MarketBar({ p25, median, p75, own }: { readonly p25: number | null; readonly median: number | null; readonly p75: number | null; readonly own: number | null }) {
  if (p25 === null || p75 === null) return null;
  const span = p75 - p25;
  const lo = p25 - span * 0.5;
  const hi = p75 + span * 0.5;
  const a = barPercent(p25, lo, hi);
  const b = barPercent(p75, lo, hi);
  const m = barPercent(median, lo, hi);
  const o = barPercent(own, lo, hi);
  if (a === null || b === null) return null;
  return (
    <div aria-hidden="true" data-testid="market-bar" style={barStyle}>
      <span style={{ position: "absolute", left: `${a}%`, width: `${b - a}%`, top: 0, bottom: 0, borderRadius: 5, background: "rgba(80,140,255,0.4)" }} />
      {m !== null ? <span style={{ position: "absolute", left: `${m}%`, top: -2, bottom: -2, width: 2, background: "currentColor", opacity: 0.6 }} /> : null}
      {o !== null ? (
        <span data-testid="market-bar-own" style={{ position: "absolute", left: `calc(${o}% - 5px)`, top: -3, width: 12, height: 16, borderRadius: 4, background: "#e0457b" }} />
      ) : null}
    </div>
  );
}

export function MarketPriceView({ data }: { readonly data: MarketPrice }) {
  if (!data.available || !data.market) {
    const copy = data.reason ? MARKET_REASON_COPY[data.reason] : "Chưa có dữ liệu giá thị trường.";
    return (
      <p className="sa-hint" data-testid="market-absent" role="status">
        {copy}
      </p>
    );
  }
  const { market, own, unit } = data;
  const per = unit?.per_label ?? "giá / đơn vị";
  const closest = (data.closest ?? []).slice(0, 5);
  return (
    <div data-testid="market-ready">
      <div className="sa-chips" style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        {data.keyword ? <span className="sa-chip sa-chip--outline">Từ khoá: {data.keyword}</span> : null}
        <span className="sa-chip sa-chip--outline">Thu thập {dateOf(data.collected_on)}</span>
        {data.stale ? <TextChip tone="warn">cũ{data.age_days !== null && data.age_days !== undefined ? ` · ${data.age_days} ngày` : ""}</TextChip> : null}
        {market.n_similar !== null ? <span className="sa-chip sa-chip--outline">{count(market.n_similar)} sản phẩm tương tự</span> : null}
      </div>
      <p style={{ margin: "12px 0 0" }}>
        <strong data-testid="market-own">{vnd(own?.price_per_unit)}</strong> <span className="sa-hint">{per} của bạn</span> · trung vị thị trường <strong data-testid="market-median">{vnd(market.median)}</strong>
        {market.own_vs_median_pct !== null ? <span> ({market.own_vs_median_pct > 0 ? "+" : ""}{pp(market.own_vs_median_pct)} so với trung vị)</span> : null}
      </p>
      <MarketBar median={market.median} own={own?.price_per_unit ?? null} p25={market.p25} p75={market.p75} />
      <p className="sa-hint" data-testid="market-range">
        P25 {vnd(market.p25)} – P75 {vnd(market.p75)} ({per}){market.position ? ` · ${POSITION_COPY[market.position]}` : ""}
      </p>
      {closest.length > 0 ? (
        <table data-testid="market-closest" style={{ width: "100%", borderCollapse: "collapse", marginTop: 8 }}>
          <caption className="sa-hint" style={{ textAlign: "left" }}>
            {closest.length} sản phẩm gần nhất
          </caption>
          <thead>
            <tr style={{ textAlign: "left" }}>
              <th>Sản phẩm</th>
              <th>Shop</th>
              <th>Giá</th>
              <th>{per}</th>
              <th>Đã bán/tháng</th>
            </tr>
          </thead>
          <tbody>
            {closest.map((l) => (
              <tr key={l.item_id}>
                <td>{l.name}</td>
                <td>{l.shop_name ?? DASH}</td>
                <td>{l.price_min !== null && l.price_max !== null && l.price_min !== l.price_max ? `${vnd(l.price_min)} – ${vnd(l.price_max)}` : vnd(l.price)}</td>
                <td>{vnd(l.price_per_unit)}</td>
                <td>{l.sold_monthly === null ? DASH : count(l.sold_monthly)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {data.note ? <p className="sa-hint">{data.note}</p> : null}
    </div>
  );
}

export function MarketPriceBlock({ scope, itemId }: { readonly scope: MarketScope | null; readonly itemId: string }) {
  const state = useMarketPrice(scope, itemId);
  return (
    <Section hint="Giá trên một đơn vị (hộp, cái, ml…) so với trang 1 kết quả tìm kiếm Shopee" testId="sa-market-price" title="Giá thị trường">
      {state.status === "loading" ? (
        <p className="sa-loading" role="status">
          Đang tải giá thị trường…
        </p>
      ) : null}
      {state.status === "error" ? (
        <p className="sd-error" role="alert">
          Chưa tải được giá thị trường.
        </p>
      ) : null}
      {state.status === "ready" ? <MarketPriceView data={state.data} /> : null}
    </Section>
  );
}
