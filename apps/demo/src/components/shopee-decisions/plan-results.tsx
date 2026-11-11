"use client";

import { DASH, dayMonth, fmt, pp, vnCount, vnd } from "../../lib/shopee-analytics/format";
import type { AdsReadback, DataMissing, DateSpan, PlanFunnel, PlanResponse } from "../../lib/shopee-decisions/plan-types";
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

const span = (d: DateSpan | null | undefined): string => (d ? `${dayMonth(d.from)} – ${dayMonth(d.to)}` : DASH);
const isNum = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n);

/** "30 ngày tới: dd/mm – dd/mm" (P99b): the window every card of the plan is counted in. */
export function HorizonLine({ plan }: { readonly plan: PlanResponse }) {
  const h = plan.aggregate?.horizon;
  if (!h) return null;
  return (
    <p className="sa-hint kh-horizon" data-testid="kh-horizon">
      <b>{h.label ?? "30 ngày tới"}</b>
      {h.label && h.label.includes(":") ? "" : `: ${span(h)}`}
    </p>
  );
}

/** No stored daily rows for the window: the message and nothing else (no figures). */
export function DataMissingNotice({ missing }: { readonly missing: DataMissing }) {
  const md = missing.missing_days;
  const n = Array.isArray(md) ? md.length : typeof md === "number" ? md : null;
  return (
    <div className="sd-check sd-check--warn" data-testid="kh-data-missing" role="alert">
      <span>
        <b>Chưa có số liệu để tính kế hoạch</b> <span className="sd-check__line" data-testid="kh-dm-message">{missing.message}</span>
        <span className="sd-check__line" data-testid="kh-dm-detail">
          {missing.window ? `Kỳ ${dayMonth(missing.window.from)}–${dayMonth(missing.window.to)}` : "Chưa rõ kỳ"}
          {n !== null ? ` · thiếu ${n} ngày` : ""}
          {missing.first_missing ? `, từ ${dayMonth(missing.first_missing)}` : ""}
        </span>
      </span>
    </div>
  );
}

/** Why a total is partial / a plan is empty / a cost is unknown, said once at the top of the numbers. */
export function PlanTotalsNotes({ plan }: { readonly plan: PlanResponse }) {
  const a = plan.aggregate;
  if (!a || a.data_missing) return null;
  return (
    <>
      {/* P100 A.8: only a plan with no card at all is empty (grouped cards leave the ungrouped
          aggregate empty while the plan still has cards) */}
      {a.empty && a.empty_note && plan.cards.length === 0 && (plan.groups?.length ?? 0) === 0 ? (
        <p className="sa-hint" data-testid="kh-empty-note">
          {a.empty_note}
        </p>
      ) : null}
      {a.totals_partial && a.totals_note ? (
        <p className="sd-check sd-check--warn" data-testid="kh-totals-note" role="note">
          {a.totals_note}
        </p>
      ) : null}
      {a.cost?.cost_complete === false || (a.cost_unknown_cards?.length ?? 0) > 0 ? (
        <p className="sa-hint" data-testid="kh-cost-unknown">
          Chưa biết chi phí{(a.cost_unknown_cards?.length ?? 0) > 0 ? ` của ${a.cost_unknown_cards!.length} thẻ` : ""}
          {a.cost?.cost_note ? `. ${a.cost.cost_note}` : ""}
        </p>
      ) : null}
    </>
  );
}

const READBACK_KEYS = [
  { key: "spend", label: "Chi tiêu", f: (n: number) => vnd(n) },
  { key: "gmv", label: "GMV", f: (n: number) => vnd(n) },
  { key: "orders", label: "Đơn", f: (n: number) => vnCount(n) },
  { key: "roas", label: "ROAS", f: (n: number) => fmt(n, 2) },
] as const;

