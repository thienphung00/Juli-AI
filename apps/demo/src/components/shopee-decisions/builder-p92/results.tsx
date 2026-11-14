"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { DASH, fmt, pp, vnd } from "../../../lib/shopee-analytics/format";
import type { BuilderOutcome } from "../../../lib/shopee-decisions/builder-api";
import { bandText, breakEvenText, floorWarningText, marginText, metricValue, refusalText, unitLines, voucherMaxText, voucherUsageText } from "../../../lib/shopee-decisions/builder-p92";
import { TextChip } from "../../shopee-analytics/ui";
import { OptionCard } from "../option-card";
import { perDayText, periodLabel, resultDays, signedCount, signedMoney } from "../option-card/format";
import type { OptionResult } from "../../../lib/shopee-decisions/option-result";
import { TargetRows } from "./targets";

/**
 * The result block of a version (artboard `TuTaoPhuongAnKinds`): Δ GMV, Δ đơn, Δ lợi nhuận with the low-high
 * range, biên sau, the cost of the change, the estimate basis, the driver metrics (CTOR = đơn ÷ lượt nhấp),
 * the break-even and the warnings. A listing without giá vốn reads "chưa tính" with a link to Thông số shop.
 */

export type ResultState =
  | { readonly status: "idle"; readonly problem: string | null }
  | { readonly status: "busy" }
  | { readonly status: "error"; readonly message: string }
  | { readonly status: "ready"; readonly outcome: BuilderOutcome };

export function basisTone(key: string | undefined): "info" | "pink" | "warn" | "flat" {
  return key === "product_history" ? "info" : key === "shop" ? "pink" : key === "prior" ? "warn" : "flat";
}

export function BasisChip({ outcome }: { readonly outcome: BuilderOutcome }) {
  const b = outcome.basis;
  return b ? <TextChip tone={basisTone(b.key)}>{b.label}</TextChip> : <span className="sd-muted">{DASH}</span>;
}

export function costText(o: BuilderOutcome): string {
  const c = o.cost;
  // P99c: a null figure says why (reason_text) — never 0đ and never a 30-day number.
  if (c && c.amount === null && c.reason_text) return c.reason_text;
  if (!c || c.amount === null) return o.kind === "variation_set" || o.cost_known === false ? DASH : "0đ";
  const per = c.source !== "result" && c.per_unit && c.expected_units ? ` (${c.expected_units} × ${vnd(c.per_unit)})` : "";
  return `${vnd(c.amount)}${per}`;
}

export function chuaTinh(o: BuilderOutcome): boolean {
  return o.profit_status === "chua_tinh" || o.cost_known === false;
}

export function ResultBlock({ index, title, state, costLink, onUntick }: { readonly index: number; readonly title: string; readonly state: ResultState; readonly costLink: string; readonly onUntick?: (id: string) => void }) {
  return (
    <section className="sa-card p2-result" data-testid="p2-result">
      <div className="sa-card__head">
        <h2 className="sa-h2">
          Kết quả P{index + 1} · {title}
        </h2>
      </div>
      {state.status === "idle" ? <p className="sa-hint">{state.problem ?? "—"}</p> : null}
      {state.status === "busy" ? (
        <p className="sa-hint" role="status">
          Đang tính…
        </p>
      ) : null}
      {state.status === "error" ? (
        <p className="sd-error" role="alert">
          {state.message}
        </p>
      ) : null}
      {state.status === "ready" ? <OutcomeBody costLink={costLink} onUntick={onUntick} outcome={state.outcome} /> : null}
    </section>
  );
}

