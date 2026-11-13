"use client";

import Link from "next/link";
import { useMemo, useState, type ReactNode } from "react";

import { useShopee } from "../../lib/shopee-analytics/context";
import { DASH, dayMonth, fmt, pc, vnCount, vnd } from "../../lib/shopee-analytics/format";
import { readWindow, type WindowState, windowParams } from "../../lib/shopee-analytics/params";
import { useResource } from "../../lib/shopee-analytics/use-resource";
import type { ShopeeLinks } from "../../lib/shopee-analytics/links";
import type { AdBase, ChannelCells, ChannelKey, ChannelProduct, ChannelRow, ChannelSplit, PlanBar, PlanMonth, WeakestMetric } from "../../lib/shopee-analytics/types";
import { METRIC_NAME, inMode, roiText, shift, type MetricKey, type ValueMode } from "../../lib/metrics";
import { MetricChip, Shift } from "../metrics/metric-chip";
import { PeriodBar } from "./period-bar";
import { ResourceState } from "./ui";

/**
 * Tổng quan (canvas board TongQuanPct): the shop in one screen. Header finding, Shop | Sản phẩm,
 * the Kế hoạch switch, the period picker with Tổng | Trung bình / ngày, the Kế hoạch card of the
 * period, KPI tiles (GMV · Lợi nhuận · Tổng chi phí · ROI), the GMV composition (Organic / Quảng
 * cáo / Tiếp thị liên kết) and the channel table. Every figure carries its change against the
 * previous period of the same length and opens Phân tích pre-filtered (`metric`, `channel`,
 * `product`, period). Host-driven: the same screen runs for the seller, Ops and the sample shop.
 * Labels and numbers only: no captions.
 */

export type Level = "shop" | "product";

const NAMES: Readonly<Record<ChannelKey, string>> = {
  organic: "Organic",
  organic_card: "Thẻ sản phẩm",
  organic_shop: "Trang shop",
  organic_video: "Video",
  organic_live: "Live",
  ads: "Quảng cáo",
  ads_product: "DVHT Sản phẩm",
  ads_shop: "DVHT Shop+",
  affiliate: "Tiếp thị liên kết",
};
const AD_BASE: Readonly<Record<AdBase, string>> = { traffic_overview: "Tổng quan lưu lượng", ads_report: "Báo cáo DVHT" };
/** The Phân tích `channel` a row opens (none for the two parents that hold several). */
const CHANNEL_OF: Partial<Record<ChannelKey, string>> = {
  organic_card: "the_san_pham",
  organic_shop: "trang_shop",
  organic_video: "video",
  organic_live: "live",
  ads_product: "ads_product",
  ads_shop: "ads_shop",
  affiliate: "lien_ket",
};
type Cell = "views" | "ctr" | "ctor" | "aov" | "gmv" | "share" | "orders";
const COLUMNS: readonly (readonly [Cell, string, MetricKey, WeakestMetric | null])[] = [
  ["views", "Lượt xem", "views", "views"],
  ["ctr", "CTR", "ctr", "ctr"],
  ["ctor", "CTOR", "ctor", "ctor"],
  ["aov", "AOV", "aov", "aov"],
  ["gmv", "GMV", "gmv", null],
  ["share", "% GMV", "gmv", null],
  ["orders", "Đơn", "orders", "orders"],
];
const RATE_CELLS: ReadonlySet<Cell> = new Set(["ctr", "ctor", "aov", "share"]);

/** 12890000 → "12,89 tr đ"; under a million the full amount. */
export function mil(n: number | null | undefined): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return DASH;
  return Math.abs(n) >= 1_000_000 ? `${fmt(n / 1_000_000, 2)} tr đ` : vnd(n);
}

function updatedText(split: ChannelSplit): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/.exec(split.updated_at ?? "");
  if (m) return `${m[3]}/${m[2]}/${m[1]} ${m[4]}:${m[5]}`;
  const d = /^(\d{4})-(\d{2})-(\d{2})/.exec(split.to);
  return d ? `${d[3]}/${d[2]}/${d[1]}` : DASH;
}

