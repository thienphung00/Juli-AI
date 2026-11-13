"use client";

import Link from "next/link";

import { DASH, fmt, pp, vnd } from "../../../lib/shopee-analytics/format";
import type { BuilderOutcome } from "../../../lib/shopee-decisions/builder-api";
import { bandText, breakEvenText, floorWarningText, marginText, metricValue, refusalText, unitLines, voucherMaxText, voucherUsageText } from "../../../lib/shopee-decisions/builder-p92";
import { TextChip } from "../../shopee-analytics/ui";
import { OptionCard } from "../option-card";
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
        <span className="sa-hint">dự kiến, theo số ngày của thay đổi</span>
      </div>
      {state.status === "idle" ? <p className="sa-hint">{state.problem ?? "Nhập thông số để xem kết quả."}</p> : null}
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
  const insufficient = o.basis?.key === "insufficient";
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
          <dt>Cơ sở ước tính</dt>
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
          {o.voucher?.per_user.limit ? ` · Giới hạn ${fmt(o.voucher.per_user.limit, 0)} lượt/người mua chưa tính vào kết quả` : ""}
        </p>
      ) : null}
      {insufficient ? <p className="sa-hint">Chưa có lần thử nào của sản phẩm hay của shop để so: Juli chỉ cho biết chi phí và mức đơn cần thêm. Chạy thử rồi đo.</p> : null}
      <div className="p2-drivers" data-testid="p2-drivers">
        <b>Chỉ số chính</b> <span className="sa-hint">(đo sau khi chạy · CTOR = đơn ÷ lượt nhấp)</span>
        <ul>
          {(o.driver?.metrics ?? []).map((m) => (
            <li key={m.key}>
              <span>{m.label}</span>
              <span>
                {metricValue(m.unit, m.before)} → {m.after_p50 === null ? "chưa ước tính" : metricValue(m.unit, m.after_p50)}
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

function WarningLines({ outcome: o }: { readonly outcome: BuilderOutcome }) {
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
