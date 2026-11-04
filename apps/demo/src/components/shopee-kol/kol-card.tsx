"use client";

import { fmt, vnd } from "../../lib/shopee-analytics/format";
import type { SliderRow } from "../../lib/shopee-decisions/types";
import { pctText } from "../../lib/shopee-kol/model";
import type { KolBlock } from "../../lib/shopee-kol/types";

/**
 * What-if inputs of a "Gửi mẫu cho KOL" / "Mời KOL" card (`CardKOL.dc.html`): the product, the number of
 * samples (a sample only) and the commission. Each change goes to the what-if of the selected version
 * as `{item_id, qty, commission_pct}` (the card's input keys); the bounds come from the card's sliders.
 */

export type KolPatch = Readonly<Record<string, unknown>>;

const bounds = (sliders: readonly SliderRow[], key: string, fallback: { min: number; max: number; step: number }) => {
  const s = sliders.find((x) => x.key === key);
  return { min: s?.min ?? fallback.min, max: s?.max ?? fallback.max, step: s?.step ?? fallback.step };
};

export function KolWhatIf({ block, sliders, patch, disabled, onChange }: { readonly block: KolBlock; readonly sliders: readonly SliderRow[]; readonly patch: KolPatch; readonly disabled: boolean; readonly onChange: (next: KolPatch) => void }) {
  const qb = bounds(sliders, "qty", { min: 1, max: 50, step: 1 });
  const rb = bounds(sliders, "commission_pct", { min: 0, max: 50, step: 0.5 });
  const qty = typeof patch["qty"] === "number" ? (patch["qty"] as number) : block.qty;
  const rate = typeof patch["commission_pct"] === "number" ? (patch["commission_pct"] as number) : block.commission_pct;
  const pid = typeof patch["item_id"] === "string" ? (patch["item_id"] as string) : block.product.item_id;
  const sample = block.sample;
  const unit = sample ? sample.unit_cogs + sample.unit_packaging : null;
  return (
    <div className="kolc" data-testid="kol-whatif">
      <div className="sb-field">
        <span className="sd-field__label">Sản phẩm</span>
        <div className="sb-chips">
          {block.choices.map((o) => (
            <button aria-pressed={pid === o.value} className={`sb-pill ${pid === o.value ? "sb-pill--on" : ""}`} disabled={disabled} key={o.value} onClick={() => onChange({ ...patch, item_id: o.value })} type="button">
              {o.label} · khoảng {fmt(o.orders_p50, 1)} đơn/tháng
            </button>
          ))}
        </div>
      </div>
      {block.invite ? null : (
        <div className="sb-field">
          <span className="sd-field__label">Số lượng mẫu</span>
          <span className="sd-stepper">
            <button aria-label="Giảm số mẫu" disabled={disabled || qty <= qb.min} onClick={() => onChange({ ...patch, qty: Math.max(qb.min, qty - qb.step) })} type="button">
              −
            </button>
            <b>{qty} mẫu</b>
            <button aria-label="Tăng số mẫu" disabled={disabled || qty >= qb.max} onClick={() => onChange({ ...patch, qty: Math.min(qb.max, qty + qb.step) })} type="button">
              +
            </button>
          </span>
          {sample && unit !== null ? (
            <span className="sa-hint" data-testid="kol-sample-formula">
              Chi phí mẫu = {qty} × (giá vốn + đóng gói {vnd(unit)}) + ship {vnd(sample.ship_fee)} = <b>{vnd(qty * unit + sample.ship_fee)}</b>
            </span>
          ) : null}
        </div>
      )}
      <div className="sb-field">
        <label className="sd-field__label" htmlFor="kol-rate">
          Hoa hồng cho KOL
        </label>
        <b className="sd-field__value">{pctText(rate)}</b>
        <input aria-label="Hoa hồng" disabled={disabled} id="kol-rate" max={rb.max} min={rb.min} onChange={(e) => onChange({ ...patch, commission_pct: Number(e.target.value) })} step={rb.step} type="range" value={rate} />
        <span className="sa-hint">
          Mức hiện tại của sản phẩm {block.commission_pct_current === null ? "—" : pctText(block.commission_pct_current)}. Hoa hồng tính trên mỗi sản phẩm bán ra, theo mức áp dụng cho sản phẩm đó.
        </span>
      </div>
    </div>
  );
}