export function daysOf(split: ChannelSplit): number {
  if (split.days) return split.days;
  const a = Date.parse(split.from);
  const b = Date.parse(split.to);
  return Number.isFinite(a) && Number.isFinite(b) ? Math.round((b - a) / 86_400_000) + 1 : 0;
}

/** Change of a figure against the previous period (a fraction), null without both. */
export function change(now: number | null | undefined, before: number | null | undefined): number | null {
  if (now === null || now === undefined || before === null || before === undefined || !Number.isFinite(now) || !Number.isFinite(before) || before === 0) return null;
  return (now - before) / Math.abs(before);
}

const pctText = (p: number | null): string => shift(p)?.text ?? "";

/** "GMV ▲ 12% · CTR Thẻ sản phẩm ▼ 3,4%": the two changes worth a glance, number-led. */
export function findingOf(split: ChannelSplit): string {
  const parts: string[] = [];
  const gmv = change(split.kpis.gmv, split.kpis_prev?.gmv);
  if (gmv !== null) parts.push(`GMV ${pctText(gmv)}`);
  const card = split.rows.find((r) => r.key === "organic_card");
  const ctr = change(card?.ctr, card?.prev?.ctr);
  if (ctr !== null) parts.push(`CTR ${NAMES.organic_card} ${pctText(ctr)}`);
  return parts.join(" · ");
}

/** The composition of GMV: each channel's share of the total GMV. */
export function compositionOf(split: ChannelSplit): readonly { key: "organic" | "ads" | "affiliate"; share: number | null; gmv: number | null; prev: number | null }[] {
  return (["organic", "ads", "affiliate"] as const).map((key) => {
    const r = split.rows.find((x) => x.key === key);
    return { key, share: r?.share ?? null, gmv: r?.gmv ?? null, prev: r?.prev?.gmv ?? null };
  });
}

/** Phân tích, pre-filtered; `channel` / `product` omitted when they do not apply. */
export function analysisHref(links: ShopeeLinks, f: { metric: MetricKey; channel?: string | null; product?: string | null; mode?: ValueMode }, state: WindowState): string {
  const p = windowParams(state);
  if (f.mode === "avg") p.set("cach", "tb");
  p.set("metric", f.metric);
  p.set("from", "tong-quan");
  if (f.channel) p.set("channel", f.channel);
  if (f.product) p.set("product", f.product);
  return links.screen("phan-tich", p);
}

