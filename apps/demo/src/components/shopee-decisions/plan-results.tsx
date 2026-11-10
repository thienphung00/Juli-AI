"use client";

import { DASH, pp, vnCount, vnd } from "../../lib/shopee-analytics/format";
import type { PlanFunnel, PlanResponse } from "../../lib/shopee-decisions/plan-types";
import { COST_DAYS_NOTE } from "./option-card/option-card";

/**
 * P99 (ADR-122 amendment): per card of Kế hoạch the base its Δ was computed on, "trước → sau" (GMV, đơn,
 * lợi nhuận), the cost per month, the break-even and the cost-days note; per product its own "hôm nay → sau".
 * Everything is read from the wire; `null` is "chưa ước tính được" or "—", never 0.
 */

const NOT_ESTIMABLE = "chưa ước tính được";

const money = (n: number | null | undefined): string => (n === null || n === undefined ? DASH : vnd(n));
const orders = (n: number | null | undefined): string => (n === null || n === undefined ? DASH : vnCount(n));

function pair(before: number | null | undefined, after: number | null | undefined, f: (n: number | null | undefined) => string): string {
  return `${f(before)} → ${f(after)}`;
}

export function CardResult({ plan, cardId }: { readonly plan: PlanResponse; readonly cardId: string }) {
  const r = plan.aggregate?.cards.find((c) => c.card_id === cardId)?.result;
  if (!r) return null;
  const be = r.break_even_orders;
  const dayNotes = r.notes.filter((n) => n.includes(COST_DAYS_NOTE));
  return (
    <div className="kh-row__result" data-testid={`kh-result-${cardId}`}>
      {r.estimable && r.before && r.after ? (
        <ul className="p2-ba" data-testid="kh-result-ba">
          <li>
            <span>GMV 30 ngày</span> <b>{pair(r.before.gmv_30d, r.after.gmv_30d, money)}</b>
          </li>
          <li>
            <span>Đơn 30 ngày</span> <b>{pair(r.before.orders_30d, r.after.orders_30d, orders)}</b>
          </li>
          <li>
            <span>Lợi nhuận 30 ngày</span> <b>{pair(r.before.profit_30d, r.after.profit_30d, money)}</b>
          </li>
        </ul>
      ) : (
        <p className="sa-hint" data-testid="kh-result-ne">
          {NOT_ESTIMABLE}
          {r.message && r.message !== NOT_ESTIMABLE ? ` · ${r.message}` : ""}
        </p>
      )}
      <p className="sa-hint" data-testid="kh-result-cost">
        Chi phí {r.cost_month === null ? DASH : `${vnd(r.cost_month)}/tháng`}
        {be !== null && be !== undefined ? ` · cần thêm ${vnCount(be)} đơn để hoà vốn` : ""}
        {r.estimable && r.delta ? ` · Δ Đơn ${svk0(r.delta.p50.dorders)}` : ""}
      </p>
      {dayNotes.map((n) => (
        <p className="sa-hint" data-testid="kh-result-note" key={n}>
          {n}
        </p>
      ))}
    </div>
  );
}

function svk0(n: number | null | undefined): string {
  if (n === null || n === undefined) return DASH;
  return `${n < 0 ? "−" : "+"}${vnCount(Math.abs(n))}`;
}

const rowsOf = (t: PlanFunnel, a: PlanFunnel | null | undefined) => [
  { key: "gmv", label: "GMV", text: pair(t.gmv_30d, a?.gmv_30d, money) },
  { key: "orders", label: "Đơn", text: pair(t.orders_30d, a?.orders_30d, orders) },
  { key: "aov", label: "AOV", text: pair(t.aov, a?.aov, money) },
  { key: "profit", label: "Lợi nhuận", text: pair(t.profit_30d, a?.profit_30d, money) },
];

/** Each product's own "hôm nay → sau" (the base its cards' Δ stand on), not the shop's. */
export function ProductToday({ plan }: { readonly plan: PlanResponse }) {
  const blocks = (plan.aggregate?.products ?? []).filter((p) => p.today);
  if (blocks.length === 0) return null;
  return (
    <div className="kh-prod-today" data-testid="kh-prod-today">
      <h3 className="sa-h3">Từng sản phẩm: hôm nay → sau (30 ngày)</h3>
      {blocks.map((p) => (
        <section className="sa-card" data-testid={`kh-prod-today-${p.product_id}`} key={p.product_id}>
          <b>{p.name ?? p.product_id}</b>
          {p.today?.margin_pct !== undefined && p.today.margin_pct !== null ? <span className="sa-hint"> · biên hôm nay {pp(p.today.margin_pct, 1)}</span> : null}
          <ul className="p2-ba">
            {rowsOf(p.today!, p.after).map((r) => (
              <li data-testid={`kh-prod-${r.key}`} key={r.key}>
                <span>{r.label}</span> <b>{r.text}</b>
              </li>
            ))}
          </ul>
          {p.after ? <span className="sa-hint">{p.after.label ?? "Dự kiến (P50)"}</span> : <span className="sa-hint">{NOT_ESTIMABLE}</span>}
        </section>
      ))}
    </div>
  );
}
