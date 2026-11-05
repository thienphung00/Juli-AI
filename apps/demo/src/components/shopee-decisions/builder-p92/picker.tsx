"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { fmt, vnd } from "../../../lib/shopee-analytics/format";
import type { PickerProduct, ProductSort, VariationList, VariationRow } from "../../../lib/shopee-decisions/builder-api";
import { VariationCompare } from "./variations";

/**
 * ① Chọn sản phẩm and ② Phân loại (artboards `TuTaoPhuongAnP92` / `…Mobile`): every active listing Juli knows
 * (not only those sold in the last 30 days), sorted by 90-day GMV, searchable, with the "thiếu giá vốn" and
 * "không bán 30 ngày qua" chips; then the variation picker with the collapsed "So sánh phân loại".
 */

const SORTS: readonly (readonly [ProductSort, string])[] = [
  ["gmv_90d", "GMV 90 ngày"],
  ["orders_90d", "Đơn 90 ngày"],
  ["orders_30d", "Đơn 30 ngày"],
  ["name", "Tên A–Z"],
];

type Filter = "all" | "missing" | "idle";
const SHOWN = 9;

const idle = (p: PickerProduct): boolean => p.orders_30d === 0;
const missing = (p: PickerProduct): boolean => p.missing_cost_chip !== null || !p.has_cost;

export function sortProducts(list: readonly PickerProduct[], sort: ProductSort): PickerProduct[] {
  const key = (p: PickerProduct): number => (sort === "gmv_90d" ? (p.gmv_90d ?? -1) : sort === "orders_90d" ? p.orders_90d : p.orders_30d);
  return [...list].sort((a, b) => (sort === "name" ? a.name.localeCompare(b.name, "vi") : key(b) - key(a)));
}

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
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<ProductSort>("gmv_90d");
  const [filter, setFilter] = useState<Filter>("all");
  const [all, setAll] = useState(false);
  const counts = useMemo(() => ({ all: products.length, missing: products.filter(missing).length, idle: products.filter(idle).length }), [products]);
  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const filtered = products.filter((p) => (filter === "missing" ? missing(p) : filter === "idle" ? idle(p) : true) && (!needle || p.name.toLowerCase().includes(needle) || p.item_id.includes(needle)));
    return sortProducts(filtered, sort);
  }, [products, q, sort, filter]);
  const shown = all || q.trim() || filter !== "all" ? rows : rows.slice(0, SHOWN);
  const sortLabel = SORTS.find(([k]) => k === sort)![1];
  return (
    <section className="sa-card p2-picker" data-testid="p2-picker">
      <div className="sa-card__head">
        <h2 className="sa-h2">① Chọn sản phẩm</h2>
        <span className="sa-hint" data-testid="p2-picker-count">
          {products.length} sản phẩm đang bán · xếp theo {sortLabel}
        </span>
      </div>
      <div className="p2-picker__bar">
        <input aria-label="Tìm sản phẩm theo tên hoặc mã" className="p2-text" onChange={(e) => setQ(e.target.value)} placeholder="⌕ Tìm theo tên hoặc mã sản phẩm" type="search" value={q} />
        <label className="p2-picker__sort">
          <span className="sa-hint">Xếp theo:</span>
          <select aria-label="Xếp theo" onChange={(e) => setSort(e.target.value as ProductSort)} value={sort}>
            {SORTS.map(([k, label]) => (
              <option key={k} value={k}>
                {label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="sb-chips" role="group" aria-label="Lọc">
        {(
          [
            ["all", `Tất cả ${counts.all}`],
            ["missing", `Thiếu giá vốn ${counts.missing}`],
            ["idle", `Không bán 30 ngày qua ${counts.idle}`],
          ] as const
        ).map(([k, label]) => (
          <button aria-pressed={filter === k} className={`sb-pill ${filter === k ? "sb-pill--dark" : ""}`} key={k} onClick={() => setFilter(k)} type="button">
            {label}
          </button>
        ))}
      </div>
      <ul className="p2-plist" data-testid="p2-plist">
        <li className="p2-prow p2-prow--head" aria-hidden="true">
          <span>Sản phẩm · mã sản phẩm</span>
          <span>GMV 90 ngày</span>
          <span>Đơn 30 ngày</span>
          <span>Đơn 90 ngày</span>
          <span>Giá vốn</span>
        </li>
        {shown.map((p) => (
          <li key={p.item_id}>
            <button aria-label={`${p.name} ${p.item_id}`} className="p2-prow" data-testid={`p2-prod-${p.item_id}`} onClick={() => onPick(p)} type="button">
              <span className="p2-prow__name">
                <b>{p.name}</b>
                <span className="sa-hint">{p.item_id}</span>
                {idle(p) ? <span className="sa-chip sa-chip--flat">không bán 30 ngày qua</span> : null}
              </span>
              <span data-label="GMV 90 ngày">{vnd(p.gmv_90d)}</span>
              <span data-label="Đơn 30 ngày">{fmt(p.orders_30d)}</span>
              <span data-label="Đơn 90 ngày">{fmt(p.orders_90d)}</span>
              <span className={`sa-chip ${missing(p) ? "sa-chip--warn" : "sa-chip--up"}`}>{missing(p) ? (p.missing_cost_chip ?? "thiếu giá vốn") : "có giá vốn"}</span>
            </button>
          </li>
        ))}
        {shown.length === 0 ? <li className="sa-hint">Không có sản phẩm khớp.</li> : null}
      </ul>
      <p className="sa-hint" data-testid="p2-picker-foot">
        Hiện {shown.length} trong {rows.length} sản phẩm đang bán
        {shown.length < rows.length ? (
          <>
            {" "}
            ·{" "}
            <button className="sa-link p2-linkbtn" onClick={() => setAll(true)} type="button">
              Xem thêm {rows.length - shown.length} sản phẩm ›
            </button>
          </>
        ) : null}{" "}
        · Danh sách gồm mọi sản phẩm Juli biết (danh mục từ Connector và các dòng đơn), kể cả sản phẩm không có đơn 30 ngày qua.
      </p>
      <p className="sa-hint">Sản phẩm “thiếu giá vốn” vẫn chọn được; lợi nhuận và biên hiện “chưa tính” cho đến khi nhập giá vốn ở Cài đặt › Thông số shop.</p>
      {excludedHidden > 0 ? (
        <p className="sa-hint" data-testid="p2-excluded-note">
          Đã loại trừ {excludedHidden} sản phẩm (ngừng bán, quà tặng, hàng phân phối, khác): không hiện ở đây, không có thẻ hay cờ Phân tích. Tổng GMV và lợi nhuận vẫn gồm đơn của chúng.{" "}
          {exclusionsHref ? (
            <Link className="sa-link" href={exclusionsHref}>
              Quản lý ở Cài đặt › Loại trừ sản phẩm ›
            </Link>
          ) : null}
        </p>
      ) : null}
    </section>
  );
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
