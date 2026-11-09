"use client";

import { useState } from "react";

import { DASH, fmt, pp, vnd } from "../../../lib/shopee-analytics/format";
import type { FunnelColumn, OptionResult } from "../../../lib/shopee-decisions/option-result";
import { TextChip } from "../../shopee-analytics/ui";
import { countPct, moneyPct, signedMoney, signedPct } from "./format";

/**
 * P98 / ADR-122 d.5: the option card — only the lines of the decision, then a collapsed "Chi tiết".
 * Everything comes from `OptionResult` (wire shape); nothing is computed here.
 */

export function profitText(r: OptionResult): { readonly main: string; readonly range: string | null; readonly buildUp: string | null } {
  const p = r.delta.profit;
  if (p === null || p.value === null) return { main: r.estimable ? "chưa tính" : "chưa ước tính được", range: null, buildUp: null };
  const range = p.low !== null && p.high !== null ? `(${signedMoney(p.low)} … ${signedMoney(p.high)})` : null;
  const buildUp = r.build_up.length > 0 ? r.build_up.map((b) => b.text).join(" ") : null;
  return { main: moneyPct(p.value, p.pct), range, buildUp };
}

export function OptionCard({ result: r, title, testId = "option-card" }: { readonly result: OptionResult; readonly title?: string; readonly testId?: string }) {
  const profit = profitText(r);
  const orders = r.delta.orders;
  const drivers = r.drivers_pct.map((d) => `${d.label} ${signedPct(d.pct)}`).join(" · ");
  const a = r.after;
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
      <dl className="p2-kv">
        <div>
          <dt>Δ Lợi nhuận</dt>
          <dd data-testid="oc-profit">
            <b>{profit.main}</b>
            {profit.range ? <span> {profit.range}</span> : null}
            {profit.buildUp ? <span className="sa-hint" data-testid="oc-buildup">{profit.buildUp}</span> : null}
          </dd>
        </div>
        <div>
          <dt>Δ GMV</dt>
          <dd data-testid="oc-gmv">
            <b>{moneyPct(r.delta.gmv.value, r.delta.gmv.pct)}</b>
          </dd>
        </div>
        <div>
          <dt>Δ Đơn</dt>
          <dd data-testid="oc-orders">
            <b>{countPct(orders.value, orders.pct)}</b>
            {orders.note ? <span className="sa-hint" data-testid="oc-note">{orders.note}</span> : null}
          </dd>
        </div>
        {drivers ? (
          <div>
            <dt>Tác động</dt>
            <dd data-testid="oc-drivers">{drivers}</dd>
          </div>
        ) : null}
        <div>
          <dt>Chi phí</dt>
          <dd data-testid="oc-cost">
            <b>{vnd(r.cost.total)}</b> <span>{r.cost.text}</span>
          </dd>
        </div>
        <div>
          <dt>{a.label}</dt>
          <dd data-testid="oc-after">
            GMV {vnd(a.gmv_before)} → {vnd(a.gmv_after)} · Lợi nhuận {vnd(a.profit_before)} → {vnd(a.profit_after)}
          </dd>
        </div>
      </dl>
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

const SOURCE_LABELS: Readonly<Record<string, string>> = { organic: "Tự nhiên", ads: "Quảng cáo", affiliate: "Liên kết", kol: "KOL", live: "Livestream", video: "Video" };

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

/** Rows sorted by `per_30d.profit` descending, null last (stable). */
export function sortByProfit<T extends { readonly result: OptionResult }>(rows: readonly T[]): T[] {
  return rows
    .map((row, i) => ({ row, i }))
    .sort((x, y) => {
      const a = x.row.result.per_30d.profit;
      const b = y.row.result.per_30d.profit;
      if (a === null && b === null) return x.i - y.i;
      if (a === null) return 1;
      if (b === null) return -1;
      return b - a || x.i - y.i;
    })
    .map((x) => x.row);
}

export interface CompareRow {
  readonly id: string | number;
  readonly name?: string;
  readonly result: OptionResult;
}

/** One row per option: Thời gian, Δ Lợi nhuận, Δ GMV, Δ Đơn (the row's own total), sorted per 30 days. */
export function CompareTable({ rows }: { readonly rows: readonly CompareRow[] }) {
  const sorted = sortByProfit(rows);
  return (
    <table className="sa-table oc-compare" data-testid="oc-compare">
      <caption className="sa-hint">Xếp theo lợi nhuận quy về 30 ngày</caption>
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
        {sorted.map(({ id, name, result: r }) => {
          const p = profitText(r);
          return (
            <tr data-testid={`oc-row-${id}`} key={id}>
              <th scope="row">{name ?? r.label}</th>
              <td>{r.after.label}</td>
              <td>{p.main}</td>
              <td>{moneyPct(r.delta.gmv.value, r.delta.gmv.pct)}</td>
              <td>{countPct(r.delta.orders.value, r.delta.orders.pct)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
