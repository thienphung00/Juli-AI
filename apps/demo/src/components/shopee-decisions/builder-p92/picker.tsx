"use client";

import { useState } from "react";

import { fmt, vnd } from "../../../lib/shopee-analytics/format";
import type { PickerProduct, VariationList, VariationRow } from "../../../lib/shopee-decisions/builder-api";
import { TablePicker } from "./table-picker";
import { VariationCompare } from "./variations";

/**
 * ① Chọn sản phẩm and ② Phân loại (artboards `TuTaoPhuongAnP92` / `…Mobile`): every active listing Juli knows
 * (not only those sold in the last 30 days), sorted by 90-day GMV, searchable, with the "thiếu giá vốn" and
 * "không bán 30 ngày qua" chips; then the variation picker with the collapsed "So sánh phân loại".
 */

export { sortProducts } from "../../../lib/shopee-decisions/picker-table";

export function Steps({ step }: { readonly step: 1 | 2 | 3 | 4 }) {
  const names = ["① Sản phẩm", "② Phân loại", "③ Loại chiến lược", "④ Nhập thông số"];
  return (
    <ol className="p2-steps" aria-label="Các bước">
      {names.map((n, i) => (
        <li aria-current={step === i + 1 ? "step" : undefined} className={`p2-step ${step === i + 1 ? "p2-step--on" : ""}`} key={n}>
          {n}
        </li>
      ))}
    </ol>
  );
}

/** ① Chọn sản phẩm: the shared table picker in one-click mode (P97 D85.12). */
export function ProductPicker({
  products,
  excludedHidden,
  exclusionsHref,
  onPick,
}: {
  readonly products: readonly PickerProduct[];
  readonly excludedHidden: number;
  readonly exclusionsHref: string | null;
  readonly onPick: (p: PickerProduct) => void;
}) {
  return <TablePicker excludedHidden={excludedHidden} exclusionsHref={exclusionsHref} mode="single" onPick={onPick} products={products} />;
}

export function ProductStrip({ product, onChange }: { readonly product: PickerProduct; readonly onChange: () => void }) {
  return (
    <div className="p2-strip" data-testid="p2-strip-product">
      <span className="p2-strip__tag">① SẢN PHẨM</span>
      <b>{product.name}</b>
      <span className="sa-hint">
        {product.item_id} · {product.has_cost ? "có giá vốn" : "thiếu giá vốn"} · {fmt(product.orders_30d)} đơn / 30 ngày · {fmt(product.orders_90d)} đơn / 90 ngày
      </span>
      <button className="sa-btn sa-btn--s" onClick={onChange} type="button">
        Đổi
      </button>
    </div>
  );
}

export function VariationStrip({ variations, all, onChange }: { readonly variations: readonly VariationRow[]; readonly all: boolean; readonly onChange: () => void }) {
  const one = !all && variations.length === 1 ? variations[0] : null;
  return (
    <div className="p2-strip" data-testid="p2-strip-variation">
      <span className="p2-strip__tag">② PHÂN LOẠI</span>
      <b>{all ? "Tất cả phân loại" : variations.map((v) => v.name).join(", ")}</b>
      {one ? (
        <span className="sa-hint">
          {vnd(one.selling_price)} · {one.price_per_unit !== null ? `${vnd(one.price_per_unit)}/đơn vị` : "—"} · biên {one.margin_pct !== null ? `${fmt(one.margin_pct, 1)}%` : (one.margin_label ?? "chưa tính")}
        </span>
      ) : null}
      <button className="sa-btn sa-btn--s" onClick={onChange} type="button">
        Đổi
      </button>
    </div>
  );
}

export function VariationStep({
  list,
  selected,
  all,
  onToggle,
  onAll,
  costLink,
  onNext,
}: {
  readonly list: VariationList;
  readonly selected: readonly string[];
  readonly all: boolean;
  readonly onToggle: (id: string) => void;
  readonly onAll: () => void;
  readonly costLink: string;
  readonly onNext: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <section className="sa-card p2-vstep" data-testid="p2-vstep">
      <div className="sa-card__head">
        <h2 className="sa-h2">② Phân loại</h2>
        <span className="sa-hint">Chiến lược áp dụng cho phân loại bạn chọn</span>
      </div>
      <div className="sb-chips" role="group" aria-label="Phân loại">
        {list.variations.map((v) => {
          const on = all || selected.includes(v.variation_id);
          return (
            <button aria-pressed={on} className={`sb-pill ${on ? "sb-pill--on" : ""}`} key={v.variation_id || "default"} onClick={() => onToggle(v.variation_id)} type="button">
              {on ? "✓ " : ""}
              {v.name}
            </button>
          );
        })}
        {list.variations.length > 1 ? (
          <button aria-pressed={all} className={`sb-pill ${all ? "sb-pill--on" : ""}`} onClick={onAll} type="button">
            Tất cả phân loại
          </button>
        ) : null}
      </div>
      <button aria-expanded={open} className="sa-btn sa-btn--s p2-expand__btn" data-testid="p2-vcmp-toggle" onClick={() => setOpen((o) => !o)} type="button">
        So sánh phân loại {open ? "▾" : "▸"}
      </button>
      {open ? <VariationCompare costLink={costLink} data={list} /> : null}
      <p className="sa-hint">Mặc định chọn một phân loại. Có thể chọn nhiều phân loại hoặc “Tất cả phân loại”.</p>
      <div className="sd-actions">
        <button className="sa-btn sa-btn--primary" data-testid="p2-vnext" disabled={!all && selected.length === 0} onClick={onNext} type="button">
          Chọn loại chiến lược ›
        </button>
      </div>
    </section>
  );
}
