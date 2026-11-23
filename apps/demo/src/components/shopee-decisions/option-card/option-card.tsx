"use client";

import { useState } from "react";

import { sourceFunnelName } from "../../../lib/platform-labels";
import { DASH, fmt, pp, vnCount, vnd } from "../../../lib/shopee-analytics/format";
import type { VersionDates } from "../../../lib/shopee-decisions/builder-api";
import { roiLabel, type AdsEditFacts, type FunnelColumn, type OptionResult } from "../../../lib/shopee-decisions/option-result";
import { forecastOfResult } from "../../../lib/shopee-decisions/forecast-display";
import { TextChip } from "../../shopee-analytics/ui";
import { MetricCell, MetricLines } from "../forecast-lines";
import { moneyPct, resultDays, signedMoney } from "./format";

/**
 * P98 / ADR-122 d.5: the option card — only the lines of the decision, then a collapsed "Chi tiết".
 * Everything comes from `OptionResult` (wire shape); nothing is computed here.
 */

export function profitText(r: OptionResult): { readonly main: string; readonly range: string | null; readonly buildUp: string | null } {
  const p = r.delta.profit;
  if (!r.estimable || p === null || p.value === null) return { main: "—", range: null, buildUp: null };
  const range = p.low !== null && p.high !== null ? `(${signedMoney(p.low)} … ${signedMoney(p.high)})` : null;
  const buildUp = r.build_up.length > 0 ? r.build_up.map((b) => b.text).join(" ") : null;
  return { main: moneyPct(p.value, p.pct), range, buildUp };
}

const NOT_ESTIMABLE = "—";
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

const arrow = (now: string, after: string | null): string => (after === null || after === now ? now : `${now} → ${after}`);
const money = (n: number | null): string => (n === null ? NOT_ESTIMABLE : vnd(n));

/** P100 B.15: the Dịch vụ hiển thị lines — CPA → CPA mới, CPA hoà vốn, kết luận, lợi nhuận sau quảng cáo, ROAS Shopee. */
export function adsLines(a: AdsEditFacts): readonly { readonly key: string; readonly label: string; readonly text: string }[] {
  const roas = (n: number | null): string => (n === null ? DASH : fmt(n, 1));
  const verdict = (v: string | null): string => v ?? NOT_ESTIMABLE;
  const lines = [
    { key: "cpa", label: "CPA → CPA mới", text: `${money(a.cpa.now)} → ${money(a.cpa.after)}` },
    { key: "be", label: "CPA hoà vốn", text: a.break_even_cpa === null ? "chưa tính (thiếu giá vốn)" : vnd(a.break_even_cpa) },
    { key: "verdict", label: "Kết luận", text: a.break_even_cpa === null ? "chưa tính" : arrow(verdict(a.verdict_text.now), a.cpa.after === null ? NOT_ESTIMABLE : verdict(a.verdict_text.after)) },
    { key: "profit", label: "Lợi nhuận sau quảng cáo", text: arrow(money(a.profit_after_ads.now), a.profit_after_ads.after === null ? NOT_ESTIMABLE : vnd(a.profit_after_ads.after)) },
    { key: "roas", label: "ROAS Shopee", text: arrow(roas(a.roas_shopee.now), a.roas_shopee.after === null ? null : roas(a.roas_shopee.after)) },
  ];
  return lines;
}

