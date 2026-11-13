"use client";

import { dayMonth } from "../../lib/shopee-analytics/format";
import type { DataMissing } from "../../lib/shopee-decisions/plan-types";

/** Kế hoạch: no stored daily rows for the window. A short label and the window / missing-day counts, nothing else. */
export function DataMissingNotice({ missing }: { readonly missing: DataMissing }) {
  const md = missing.missing_days;
  const n = Array.isArray(md) ? md.length : typeof md === "number" ? md : null;
  return (
    <div className="sd-check sd-check--warn" data-testid="kh-data-missing" role="alert">
      <span>
        <b>Chưa có số liệu</b>
        <span className="sd-check__line" data-testid="kh-dm-detail">
          {missing.window ? `Kỳ ${dayMonth(missing.window.from)}–${dayMonth(missing.window.to)}` : "—"}
          {n !== null ? ` · thiếu ${n} ngày` : ""}
          {missing.first_missing ? `, từ ${dayMonth(missing.first_missing)}` : ""}
        </span>
      </span>
    </div>
  );
}
