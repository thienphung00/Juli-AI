import Link from "next/link";

import type { ShopAnalysisEnvelope } from "../../lib/shop-analysis/types";
import { NO_DATA } from "../../lib/shop-analysis/derive";
import {
  buildHomeOverview,
  METRIC_COLUMNS,
  type HomeMetricCell,
  type HomeStreamRow,
  type HomeTotalCard,
  type MetricKey,
} from "../../lib/shop-report/home-metrics";
import { compactMoney, num, pct, slashDate, vnClock, vnWeekdayDate } from "../../lib/vn-format";
import { AppPageHeader } from "../app-shell/page-header";

/**
 * Trang chủ (AC-8.5, ADR-109 decision 3) — the sales demo video's overview:
 * GMV / Đơn / AOV cards over the 5-stream matrix (Lượt hiển thị sản phẩm/ngày,
 * CTR, CTOR, AOV per stream, tinted by direction "so với kỳ trước", Liên kết
 * greyed "chỉ theo dõi"). Pure view of one ADR-108 envelope: the signed-in
 * shop's (`signed-in-home.tsx`) or the bundled sample (`sample-home.tsx`).
 * Every linked cell opens Phân tích at that stream × metric.
 */

const ARROW = { up: "▲", down: "▼", flat: "" } as const;

function formatMetric(metric: MetricKey, value: number | null): string {
  if (metric === "impressions") return num(value, 0);
  if (metric === "aov") return compactMoney(value);
  return pct(value);
}

function formatCard(card: HomeTotalCard, value: number | null): string {
  return card.kind === "money" ? compactMoney(value) : num(value, 0);
}

function headline(cards: readonly HomeTotalCard[], days: number): string {
  const gmv = cards.find((c) => c.key === "gmv");
  if (!gmv || gmv.tone === "flat") return `GMV ${days} ngày đi ngang so với kỳ trước`;
  const verb = gmv.tone === "up" ? "tăng" : "giảm";
  return `GMV ${days} ngày ${verb} ${gmv.changeText.replace(/^[+−]/, "")} so với kỳ trước`;
}

function MatrixCell({ cell, row }: { readonly cell: HomeMetricCell; readonly row: HomeStreamRow }) {
  const column = METRIC_COLUMNS.find((c) => c.metric === cell.metric)?.label ?? cell.metric;
  const value = formatMetric(cell.metric, cell.last);
  const tone = row.monitorOnly ? "muted" : cell.tone;
  const delta =
    cell.changeText === "—" ? "chưa so sánh được" : `${ARROW[cell.tone]} ${cell.changeText} so với kỳ trước`.trim();
  const body = (
    <>
      <span aria-hidden="true" className="matrix-cell__label">
        {column}
      </span>
      <b className="num">{value}</b>
      <span className="matrix-cell__delta">
        {delta}
        {cell.estimated ? " · ước tính" : ""}
      </span>
    </>
  );
  return (
    <td className={`matrix-cell matrix-cell--${tone}`}>
      {cell.href ? (
        <Link
          aria-label={`${column} ${row.label}: ${value}, ${delta}. Xem trong Phân tích`}
          className="matrix-cell__link"
          href={cell.href}
        >
          {body}
        </Link>
      ) : (
        <div className="matrix-cell__static">{body}</div>
      )}
    </td>
  );
}

export function StreamMatrix({ envelope }: { readonly envelope: ShopAnalysisEnvelope }) {
  const model = buildHomeOverview(envelope);
  return (
    <div className="card stream-matrix-card">
      <p aria-label="GMV bằng Lượt hiển thị nhân CTR nhân CTOR nhân AOV" className="gmv-formula">
        <span className="gmv-formula__term gmv-formula__term--gmv">GMV</span>
        <span aria-hidden="true">=</span>
        <span className="gmv-formula__term">Lượt hiển thị</span>
        <span aria-hidden="true">×</span>
        <span className="gmv-formula__term">CTR</span>
        <span aria-hidden="true">×</span>
        <span className="gmv-formula__term">CTOR</span>
        <span aria-hidden="true">×</span>
        <span className="gmv-formula__term">AOV</span>
      </p>
      <div aria-label="Ma trận 5 luồng truy cập" className="stream-matrix-wrap" role="region" tabIndex={0}>
        <table className="stream-matrix">
          <thead>
            <tr>
              <th scope="col">Luồng truy cập</th>
              {METRIC_COLUMNS.map((column) => (
                <th key={column.metric} scope="col">
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          {model.groups.map((group) => (
            <tbody className={`stream-matrix__group stream-matrix__group--${group.group}`} key={group.group}>
              <tr>
                <th className="stream-matrix__group-label" colSpan={5} scope="rowgroup">
                  {group.label}
                </th>
              </tr>
              {group.rows.map((row) => (
                <tr data-channel={row.channel} key={row.channel}>
                  <th className="stream-matrix__stream" scope="row">
                    {row.label}
                    <span>{row.sub}</span>
                  </th>
                  {row.missing ? (
                    <td className="matrix-cell matrix-cell--missing" colSpan={4}>
                      {NO_DATA}
                    </td>
                  ) : (
                    row.cells.map((cell) => <MatrixCell cell={cell} key={cell.metric} row={row} />)
                  )}
                </tr>
              ))}
            </tbody>
          ))}
        </table>
      </div>
    </div>
  );
}

export interface HomeOverviewProps {
  readonly envelope: ShopAnalysisEnvelope;
  /** The bundled synthetic report — says so on the page. */
  readonly sample?: boolean;
}

export function HomeOverview({ envelope, sample = false }: HomeOverviewProps) {
  const model = buildHomeOverview(envelope);
  const day = vnWeekdayDate(envelope.built_at);
  const clock = vnClock(envelope.built_at);
  const end = slashDate(model.lastWindowEnd);

  return (
    <section aria-labelledby="home-title" className="home-overview">
      <AppPageHeader
        eyebrow={day ? `Trang chủ · ${day}` : "Trang chủ"}
        lede={`${clock ? `Juli dựng báo cáo lúc ${clock} và so` : "Juli so"} từng chỉ số của 5 luồng truy cập trong ${model.windowDays} ngày đến ${end} với ${model.windowDays} ngày trước đó.`}
        title={headline(model.cards, model.windowDays)}
        titleId="home-title"
      />
      {sample ? (
        <p className="demo-notice sample-notice" data-testid="mock-data-notice">
          Dữ liệu mẫu · {model.shopName} là shop minh họa, không phải shop của bạn.
        </p>
      ) : null}

      <div className="home-stats">
        {model.cards.map((card) => (
          <div className="card home-stat" data-testid={`home-stat-${card.key}`} key={card.key}>
            <p className="home-stat__label">{card.label}</p>
            <p className="home-stat__value num">{formatCard(card, card.last)}</p>
            <p className="home-stat__prior num">
              trước {formatCard(card, card.prior)}{" "}
              <span className={`change-pill change-pill--${card.tone}`}>
                {ARROW[card.tone]} {card.changeText}
              </span>
            </p>
          </div>
        ))}
      </div>

      <StreamMatrix envelope={envelope} />
    </section>
  );
}