/** What the hand-made Ads campaign of an `ads_new_campaign` card actually did (P99b read-back). */
export function AdsReadbackBlock({ readback }: { readonly readback: AdsReadback | null | undefined }) {
  if (!readback) return null;
  const actual = readback.actual;
  const c = readback.campaign;
  if (readback.state !== "matched") {
    return (
      <div className="kh-readback" data-state={readback.state} data-testid="kh-readback">
        <b data-testid="kh-readback-label">{readback.label ?? (readback.state === "ambiguous" ? "Có nhiều chiến dịch có thể khớp" : "Chưa tìm thấy chiến dịch")}</b>
        <p className="sa-hint" data-testid="kh-readback-reason">
          {readback.reason_text ?? "Chưa đọc được chiến dịch này."}
        </p>
        {(readback.candidates ?? []).length > 0 ? (
          <ul className="sa-hint" data-testid="kh-readback-candidates">
            {readback.candidates!.map((k, i) => (
              <li key={`${k.name ?? "c"}-${i}`}>
                {k.name ?? "Chiến dịch chưa đặt tên"}
                {k.first_day ? ` · bắt đầu ${dayMonth(k.first_day)}` : ""}
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    );
  }
  return (
    <div className="kh-readback" data-state="matched" data-testid="kh-readback">
      <b data-testid="kh-readback-label">{readback.label ?? "Đã khớp chiến dịch"}</b>
      <span className="sa-hint" data-testid="kh-readback-name">
        {" "}
        · {c?.name ?? "Chiến dịch chưa đặt tên"}
        {c?.first_day ? ` · bắt đầu ${dayMonth(c.first_day)}` : ""}
      </span>
      {readback.started_before_card ? (
        <p className="sa-hint" data-testid="kh-readback-before">
          Chiến dịch bắt đầu trước khi có thẻ này.
        </p>
      ) : null}
      {actual ? (
        <>
          <ul className="p2-ba" data-testid="kh-readback-actual">
            {READBACK_KEYS.map((k) => {
              const v = actual[k.key];
              return (
                <li data-testid={`kh-readback-${k.key}`} key={k.key}>
                  <span>{k.label}</span> <b>{isNum(v) ? k.f(v) : `chưa có dữ liệu${actual.reasons?.[k.key] ? ` · ${actual.reasons[k.key]}` : ""}`}</b>
                </li>
              );
            })}
          </ul>
          <p className="sa-hint" data-testid="kh-readback-coverage">
            {isNum(actual.days_covered) && isNum(actual.days_expected) ? `Có số liệu ${actual.days_covered}/${actual.days_expected} ngày` : "Chưa rõ số ngày có số liệu"}
            {actual.from && actual.to ? ` (${dayMonth(actual.from)} – ${dayMonth(actual.to)})` : ""}
            {actual.reasons?.coverage ? ` · ${actual.reasons.coverage}` : ""}
          </p>
        </>
      ) : (
        <p className="sa-hint" data-testid="kh-readback-none">
          Chưa có dữ liệu thực tế của chiến dịch này.
        </p>
      )}
    </div>
  );
}

export function CardResult({ plan, cardId }: { readonly plan: PlanResponse; readonly cardId: string }) {
  const r = plan.aggregate?.cards.find((c) => c.card_id === cardId)?.result;
  if (!r) return null;
  const be = r.break_even_orders;
  const dayNotes = r.notes.filter((n) => n.includes(COST_DAYS_NOTE));
  const outside = r.outside_horizon === true || r.reason === "outside_horizon";
  const counted = r.counted !== false && !outside;
  const costVal = r.cost_horizon !== undefined ? r.cost_horizon : r.cost_month;
  const costUnknown = r.cost_known === false;
  return (
    <div className="kh-row__result" data-testid={`kh-result-${cardId}`}>
      {r.own_dates || isNum(r.own_days) ? (
        <p className="sa-hint" data-testid="kh-result-days">
          Thẻ chạy {isNum(r.own_days) ? `${r.own_days} ngày` : DASH}
          {r.own_dates ? ` (${span(r.own_dates)})` : ""}
          {counted ? ` · tính vào kế hoạch ${isNum(r.counted_days) ? `${r.counted_days} ngày` : DASH}${r.counted_dates ? ` (${span(r.counted_dates)})` : ""}` : ""}
        </p>
      ) : r.dated === false ? (
        <p className="sa-hint" data-testid="kh-result-days">
          Thẻ chưa có ngày chạy.
        </p>
      ) : null}
      {outside ? (
        <p className="sd-check sd-check--warn" data-testid="kh-result-outside" role="note">
          {r.message ?? "Ngoài 30 ngày tới: không tính vào kế hoạch."}
        </p>
      ) : r.estimable && r.before && r.after ? (
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
        {costUnknown ? "Chưa biết chi phí" : `Chi phí trong 30 ngày tới ${isNum(costVal) ? vnd(costVal) : DASH}`}
        {costUnknown && r.cost_note ? ` · ${r.cost_note}` : ""}
        {be !== null && be !== undefined ? ` · cần thêm ${vnCount(be)} đơn để hoà vốn` : ""}
        {counted && r.estimable && r.delta ? ` · Δ Đơn ${svk0(r.delta.p50.dorders)}` : ""}
      </p>
      {r.partial_note ? (
        <p className="sa-hint" data-testid="kh-result-partial">
          {r.partial_note}
        </p>
      ) : null}
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
