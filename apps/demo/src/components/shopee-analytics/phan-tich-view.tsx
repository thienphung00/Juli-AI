"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { METRIC_NAME, METRIC_ORDER, shift, type MetricKey, type ValueMode } from "../../lib/metrics";
import { useShopee } from "../../lib/shopee-analytics/context";
import {
  CHANNEL_LABEL,
  type SortKey,
  impactText,
  readMetricParams,
  sortRows,
  valueText,
} from "../../lib/shopee-analytics/metric-view";
import { readWindow, windowParams, type WindowState } from "../../lib/shopee-analytics/params";
import type { KolSection as KolSectionData, MetricView, MetricViewRow } from "../../lib/shopee-analytics/types";
import { useResource } from "../../lib/shopee-analytics/use-resource";
import { MetricChip, Shift } from "../metrics/metric-chip";
import { KolSection } from "../shopee-kol/kol-section";
import { PeriodBar } from "./period-bar";
import { Empty, PageHead, ResourceState, Ini, initialsOf } from "./ui";

/**
 * Phân tích (board B): one metric at a time. Header finding, period + Tổng | Trung bình / ngày,
 * the seven metric chips, "Theo luồng", "Theo sản phẩm" and the KOL section. Each row ends in the
 * next step: "Đề xuất (n) ›" (Quyết định › Đề xuất filtered by metric / product) or "Tự tạo ›".
 * URL: `metric`, `channel`, `product`, `cach=tb` (Trung bình / ngày) and the window.
 */

/** Params that belong to this screen: kept when the window changes. */
const WINDOW_KEYS = new Set(["ky", "thang", "tu", "den", "cmp", "focus", "from", "card", "tab"]);

/** Phân tích at another window, keeping metric / channel / product / mode. */
export function periodQuery(params: URLSearchParams, next: WindowState): URLSearchParams {
  const p = new URLSearchParams();
  params.forEach((v, k) => {
    if (!WINDOW_KEYS.has(k)) p.append(k, v);
  });
  windowParams(next).forEach((v, k) => p.set(k, v));
  return p;
}

/** The screen's own params, normalised (old `kpi` / `src` / `focus` become `metric` / `channel` / `product`). */
function nextQuery(params: URLSearchParams, patch: Record<string, string | null>): URLSearchParams {
  const cur = readMetricParams(params);
  const p = new URLSearchParams();
  windowParams(readWindow(params)).forEach((v, k) => p.set(k, v));
  const put = (k: string, v: string | null) => v && p.set(k, v);
  const val = (k: string, d: string | null) => (k in patch ? patch[k] : d);
  put("metric", val("metric", cur.metric));
  put("channel", val("channel", cur.channel));
  put("product", val("product", cur.product));
  put("cach", val("cach", cur.mode === "avg" ? "tb" : null));
  return p;
}

export function PhanTichPageView({ params }: { readonly params: URLSearchParams }) {
  const host = useShopee();
  const state = useMemo(() => readWindow(params), [params]);
  const sel = useMemo(() => readMetricParams(params), [params]);
  const key = `${host.shopKey}|pt|${JSON.stringify(state.query)}|${sel.metric}|${sel.channel}|${sel.product}`;
  const data = useResource(
    () => host.api.metricView({ ...state.query, metric: sel.metric, channel: sel.channel, productId: sel.product }),
    key,
  );
  const kol = useResource<KolSectionData>(() => host.api.kolSection(state.query), `${host.shopKey}|ptk|${JSON.stringify(state.query)}`);
  const href = (patch: Record<string, string | null>) => host.links.screen("phan-tich", nextQuery(params, patch));
  return (
    <div className="sa-page sa-p100" data-testid="sa-phan-tich">
      <ResourceState resource={data}>
        {(v) => (
          <>
            <Head sel={sel.metric} view={v} />
            <div className="jp-bar">
              <PeriodBar hrefFor={(next) => host.links.screen("phan-tich", periodQuery(nextQuery(params, {}), next))} previous={null} state={state} window={{ from: v.from, to: v.to, days: v.days }} />
              <ModeSwitch href={href} mode={sel.mode} />
            </div>
            <MetricChips href={href} sel={sel.metric} total={v.total} />
            <ByChannel href={href} state={state} mode={sel.mode} sel={sel} view={v} />
            <ByProduct mode={sel.mode} sel={sel} state={state} view={v} />
          </>
        )}
      </ResourceState>
      <ResourceState resource={kol}>
        {(k) => (
          <KolSection
            builderHref={(r) => host.links.builder("quyet-dinh", r.item_id)}
            data={k}
            decisionsHref={(r) => host.links.decisions({ product: r.item_id }, state)}
            mode={sel.mode}
          />
        )}
      </ResourceState>
    </div>
  );
}

/** "CTR ▼ 12 % · Thẻ sản phẩm · 3 sản phẩm kéo xuống": the number first. */
function Head({ sel, view }: { readonly sel: MetricKey; readonly view: MetricView }) {
  const s = shift(view.total.change);
  const worst = [...view.channels].filter((c) => typeof c.impact === "number" && c.impact < 0).sort((a, b) => (a.impact ?? 0) - (b.impact ?? 0))[0];
  const down = view.products.filter((p) => typeof p.impact === "number" && p.impact < 0).length;
  const parts = [`${METRIC_NAME[sel]}${s ? ` ${s.text}` : ""}`];
  if (worst) parts.push(CHANNEL_LABEL[worst.key] ?? worst.key);
  if (down > 0) parts.push(`${down} sản phẩm kéo xuống`);
  return <PageHead eyebrow={`PHÂN TÍCH · ${view.days} NGÀY · SO VỚI ${view.days} NGÀY TRƯỚC`} title={parts.join(" · ")} />;
}

