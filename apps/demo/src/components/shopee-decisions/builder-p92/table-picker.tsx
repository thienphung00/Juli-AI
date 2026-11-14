"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { shopeeImageSrc } from "../../../lib/shopee-analytics/image-src";
import { fmt, pp, vnd } from "../../../lib/shopee-analytics/format";
import type { PickerProduct, ProductSort } from "../../../lib/shopee-decisions/builder-api";
import { MARGIN_BANDS, NO_FILTERS, addIds, categoriesOf, filterProducts, filtersActive, isIdle, isMissingCost, matchPasted, removeId, type MarginBand, type PickerFilters } from "../../../lib/shopee-decisions/picker-table";

/**
 * P97 D85.12 · ONE table picker for every kind: search by name or ID; filters (ngành hàng, biên,
 * CTOR giảm, có đề xuất, đang chạy QC / KOL); rows with GMV, biên and tồn kho; "chọn tất cả theo bộ
 * lọc"; a pasted list of ids; the selection stays visible with its count and ×.
 *
 * `single`: a click on a row picks it (step ① of the builder). `multi`: checkbox rows and a
 * selection list (targets of a card, partners of a combo, products of a voucher ...).
 */

const SORTS: readonly (readonly [ProductSort, string])[] = [
  ["gmv_90d", "GMV 90 ngày"],
  ["orders_90d", "Đơn 90 ngày"],
  ["orders_30d", "Đơn 30 ngày"],
  ["name", "Tên A–Z"],
];

const SHOWN = 9;
const SHOWN_MULTI = 30;

interface Common {
  readonly products: readonly PickerProduct[];
  readonly title?: string;
  readonly excludedHidden?: number;
  readonly exclusionsHref?: string | null;
  /** Ids that cannot be chosen here (already the main product, already in the combo ...). */
  readonly disabled?: readonly string[];
}

export type TablePickerProps = Common &
  (
    | { readonly mode: "single"; readonly onPick: (p: PickerProduct) => void }
    | { readonly mode: "multi"; readonly selected: readonly string[]; readonly onChange: (ids: readonly string[]) => void; readonly max?: number }
  );

function ProductThumb({ src }: { readonly src: string | null | undefined }) {
  const image = shopeeImageSrc(src);
  return image ? <img alt="" className="p2-prow__img" src={image} /> : null;
}

const marginText = (p: PickerProduct): string => (p.margin_pct === null || p.margin_pct === undefined || !p.has_cost ? "chưa tính" : pp(p.margin_pct, 1));

