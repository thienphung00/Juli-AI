"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { DASH, pp, vnd } from "../../../lib/shopee-analytics/format";
import type { BuilderApi, VariationList, VariationRow } from "../../../lib/shopee-decisions/builder-api";

/**
 * "So sánh phân loại" (B-2): per variation only the list price, the selling price, the price per unit and
 * the profit margin; every other metric belongs to the whole product. Used by the builder's variation step
 * and by the product page (Sản phẩm). A variation without giá vốn reads "chưa tính".
 */

export type VariationState = { readonly status: "loading" } | { readonly status: "error" } | { readonly status: "ready"; readonly data: VariationList };

export function useVariationList(api: BuilderApi | undefined, itemId: string | null): VariationState {
  const [state, setState] = useState<{ key: string; value: VariationState } | null>(null);
  const key = api && itemId ? itemId : "";
  useEffect(() => {
    if (!api || !itemId) return;
    let live = true;
    api.variations(itemId).then(
      (data) => live && setState({ key, value: { status: "ready", data } }),
      () => live && setState({ key, value: { status: "error" } }),
    );
    return () => {
      live = false;
    };
    // `key` says the product changed; `api` is rebuilt with the host.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return key && state?.key === key ? state.value : { status: "loading" };
}

export function unitText(v: VariationRow): string {
  return v.price_per_unit === null ? DASH : `${vnd(v.price_per_unit)}/đơn vị`;
}

function MarginCell({ v, costLink }: { readonly v: VariationRow; readonly costLink: string }) {
  if (v.margin_pct === null) {
    return (
      <span title={v.margin_reason ?? undefined}>
        {v.margin_label ?? "chưa tính"}{" "}
        <Link href={costLink} className="sa-link">
          Thông số shop ›
        </Link>
      </span>
    );
  }
  return <b>{pp(v.margin_pct, 1)}</b>;
}

export function VariationCompare({ data, costLink }: { readonly data: VariationList; readonly costLink: string }) {
  return (
    <div className="p2-vcmp" data-testid="p2-vcmp">
      <div className="p2-vcmp__table" role="table" aria-label="So sánh phân loại">
        <div className="p2-vcmp__row p2-vcmp__row--head" role="row">
          <span role="columnheader">Phân loại</span>
          <span role="columnheader">Giá niêm yết</span>
          <span role="columnheader">Giá bán</span>
          <span role="columnheader">Giá mỗi đơn vị</span>
          <span role="columnheader">Biên lợi nhuận</span>
        </div>
        {data.variations.map((v) => (
          <div className="p2-vcmp__row" data-testid={`p2-vcmp-${v.variation_id || "default"}`} key={v.variation_id || "default"} role="row">
            <span role="cell">
              <b>{v.name}</b>
            </span>
            <span data-label="Giá niêm yết" role="cell">
              {vnd(v.list_price)}
            </span>
            <span data-label="Giá bán" role="cell">
              {vnd(v.selling_price)}
            </span>
            <span data-label="Giá mỗi đơn vị" role="cell">
              {unitText(v)}
            </span>
            <span data-label="Biên lợi nhuận" role="cell">
              <MarginCell costLink={costLink} v={v} />
            </span>
          </div>
        ))}
      </div>
      <p className="sa-hint">Chỉ giá và biên của từng phân loại; mọi chỉ số khác (lượt xem, CTR, CTOR, đơn, AOV) là của cả sản phẩm. Giá mỗi đơn vị lấy số lượng từ tên phân loại; nếu tên không có số, lấy từ cột “số lượng trong gói” của Thông số shop.</p>
      {data.margin_basis ? <p className="sa-hint">{data.margin_basis}.</p> : null}
    </div>
  );
}

/** The collapsed expand: "So sánh phân loại ▸ / ▾". Loads the variations when first opened. */
export function VariationExpand({ api, itemId, costLink, defaultOpen = false }: { readonly api: BuilderApi; readonly itemId: string; readonly costLink: string; readonly defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const state = useVariationList(open ? api : undefined, open ? itemId : null);
  return (
    <div className="p2-expand" data-testid="p2-expand">
      <button aria-expanded={open} className="sa-btn sa-btn--s" onClick={() => setOpen((o) => !o)} type="button">
        So sánh phân loại {open ? "▾" : "▸"}
      </button>
      {open && state.status === "loading" ? (
        <p className="sa-hint" role="status">
          Đang tải phân loại…
        </p>
      ) : null}
      {open && state.status === "error" ? (
        <p className="sd-error" role="alert">
          Chưa tải được phân loại.
        </p>
      ) : null}
      {open && state.status === "ready" ? <VariationCompare costLink={costLink} data={state.data} /> : null}
    </div>
  );
}
