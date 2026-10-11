"use client";

import { fmtFreshness } from "../../lib/ops/format";
import type { Freshness } from "../../lib/ops/types";
import { C } from "./ops-shell";

/**
 * D27.1: "● Số liệu đến hết DD/MM · cập nhật lúc HH:MM hôm nay · Làm mới"
 * (artboard OpsSimulate.dc.html header). Amber "Đang tính lại…" while a refresh
 * runs. "Làm mới" is hidden for Xem (the API answers 403). No line at all when
 * the backend sends no `generated_at`.
 */
export function FreshnessLine({
  data,
  refreshing,
  canRefresh,
  onRefresh,
  error,
}: {
  readonly data: Freshness | null | undefined;
  readonly refreshing: boolean;
  readonly canRefresh: boolean;
  readonly onRefresh: () => void;
  readonly error?: string | null;
}) {
  const text = fmtFreshness(data);
  if (!text && !refreshing) return null;
  return (
    <div data-testid="ops-freshness" role="status" style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 13, color: C.body, flexWrap: "wrap" }}>
      <span aria-hidden="true" style={{ width: 8, height: 8, borderRadius: 999, background: refreshing ? "#e0a100" : "#2f9e5b" }} />
      <span>{refreshing ? "Đang tính lại…" : text}</span>
      {!refreshing && canRefresh ? (
        <button
          onClick={onRefresh}
          style={{ font: "inherit", fontSize: 13, fontWeight: 600, color: C.pink, background: "transparent", border: 0, minHeight: 32, cursor: "pointer", padding: 0 }}
          type="button"
        >
          Làm mới
        </button>
      ) : null}
      {error && !refreshing ? <span style={{ color: C.red }}>{error}</span> : null}
    </div>
  );
}
