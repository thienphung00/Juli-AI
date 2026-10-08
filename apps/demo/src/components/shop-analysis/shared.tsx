import type { ReactNode } from "react";

import {
  addToCartRate,
  aov,
  ctor,
  ctr,
  FACTOR_LABELS,
  itemsPerOrder,
  NOT_PROVIDED,
  refundShare,
} from "../../lib/shop-analysis/derive";
import type {
  ConfidenceLabel,
  Counts,
  FunnelComparison,
} from "../../lib/shop-analysis/types";
import { change, money, num, pct, signedMoney } from "../../lib/vn-format";

export function ChangeChip({
  prior,
  last,
}: {
  readonly prior: number | null | undefined;
  readonly last: number | null | undefined;
}) {
  const delta = change(prior, last);
  return <span className={`change-chip change-chip--${delta.tone}`}>{delta.text}</span>;
}

const CONFIDENCE_CLASS: Record<ConfidenceLabel, string> = {
  "Rõ": "badge badge-success",
  "Tham khảo": "badge badge-warning",
  "Chưa đủ dữ liệu": "badge badge-neutral",
};

export function ConfidenceBadge({ label }: { readonly label: ConfidenceLabel | null | undefined }) {
  if (!label) return <span className="text-muted">—</span>;
  return <span className={CONFIDENCE_CLASS[label] ?? "badge badge-neutral"}>{label}</span>;
}

export function TableWrap({ children, label }: { readonly children: ReactNode; readonly label?: string }) {
  return (
    <div className="analysis-table-wrap" role={label ? "region" : undefined} aria-label={label} tabIndex={label ? 0 : undefined}>
      {children}
    </div>
  );
}

export function Note({ children }: { readonly children: ReactNode }) {
  return <p className="analysis-note">{children}</p>;
}

/** Backend `render._contrib_line`: the four-factor split of the GMV change. */
export function ContributionLine({ comparison }: { readonly comparison: FunnelComparison }) {
  const factors = comparison.factors ?? [];
  if (factors.length === 0 || factors[0].contribution === null) {
    return (
      <p className="analysis-contrib analysis-note">
        Không tách được thay đổi GMV thành bốn yếu tố (một kỳ không có đơn).
      </p>
    );
  }
  const gmvChange = comparison.last.gmv - comparison.prior.gmv;
  return (
    <div className="analysis-contrib">
      <span className="analysis-note">Góp vào thay đổi GMV/ngày ({signedMoney(gmvChange)}):</span>
      {factors.map((factor) => (
        <span key={factor.factor} className="analysis-contrib__item">
          {FACTOR_LABELS[factor.factor]}: <b>{signedMoney(factor.contribution)}</b>{" "}
          <ConfidenceBadge label={factor.confidence} />
        </span>
      ))}
    </div>
  );
}

type Kind = "num" | "pct" | "money" | "dec";

const KPI_ROWS: ReadonlyArray<{
  label: string;
  kind: Kind;
  read: (c: Counts) => number | null;
  extra?: boolean;
  confidence?: (c: FunnelComparison) => ConfidenceLabel | null | undefined;
}> = [
  { label: "Lượt hiển thị sản phẩm", kind: "num", read: (c) => c.impressions, confidence: (c) => c.factors?.[0]?.confidence },
  { label: "CTR (Tỷ lệ nhấp)", kind: "pct", read: ctr, confidence: (c) => c.factors?.[1]?.confidence },
  { label: "Lượt nhấp vào sản phẩm", kind: "num", read: (c) => c.clicks },
  { label: "Tỷ lệ thêm vào giỏ hàng", kind: "pct", read: addToCartRate, confidence: (c) => c.add_to_cart_rate_confidence },
  { label: "Số lượt thêm vào giỏ hàng", kind: "num", read: (c) => c.add_to_cart },
  { label: "Đơn hàng SKU", kind: "num", read: (c) => c.sku_orders },
  { label: "CTOR", kind: "pct", read: ctor, confidence: (c) => c.factors?.[2]?.confidence },
  { label: "AOV (SKU)", kind: "money", read: aov, confidence: (c) => c.factors?.[3]?.confidence },
  { label: "GMV", kind: "money", read: (c) => c.gmv, confidence: (c) => c.gmv_confidence },
  { label: "Số món trên đơn", kind: "dec", read: itemsPerOrder, extra: true },
  { label: "Hoàn tiền ÷ GMV", kind: "pct", read: refundShare, extra: true },
];

export function formatKind(kind: Kind, value: number | null | undefined): string {
  if (kind === "pct") return pct(value);
  if (kind === "money") return money(value);
  if (kind === "dec") return num(value, 2);
  return num(value);
}

/** Backend `render._kpi_table`: 30 ngày trước vs 30 ngày gần đây. */
export function KpiTable({
  comparison,
  withExtras = true,
  label,
}: {
  readonly comparison: FunnelComparison;
  readonly withExtras?: boolean;
  readonly label: string;
}) {
  return (
    <TableWrap label={label}>
      <table className="analysis-table">
        <thead>
          <tr>
            <th scope="col">Chỉ số (trung bình mỗi ngày)</th>
            <th scope="col">30 ngày trước</th>
            <th scope="col">30 ngày gần đây</th>
            <th scope="col">Thay đổi</th>
            <th scope="col">Mức tin cậy</th>
          </tr>
        </thead>
        <tbody>
          {KPI_ROWS.filter((row) => withExtras || !row.extra).map((row) => {
            const prior = row.read(comparison.prior);
            const last = row.read(comparison.last);
            if (prior === null && last === null) {
              return (
                <tr key={row.label}>
                  <th scope="row">{row.label}</th>
                  <td colSpan={4}>{NOT_PROVIDED}</td>
                </tr>
              );
            }
            return (
              <tr key={row.label}>
                <th scope="row">{row.label}</th>
                <td>{formatKind(row.kind, prior)}</td>
                <td>{formatKind(row.kind, last)}</td>
                <td>
                  <ChangeChip prior={prior} last={last} />
                </td>
                <td>
                  <ConfidenceBadge label={row.confidence?.(comparison)} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </TableWrap>
  );
}

export function Verdict({ headline, lookNext }: { readonly headline: string; readonly lookNext: string }) {
  return (
    <div className="analysis-verdict">
      <p className="analysis-verdict__headline">{headline}</p>
      <p>
        <b>Cần xem tiếp:</b> {lookNext}
      </p>
    </div>
  );
}
