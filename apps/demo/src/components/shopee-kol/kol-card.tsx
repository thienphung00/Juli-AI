"use client";

import { fmt, vnd } from "../../lib/shopee-analytics/format";
import type { KolCert } from "../../lib/shopee-kol/types";

/**
 * What-if inputs of a "Gửi mẫu cho KOL" / "Mời KOL" card (`CardKOL.dc.html`): the product, the number of
 * samples (a sample only) and the commission. Each change goes to the what-if of the selected version
 * as `{product_id, qty, commission_pct}` (assumed input keys).
 */

export type KolPatch = Readonly<Record<string, unknown>>;

export function KolWhatIf({ cert, patch, disabled, onChange }: { readonly cert: KolCert; readonly patch: KolPatch; readonly disabled: boolean; readonly onChange: (next: KolPatch) => void }) {
  const qty = typeof patch["qty"] === "number" ? (patch["qty"] as number) : (cert.qty ?? 1);
  const rate = typeof patch["commission_pct"] === "number" ? (patch["commission_pct"] as number) : cert.commission_pct;
  const pid = typeof patch["product_id"] === "string" ? (patch["product_id"] as string) : cert.product_id;
  const unit = cert.sample.unit_cost;
  const ship = cert.sample.ship;
  return (
    <div className="kolc" data-testid="kol-whatif">
      <div className="sb-field">
        <span className="sd-field__label">Sản phẩm</span>
        <div className="sb-chips">
          {cert.product_options.map((o) => (
            <button aria-pressed={pid === o.product_id} className={`sb-pill ${pid === o.product_id ? "sb-pill--on" : ""}`} disabled={disabled} key={o.product_id} onClick={() => onChange({ ...patch, product_id: o.product_id, commission_pct: o.commission_pct })} type="button">
              {o.name} · hoa hồng {fmt(o.commission_pct, 0)}%
            </button>
          ))}
        </div>
      </div>
      {cert.invite ? null : (
        <div className="sb-field">
          <span className="sd-field__label">Số lượng mẫu</span>
          <span className="sd-stepper">
            <button aria-label="Giảm số mẫu" disabled={disabled || qty <= 1} onClick={() => onChange({ ...patch, qty: Math.max(1, qty - 1) })} type="button">
              −
            </button>
            <b>{qty} mẫu</b>
            <button aria-label="Tăng số mẫu" disabled={disabled || qty >= 10} onClick={() => onChange({ ...patch, qty: Math.min(10, qty + 1) })} type="button">
              +
            </button>
          </span>
          <span className="sa-hint" data-testid="kol-sample-formula">
            Chi phí mẫu = {qty} × (giá vốn + đóng gói {vnd(unit)}) + ship {vnd(ship)} = <b>{vnd(typeof unit === "number" && typeof ship === "number" ? qty * unit + ship : cert.sample.cost)}</b>
          </span>
        </div>
      )}
      <div className="sb-field">
        <label className="sd-field__label" htmlFor="kol-rate">
          Hoa hồng cho KOL
        </label>
        <b className="sd-field__value">{fmt(rate, 0)}%</b>
        <input aria-label="Hoa hồng" disabled={disabled} id="kol-rate" max={20} min={5} onChange={(e) => onChange({ ...patch, commission_pct: Number(e.target.value) })} step={1} type="range" value={rate} />
        <span className="sa-hint">
          Mức hiện tại của sản phẩm {cert.current_commission_pct === null ? "—" : `${fmt(cert.current_commission_pct, 0)}%`}. Hoa hồng tính trên mỗi sản phẩm bán ra, theo mức áp dụng cho sản phẩm đó.
        </span>
      </div>
    </div>
  );
}