function ModeSwitch({ mode, href }: { readonly mode: ValueMode; readonly href: (patch: Record<string, string | null>) => string }) {
  return (
    <div aria-label="Cách tính" className="sa-seg sa-seg--round jp-mode" role="group">
      <Link aria-current={mode === "total" ? "true" : undefined} className={`sa-seg__item${mode === "total" ? " sa-seg__item--on" : ""}`} href={href({ cach: null })}>
        Tổng
      </Link>
      <Link aria-current={mode === "avg" ? "true" : undefined} className={`sa-seg__item${mode === "avg" ? " sa-seg__item--on" : ""}`} href={href({ cach: "tb" })}>
        Trung bình / ngày
      </Link>
    </div>
  );
}

function MetricChips({ sel, href, total }: { readonly sel: MetricKey; readonly href: (patch: Record<string, string | null>) => string; readonly total: MetricViewRow }) {
  return (
    <div aria-label="Chỉ số" className="jp-chips" role="group">
      {METRIC_ORDER.map((m) => (
        <Link aria-current={m === sel ? "true" : undefined} className="jp-chip-link" data-testid={`pt-chip-${m}`} href={href({ metric: m, channel: null })} key={m}>
          <MetricChip metric={m} on={m === sel}>
            <span>{METRIC_NAME[m]}</span>
            {m === sel ? <Shift pct={total.change} /> : null}
          </MetricChip>
        </Link>
      ))}
    </div>
  );
}

function Cta({ row, metric, product, channel, state }: { readonly state: WindowState; readonly row: MetricViewRow; readonly metric: MetricKey; readonly product: string | null; readonly channel: string | null }) {
  const { links } = useShopee();
  return row.cards > 0 ? (
    <Link className="jp-cta jp-cta--on" href={links.decisions({ metric, product, channel }, state)}>
      Đề xuất ({row.cards}) ›
    </Link>
  ) : (
    <Link className="jp-cta" href={links.builder("quyet-dinh", product)}>
      Tự tạo ›
    </Link>
  );
}

function ByChannel({ view, sel, mode, href, state }: { readonly state: WindowState; readonly view: MetricView; readonly sel: ReturnType<typeof readMetricParams>; readonly mode: ValueMode; readonly href: (patch: Record<string, string | null>) => string }) {
  const m = sel.metric;
  const days = view.days;
  return (
    <section aria-label="Theo luồng" className="sa-card jp-section" data-testid="pt-channels">
      <h2 className="sa-h2">Theo luồng</h2>
      <div className="jp-grid jp-grid--ch jp-grid--head">
        <span>Luồng</span>
        <span>Kỳ này</span>
        <span>Kỳ trước</span>
        <span>Thay đổi</span>
        <span>GMV ảnh hưởng</span>
        <span />
      </div>
      {view.channels.map((r) => (
        <div className={`jp-grid jp-grid--ch${sel.channel === r.key ? " jp-grid--on" : ""}`} data-testid={`pt-channel-${r.key}`} key={r.key}>
          <Link className="jp-name" href={href({ channel: sel.channel === r.key ? null : r.key })}>
            {CHANNEL_LABEL[r.key] ?? r.key}
            {r.ad_base ? <span className="jp-tag">Báo cáo DVHT</span> : null}
          </Link>
          <b>{valueText(m, r.now, days, mode)}</b>
          <span>{valueText(m, r.prev, days, mode)}</span>
          <span className="jp-shift-cell"><Shift pct={r.change} /></span>
          <span>{impactText(r, days, mode)}</span>
          <Cta channel={r.key} metric={m} state={state} product={sel.product} row={r} />
        </div>
      ))}
    </section>
  );
}

function ByProduct({ view, sel, mode, state }: { readonly state: WindowState; readonly view: MetricView; readonly sel: ReturnType<typeof readMetricParams>; readonly mode: ValueMode }) {
  const { links } = useShopee();
  const m = sel.metric;
  const [sortBy, setSortBy] = useState<SortKey>("impact");
  const rows = sortRows(view.products, sortBy);
  return (
    <section aria-label="Theo sản phẩm" className="sa-card jp-section" data-testid="pt-products">
      <div className="jp-section__head">
        <h2 className="sa-h2">Theo sản phẩm</h2>
        <label className="jp-sort">
          Xếp theo
          <select aria-label="Xếp theo" onChange={(e) => setSortBy(e.target.value as SortKey)} value={sortBy}>
            <option value="impact">GMV ảnh hưởng</option>
            <option value="change">Thay đổi</option>
          </select>
        </label>
      </div>
      <div className="jp-grid jp-grid--pr jp-grid--head">
        <span>Sản phẩm</span>
        <span>Kỳ này</span>
        <span>Kỳ trước</span>
        <span>Thay đổi</span>
        <span>GMV ảnh hưởng</span>
        <span />
      </div>
      {rows.map((p) => (
        <div className="jp-grid jp-grid--pr" data-testid={`pt-product-${p.product_id}`} key={p.product_id}>
          <Link className="jp-who jp-prod" href={links.product(p.product_id)}>
            <Ini src={p.image_url} text={initialsOf(p.name)} />
            <span className="jp-clip">{p.name}</span>
          </Link>
          <b>{valueText(m, p.now, view.days, mode)}</b>
          <span>{valueText(m, p.prev, view.days, mode)}</span>
          <span className="jp-shift-cell"><Shift pct={p.change} /></span>
          <span>{impactText(p, view.days, mode)}</span>
          <Cta channel={sel.channel} metric={m} state={state} product={p.product_id} row={p} />
        </div>
      ))}
      {rows.length === 0 ? <Empty testId="pt-products-empty">—</Empty> : null}
    </section>
  );
}
