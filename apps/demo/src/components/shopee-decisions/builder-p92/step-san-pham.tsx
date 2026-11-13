"use client";

import { useMemo, useState, type ReactNode } from "react";

import { DASH, fmt, pp, vnd } from "../../../lib/shopee-analytics/format";
import { shopeeImageSrc } from "../../../lib/shopee-analytics/image-src";
import type { ChannelSplitProduct, PickerProduct, WeakestMetric } from "../../../lib/shopee-decisions/builder-api";
import { METRIC_LABELS } from "../../../lib/shopee-decisions/builder-p92";
import { NavLink } from "../ui";

/**
 * Step ① Sản phẩm (artboard Flow1): search, "Cả shop", and one card per product with its GMV 30 ngày, biên, the
 * Organic / Quảng cáo / TTLK split and the weakest metric. The figures come from the channel-split endpoint; a
 * missing figure (or no endpoint) reads "—" and the picker's own names, order and exclusions stay.
 */

const PAGE = 12;

export type ChannelMap = ReadonlyMap<string, ChannelSplitProduct>;

export const money = (n: number | null | undefined): string => (typeof n === "number" ? vnd(n) : DASH);

export function weakestText(m: WeakestMetric | null | undefined): string {
  return m ? METRIC_LABELS[m] : DASH;
}

export function ProductCard({ product, split, on, onPick }: { readonly product: PickerProduct; readonly split: ChannelSplitProduct | undefined; readonly on: boolean; readonly onPick: () => void }) {
  const margin = split?.margin ?? null;
  const metric = split?.weakest_metric ?? null;
  const image = shopeeImageSrc(split?.image_url);
  return (
    <button aria-pressed={on} className={`p2-pcard ${on ? "p2-pcard--on" : ""}`} data-testid={`p2-prod-${product.item_id}`} onClick={onPick} type="button">
      <span className="p2-pcard__top">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        {image ? <img alt="" className="p2-pcard__img" src={image} /> : <span aria-hidden="true" className="p2-pcard__img" />}
        <span>
          <span className="p2-pcard__name">{product.name}</span>
          <br />
          <span className="sa-hint">
            GMV 30 ngày {money(split?.gmv)} · biên {margin === null ? DASH : pp(margin, 1)}
          </span>
        </span>
      </span>
      <dl className="p2-pcard__split">
        <div>
          <dt>Organic</dt>
          <dd>{money(split?.organic_gmv)}</dd>
        </div>
        <div>
          <dt>Quảng cáo</dt>
          <dd>{money(split?.ads_gmv)}</dd>
        </div>
        <div>
          <dt>TTLK</dt>
          <dd>{money(split?.affiliate_gmv)}</dd>
        </div>
      </dl>
      <span className="p2-pcard__gap">
        Điểm nghẽn: {metric ? <span className={`p2-m p2-m--${metric}`}>{weakestText(metric)}</span> : <b>{DASH}</b>}
      </span>
    </button>
  );
}

export function StepSanPham({
  products,
  channel,
  excludedHidden,
  exclusionsHref,
  selected,
  shopWide,
  onPick,
  onShop,
  children,
  onNext,
  canNext,
}: {
  readonly products: readonly PickerProduct[];
  readonly channel: ChannelMap | null;
  readonly excludedHidden: number;
  readonly exclusionsHref: string | null;
  readonly selected: PickerProduct | null;
  readonly shopWide: boolean;
  readonly onPick: (p: PickerProduct) => void;
  readonly onShop: () => void;
  /** The inline variation choice, shown once a product is picked. */
  readonly children?: ReactNode;
  readonly onNext: () => void;
  readonly canNext: boolean;
}) {
  const [q, setQ] = useState("");
  const [all, setAll] = useState(false);
  const found = useMemo(() => {
    const t = q.trim().toLowerCase();
    return t === "" ? products : products.filter((p) => p.name.toLowerCase().includes(t) || p.item_id.toLowerCase().includes(t));
  }, [products, q]);
  const shown = all || q.trim() !== "" ? found : found.slice(0, PAGE);
  return (
    <section className="p2-step1" data-testid="p2-picker">
      <div className="p2-find">
        <input aria-label="Tìm sản phẩm" className="p2-text" onChange={(e) => setQ(e.target.value)} placeholder="Tìm sản phẩm" type="search" value={q} />
        <button aria-pressed={shopWide} className={`sa-btn ${shopWide ? "sa-btn--primary" : ""}`} data-testid="p2-shop" onClick={onShop} type="button">
          Cả shop
        </button>
      </div>
      <div className="p2-pcards" data-testid="p2-plist">
        {shown.map((p) => (
          <ProductCard key={p.item_id} on={!shopWide && selected?.item_id === p.item_id} onPick={() => onPick(p)} product={p} split={channel?.get(p.item_id)} />
        ))}
      </div>
      {!all && q.trim() === "" && found.length > PAGE ? (
        <button className="sa-link p2-linkbtn" onClick={() => setAll(true)} type="button">
          Xem thêm {found.length - PAGE} sản phẩm
        </button>
      ) : null}
      {excludedHidden > 0 && exclusionsHref ? (
        <NavLink className="sa-link" testId="p2-excluded-note" href={exclusionsHref}>
          Đã loại trừ {fmt(excludedHidden)} sản phẩm
        </NavLink>
      ) : null}
      {children}
      <div className="p2-foot">
        <span />
        <button className="sa-btn sa-btn--primary" data-testid="p2-vnext" disabled={!canNext} onClick={onNext} type="button">
          Tiếp tục
        </button>
      </div>
    </section>
  );
}
