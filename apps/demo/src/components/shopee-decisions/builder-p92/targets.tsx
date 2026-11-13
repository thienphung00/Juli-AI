"use client";

import { DASH, fmt, sv } from "../../../lib/shopee-analytics/format";
import type { BuilderOutcome, OutcomeTarget } from "../../../lib/shopee-decisions/builder-api";
import { MAX_TARGETS, floorWarningText, refusalText } from "../../../lib/shopee-decisions/builder-p92";
import type { PanelCtx } from "./shared";
import { TablePicker } from "./table-picker";

/**
 * P97 D85.13 · one card, many targets. `ProductTargets` is the picker a many-target form shows (the same
 * table picker as step ①); `TargetRows` is the card's result under the total: a row per target with its
 * own figures and floor breaches, and a checkbox to untick a target (the card is then evaluated again).
 */

export function ProductTargets({ ctx, selected, onChange, title, hint, max = MAX_TARGETS }: { readonly ctx: PanelCtx; readonly selected: readonly string[]; readonly onChange: (ids: readonly string[]) => void; readonly title: string; readonly hint?: string; readonly max?: number }) {
  return (
    <div className="p2-targets" data-testid="p2-targets">
      <TablePicker max={max} mode="multi" onChange={onChange} products={ctx.products} selected={selected} title={title} />
    </div>
  );
}

export function targetsOf(o: BuilderOutcome | null | undefined): readonly OutcomeTarget[] {
  return o?.targets ?? [];
}

const figure = (t: OutcomeTarget, key: "dgmv_p50" | "dprofit_p50" | "cost_month"): string => {
  const n = t[key];
  return n === null || n === undefined ? DASH : key === "cost_month" ? sv(n === 0 ? 0 : n) : sv(n);
};

export function TargetRows({ outcome, onUntick, disabled }: { readonly outcome: BuilderOutcome; readonly onUntick?: (id: string) => void; readonly disabled?: boolean }) {
  const rows = targetsOf(outcome);
  if (rows.length === 0) return null;
  const joint = outcome.targets_mode === "joint";
  const bad = rows.filter((r) => r.breach).length;
  return (
    <div className="p2-trows" data-testid="p2-trows">
      <b>
        {joint ? "Từng sản phẩm" : "Từng đối tượng"} ({fmt(rows.length)})
      </b>
            {bad > 0 ? (
        <p className="sd-check sd-check--bad" role="alert">
          <span>
            <b>Chạm giá sàn:</b> {fmt(bad)} đối tượng. Bỏ tick đối tượng đó để tính lại, hoặc giữ và xác nhận khi chọn.
          </span>
        </p>
      ) : null}
      <ul className="p2-trows__list">
        <li className="p2-trow p2-trow--head" aria-hidden="true">
          <span />
          <span>Đối tượng</span>
          <span>Δ GMV (P50)</span>
          <span>Δ lợi nhuận (P50)</span>
          <span>Chi phí</span>
        </li>
        {rows.map((t) => (
          <li className={`p2-trow ${t.breach ? "p2-trow--bad" : ""}`} data-testid={`p2-trow-${t.id}`} key={t.id}>
            <input aria-label={`Áp dụng cho ${t.name ?? t.id}`} checked disabled={disabled || !onUntick} onChange={() => onUntick?.(t.id)} type="checkbox" />
            <span className="p2-trow__name">
              <b>{t.name ?? t.id}</b>
              <span className="sa-hint">{t.id}</span>
            </span>
            {t.ok ? (
              <>
                <span data-label="Δ GMV">{figure(t, "dgmv_p50")}</span>
                <span data-label="Δ lợi nhuận">{t.dprofit_p50 === null || t.dprofit_p50 === undefined ? "chưa tính" : figure(t, "dprofit_p50")}</span>
                <span data-label="Chi phí">{figure(t, "cost_month")}</span>
                {t.breach ? (
                  <span className="p2-trow__warn" role="alert">
                    Chạm giá sàn: {(t.breaches ?? []).map(floorWarningText).join(" ")}
                  </span>
                ) : null}
              </>
            ) : (
              <span className="sd-error p2-trow__warn" role="alert">
                {refusalText({ refusal: t.refusal ?? null })}
              </span>
            )}
          </li>
        ))}
      </ul>
      {outcome.fill ? (
        <p className="sa-hint" data-testid="p2-fill-mode">
          {outcome.fill.mode === "bulk" ? "Điền hàng loạt: 1 lượt" : `Số lượt điền: ${fmt(outcome.fill.targets)}`}
        </p>
      ) : null}
    </div>
  );
}
