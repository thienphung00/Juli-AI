"use client";

import Link from "next/link";
import { useMemo, useState, type ReactNode } from "react";

import { useShopee } from "../../lib/shopee-analytics/context";
import { DASH, fmt, pc, vnCount, vnd } from "../../lib/shopee-analytics/format";
import { readWindow, type WindowState, windowParams } from "../../lib/shopee-analytics/params";
import { useResource } from "../../lib/shopee-analytics/use-resource";
import type { AdBase, ChannelKey, ChannelProduct, ChannelRow, ChannelSplit, PlanBar, PlanMonth, WeakestMetric } from "../../lib/shopee-analytics/types";
import { PeriodBar } from "./period-bar";
import { ResourceState } from "./ui";

/**
 * Tổng quan (canvas board TongQuan): the shop in one screen. Header (shop, platform, last data
 * time), the Shop | Sản phẩm toggle, a number-led finding, the channel table (Organic / Quảng
 * cáo / Tiếp thị liên kết; the Quảng cáo figures name the ad base they come from and are never
 * summed across bases), four KPI tiles and the Kế hoạch card (month to date against the goal).
 * Labels and numbers only: no captions.
 */

export type Level = "shop" | "product";

const NAMES: Readonly<Record<ChannelKey, string>> = {
  organic: "Organic",
  organic_card: "Thẻ sản phẩm",
  organic_shop: "Shop",
  ads: "Quảng cáo",
  ads_product: "DVHT Sản phẩm",
  ads_shop: "DVHT Shop+",
  affiliate: "Tiếp thị liên kết",
};
const AD_BASE: Readonly<Record<AdBase, string>> = { traffic_overview: "Tổng quan lưu lượng", ads_report: "Báo cáo QC" };
/** The Phân tích source a row opens (shop level only). */
const ROW_SOURCE: Partial<Record<ChannelKey, string>> = { organic_shop: "trang_shop", ads: "ads", affiliate: "lien_ket" };
const COLUMNS: readonly (readonly [string, WeakestMetric | null])[] = [
  ["Lượt xem", "views"],
  ["CTR", "ctr"],
  ["CTOR", "ctor"],
  ["AOV", "aov"],
  ["GMV", null],
  ["Đơn", "orders"],
];

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

function daysOf(split: ChannelSplit): number {
  const a = Date.parse(split.from);
  const b = Date.parse(split.to);
  return Number.isFinite(a) && Number.isFinite(b) ? Math.round((b - a) / 86_400_000) + 1 : 0;
}

/** "Organic 28% GMV · Quảng cáo 63% · Tiếp thị liên kết 9%": each channel's share of the GMV. */
export function findingOf(split: ChannelSplit): string {
  const total = split.kpis.gmv;
  if (!total || total <= 0) return "";
  const parts: string[] = [];
  for (const key of ["organic", "ads", "affiliate"] as const) {
    const gmv = split.rows.find((r) => r.key === key)?.gmv;
    if (gmv === null || gmv === undefined) continue;
    parts.push(`${NAMES[key]} ${pc(gmv / total, 0)}${parts.length === 0 ? " GMV" : ""}`);
  }
  return parts.join(" · ");
}

export function TongQuanView({ params }: { readonly params: URLSearchParams }) {
  const host = useShopee();
  const state = useMemo(() => readWindow(params), [params]);
  const [level, setLevel] = useState<Level>("shop");
  const [productId, setProductId] = useState<string | null>(null);
  const [plan, setPlan] = useState(true);
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
  const hrefFor = (next: WindowState) => host.links.screen("tong-quan", windowParams(next));

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
      </div>

      <ResourceState resource={split}>
        {(data) => (
          <>
            <div className="sa-row">
              <PeriodBar hrefFor={hrefFor} previous={null} state={state} window={{ from: data.from, to: data.to, days: daysOf(data) }} />
            </div>
            <p className="sa-tq__finding" data-testid="sa-finding">
              {findingOf(data)}
            </p>
            {plan && data.plan ? <PlanCard plan={data.plan} /> : null}
            <Tiles data={data} state={state} />
            <ChannelTable data={data} state={state} weakest={level === "product" ? (chosen?.weakest_metric ?? null) : null} />
          </>
        )}
      </ResourceState>
    </div>
  );
}

