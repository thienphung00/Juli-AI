"use client";

import { DASH, pp, sv } from "../../lib/shopee-analytics/format";
import type { PlanApi, PlanResponse, PlanStep, ProductBlock } from "../../lib/shopee-decisions/plan-types";
import { TextChip } from "../shopee-analytics/ui";

/**
 * P92 B-10 "Kế hoạch gối nhau": per product the draft is a sequence price, giảm giá, voucher,
 * combo / mua kèm / quà tặng, ads. Each step is evaluated on top of the previous ones, so the
 * margin and Δ lợi nhuận after every step (and in total) are shown. Moving or removing a card
 * re-evaluates the rest. `null` is "chưa tính", never 0.
 */

const NOT_COUNTED = "—";
const num = (n: number | null | undefined, f: (x: number) => string): string => (n === null || n === undefined ? NOT_COUNTED : f(n));

export function productsWithSteps(plan: PlanResponse): readonly ProductBlock[] {
  return (plan.aggregate?.products ?? []).filter((p) => (p.steps?.items.length ?? 0) >= 2);
}

function StepRow({ step, position, last, first, busy, readOnly, onMove, onRemove }: { readonly step: PlanStep; readonly position: number; readonly first: boolean; readonly last: boolean; readonly busy: boolean; readonly readOnly: boolean; readonly onMove?: (dir: -1 | 1) => void; readonly onRemove?: () => void }) {
  return (
    <tr data-testid={`kh-step-${step.card_id}`}>
      <td>{position}</td>
      <td>
        <b>{step.step_label}</b> <span className="sa-hint">{step.title ?? step.change_kind}</span>
        {step.version_label ? <span className="sa-hint"> · {step.version_label}</span> : null}
        {step.floor_ok ? null : <TextChip tone="down">Chạm giá sàn</TextChip>}
      </td>
      <td data-testid="kh-step-margin">
        {num(step.margin_pct_before, (x) => pp(x))} → <b>{num(step.margin_pct_after, (x) => pp(x))}</b>
      </td>
      <td data-testid="kh-step-dstep">{num(step.dprofit_step_p50, sv)}</td>
      <td data-testid="kh-step-dtotal">{num(step.dprofit_total_p50, sv)}</td>
      <td>
        {readOnly ? null : (
          <span style={{ display: "inline-flex", gap: 4 }}>
            <button aria-label={`Lên: ${step.step_label}`} className="sa-btn sa-btn--s" disabled={busy || first || !onMove} onClick={() => onMove?.(-1)} type="button">
              Lên
            </button>
            <button aria-label={`Xuống: ${step.step_label}`} className="sa-btn sa-btn--s" disabled={busy || last || !onMove} onClick={() => onMove?.(1)} type="button">
              Xuống
            </button>
            <button aria-label={`Bỏ: ${step.step_label}`} className="sa-btn sa-btn--s" disabled={busy || !onRemove} onClick={() => onRemove?.()} type="button">
              Bỏ
            </button>
          </span>
        )}
      </td>
    </tr>
  );
}

export function PlanSteps({ plan, api, busy, done, onAct }: { readonly plan: PlanResponse; readonly api: PlanApi; readonly busy: boolean; readonly done: boolean; readonly onAct: (call: () => Promise<PlanResponse>) => Promise<void> }) {
  const products = productsWithSteps(plan);
  if (products.length === 0) return null;
  const planIndex = new Map(plan.cards.map((c, i) => [c.card_id, i + 1]));
  const shop = plan.aggregate?.steps_summary?.shop;
  return (
    <div data-testid="kh-steps">
      <h3 className="sa-h2">Từng bước, gối lên nhau</h3>
      {products.map((p) => {
        const steps = p.steps!;
        return (
          <section className="sa-card" data-testid={`kh-steps-${p.product_id}`} key={p.product_id}>
            <div className="kh-plan__head">
              <b>{p.name ?? p.product_id}</b>
              {steps.custom_order ? <TextChip tone="info">Thứ tự tự chọn</TextChip> : null}
            </div>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ textAlign: "left" }}>
                  <th>#</th>
                  <th>Bước</th>
                  <th>Biên sau bước</th>
                  <th>Δ lợi nhuận bước này</th>
                  <th>Δ lợi nhuận tích luỹ</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {steps.items.map((s, i) => (
                  <StepRow
                    busy={busy}
                    first={i === 0}
                    key={s.card_id}
                    last={i === steps.items.length - 1}
                    onMove={
                      api.move
                        ? (dir) => {
                            const other = steps.items[i + dir];
                            const target = other ? planIndex.get(other.card_id) : undefined;
                            if (target !== undefined) void onAct(() => api.move!(s.card_id, target));
                          }
                        : undefined
                    }
                    onRemove={() => void onAct(() => api.remove(s.card_id))}
                    position={s.index}
                    readOnly={done}
                    step={s}
                  />
                ))}
              </tbody>
              <tfoot>
                <tr data-testid={`kh-steps-total-${p.product_id}`}>
                  <td />
                  <td>
                    <b>Tổng sản phẩm</b>
                  </td>
                  <td>
                    {num(steps.total.margin_pct_before, (x) => pp(x))} → <b>{num(steps.total.margin_pct_after, (x) => pp(x))}</b>
                  </td>
                  <td />
                  <td data-testid="kh-steps-total-p50">
                    <b>{num(steps.total.dprofit_p50, sv)}</b>
                    <span className="sa-hint"> · chắc chắn {num(steps.total.dprofit_certain, sv)}</span>
                  </td>
                  <td />
                </tr>
              </tfoot>
            </table>
          </section>
        );
      })}
      {shop ? (
        <p data-testid="kh-steps-shop">
          <b>Cả shop ({shop.products} sản phẩm):</b> Δ lợi nhuận {num(shop.dprofit_p50, sv)} · chắc chắn {num(shop.dprofit_certain, sv)} · biên sau {shop.margin_pct_after === null ? DASH : pp(shop.margin_pct_after)}
        </p>
      ) : null}
    </div>
  );
}
