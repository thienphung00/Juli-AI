"use client";

import Link from "next/link";

import { inMode, type ValueMode } from "../../lib/metrics";
import { fmt } from "../../lib/shopee-analytics/format";
import { money, signedMoney } from "../../lib/shopee-analytics/metric-view";
import type { KolSection as KolSectionData, KolSectionRow } from "../../lib/shopee-analytics/types";
import { Shift } from "../metrics/metric-chip";

/**
 * Phân tích › Tiếp thị liên kết theo KOL (board B). Presentational: the data and the two row links
 * come from the screen's host, so the seller app, Ops and the reviewer's sample shop render the same.
 */
export function KolSection({
  data,
  mode,
  decisionsHref,
  builderHref,
}: {
  readonly data: KolSectionData;
  readonly mode: ValueMode;
  readonly decisionsHref: (row: KolSectionRow) => string;
  readonly builderHref: (row: KolSectionRow) => string;
}) {
  const t = data.totals;
  const sum = (v: number | null) => money(inMode(v, data.days, mode));
  const count = (v: number | null) => {
    const x = inMode(v, data.days, mode);
    return fmt(x, mode === "avg" && (x ?? 0) < 100 ? 1 : 0);
  };
  return (
    <section aria-label="Tiếp thị liên kết theo KOL" className="sa-card jp-section" data-testid="pt-kol">
      <div className="jp-section__head">
        <h2 className="sa-h2">Tiếp thị liên kết theo KOL</h2>
        <div className="jp-kol-totals" data-testid="pt-kol-totals">
          <span>
            <span className="jp-dim">Lượt nhấp</span> <b>{count(t.clicks)}</b>
          </span>
          <span>
            <span className="jp-dim">Đơn</span> <b>{count(t.orders)}</b>
          </span>
          <span>
            <span className="jp-dim">GMV</span> <b>{sum(t.gmv)}</b>
          </span>
          <span>
            <span className="jp-dim">Video KOL</span> {sum(t.video_gmv)}
          </span>
          <span>
            <span className="jp-dim">Live KOL</span> {sum(t.live_gmv)}
          </span>
          <span>
            <span className="jp-dim">Khác</span> {sum(t.other_gmv)}
          </span>
        </div>
      </div>
      <div className="jp-grid jp-grid--kol jp-grid--head">
        <span>KOL</span>
        <span>Kênh</span>
        <span>Lượt nhấp</span>
        <span>Đơn</span>
        <span>GMV</span>
        <span>Hoa hồng</span>
        <span>Lợi nhuận</span>
        <span>Thay đổi</span>
        <span />
      </div>
      {data.rows.map((r) => {
        const good = (r.profit ?? 0) >= 0;
        return (
          <div className="jp-grid jp-grid--kol" data-testid={`pt-kol-${r.kol_key}-${r.item_id}`} key={`${r.kol_key}|${r.item_id}|${r.channel}`}>
            <span className="jp-who">
              <span aria-hidden="true" className="jp-av" />
              <span className="jp-who__text">
                <b>{r.handle}</b>
                <span className="jp-dim jp-clip">{r.product_name}</span>
              </span>
            </span>
            <span>{r.channel_label ?? r.channel}</span>
            <span>{count(r.clicks)}</span>
            <span>{count(r.orders)}</span>
            <span>{sum(r.gmv)}</span>
            <span>{sum(r.commission)}</span>
            <span className={good ? "jp-up" : "jp-down"}>{signedMoney(inMode(r.profit, data.days, mode))}</span>
            <Shift pct={r.change} />
            {r.cards > 0 ? (
              <Link className="jp-cta jp-cta--on" href={decisionsHref(r)}>
                Đề xuất ({r.cards}) ›
              </Link>
            ) : (
              <Link className="jp-cta" href={builderHref(r)}>
                Tự tạo ›
              </Link>
            )}
          </div>
        );
      })}
    </section>
  );
}
