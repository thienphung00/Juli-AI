"use client";

import { METRIC_DEFS, type MetricId } from "../../lib/metrics/registry.generated";
import { SPLIT_CHANNEL_ORDER, splitChannelName } from "../../lib/metrics/split";
import { inMode, type ValueMode } from "../../lib/metrics";
import { DASH } from "../../lib/shopee-analytics/format";
import type { ProfitSplit, SplitColumn, SplitRow } from "../../lib/shopee-analytics/types";
import { mil } from "./tong-quan";

/**
 * D5 (Track P wire): Lợi nhuận theo kênh — Organic / Quảng cáo / TTLK of the shop or one product, with the
 * combined Ưu đãi column and a total row that adds up (the shop-level remainder no product owns is its own row).
 * Column names come from the registry; labels and numbers only, no captions.
 */

const COLUMN_ID: Readonly<Record<SplitColumn, MetricId>> = {
  gmv: "gmv",
  orders: "orders",
  net_revenue: "net_revenue",
  cost_offers: "cost_offers",
  contribution: "contribution",
  cost_ads: "cost_ads",
  cost_affiliate: "cost_affiliate",
  profit: "profit",
};

/** The row the shop level adds for what no product owns (ads of no product, other marketing). */
const UNATTRIBUTED_LABEL = "Chưa gán sản phẩm";

export function ProfitSplitTable({ split, days, mode }: { readonly split: ProfitSplit; readonly days: number; readonly mode: ValueMode }) {
  // owner #51: Lợi nhuận đóng góp is export-only; the screen keeps the other columns (the total row still adds up)
  const cols = split.columns.filter((c) => c !== "contribution");
  const cell = (row: SplitRow, c: SplitColumn): string => {
    const v = row[c];
    if (v === null || v === undefined) return DASH;
    const x = inMode(v, days, mode);
    return c === "orders" ? (x === null ? DASH : String(Math.round(x))) : mil(x);
  };
  const line = (key: string, label: string, row: SplitRow) => (
    <div className={`sa-tq__row${key === "total" ? " sa-tq__row--total" : ""}`} data-testid={`sa-split-${key}`} key={key} role="row">
      <span className="sa-tq__name" role="cell">
        {label}
      </span>
      {cols.map((c) => (
        <span className="sa-tq__cell" data-testid={`sa-split-${key}-${c}`} key={c} role="cell">
          {cell(row, c)}
        </span>
      ))}
    </div>
  );
  return (
    <section className="sa-tq__table sa-tq__split" data-testid="sa-split" role="table">
      <div className="sa-tq__row sa-tq__row--head" role="row">
        <span role="columnheader">Kênh</span>
        {cols.map((c) => (
          <span key={c} role="columnheader">
            {METRIC_DEFS[COLUMN_ID[c]].label_vi}
          </span>
        ))}
      </div>
      {SPLIT_CHANNEL_ORDER.map((ch) => line(ch, splitChannelName(ch), split.rows[ch]))}
      {split.unattributed ? line("unattributed", UNATTRIBUTED_LABEL, split.unattributed) : null}
      {line("total", "Tổng", split.total)}
    </section>
  );
}