export function TongQuanView({ params }: { readonly params: URLSearchParams }) {
  const host = useShopee();
  const state = useMemo(() => readWindow(params), [params]);
  const [level, setLevel] = useState<Level>("shop");
  const [productId, setProductId] = useState<string | null>(null);
  const [plan, setPlan] = useState(true);
  const mode: ValueMode = params.get("cach") === "tb" ? "avg" : "total";
  const queryKey = JSON.stringify(state.query);
  const products = useResource(() => host.api.channelSplitProducts(state.query), `${host.shopKey}|cs-products|${queryKey}`);
  const pid = level === "product" ? productId : null;
  const split = useResource(() => host.api.channelSplit(state.query, pid), `${host.shopKey}|cs|${queryKey}|${pid ?? ""}`);
  const list: readonly ChannelProduct[] = products.status === "ready" ? products.data.products : [];
  const chosen = list.find((p) => p.product_id === productId) ?? null;

  const toProduct = () => {
    setLevel("product");
    setProductId((cur) => cur ?? list[0]?.product_id ?? null);
  };
  const ready = split.status === "ready" ? split.data : null;
  const modeHref = (m: ValueMode, next: WindowState = state) => {
    const q = windowParams(next);
    if (m === "avg") q.set("cach", "tb");
    return host.links.screen("tong-quan", q);
  };
  const hrefFor = (next: WindowState) => modeHref(mode, next);
  const finding = ready ? findingOf(ready) : "";

  return (
    <div className="sa-page" data-testid="sa-tong-quan">
      <header className="sa-head">
        <div className="sa-eyebrow">{ready ? `TỔNG QUAN · ${daysOf(ready)} NGÀY` : "TỔNG QUAN"}</div>
        <div className="sa-head__line">
          <h1 className="sa-h1">{host.shopName || "Shop"}</h1>
          <span className="sa-chip" data-testid="sa-platform">
            Shopee
          </span>
          {ready ? (
            <span className="sa-fresh" data-testid="sa-fresh">
              Cập nhật {updatedText(ready)}
            </span>
          ) : null}
        </div>
        <p className="sa-tq__finding" data-testid="sa-finding">
          {finding}
        </p>
      </header>

      <div className="sa-row">
        <div aria-label="Cấp xem" className="sa-seg sa-seg--round" data-testid="sa-level" role="group">
          <button aria-pressed={level === "shop"} className={`sa-seg__item${level === "shop" ? " sa-seg__item--on" : ""}`} onClick={() => setLevel("shop")} type="button">
            Shop
          </button>
          <button aria-pressed={level === "product"} className={`sa-seg__item${level === "product" ? " sa-seg__item--on" : ""}`} onClick={toProduct} type="button">
            Sản phẩm
          </button>
        </div>
        {level === "product" ? (
          <>
            <select aria-label="Sản phẩm" className="sa-tq__select" data-testid="sa-product-pick" onChange={(e) => setProductId(e.target.value || null)} value={productId ?? ""}>
              {list.map((p) => (
                <option key={p.product_id} value={p.product_id}>
                  {p.name}
                </option>
              ))}
            </select>
            {productId ? (
              <Link className="sa-link" data-testid="sa-product-open" href={host.links.product(productId, { from: "tong-quan" }, state)}>
                Mở sản phẩm ›
              </Link>
            ) : null}
          </>
        ) : null}
        <button
          aria-checked={plan}
          className={`sa-tq__switch${plan ? " sa-tq__switch--on" : ""}`}
          data-testid="sa-plan-toggle"
          onClick={() => setPlan((v) => !v)}
          role="switch"
          type="button"
        >
          <span aria-hidden="true" className="sa-tq__knob" />
          Kế hoạch
        </button>
      </div>

      <div className="sa-row">
        <PeriodBar hrefFor={hrefFor} state={state} window={ready ? { from: ready.from, to: ready.to, days: daysOf(ready) } : null} />
        <div aria-label="Cách xem số" className="sa-seg sa-seg--round" data-testid="sa-mode" role="group">
          <Link aria-current={mode === "total" ? "true" : undefined} className={`sa-seg__item${mode === "total" ? " sa-seg__item--on" : ""}`} href={modeHref("total")}>
            Tổng
          </Link>
          <Link aria-current={mode === "avg" ? "true" : undefined} className={`sa-seg__item${mode === "avg" ? " sa-seg__item--on" : ""}`} href={modeHref("avg")}>
            Trung bình / ngày
          </Link>
        </div>
      </div>

      <ResourceState resource={split}>
        {(data) => (
          <>
            {plan && data.plan ? <PlanCard plan={data.plan} /> : null}
            <Tiles data={data} mode={mode} product={pid} state={state} />
            <Composition data={data} mode={mode} product={pid} state={state} />
            <ChannelTable data={data} mode={mode} product={pid} state={state} weakest={level === "product" ? (chosen?.weakest_metric ?? null) : null} />
          </>
        )}
      </ResourceState>
    </div>
  );
}

const suffix = (mode: ValueMode) => (mode === "avg" ? " / ngày" : "");

