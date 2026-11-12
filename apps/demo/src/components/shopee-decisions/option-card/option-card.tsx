"use client";

import { useState } from "react";

import { DASH, fmt, pp, vnCount, vnd } from "../../../lib/shopee-analytics/format";
import type { VersionDates } from "../../../lib/shopee-decisions/builder-api";
import type { FunnelColumn, OptionResult } from "../../../lib/shopee-decisions/option-result";
import { TextChip } from "../../shopee-analytics/ui";
import { countPct, moneyPct, signedMoney } from "./format";

/**
 * P98 / ADR-122 d.5: the option card — only the lines of the decision, then a collapsed "Chi tiết".
 * Everything comes from `OptionResult` (wire shape); nothing is computed here.
 */

export function profitText(r: OptionResult): { readonly main: string; readonly range: string | null; readonly buildUp: string | null } {
  const p = r.delta.profit;
  if (!r.estimable || p === null || p.value === null) return { main: r.estimable ? "chưa tính" : "chưa ước tính được", range: null, buildUp: null };
  const range = p.low !== null && p.high !== null ? `(${signedMoney(p.low)} … ${signedMoney(p.high)})` : null;
  const buildUp = r.build_up.length > 0 ? r.build_up.map((b) => b.text).join(" ") : null;
  return { main: moneyPct(p.value, p.pct), range, buildUp };
}

const NOT_ESTIMABLE = "chưa ước tính được";
/** P99: the note the engine adds when profit per order stands on the days that have costs. */
export const COST_DAYS_NOTE = "ngày có dữ liệu chi phí";

/** P100-C: the one break-even line — "cần thêm 12 đơn để hoà vốn", "… hoặc AOV ≥ 210.000đ …". */
export function breakEvenLine(r: OptionResult): string | null {
  const n = r.cost.break_even_orders;
  const aov = r.cost.break_even_aov;
  const parts: string[] = [];
  if (n !== null && n !== undefined) parts.push(`cần thêm ${vnCount(Math.ceil(n - 1e-6))} đơn`);
  if (aov !== null && aov !== undefined) parts.push(`${parts.length ? "hoặc " : "cần "}AOV ≥ ${vnd(aov)}`);
  return parts.length ? `${parts.join(" ")} để hoà vốn` : null;
}

/** The period the primary Δ and cost stand on: the version's set dates, else its first N days. */
export function datesText(dates: VersionDates | null | undefined, r: OptionResult): string {
  if (dates?.label) return dates.label;
  return r.after.label || (r.days ? `${r.days} ngày đầu` : "chưa có ngày");
}

const FUNNEL: readonly { readonly key: "views" | "ctr" | "ctor" | "aov"; readonly label: string; readonly fmt: (n: number | null) => string }[] = [
  { key: "views", label: "Hiển thị", fmt: (n) => fmt(n, 0) },
  { key: "ctr", label: "CTR", fmt: (n) => pp(n, 2) },
  { key: "ctor", label: "CTOR", fmt: (n) => pp(n, 2) },
  { key: "aov", label: "AOV", fmt: (n) => vnd(n) },
];

/** P100-C (B.6): "Hiển thị 10.000 → 10.200 · CTR 3,50% → 3,60% · CTOR … · AOV …" (before → likely). */
function funnelText(r: OptionResult): string | null {
  const b = r.detail.before;
  const a = r.detail.likely;
  if (!r.estimable || !a) return null;
  return FUNNEL.map((m) => `${m.label} ${m.fmt(b[m.key])} → ${m.fmt(a[m.key])}`).join(" · ");
}

/** P100-C (B.6): "34,1% → 31,0% (−3,1 điểm)" — secondary to Δ tổng lợi nhuận. */
function marginText(r: OptionResult): string | null {
  const m = r.margin;
  if (!m || m.before_pct === null || m.after_pct === null || m.shift_pts === null) return null;
  const s = fmt(Math.abs(m.shift_pts), 1);
  const sign = m.shift_pts < 0 && s !== "0,0" ? "−" : "+";
  return `${pp(m.before_pct, 1)} → ${pp(m.after_pct, 1)} (${sign}${s} điểm)`;
}