export function TablePicker(props: TablePickerProps) {
  const { products, mode } = props;
  const [filters, setFilters] = useState<PickerFilters>(NO_FILTERS);
  const [sort, setSort] = useState<ProductSort>("gmv_90d");
  const [all, setAll] = useState(false);
  const [paste, setPaste] = useState("");
  const [pasteNote, setPasteNote] = useState<string | null>(null);
  const set = (patch: Partial<PickerFilters>) => setFilters((f) => ({ ...f, ...patch }));
  const disabled = useMemo(() => new Set(props.disabled ?? []), [props.disabled]);
  const selected = mode === "multi" ? props.selected : [];
  const max = mode === "multi" ? props.max : undefined;

  const categories = useMemo(() => categoriesOf(products), [products]);
  const counts = useMemo(
    () => ({
      all: products.length,
      missing: products.filter(isMissingCost).length,
      idle: products.filter(isIdle).length,
      ctorDown: products.filter((p) => p.ctor_down === true).length,
      hasProposal: products.filter((p) => p.has_proposal === true).length,
      inAds: products.filter((p) => p.in_ads === true).length,
      inKol: products.filter((p) => p.in_kol === true).length,
    }),
    [products],
  );
  const rows = useMemo(() => filterProducts(products, filters, sort), [products, filters, sort]);
  const limit = mode === "single" ? SHOWN : SHOWN_MULTI;
  const shown = all || filtersActive(filters) ? rows : rows.slice(0, limit);
  const sortLabel = SORTS.find(([k]) => k === sort)![1];
  const byId = useMemo(() => new Map(products.map((p) => [p.item_id, p])), [products]);

  const change = (ids: readonly string[]) => {
    if (mode === "multi") props.onChange(max !== undefined ? ids.slice(0, max) : ids);
  };
  const toggle = (id: string) => change(selected.includes(id) ? removeId(selected, id) : addIds(selected, [id], max));
  const pickable = rows.filter((p) => !disabled.has(p.item_id));
  const selectFiltered = () => change(addIds(selected, pickable.map((p) => p.item_id), max));
  const pasteIds = () => {
    const { found, missing } = matchPasted(
      products.filter((p) => !disabled.has(p.item_id)),
      paste,
    );
    change(addIds(selected, found, max));
    setPasteNote(
      `Đã chọn ${fmt(found.length)} mã${missing.length ? `; ${fmt(missing.length)} mã không tìm thấy hoặc không chọn được: ${missing.slice(0, 5).join(", ")}${missing.length > 5 ? "…" : ""}` : ""}.`,
    );
    setPaste("");
  };

  const chip = (key: keyof Pick<PickerFilters, "ctorDown" | "hasProposal" | "inAds" | "inKol">, label: string, n: number) => (
    <button aria-pressed={filters[key]} className={`sb-pill ${filters[key] ? "sb-pill--dark" : ""}`} key={key} onClick={() => set({ [key]: !filters[key] })} type="button">
      {label} {n}
    </button>
  );

  return (
    <section className="sa-card p2-picker" data-testid="p2-picker">
      <div className="sa-card__head">
        <h2 className="sa-h2">{props.title ?? (mode === "single" ? "① Chọn sản phẩm" : "Chọn sản phẩm")}</h2>
        <span className="sa-hint" data-testid="p2-picker-count">
          {products.length} sản phẩm đang bán · xếp theo {sortLabel}
        </span>
      </div>
      <div className="p2-picker__bar">
        <input aria-label="Tìm sản phẩm theo tên hoặc mã" className="p2-text" onChange={(e) => set({ q: e.target.value })} placeholder="⌕ Tìm theo tên hoặc mã sản phẩm" type="search" value={filters.q} />
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
        {categories.length > 0 ? (
          <label className="p2-picker__sort">
            <span className="sa-hint">Ngành hàng:</span>
            <select aria-label="Ngành hàng" onChange={(e) => set({ category: e.target.value })} value={filters.category}>
              <option value="">Tất cả ngành hàng</option>
              {categories.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <label className="p2-picker__sort">
          <span className="sa-hint">Biên:</span>
          <select aria-label="Biên" onChange={(e) => set({ margin: e.target.value as MarginBand })} value={filters.margin}>
            {MARGIN_BANDS.map(([k, label]) => (
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
          <button aria-pressed={filters.chip === k} className={`sb-pill ${filters.chip === k ? "sb-pill--dark" : ""}`} key={k} onClick={() => set({ chip: k })} type="button">
            {label}
          </button>
        ))}
        {chip("ctorDown", "CTOR giảm", counts.ctorDown)}
        {chip("hasProposal", "Có đề xuất", counts.hasProposal)}
        {chip("inAds", "Đang chạy QC", counts.inAds)}
        {chip("inKol", "Đang chạy KOL", counts.inKol)}
        {filtersActive(filters) ? (
          <button className="sa-link p2-linkbtn" onClick={() => setFilters(NO_FILTERS)} type="button">
            Bỏ bộ lọc
          </button>
        ) : null}
      </div>

      {mode === "multi" ? (
        <div className="p2-picker__bulk">
          <button className="sa-btn sa-btn--s" data-testid="p2-select-filtered" disabled={pickable.length === 0 || (max !== undefined && selected.length >= max)} onClick={selectFiltered} type="button">
            Chọn tất cả theo bộ lọc ({fmt(pickable.length)})
          </button>
          <details className="p2-paste">
            <summary>Dán danh sách mã sản phẩm</summary>
            <textarea aria-label="Dán danh sách mã sản phẩm" onChange={(e) => setPaste(e.target.value)} placeholder="Mỗi mã một dòng, hoặc cách nhau bằng dấu phẩy" rows={3} value={paste} />
            <button className="sa-btn sa-btn--s" data-testid="p2-paste-go" disabled={paste.trim() === ""} onClick={pasteIds} type="button">
              Chọn các mã này
            </button>
          </details>
          {pasteNote ? (
            <p className="sa-hint" data-testid="p2-paste-note" role="status">
              {pasteNote}
            </p>
          ) : null}
        </div>
      ) : null}

      <ul className={`p2-plist ${mode === "multi" ? "p2-plist--multi" : ""}`} data-testid="p2-plist">
        <li className="p2-prow p2-prow--head" aria-hidden="true">
          {mode === "multi" ? <span /> : null}
          <span>Sản phẩm · mã sản phẩm</span>
          <span>GMV 90 ngày</span>
          <span>Biên</span>
          <span>Tồn kho</span>
          <span>Đơn 30 ngày</span>
          <span>Giá vốn</span>
        </li>
        {shown.map((p) => {
          const body = (
            <>
              <span className="p2-prow__name">
                <ProductThumb src={p.image_url} />
                <b>{p.name}</b>
                <span className="sa-hint">{p.item_id}</span>
                {p.category ? <span className="sa-hint">{p.category}</span> : null}
                {isIdle(p) ? <span className="sa-chip sa-chip--flat">không bán 30 ngày qua</span> : null}
                {p.ctor_down === true ? <span className="sa-chip sa-chip--warn">CTOR giảm</span> : null}
                {p.has_proposal ? <span className="sa-chip sa-chip--flat">có đề xuất</span> : null}
                {p.in_ads ? <span className="sa-chip sa-chip--flat">đang chạy QC</span> : null}
                {p.in_kol ? <span className="sa-chip sa-chip--flat">đang chạy KOL</span> : null}
              </span>
              <span data-label="GMV 90 ngày">{vnd(p.gmv_90d)}</span>
              <span data-label="Biên">{marginText(p)}</span>
              <span data-label="Tồn kho">{p.stock === null ? "—" : fmt(p.stock)}</span>
              <span data-label="Đơn 30 ngày">{fmt(p.orders_30d)}</span>
              <span className={`sa-chip ${isMissingCost(p) ? "sa-chip--warn" : "sa-chip--up"}`}>{isMissingCost(p) ? (p.missing_cost_chip ?? "thiếu giá vốn") : "có giá vốn"}</span>
            </>
          );
          if (props.mode === "single") {
            return (
              <li key={p.item_id}>
                <button aria-label={`${p.name} ${p.item_id}`} className="p2-prow" data-testid={`p2-prod-${p.item_id}`} onClick={() => props.onPick(p)} type="button">
                  {body}
                </button>
              </li>
            );
          }
          const on = selected.includes(p.item_id);
          const off = disabled.has(p.item_id) || (!on && max !== undefined && selected.length >= max);
          return (
            <li key={p.item_id}>
              <label className={`p2-prow p2-prow--check ${on ? "p2-prow--on" : ""}`} data-testid={`p2-prod-${p.item_id}`}>
                <input aria-label={`Chọn ${p.name}`} checked={on} disabled={off} onChange={() => toggle(p.item_id)} type="checkbox" />
                {body}
              </label>
            </li>
          );
        })}
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
        ) : null}
      </p>
      {mode === "multi" ? (
        <SelectionList
          byId={byId}
          max={max}
          onClear={() => change([])}
          onRemove={(id) => change(removeId(selected, id))}
          selected={selected}
        />
      ) : null}
      {mode === "single" && (props.excludedHidden ?? 0) > 0 ? (
        <p className="sa-hint" data-testid="p2-excluded-note">
          Đã loại trừ {props.excludedHidden} sản phẩm{" "}
          {props.exclusionsHref ? (
            <Link className="sa-link" href={props.exclusionsHref}>
              Loại trừ sản phẩm ›
            </Link>
          ) : null}
        </p>
      ) : null}
    </section>
  );
}

function SelectionList({ selected, byId, onRemove, onClear, max }: { readonly selected: readonly string[]; readonly byId: ReadonlyMap<string, PickerProduct>; readonly onRemove: (id: string) => void; readonly onClear: () => void; readonly max?: number }) {
  return (
    <div className="p2-sel" data-testid="p2-sel">
      <div className="p2-sel__head">
        <b data-testid="p2-sel-count">Đã chọn {fmt(selected.length)} sản phẩm{max !== undefined ? ` (tối đa ${fmt(max)})` : ""}</b>
        {selected.length > 0 ? (
          <button className="sa-link p2-linkbtn" onClick={onClear} type="button">
            Bỏ chọn hết
          </button>
        ) : null}
      </div>
      {selected.length === 0 ? (
        <p className="sa-hint">—</p>
      ) : (
        <ul className="p2-sel__list">
          {selected.map((id) => (
            <li className="sb-pill sb-pill--on" key={id}>
              {byId.get(id)?.name ?? id}
              <button aria-label={`Bỏ ${byId.get(id)?.name ?? id}`} className="p2-sel__x" onClick={() => onRemove(id)} type="button">
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