function Tiles({ data, mode, product, state }: { readonly data: ChannelSplit; readonly mode: ValueMode; readonly product: string | null; readonly state: WindowState }) {
  const { links } = useShopee();
  const days = daysOf(data);
  const k = data.kpis;
  const p = data.kpis_prev ?? null;
  const money = (v: number | null | undefined) => mil(inMode(v, days, mode));
  const href = (metric: MetricKey) => analysisHref(links, { metric, product, mode }, state);
  const tile = (key: string, label: string, value: string, shiftPct: number | null, metric: MetricKey, good: 1 | -1, lines?: ReactNode): ReactNode => (
    <Link className="sa-tile" data-testid={`sa-tile-${key}`} href={href(metric)} key={key}>
      <span className="sa-tile__top">
        <span className="sa-tile__label">{label}</span>
      </span>
      <span className="sa-tile__value">{value}</span>
      <Shift good={good} pct={shiftPct} testId={`sa-shift-${key}`} />
      {lines}
    </Link>
  );
  const line = (key: string, label: string, v: number | null, before: number | null | undefined, tag?: string) => (
    <span className="sa-tq__line" data-testid={`sa-cost-${key}`} key={key}>
      <span>
        {label}
        {tag ? <span className="sa-tq__src"> {tag}</span> : null}
      </span>
      <span>{money(v)}</span>
      <Shift good={-1} pct={change(v, before)} />
    </span>
  );
  return (
    <div className="sa-tiles sa-tq__tiles" data-testid="sa-tiles">
      {tile("gmv", `GMV${suffix(mode)}`, money(k.gmv), change(k.gmv, p?.gmv), "gmv", 1)}
      {tile("profit", `Lợi nhuận${suffix(mode)}`, money(k.profit), change(k.profit, p?.profit), "margin", 1)}
      {tile(
        "cost",
        `Tổng chi phí${suffix(mode)}`,
        money(k.cost_total),
        change(k.cost_total, p?.cost_total),
        "margin",
        -1,
        <>
          {line("ads", "Quảng cáo", k.cost_ads, p?.cost_ads, AD_BASE.ads_report)}
          {line("affiliate", "Tiếp thị liên kết", k.cost_affiliate, p?.cost_affiliate)}
          {line("offers", "Ưu đãi", k.cost_offers, p?.cost_offers)}
        </>,
      )}
      {tile("roi", "ROI", roiText(k.roi), change(k.roi, p?.roi), "margin", 1)}
    </div>
  );
}

function Composition({ data, mode, product, state }: { readonly data: ChannelSplit; readonly mode: ValueMode; readonly product: string | null; readonly state: WindowState }) {
  const { links } = useShopee();
  const days = daysOf(data);
  const items = compositionOf(data);
  if (items.every((i) => i.share === null)) return null;
  return (
    <section className="sa-card sa-tq__comp" data-testid="sa-composition">
      <div className="sa-tq__comp-head">
        <MetricChip metric="gmv" />
        <span>{mil(inMode(data.kpis.gmv, days, mode))}</span>
      </div>
      <div className="sa-tq__bar" aria-hidden="true">
        {items.map((i) => (
          <span className={`sa-tq__seg sa-tq__seg--${i.key}`} key={i.key} style={{ width: `${Math.max(0, (i.share ?? 0) * 100)}%` }} />
        ))}
      </div>
      <div className="sa-tq__comp-items">
        {items.map((i) => (
          <Link className="sa-tq__comp-item" data-testid={`sa-comp-${i.key}`} href={analysisHref(links, { metric: "gmv", channel: CHANNEL_OF[i.key], product, mode }, state)} key={i.key}>
            <span>{NAMES[i.key]}</span>
            <b>{i.share === null ? DASH : pc(i.share, 0)}</b>
            <span>{mil(inMode(i.gmv, days, mode))}</span>
            <Shift pct={change(i.gmv, i.prev)} />
          </Link>
        ))}
      </div>
    </section>
  );
}

function cellValue(r: ChannelRow | ChannelCells, c: Cell, days: number, mode: ValueMode): number | null {
  const raw = r[c] ?? null;
  return RATE_CELLS.has(c) ? raw : inMode(raw, days, mode);
}

function cellText(c: Cell, v: number | null): string {
  if (v === null) return DASH;
  switch (c) {
    case "views":
      return fmt(v, v < 100 && !Number.isInteger(v) ? 1 : 0);
    case "ctr":
    case "ctor":
      return pc(v, 1);
    case "share":
      return pc(v, 1);
    case "aov":
      return vnd(v);
    case "gmv":
      return mil(v);
    default:
      return vnCount(v);
  }
}

