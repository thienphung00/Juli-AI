"use client";

import { splitRows } from "../../lib/shopee-decisions/plan-model";
import type { PlanSplit } from "../../lib/shopee-decisions/plan-types";

/** D5: the plan's Δ per channel (Organic / Quảng cáo / TTLK) from `split.delta_p50`, with a total row that adds up. Labels and numbers only. */
export function PlanSplitTable({ split, testId = "kh-split" }: { readonly split: PlanSplit; readonly testId?: string }) {
  const rows = splitRows(split);
  if (rows.length === 0) return null;
  return (
    <div className="kh-agg__table" data-testid={testId}>
      <div className="kh-agg__row kh-agg__row--head">
        <span>Kênh</span>
        <span>Δ lợi nhuận</span>
        <span>Δ GMV · Δ đơn</span>
      </div>
      {rows.map((r) => (
        <div className="kh-agg__row" data-testid={`${testId}-${r.key}`} key={r.key}>
          <span>{r.key === "total" ? <b>{r.label}</b> : r.label}</span>
          <span data-testid={`${testId}-${r.key}-profit`}>{r.dprofit}</span>
          <span>
            {r.dgmv} · {r.dorders}
          </span>
        </div>
      ))}
    </div>
  );
}