function AdsBlock({ ads: a }: { readonly ads: AdsEditFacts }) {
    return (
    <div className="oc__ads" data-testid="oc-ads">
      <dl className="p2-kv">
        {adsLines(a).map((l) => (
          <div key={l.key}>
            <dt>{l.label}</dt>
            <dd data-testid={`oc-ads-${l.key}`}>{l.text}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export function OptionCard({ result: r, title, testId = "option-card", dates, profitReason }: { readonly result: OptionResult; readonly title?: string; readonly testId?: string; readonly dates?: VersionDates | null; /** G5: the profit_unknown warning's text, for a blank profit. */ readonly profitReason?: string }) {
  const profit = profitText(r);
  const orders = r.delta.orders;
  const forecast = forecastOfResult(r);
  const beLine = breakEvenLine(r);
  const funnel = funnelText(r);
  const margin = marginText(r);
  const roiValue = r.roi?.value;
  const roi = roiValue === null || roiValue === undefined ? null : fmt(roiValue, 1);
  const days = resultDays(r);
  const costNotes = r.notes.filter((n) => n.includes(COST_DAYS_NOTE));
  // UI grill G5: a "—" says why on hover (the server's reason text; the code is never shown)
  const why = r.reason_text ?? undefined;
  const profitWhy = r.estimable ? undefined : (why ?? profitReason);
  return (
    <article className="oc" data-testid={testId}>
      <header className="oc__head">
        <b>{title ?? r.label}</b>
        {r.basis_weak ? (
          <span data-testid="oc-weak">
            <TextChip tone="warn">chung</TextChip>
          </span>
        ) : null}
      </header>
      <p className="sa-hint" data-testid="oc-dates">
        Tính cho: <b>{datesText(dates, r)}</b>
        {dates && !dates.set ? " (chưa đặt ngày)" : ""}
      </p>
      <dl className="p2-kv">
        <div>
          <dt>Dự kiến</dt>
          <dd data-testid="oc-forecast">
            <MetricLines days={days} fallbackWhy={profitWhy ?? why} forecast={forecast} testId="oc-fc" />
            {profit.buildUp ? <span className="sa-hint" data-testid="oc-buildup">{profit.buildUp}</span> : null}
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
            <dt>{roiLabel(r)}</dt>
            <dd data-testid="oc-roi">{roi}</dd>
          </div>
        ) : null}
        <div>
          <dt>Chi phí</dt>
          <dd data-testid="oc-cost">
            <b>{r.cost.total > 0 ? vnd(r.cost.total) : r.cost.total < 0 ? `Giảm ${vnd(-r.cost.total)}` : "Không có chi phí thêm"}</b>
            {r.cost.discount_given?.text ? (
              <span className="sa-hint" data-testid="oc-discount-given">
                {r.cost.discount_given.text}
              </span>
            ) : null}
          </dd>
        </div>
        {beLine ? (
          <div>
            <dt>Hoà vốn</dt>
            <dd data-testid="oc-breakeven">{beLine}</dd>
          </div>
        ) : null}
      </dl>
      {r.ads ? <AdsBlock ads={r.ads} /> : null}
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

/** Shopee's funnel-row source names (kept for tests); the card itself reads the host's platform table. */
export const SOURCE_LABELS: Readonly<Record<string, string>> = Object.fromEntries(
  ["the_san_pham_khac", "trang_shop", "live", "video", "lien_ket", "chenh_lech_nguon"].map((k) => [k, sourceFunnelName("shopee", k) ?? k]),
);

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
                    <th scope="row">{sourceFunnelName("shopee", s) ?? s}</th>
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

/** One row per option: Thời gian, then Lợi nhuận / GMV / Đơn / AOV dự kiến (one amount, hiện tại and the change under it). P100 B.6: no "Quy đổi 30 ngày" column. */
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
          <th>Lợi nhuận dự kiến</th>
          <th>GMV dự kiến</th>
          <th>Đơn dự kiến</th>
          <th>AOV dự kiến</th>
        </tr>
      </thead>
      <tbody>
        {sorted.map(({ id, name, result: r, dates }) => {
          const f = forecastOfResult(r);
          return (
            <tr data-testid={`oc-row-${id}`} key={id}>
              <th scope="row">{name ?? r.label}</th>
              <td>{datesText(dates, r)}</td>
              {(["profit", "gmv", "orders", "aov"] as const).map((k) => (
                <td key={k}>
                  <MetricCell fallbackWhy={r.reason_text} forecast={f} metric={k} testId={`oc-row-${id}-${k}`} />
                </td>
              ))}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