function ChannelTable({ data, mode, product, state, weakest }: { readonly data: ChannelSplit; readonly mode: ValueMode; readonly product: string | null; readonly state: WindowState; readonly weakest: WeakestMetric | null }) {
  const { links } = useShopee();
  const days = daysOf(data);
  const perDay = (c: Cell) => !RATE_CELLS.has(c) && mode === "avg";
  return (
    <section className="sa-tq__table" data-testid="sa-channels" role="table">
      <div className="sa-tq__row sa-tq__row--head" role="row">
        <span role="columnheader">Luồng</span>
        {COLUMNS.map(([cell, label, , weak]) => (
          <span className={weak !== null && weak === weakest ? "sa-tq__weak" : undefined} data-weak={weak !== null && weak === weakest ? "true" : undefined} key={cell} role="columnheader">
            {label}
            {perDay(cell) ? " / ngày" : ""}
          </span>
        ))}
      </div>
      {data.rows.map((r) => {
        const channel = CHANNEL_OF[r.key];
        return (
          <div className={`sa-tq__row${r.parent ? " sa-tq__row--child" : ""}`} data-testid={`sa-channel-${r.key}`} key={r.key} role="row">
            <span className="sa-tq__name" role="cell">
              <Link href={analysisHref(links, { metric: "gmv", channel, product, mode }, state)}>{NAMES[r.key]}</Link>
              {r.ad_base ? (
                <span className="sa-tq__src" data-testid={`sa-base-${r.key}`}>
                  {AD_BASE[r.ad_base]}
                </span>
              ) : null}
            </span>
            {COLUMNS.map(([cell, , metric]) => {
              const v = cellValue(r, cell, days, mode);
              const before = r.prev ? cellValue(r.prev, cell, days, mode) : null;
              return (
                <Link className="sa-tq__cell" data-testid={`sa-cell-${r.key}-${cell}`} href={analysisHref(links, { metric, channel, product, mode }, state)} key={cell} role="cell">
                  <span>{cellText(cell, v)}</span>
                  {v === null ? null : <Shift pct={change(v, before)} />}
                </Link>
              );
            })}
          </div>
        );
      })}
    </section>
  );
}

/** Ahead of pace = the share of the goal reached is at least the share of the period elapsed. */
export function aheadOfPace(bar: PlanBar, day: number, days: number): boolean {
  if (bar.ahead !== undefined && bar.ahead !== null) return bar.ahead;
  return bar.goal !== null && bar.goal > 0 && bar.now !== null && days > 0 && bar.now / bar.goal >= day / days;
}

function PlanCard({ plan }: { readonly plan: PlanMonth }) {
  const marker = plan.today_marker === null ? null : Math.min(100, plan.today_marker * 100);
  const bar = (label: string, key: string, b: PlanBar) => {
    const hasGoal = b.goal !== null && b.goal > 0;
    const pct = hasGoal && b.now !== null ? Math.max(0, Math.min(100, (b.now / (b.goal as number)) * 100)) : 0;
    const ahead = aheadOfPace(b, plan.day, plan.days);
    return (
      <div className="sa-tq__goal" data-testid={`sa-plan-${key}`} key={key}>
        <div className="sa-tq__goal-top">
          <span>{label}</span>
          <span>{hasGoal ? `${mil(b.now)} / ${mil(b.goal)}` : mil(b.now)}</span>
        </div>
        <div className="sa-tq__track">
          {hasGoal ? <span className={`sa-tq__fill ${ahead ? "sa-tq__fill--ahead" : "sa-tq__fill--behind"}`} data-ahead={ahead ? "true" : "false"} data-testid={`sa-plan-${key}-fill`} style={{ width: `${pct}%` }} /> : null}
          {hasGoal && marker !== null ? <span aria-hidden="true" className="sa-tq__today" data-testid={`sa-plan-${key}-today`} style={{ left: `${marker}%` }} /> : null}
        </div>
      </div>
    );
  };
  return (
    <section className="sa-card sa-tq__plan" data-testid="sa-plan">
      <div className="sa-tq__plan-head">
        <b>
          Kế hoạch · {dayMonth(plan.from)} – {dayMonth(plan.to)}
        </b>
        <span>
          {plan.day}/{plan.days} ngày
        </span>
      </div>
      {bar(METRIC_NAME.gmv, "gmv", plan.gmv)}
      {bar("Lợi nhuận", "profit", plan.profit)}
    </section>
  );
}