export function OutcomeBody({ outcome: o, costLink, onUntick }: { readonly outcome: BuilderOutcome; readonly costLink: string; readonly onUntick?: (id: string) => void }) {
  if (!o.ok) {
    return (
      <p className="sd-error" role="alert">
        {refusalText(o)}
      </p>
    );
  }
  if (o.result) {
    return (
      <div className="p2-result__body">
        <OptionCard dates={o.dates} result={o.result} />
        <WarningLines outcome={o} />
      </div>
    );
  }
  const unknown = chuaTinh(o);
  const gmv = bandText(o.delta?.gmv);
  const orders = bandText(o.delta?.orders, "orders");
  const profit = bandText(o.delta?.profit);
  const after = o.margin_after_pct ?? null;
  const before = o.margin_before_pct ?? null;
  return (
    <div className="p2-result__body">
      <dl className="p2-kv">
        <div>
          <dt>Δ GMV</dt>
          <dd data-testid="p2-dgmv">
            <b>{gmv.main}</b>
            <span>{gmv.range}</span>
          </dd>
        </div>
        <div>
          <dt>Δ đơn</dt>
          <dd data-testid="p2-dorders">
            <b>{orders.main}</b>
            <span>{o.delta?.orders_note ?? orders.range}</span>
          </dd>
        </div>
        <div>
          <dt>Δ lợi nhuận</dt>
          <dd data-testid="p2-dprofit">
            {unknown ? (
              <>
                <b>chưa tính</b>
                <span>
                  chưa có giá vốn · <Link href={costLink}>Cài đặt › Thông số shop</Link>
                </span>
              </>
            ) : (
              <>
                <b>{profit.main}</b>
                <span>{profit.range}</span>
              </>
            )}
          </dd>
        </div>
        <div>
          <dt>Biên sau</dt>
          <dd data-testid="p2-margin">
            {unknown || after === null ? (
              <b>{unknown ? "chưa tính" : DASH}</b>
            ) : (
              <>
                <b>{marginText(after)}</b>
                <span>hôm nay {pp(before, 1)}</span>
              </>
            )}
          </dd>
        </div>
        <div>
          <dt>Chi phí của thay đổi</dt>
          <dd data-testid="p2-cost">
            <b>{costText(o)}</b>
            {o.cost?.label ? <span>{o.cost.label}</span> : null}
          </dd>
        </div>
        <div>
          <dt>Cơ sở</dt>
          <dd data-testid="p2-basis">
            <BasisChip outcome={o} />
            {o.basis?.detail ? <span>{o.basis.detail}</span> : null}
          </dd>
        </div>
      </dl>
      <TargetRows onUntick={onUntick} outcome={o} />
      {unitLines(o).length > 0 ? (
        <ul className="p2-units" data-testid="p2-units">
          {unitLines(o).map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      ) : null}
      {voucherUsageText(o) ? (
        <p className="p2-usage" data-testid="p2-usage">
          <b>{voucherUsageText(o)}</b>
          {voucherMaxText(o) ? ` · ${voucherMaxText(o)}` : ""}
          {o.voucher?.per_user.limit ? ` · Giới hạn ${fmt(o.voucher.per_user.limit, 0)} lượt/người mua` : ""}
        </p>
      ) : null}
      <div className="p2-drivers" data-testid="p2-drivers">
        <b>Chỉ số chính</b>
        <ul>
          {(o.driver?.metrics ?? []).map((m) => (
            <li key={m.key}>
              <span>{m.label}</span>
              <span>
                {metricValue(m.unit, m.before)} → {m.after_p50 === null ? "—" : metricValue(m.unit, m.after_p50)}
              </span>
            </li>
          ))}
        </ul>
      </div>
      <p className="p2-be" data-testid="p2-breakeven">
        <b>Hoà vốn:</b> {breakEvenText(o)}
      </p>
      <WarningLines outcome={o} />
    </div>
  );
}

export function WarningLines({ outcome: o }: { readonly outcome: BuilderOutcome }) {
  return (
    <>
      {(o.warnings ?? []).map((w, i) => (
        <div className={`sd-check ${w.type === "floor" || w.type === "spend_cap" ? "sd-check--bad" : ""}`} key={i} role="alert">
          <span>
            <b>{w.type === "floor" ? "Chạm giá sàn:" : w.type === "spend_cap" ? "Sát trần chi:" : w.type === "cost_unknown" ? "Chưa có giá vốn:" : "Lưu ý:"}</b> {floorWarningText(w)}
          </span>
        </div>
      ))}
    </>
  );
}

// ── P100 step ③ result card ──────────────────────────────────────────────

export type VerdictTone = "up" | "down" | "flat";

/** "Có lãi" when the change adds profit, "Lỗ phần thêm 150.000đ" when it loses; flat when not estimable. */
export function verdictOf(r: OptionResult): { readonly text: string; readonly tone: VerdictTone } {
  const v = r.delta.profit?.value;
  if (!r.estimable || v === null || v === undefined) return { text: "—", tone: "flat" };
  return v >= 0 ? { text: "Có lãi", tone: "up" } : { text: `Lỗ phần thêm ${vnd(Math.round(-v))}`, tone: "down" };
}

/** A finding for the ads edit, e.g. "Chiến dịch đang có lãi: CPA 33.333đ, hoà vốn 50.000đ". */
export function adsTitle(r: OptionResult): string | null {
  const a = r.ads;
  if (!a || a.cpa.now === null || a.break_even_cpa === null) return null;
  const word = a.verdict.now === "co_lai" ? "đang có lãi" : "đang lỗ";
  return `Chiến dịch ${word}: CPA ${vnd(a.cpa.now)}, hoà vốn ${vnd(a.break_even_cpa)}`;
}

const arrow = (a: string, b: string | null): string => (b === null || b === a ? a : `${a} → ${b}`);

/** CPA now → after against the break-even CPA: a bar whose marker sits at the break-even. */
export function CpaBar({ cpaNow, cpaAfter, breakEven }: { readonly cpaNow: number | null; readonly cpaAfter: number | null; readonly breakEven: number | null }) {
  if (breakEven === null || breakEven <= 0) return null;
  const top = Math.max(breakEven * 1.5, cpaNow ?? 0, cpaAfter ?? 0);
  const pct = (n: number | null) => (n === null ? 0 : Math.min(100, Math.max(0, (n / top) * 100)));
  const after = cpaAfter ?? cpaNow;
  const over = after !== null && after >= breakEven;
  return (
    <div className="p3-cpa" data-testid="p3-cpa">
      <div className="p3-cpa__label">CPA so với hoà vốn</div>
      <div className="p3-cpa__track">
        <div className={`p3-cpa__fill ${over ? "p3-cpa__fill--over" : ""}`} data-testid="p3-cpa-fill" style={{ width: `${pct(after)}%` }} />
        <div className="p3-cpa__mark" data-testid="p3-cpa-mark" style={{ left: `${pct(breakEven)}%` }} />
      </div>
      <div className="p3-cpa__legend">
        <span>
          CPA {cpaNow === null ? DASH : vnd(cpaNow)} → {cpaAfter === null ? DASH : vnd(cpaAfter)}
        </span>
        <span>Hoà vốn {vnd(breakEven)}</span>
      </div>
    </div>
  );
}

function Tile({ label, total, days, testId }: { readonly label: string; readonly total: number | null | undefined; readonly days: number; readonly testId: string }) {
  const per = perDayText(total, days);
  const tone = total === null || total === undefined ? "flat" : total < 0 ? "down" : "up";
  return (
    <div className="p3-tile" data-testid={testId}>
      <div className="p3-tile__label">{label}</div>
      <div className={`p3-tile__value sa-tone--${tone}`}>{signedMoney(total)}</div>
      {per ? <div className="p3-tile__per" data-testid={`${testId}-perday`}>{per}</div> : null}
    </div>
  );
}

/** Step ③ right-hand card (artboard Flow3): verdict, Δ lợi nhuận and Δ GMV for the whole period with ≈ per day, then the rows the kind has. */
export function VersionResult({ outcome: o, result: r, name }: { readonly outcome: BuilderOutcome; readonly result: OptionResult; readonly name: string }) {
  return (
    <ResultCard name={name} result={r}>
      <WarningLines outcome={o} />
    </ResultCard>
  );
}

/**
 * The result card itself, from an `OptionResult` alone: Tự tạo's step ③ and the card page's Kết quả
 * (one card, one number: the card stores this result). `breakEven` adds "Hoà vốn cần ≥ N đơn".
 */
export function ResultCard({ result: r, name, breakEven = false, children }: { readonly result: OptionResult; readonly name: string; readonly breakEven?: boolean; readonly children?: ReactNode }) {
  const days = resultDays(r);
  const period = periodLabel(days);
  const v = verdictOf(r);
  const a = r.ads;
  const rows: { readonly key: string; readonly label: string; readonly text: string }[] = [];
  if (a) {
    rows.push({ key: "spend", label: "Chi phí cả kỳ", text: arrow(a.spend.now === null ? DASH : vnd(a.spend.now), a.spend.after === null ? null : vnd(a.spend.after)) });
    const d = a.orders.now !== null && a.orders.after !== null ? a.orders.after - a.orders.now : null;
    rows.push({ key: "orders", label: "Đơn quảng cáo", text: `${a.orders.now === null ? DASH : fmt(a.orders.now, 0)} → ${a.orders.after === null ? DASH : fmt(a.orders.after, 0)}${d === null ? "" : ` (${signedCount(d)})`}` });
    if (a.incremental.orders_extra !== null) rows.push({ key: "lost", label: "Trong đó đơn mất thật", text: signedCount(a.incremental.orders_extra) });
    rows.push({ key: "profit", label: "Lợi nhuận sau quảng cáo", text: arrow(a.profit_after_ads.now === null ? DASH : vnd(a.profit_after_ads.now), a.profit_after_ads.after === null ? null : vnd(a.profit_after_ads.after)) });
    rows.push({ key: "roas", label: "ROAS Shopee", text: arrow(a.roas_shopee.now === null ? DASH : fmt(a.roas_shopee.now, 1), a.roas_shopee.after === null ? null : fmt(a.roas_shopee.after, 1)) });
  } else {
    rows.push({ key: "orders", label: "Δ đơn", text: r.estimable ? signedCount(r.delta.orders.value) : "—" });
    rows.push({ key: "cost", label: "Chi phí", text: r.cost.total > 0 ? vnd(r.cost.total) : r.cost.total < 0 ? `Giảm ${vnd(-r.cost.total)}` : "Không có chi phí thêm" });
    if (r.roi?.value !== null && r.roi?.value !== undefined) rows.push({ key: "roi", label: "ROI", text: fmt(r.roi.value, 1) });
    const m = r.margin;
    if (m && m.before_pct !== null && m.after_pct !== null) rows.push({ key: "margin", label: "Biên lợi nhuận", text: `${pp(m.before_pct, 1)} → ${pp(m.after_pct, 1)}` });
    const be = r.cost.break_even_orders;
    if (breakEven && be !== null && be !== undefined) rows.push({ key: "breakeven", label: "Hoà vốn", text: `cần ≥ ${fmt(Math.ceil(be - 1e-6), 0)} đơn` });
  }
  const title = adsTitle(r);
  return (
    <div className="p3-result" data-testid="p3-result">
      {title ? <h3 className="p3-finding" data-testid="p3-finding">{title}</h3> : null}
      <div className="p3-result__head">
        <b>{name}</b>
        <span className={`p3-verdict p3-verdict--${v.tone}`} data-testid="p3-verdict">
          {v.text}
        </span>
      </div>
      <div className="p3-tiles">
        <Tile days={days} label={`Δ lợi nhuận ${period}`} testId="p3-dprofit" total={r.estimable ? r.delta.profit?.value : null} />
        <Tile days={days} label={`Δ GMV ${period}`} testId="p3-dgmv" total={r.estimable ? r.delta.gmv.value : null} />
      </div>
      {a ? <CpaBar breakEven={a.break_even_cpa} cpaAfter={a.cpa.after} cpaNow={a.cpa.now} /> : null}
      <table className="p3-rows">
        <tbody>
          {rows.map((x) => (
            <tr data-testid={`p3-row-${x.key}`} key={x.key}>
              <td>{x.label}</td>
              <td>{x.text}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {children}
    </div>
  );
}