export function OptionCard({ result: r, title, testId = "option-card", dates }: { readonly result: OptionResult; readonly title?: string; readonly testId?: string; readonly dates?: VersionDates | null }) {
  const profit = profitText(r);
  const orders = r.delta.orders;
  const ne = !r.estimable;
  const gmvText = ne ? NOT_ESTIMABLE : moneyPct(r.delta.gmv.value, r.delta.gmv.pct);
  const ordersText = ne ? NOT_ESTIMABLE : countPct(orders.value, orders.pct);
  const beLine = breakEvenLine(r);
  const funnel = funnelText(r);
  const margin = marginText(r);
  const roiValue = r.roi?.value;
  const roi = roiValue === null || roiValue === undefined ? null : fmt(roiValue, 1);
  const costNotes = r.notes.filter((n) => n.includes(COST_DAYS_NOTE));
  return (
    <article className="oc" data-testid={testId}>
      <header className="oc__head">
        <b>{title ?? r.label}</b>
        {r.basis_weak ? (
          <span data-testid="oc-weak">
            <TextChip tone="warn">ước tính chung</TextChip>
          </span>
        ) : null}
      </header>
      <p className="sa-hint" data-testid="oc-dates">
        Tính cho: <b>{datesText(dates, r)}</b>
        {dates && !dates.set ? " (chưa đặt ngày)" : ""}
      </p>
      <dl className="p2-kv">
        <div>
          <dt>Δ Tổng lợi nhuận</dt>
          <dd data-testid="oc-profit">
            <b>{profit.main}</b>
            {profit.range ? <span> {profit.range}</span> : null}
            {profit.buildUp ? <span className="sa-hint" data-testid="oc-buildup">{profit.buildUp}</span> : null}
          </dd>
        </div>
        <div>
          <dt>Δ GMV</dt>
          <dd data-testid="oc-gmv">
            <b>{gmvText}</b>
          </dd>
        </div>
        <div>
          <dt>Δ Đơn</dt>
          <dd data-testid="oc-orders">
            <b>{ordersText}</b>
            {orders.note ? <span className="sa-hint" data-testid="oc-note">{orders.note}</span> : null}
          </dd>
        </div>
        {funnel ? (
          <div>
            <dt>Phễu</dt>
            <dd data-testid="oc-funnel">{funnel}</dd>
          </div>
        ) : null}
        {margin ? (
          <div>
            <dt>Biên lợi nhuận</dt>
            <dd data-testid="oc-margin">{margin}</dd>
          </div>
        ) : null}
        {roi ? (
          <div>
            <dt>ROI</dt>
            <dd data-testid="oc-roi">{roi}</dd>
          </div>
        ) : null}
        <div>
          <dt>Chi phí</dt>
          <dd data-testid="oc-cost">
            <b>{r.cost.total > 0 ? vnd(r.cost.total) : "Không có chi phí thêm"}</b>
          </dd>
        </div>
        {beLine ? (
          <div>
            <dt>Hoà vốn</dt>
            <dd data-testid="oc-breakeven">{beLine}</dd>
          </div>
        ) : null}
      </dl>
      {costNotes.map((n) => (
        <p className="sa-hint" data-testid="oc-cost-days" key={n}>
          {n}
        </p>
      ))}
      <OptionDetail result={r} />
    </article>
  );
}

const METRICS: readonly { readonly key: keyof FunnelColumn; readonly label: string; readonly fmt: (n: number | null) => string }[] = [
  { key: "views", label: "Lượt xem", fmt: (n) => fmt(n, 0) },
  { key: "ctr", label: "CTR", fmt: (n) => pp(n, 2) },
  { key: "ctor", label: "CTOR", fmt: (n) => pp(n, 2) },
  { key: "orders", label: "Đơn", fmt: (n) => fmt(n, 0) },
  { key: "aov", label: "AOV", fmt: (n) => vnd(n) },
  { key: "gmv", label: "GMV", fmt: (n) => vnd(n) },
  { key: "profit", label: "Lợi nhuận", fmt: (n) => vnd(n) },
];

