import { ConfidenceBadge } from "../shop-analysis/shared";
import { formatMetric, METRIC_NAMES } from "../../lib/phan-tich/model";
import type { RankingPayload, RankingRow, RowKind } from "../../lib/phan-tich/types";
import { signedMoney } from "../../lib/vn-format";

/**
 * The ranked table under the funnels (ADR-109 d.5): which rows moved the
 * clicked metric, by the GMV/day their change carried. "Kéo xuống" lists the
 * largest negative first, "Kéo lên" the largest positive; the closing rows
 * (ít đơn / các … khác / thay đổi cơ cấu, plus the rows of the other
 * direction folded into one line) make the table add up to the cell's GMV
 * figure, printed as "Tổng = …".
 */

export type Direction = "down" | "up";

export type RankingState =
  | { readonly status: "loading" }
  | { readonly status: "empty" }
  | { readonly status: "error" }
  | { readonly status: "ready"; readonly payload: RankingPayload };

const SUBJECT: Record<RowKind, { title: string; column: string; noun: string }> = {
  product: { title: "SKU", column: "Mã · Sản phẩm", noun: "sản phẩm" },
  live_session: { title: "Phiên LIVE", column: "Phiên LIVE · ngày", noun: "phiên LIVE" },
  video: { title: "Video", column: "Video", noun: "video" },
};

export function rankingTitle(kind: RowKind, metricName: string, direction: Direction): string {
  return `${SUBJECT[kind].title} kéo ${metricName} ${direction === "down" ? "xuống" : "lên"}`;
}

export interface DisplayedClosing {
  readonly key: string;
  readonly label: string;
  readonly gmv: number;
}

/** The closing rows shown under a direction's list; listed + these = the factor. */
export function closingRows(payload: RankingPayload, direction: Direction): DisplayedClosing[] {
  const other = direction === "down" ? payload.up : payload.down;
  const noun = SUBJECT[payload.row_kind].noun;
  const rows: DisplayedClosing[] = [];
  if (other.length > 0) {
    rows.push({
      key: "other",
      label: `${other.length} ${noun} kéo ${direction === "down" ? "lên" : "xuống"} (xem ${direction === "down" ? "Kéo lên" : "Kéo xuống"})`,
      gmv: other.reduce((sum, r) => sum + r.gmv_per_day, 0),
    });
  }
  const { few, others, mix } = payload.closing;
  if ((few.count ?? 0) > 0 || few.gmv_per_day !== 0) rows.push({ key: "few", label: few.label, gmv: few.gmv_per_day });
  if ((others.count ?? 0) > 0 || others.gmv_per_day !== 0) {
    rows.push({ key: "others", label: `${others.label}${others.count ? ` (${others.count})` : ""}`, gmv: others.gmv_per_day });
  }
  rows.push({ key: "mix", label: mix.label, gmv: mix.gmv_per_day });
  return rows;
}

export function rowLabel(row: RankingRow, kind: RowKind): { code: string | null; name: string } {
  return kind === "product" ? { code: row.id, name: row.name } : { code: null, name: row.name };
}

interface RankingTableProps {
  readonly payload: RankingPayload;
  readonly direction: Direction;
  readonly selectedRowId: string | null;
  readonly onSelectRow: (row: RankingRow) => void;
}

export function RankingTable({ payload, direction, selectedRowId, onSelectRow }: RankingTableProps) {
  const rows = direction === "down" ? payload.down : payload.up;
  const metric = payload.metric;
  const subject = SUBJECT[payload.row_kind];
  const scale = Math.max(1, ...[...payload.down, ...payload.up].map((r) => Math.abs(r.gmv_per_day)));
  const closing = closingRows(payload, direction);
  const metricHeader = `${METRIC_NAMES[metric]}${metric === "impressions" ? "/ngày" : ""} · trước → nay`;

  return (
    <div className="pt-table-wrap" role="region" aria-label={rankingTitle(payload.row_kind, METRIC_NAMES[metric], direction)} tabIndex={0}>
      <table className="pt-table" data-testid="ranking-table">
        <thead>
          <tr>
            <th scope="col">{subject.column}</th>
            <th scope="col">{metricHeader}</th>
            <th scope="col">
              <span className="juli-sr-only">Mức kéo</span>
            </th>
            <th scope="col">GMV/ngày</th>
            <th scope="col">Mức tin cậy</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td className="pt-table__none" colSpan={5}>
                Không có {subject.noun} nào kéo {METRIC_NAMES[metric]} {direction === "down" ? "xuống" : "lên"} đủ để liệt kê.
              </td>
            </tr>
          ) : (
            rows.map((row) => {
              const label = rowLabel(row, payload.row_kind);
              const selected = row.id === selectedRowId;
              const width = `${Math.max(4, (Math.abs(row.gmv_per_day) / scale) * 100)}%`;
              return (
                <tr className={selected ? "pt-row pt-row--selected" : "pt-row"} data-row-id={row.id} key={row.id}>
                  <th scope="row">
                    <button
                      aria-pressed={selected}
                      className="pt-row__button"
                      onClick={() => onSelectRow(row)}
                      type="button"
                    >
                      {label.code ? <b className="pt-row__code">{label.code}</b> : null}
                      <span className="pt-row__name">{label.name}</span>
                    </button>
                  </th>
                  <td className="num pt-table__metric">
                    {formatMetric(metric, row.prior)} → <b>{formatMetric(metric, row.last)}</b>
                  </td>
                  <td className="pt-table__bar" aria-hidden="true">
                    <span className="pt-bar">
                      <i className={row.gmv_per_day < 0 ? "pt-bar__fill pt-bar__fill--down" : "pt-bar__fill pt-bar__fill--up"} style={{ width }} />
                    </span>
                  </td>
                  <td className="num pt-table__gmv">{signedMoney(row.gmv_per_day)}</td>
                  <td>
                    <ConfidenceBadge label={row.confidence} />
                  </td>
                </tr>
              );
            })
          )}
        </tbody>
        <tbody className="pt-table__closing">
          {closing.map((row) => (
            <tr data-closing={row.key} key={row.key}>
              <th scope="row" colSpan={3}>
                {row.label}
              </th>
              <td className="num pt-table__gmv">{signedMoney(row.gmv)}</td>
              <td />
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <th scope="row" colSpan={3}>
              Cộng các dòng trên · phần {METRIC_NAMES[metric]} trong thay đổi GMV/ngày của luồng
            </th>
            <td className="num pt-table__gmv" data-testid="ranking-total">
              Tổng = {signedMoney(payload.stream_factor_gmv)}
            </td>
            <td />
          </tr>
        </tfoot>
      </table>
    </div>
  );
}
