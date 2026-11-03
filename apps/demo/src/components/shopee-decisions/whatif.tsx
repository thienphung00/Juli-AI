"use client";

import { fmt } from "../../lib/shopee-analytics/format";
import { sliderText } from "../../lib/shopee-decisions/model";
import type { Card, SliderRow } from "../../lib/shopee-decisions/types";

/**
 * The what-if inputs of one card. The sliders come from the card (`whatif.sliders`: min / max /
 * step per change kind - voucher value and max, minimum spend, quantity, days; promotion and sale
 * discount; ads budget and ROAS target; combo tiers; affiliate commission). A voucher adds the
 * value type (đ or %) and the per-user limit, which Seller Centre data cannot confirm.
 */

export type Patch = Readonly<Record<string, unknown>>;

function valueOf(card: Card, patch: Patch, key: string): number | null {
  const v = key in patch ? patch[key] : card.inputs[key];
  return typeof v === "number" ? v : null;
}

function SliderField({ s, value, disabled, onChange }: { readonly s: SliderRow; readonly value: number | null; readonly disabled: boolean; readonly onChange: (next: number) => void }) {
  const shown = value ?? s.min;
  return (
    <div className="sd-field" data-testid={`sd-field-${s.key}`}>
      <label className="sd-field__label" htmlFor={`sd-${s.key}`}>
        {s.label}
      </label>
      <b className="sd-field__value">{value === null ? "Chưa đặt" : sliderText(s, value)}</b>
      <input
        aria-label={s.label}
        disabled={disabled}
        id={`sd-${s.key}`}
        max={s.max}
        min={s.min}
        onChange={(event) => onChange(Number(event.target.value))}
        step={s.step}
        type="range"
        value={shown}
      />
      <div className="sd-field__range">
        <span>{sliderText(s, s.min)}</span>
        <span>{sliderText(s, s.max)}</span>
      </div>
    </div>
  );
}

function Stepper({ label, value, unit, disabled, min, max, onChange }: { readonly label: string; readonly value: number; readonly unit: string; readonly disabled: boolean; readonly min: number; readonly max: number; readonly onChange: (n: number) => void }) {
  return (
    <span className="sd-stepper">
      <button aria-label={`Giảm ${label}`} disabled={disabled || value <= min} onClick={() => onChange(value - 1)} type="button">
        −
      </button>
      <b>{`${fmt(value, 0)} ${unit}`}</b>
      <button aria-label={`Tăng ${label}`} disabled={disabled || value >= max} onClick={() => onChange(value + 1)} type="button">
        +
      </button>
    </span>
  );
}

/** A % voucher is capped per order; the generator leaves the cap out of a fixed-value card. */
const MAX_VALUE_SLIDER: SliderRow = { key: "max_value", label: "Mức giảm tối đa", unit: "vnd", min: 1_000, max: 500_000, step: 1_000, default: null };

export function WhatIfPanel({ card, patch, disabled, onChange }: { readonly card: Card; readonly patch: Patch; readonly disabled: boolean; readonly onChange: (next: Patch) => void }) {
  const isVoucher = card.family === "voucher";
  const hasMax = isVoucher && card.change_kind === "min_spend_voucher";
  const sliders = hasMax && !card.whatif.sliders.some((s) => s.key === "max_value") ? [...card.whatif.sliders, MAX_VALUE_SLIDER] : card.whatif.sliders;
  const pct = valueOf(card, patch, "pct");
  const isPct = pct !== null;
  const value = valueOf(card, patch, "value");
  const perUser = valueOf(card, patch, "per_user_limit") ?? 1;

  if (sliders.length === 0 && !isVoucher) {
    return (
      <div className="sd-whatif" data-testid="sd-whatif">
        <p className="sa-hint">Thẻ này không có thông số để chỉnh: chỉ duyệt hoặc từ chối.</p>
      </div>
    );
  }
  return (
    <div className="sd-whatif" data-testid="sd-whatif">
      {isVoucher && hasMax ? (
        <div className="sd-field" data-testid="sd-voucher-type">
          <span className="sd-field__label">Giá trị voucher</span>
          <span className="sa-seg sa-seg--round">
            <button
              aria-pressed={!isPct}
              className={`sa-seg__item ${!isPct ? "sa-seg__item--on" : ""}`}
              disabled={disabled}
              onClick={() => onChange({ ...patch, pct: null, value: value ?? valueOf(card, patch, "max_value") ?? 10_000 })}
              type="button"
            >
              đ
            </button>
            <button
              aria-pressed={isPct}
              className={`sa-seg__item ${isPct ? "sa-seg__item--on" : ""}`}
              disabled={disabled}
              onClick={() => onChange({ ...patch, pct: pct ?? 10, value: null, max_value: valueOf(card, patch, "max_value") ?? value ?? 20_000 })}
              type="button"
            >
              %
            </button>
          </span>
        </div>
      ) : null}
      {isVoucher && hasMax && isPct ? (
        <div className="sd-field" data-testid="sd-field-pct">
          <label className="sd-field__label" htmlFor="sd-pct">
            Giảm theo % đơn
          </label>
          <b className="sd-field__value">{`${fmt(pct, 0)}%`}</b>
          <input aria-label="Giảm theo % đơn" disabled={disabled} id="sd-pct" max={50} min={1} onChange={(event) => onChange({ ...patch, pct: Number(event.target.value), value: null })} step={1} type="range" value={pct} />
          <div className="sd-field__range">
            <span>1%</span>
            <span>50%</span>
          </div>
        </div>
      ) : null}
      {sliders.map((s) => {
        // A % voucher has no fixed value: the cap (max) is its lever. A fixed one has no cap.
        if (isVoucher && hasMax && s.key === "value" && isPct) return null;
        if (isVoucher && hasMax && s.key === "max_value" && !isPct) return null;
        return <SliderField disabled={disabled} key={s.key} onChange={(next) => onChange({ ...patch, [s.key]: next })} s={s} value={valueOf(card, patch, s.key)} />;
      })}
      {isVoucher ? (
        <div className="sd-field" data-testid="sd-field-per-user">
          <span className="sd-field__label">Giới hạn mỗi người</span>
          <Stepper disabled={disabled} label="giới hạn mỗi người" max={10} min={1} onChange={(n) => onChange({ ...patch, per_user_limit: n })} unit="lần" value={perUser} />
          <span className="sd-field__note">Không kiểm được từ dữ liệu: Seller Centre không cho biết một khách dùng mấy lần, nên số này không đổi con số nào trên thẻ.</span>
        </div>
      ) : null}
    </div>
  );
}