export const SOURCE_LABELS: Readonly<Record<string, string>> = {
  the_san_pham_khac: "Thẻ sản phẩm (ngoài Trang shop)",
  trang_shop: "Trang shop",
  live: "Live",
  video: "Video",
  lien_ket: "Liên kết",
  chenh_lech_nguon: "Chênh lệch nguồn",
};

function columns(r: OptionResult): readonly { readonly name: string; readonly col: FunnelColumn | null }[] {
  return [
    { name: "Trước", col: r.detail.before },
    { name: "Thấp", col: r.detail.low },
    { name: "Khả dĩ", col: r.detail.likely },
    { name: "Cao", col: r.detail.high },
  ];
}

/** "Chi tiết" (collapsed): the seven funnel metrics for before / low / likely / high, by source, notes. */
export function OptionDetail({ result: r }: { readonly result: OptionResult }) {
  const [open, setOpen] = useState(false);
  const cols = columns(r);
  const sources = Object.keys(r.detail.likely?.by_source ?? r.detail.before.by_source);
  return (
    <div className="oc__detail">
      <button aria-expanded={open} className="sa-link p2-linkbtn" data-testid="oc-toggle" onClick={() => setOpen((v) => !v)} type="button">
        Chi tiết
      </button>
      {open ? (
        <div data-testid="oc-detail">
          <table className="sa-table">
            <thead>
              <tr>
                <th />
                {cols.map((c) => (
                  <th key={c.name}>{c.name}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {METRICS.map((m) => (
                <tr data-testid={`oc-metric-${m.key}`} key={m.key}>
                  <th scope="row">{m.label}</th>
                  {cols.map((c) => {
                    const v = c.col ? (c.col[m.key] as number | null) : null;
                    return <td key={c.name}>{c.col ? m.fmt(v) : DASH}</td>;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          {sources.length > 0 ? (
            <table className="sa-table" data-testid="oc-sources">
              <caption className="sa-hint">Theo nguồn</caption>
              <tbody>
                {sources.map((s) => (
                  <tr key={s}>
                    <th scope="row">{SOURCE_LABELS[s] ?? s}</th>
                    {cols.map((c) => {
                      const row = c.col?.by_source[s];
                      return (
                        <td key={c.name}>
                          {row ? `${fmt(row["orders"] ?? null, 0)} đơn · ${vnd(row["gmv"] ?? null)}` : DASH}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
          {r.notes.length > 0 ? (
            <ul className="sa-hint" data-testid="oc-notes">
              {r.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export interface CompareRow {
  readonly id: string | number;
  readonly name?: string;
  readonly result: OptionResult;
  readonly dates?: VersionDates | null;
}

/** One row per option: Thời gian, Δ Lợi nhuận, Δ GMV, Δ Đơn (the row's own total). P100 B.6: no "Quy đổi 30 ngày" column. */
/** P99c: rows come in the server's order (`compare`); the table never re-sorts them. */
export function CompareTable({ rows, sortBasis }: { readonly rows: readonly CompareRow[]; readonly sortBasis?: string | null }) {
  const sorted = rows;
  return (
    <table className="sa-table oc-compare" data-testid="oc-compare">
      <caption className="sa-hint" data-testid="oc-sort-basis">{sortBasis ? `Xếp theo: ${sortBasis}` : "Thứ tự do máy chủ xếp"}</caption>
      <thead>
        <tr>
          <th>Phương án</th>
          <th>Thời gian</th>
          <th>Δ Lợi nhuận</th>
          <th>Δ GMV</th>
          <th>Δ Đơn</th>
        </tr>
      </thead>
      <tbody>
        {sorted.map(({ id, name, result: r, dates }) => {
          const p = profitText(r);
          return (
            <tr data-testid={`oc-row-${id}`} key={id}>
              <th scope="row">{name ?? r.label}</th>
              <td>{datesText(dates, r)}</td>
              <td>{p.main}</td>
              <td>{!r.estimable ? NOT_ESTIMABLE : moneyPct(r.delta.gmv.value, r.delta.gmv.pct)}</td>
              <td>{!r.estimable ? NOT_ESTIMABLE : countPct(r.delta.orders.value, r.delta.orders.pct)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