function Tiles({ data, state }: { readonly data: ChannelSplit; readonly state: WindowState }) {
  const { links } = useShopee();
  const k = data.kpis;
  const tile = (key: string, label: string, value: number | null, sub: string, tag?: string, href?: string): ReactNode => {
    const body = (
      <>
        <span className="sa-tile__top">
          <span className="sa-tile__label">{label}</span>
          {tag ? <span className="sa-tq__src">{tag}</span> : null}
        </span>
        <span className="sa-tile__value">{mil(value)}</span>
        {sub ? <span className="sa-tile__impact">{sub}</span> : null}
      </>
    );
    return href ? (
      <Link className="sa-tile" data-testid={`sa-tile-${key}`} href={href} key={key}>
        {body}
      </Link>
    ) : (
      <div className="sa-tile" data-testid={`sa-tile-${key}`} key={key}>
        {body}
      </div>
    );
  };
  const rank = data.level === "shop" ? links.ranking({ kpi: "gmv", src: "all", from: "tong-quan" }, state) : undefined;
  return (
    <div className="sa-tiles sa-tq__tiles" data-testid="sa-tiles">
      {tile("gmv", "GMV", k.gmv, k.orders === null ? "" : `${vnCount(k.orders)} đơn`, undefined, rank)}
      {tile("profit", "Lợi nhuận", k.profit, "")}
      {tile("ads", "Chi phí quảng cáo", k.ads_cost, "", AD_BASE.ads_report)}
      {tile("affiliate", "Chi phí tiếp thị liên kết", k.affiliate_cost, "")}
    </div>
  );
}

function cells(r: ChannelRow): readonly string[] {
  return [fmt(r.views), pc(r.ctr, 1), pc(r.ctor, 1), vnd(r.aov), mil(r.gmv), vnCount(r.orders)];
}

function ChannelTable({ data, state, weakest }: { readonly data: ChannelSplit; readonly state: WindowState; readonly weakest: WeakestMetric | null }) {
  const { links } = useShopee();
  return (
    <section className="sa-tq__table" data-testid="sa-channels" role="table">
      <div className="sa-tq__row sa-tq__row--head" role="row">
        <span role="columnheader">Luồng</span>
        {COLUMNS.map(([label, metric]) => (
          <span className={metric !== null && metric === weakest ? "sa-tq__weak" : undefined} data-weak={metric !== null && metric === weakest ? "true" : undefined} key={label} role="columnheader">
            {label}
          </span>
        ))}
      </div>
      {data.rows.map((r) => {
        const src = data.level === "shop" ? ROW_SOURCE[r.key] : undefined;
        const name = NAMES[r.key];
        return (
          <div className={`sa-tq__row${r.parent ? " sa-tq__row--child" : ""}`} data-testid={`sa-channel-${r.key}`} key={r.key} role="row">
            <span className="sa-tq__name" role="cell">
              {src ? (
                <Link href={links.ranking({ kpi: "gmv", src, from: "tong-quan" }, state)}>{name}</Link>
              ) : (
                name
              )}
              {r.ad_base ? (
                <span className="sa-tq__src" data-testid={`sa-base-${r.key}`}>
                  {AD_BASE[r.ad_base]}
                </span>
              ) : null}
            </span>
            {cells(r).map((c, i) => (
              <span key={COLUMNS[i]?.[0]} role="cell">
                {c}
              </span>
            ))}
          </div>
        );
      })}
    </section>
  );
}

/** Ahead of pace = the month's share of the goal reached is at least the month's elapsed share. */
export function aheadOfPace(bar: PlanBar, day: number, days: number): boolean {
  return bar.goal !== null && bar.goal > 0 && bar.now !== null && days > 0 && bar.now / bar.goal >= day / days;
}

function PlanCard({ plan }: { readonly plan: PlanMonth }) {
  const today = plan.days_in_month > 0 ? Math.min(100, (plan.day / plan.days_in_month) * 100) : 0;
  const bar = (label: string, key: string, b: PlanBar) => {
    const hasGoal = b.goal !== null && b.goal > 0;
    const pct = hasGoal && b.now !== null ? Math.max(0, Math.min(100, (b.now / (b.goal as number)) * 100)) : 0;
    const ahead = aheadOfPace(b, plan.day, plan.days_in_month);
    return (
      <div className="sa-tq__goal" data-testid={`sa-plan-${key}`} key={key}>
        <div className="sa-tq__goal-top">
          <span>{label}</span>
          <span>{hasGoal ? `${mil(b.now)} / ${mil(b.goal)}` : mil(b.now)}</span>
        </div>
        <div className="sa-tq__track">
          {hasGoal ? <span className={`sa-tq__fill ${ahead ? "sa-tq__fill--ahead" : "sa-tq__fill--behind"}`} data-ahead={ahead ? "true" : "false"} data-testid={`sa-plan-${key}-fill`} style={{ width: `${pct}%` }} /> : null}
          {hasGoal ? <span aria-hidden="true" className="sa-tq__today" data-testid={`sa-plan-${key}-today`} style={{ left: `${today}%` }} /> : null}
        </div>
      </div>
    );
  };
  return (
    <section className="sa-card sa-tq__plan" data-testid="sa-plan">
      <div className="sa-tq__plan-head">
        <b>Tháng {Number(plan.month.slice(5, 7))}</b>
        <span>
          {plan.day}/{plan.days_in_month} ngày
        </span>
      </div>
      {bar("GMV", "gmv", plan.gmv)}
      {bar("Lợi nhuận", "profit", plan.profit)}
    </section>
  );
}
