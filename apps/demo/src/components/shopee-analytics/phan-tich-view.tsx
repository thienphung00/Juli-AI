"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { useShopee } from "../../lib/shopee-analytics/context";
import { DASH, fmt, pc, pp, sv, vnd } from "../../lib/shopee-analytics/format";
import { readWindow, srcOfFlowKey, windowParams, type WindowState } from "../../lib/shopee-analytics/params";
import { useResource } from "../../lib/shopee-analytics/use-resource";
import type { Critical, CriticalItem, N } from "../../lib/shopee-analytics/types";
import { KolView } from "../shopee-kol/kol-view";
import { PeriodBar } from "./period-bar";
import { Empty, Ini, InfoToggle, Notice, PageHead, PriceMargin, ResourceState, initialsOf } from "./ui";

/**
 * Phân tích (artboard PhanTich): the critical list ranked by the đồng each item has at stake. An
 * item is one metric of one scope held against ONE reference (the flow's normal band, a target,
 * the floor price, ROAS break-even or the shop median), drawn as a band chart; the cause is the
 * funnel stage plus one sentence; each item links to its Xếp hạng row and to its card. Items inside
 * their reference fold into "Trong dải bình thường" and are not counted in the total at stake.
 */

const STAGES = ["Lượt xem", "CTR", "CTOR", "AOV", "Biên"] as const;
const STAGE_INDEX: Record<string, number> = { views: 0, ctr: 1, ctor: 2, aov: 3 };

const FILTERS: readonly (readonly [string, string])[] = [
  ["all", "Tất cả"],
  ["views", "Lượt xem"],
  ["ctor", "CTR và CTOR"],
  ["aov", "AOV"],
  ["bien", "Biên và giá sàn"],
  ["ads", "Quảng cáo"],
];

function filterOf(item: CriticalItem): string {
  if (item.kpi === "views") return "views";
  if (item.kpi === "ctr" || item.kpi === "ctor") return "ctor";
  if (item.kpi === "aov") return "aov";
  if (item.kpi === "roas") return "ads";
  return "bien";
}

function valueText(item: CriticalItem, v: N): string {
  if (v === null) return DASH;
  if (item.kpi === "ctr" || item.kpi === "ctor") return pc(v);
  if (item.kpi === "bien" && item.reference.type === "target") return pp(v, 1);
  if (item.kpi === "roas") return fmt(v, 1);
  if (item.kpi === "orders") return fmt(v);
  return vnd(v);
}

function kpiLabel(item: CriticalItem): string {
  const base: Record<string, string> = {
    views: "Lượt xem",
    ctr: "CTR",
    ctor: "CTOR",
    aov: "AOV",
    bien: item.reference.type === "floor" ? "Giá sau voucher" : "Biên cuối",
    roas: "ROAS trực tiếp",
    gmv: "GMV theo mục tiêu tháng",
    orders: "Số đơn theo mục tiêu tháng",
  };
  return base[item.kpi] ?? item.kpi;
}

function sourceLabel(item: CriticalItem): string {
  if (item.flow_label) return item.flow_label;
  if (item.reference.type === "break_even") return "Quảng cáo (đơn đã đặt)";
  if (item.reference.type === "floor") return `SKU ${item.reference.sku ?? ""}`.trim();
  return item.level === "shop" ? "Cả shop" : "Tất cả";
}

function deviationText(item: CriticalItem): string {
  const ref = item.reference;
  const cur = item.current;
  if (cur === null) return DASH;
  switch (ref.type) {
    case "band":
      return ref.low == null ? DASH : `Thấp hơn dải ${fmt((ref.low - cur) * 100, 2)} điểm`;
    case "target":
      return ref.value == null
        ? DASH
        : item.kpi === "bien"
          ? `Thấp hơn mục tiêu ${fmt(ref.value - cur, 1)} điểm`
          : `Thấp hơn mục tiêu ${vnd(ref.value - cur)}`;
    case "floor":
      return ref.value == null ? DASH : `Thấp hơn giá sàn ${vnd(ref.value - cur)}`;
    case "break_even":
      return ref.value == null ? DASH : `Thấp hơn hoà vốn ${fmt(ref.value - cur, 1)}`;
    default:
      return ref.value == null ? DASH : `Thấp hơn trung vị ${item.kpi === "ctr" || item.kpi === "ctor" ? `${fmt((ref.value - cur) * 100, 2)} điểm` : vnd(ref.value - cur)}`;
  }
}

function refText(item: CriticalItem): string {
  const r = item.reference;
  const v = (n: N | undefined) => (n == null ? DASH : valueText(item, n));
  if (r.type === "band") return `Dải bình thường ${v(r.low)}–${v(r.high)} (${r.label})`;
  return `${r.label}: ${v(r.value)}`;
}

/** Positions (percent) of the dot, the band and the reference tick on the item's own axis. */
export function chartOf(item: CriticalItem) {
  const r = item.reference;
  const pts = [item.current, r.value, r.low, r.high].filter((x): x is number => typeof x === "number");
  if (pts.length === 0) return null;
  const mn = Math.min(...pts);
  const mx = Math.max(...pts);
  const pad = (mx - mn) * 0.25 || Math.abs(mx) * 0.1 || 1;
  const lo = Math.max(0, mn - pad);
  const hi = mx + pad;
  const pos = (x: number) => Math.max(0, Math.min(100, ((x - lo) / (hi - lo)) * 100));
  return {
    dot: item.current === null ? null : Math.max(2, Math.min(98, pos(item.current))),
    band: r.low != null && r.high != null ? { left: pos(r.low), width: pos(r.high) - pos(r.low) } : null,
    tick: r.type !== "band" && r.value != null ? pos(r.value) : null,
  };
}

function ItemChart({ item, small }: { readonly item: CriticalItem; readonly small?: boolean }) {
  const c = chartOf(item);
  if (!c) return null;
  return (
    <div className="sa-band" data-testid={`sa-band-${item.id}`}>
      <span className="sa-band__rail" />
      {c.band ? <span className="sa-band__range" style={{ left: `${c.band.left}%`, width: `${c.band.width}%` }} /> : null}
      {c.tick !== null && !small ? <span className="sa-band__tick" style={{ left: `${c.tick}%` }} /> : null}
      {c.dot !== null ? <span className={`sa-band__dot ${small ? "sa-band__dot--ok" : ""}`} style={{ left: `${c.dot}%` }} /> : null}
    </div>
  );
}

export function PhanTichPageView({ params }: { readonly params: URLSearchParams }) {
  const host = useShopee();
  const state = useMemo(() => readWindow(params), [params]);
  const key = `${host.shopKey}|ct|${JSON.stringify(state.query)}`;
  const data = useResource(() => host.api.critical(state.query), key);
  if (host.kol && params.get("tab") === "kol") return <KolView />;
  return (
    <div className="sa-page" data-testid="sa-phan-tich">
      {host.kol ? (
        <nav aria-label="Phân tích" className="sa-seg sa-seg--round sa-tabs" data-testid="sa-pt-tabs">
          <Link className="sa-seg__item sa-seg__item--on" href={host.links.critical()}>
            Điểm cần xem
          </Link>
          <Link className="sa-seg__item" href={host.links.screen("phan-tich", new URLSearchParams({ tab: "kol" }))}>
            KOL
          </Link>
        </nav>
      ) : null}
      <ResourceState resource={data}>{(c) => <Loaded critical={c} state={state} />}</ResourceState>
    </div>
  );
}

function Loaded({ critical: c, state }: { readonly critical: Critical; readonly state: WindowState }) {
  const { links } = useShopee();
  const [filter, setFilter] = useState("all");
  const [okOpen, setOkOpen] = useState(false);
  const shown = c.items.filter((it) => filter === "all" || filterOf(it) === filter);
  // The "trong dải bình thường" list follows the same filter as the items that need attention.
  const inBand = c.in_band.filter((it) => filter === "all" || filterOf(it) === filter);
  const sumDay = shown.reduce((t, it) => t + (it.at_stake_per_day ?? 0), 0);
  const withCard = shown.filter((it) => it.card);
  const firstCard = withCard[0]?.card;
  const href = (next: WindowState) => links.screen("phan-tich", windowParams(next));
  return (
    <>
      <PageHead
        chips={
          <span className="sa-chip sa-chip--outline">
            {c.window.days} ngày · so với {c.window.days} ngày trước
          </span>
        }
        eyebrow="PHÂN TÍCH"
        info={
          <InfoToggle>
            Một chỉ số được xếp &ldquo;cần chú ý&rdquo; khi nằm ngoài dải bình thường của luồng, thấp hơn mục tiêu, dưới giá sàn
            (hoặc ROAS dưới điểm hoà vốn), hoặc thấp hơn trung vị của shop. {c.ranking_rule}
          </InfoToggle>
        }
        title={`${c.items.length} chỉ số cần chú ý`}
      />
      <PeriodBar hrefFor={href} previous={null} state={state} window={c.window} />
      {c.notes.map((n) => (
        <Notice key={n.code} testId={`sa-note-${n.code}`} tone="info">
          {n.message}
        </Notice>
      ))}

      {c.items.length > 0 ? (
        <div className="sa-juli" data-testid="sa-at-stake">
          <span>
            <b className="sa-tone--pink">✦ Juli gợi ý</b> · Tổng ₫ có nguy cơ:{" "}
            <b className="sa-tone--down">{sv(-sumDay)}/ngày</b> ({sv(-sumDay * 30)}/tháng)
          </span>
          {firstCard ? (
            <Link className="sa-btn sa-btn--primary" href={links.card(firstCard.id, "phan-tich")}>
              Xem {withCard.length} đề xuất ›
            </Link>
          ) : (
            <span className="sa-hint">Chưa có đề xuất cho các mục này</span>
          )}
        </div>
      ) : null}

      <div className="sa-chips">
        <span className="sa-hint">Chỉ số</span>
        {FILTERS.map(([k, label]) => (
          <button
            aria-pressed={filter === k}
            className={`sa-pill ${filter === k ? "sa-pill--on" : ""}`}
            key={k}
            onClick={() => setFilter(k)}
            type="button"
          >
            {label}
          </button>
        ))}
        <span className="sa-hint sa-row__end">Xếp theo ₫ có nguy cơ, nhiều → ít</span>
      </div>

      <section className="sa-card" data-testid="sa-critical-list">
        <div className="sa-crow sa-crow--head">
          <span>Mục · nguồn · chỉ số</span>
          <span>Hiện trạng</span>
          <span>Lệch so với</span>
          <span>Nguyên nhân</span>
          <span className="sa-right">₫ có nguy cơ</span>
        </div>
        {shown.map((it, i) => {
          const stage = STAGE_INDEX[it.cause.stage] ?? 4;
          const rankKpi = it.ranking_link.kpi === "roas" ? "gmv" : it.ranking_link.kpi;
          const rankSrc = it.ranking_link.src === "all" ? "all" : srcOfFlowKey(it.ranking_link.src);
          return (
            <div className="sa-crow" data-testid={`sa-item-${it.id}`} id={it.id} key={it.id}>
              <div className="sa-crow__who">
                <span className="sa-crow__rank">{it.rank ?? i + 1}</span>
                <Ini text={initialsOf(it.name ?? "Cả shop")} />
                <span>
                  <span className="sa-mname__t">{it.name ?? "Cả shop"}</span>
                  {it.product_id && it.margin_basis ? <PriceMargin margin={it.margin_pct} p={it} /> : null}
                  <span className="sa-tags">
                    <span className="sa-tag2">{sourceLabel(it)}</span>
                    <span className="sa-tag2">{kpiLabel(it)}</span>
                    {it.money_basis === "placed" ? <span className="sa-tag2">đơn đã đặt</span> : null}
                    {it.assumed_cost ? <span className="sa-tag2">giá vốn giả định (1/3 giá)</span> : null}
                  </span>
                </span>
              </div>
              <div>
                <span className="sa-crow__value sa-tone--down">{valueText(it, it.current)}</span>
                {it.deviation_pct !== null ? (
                  <span className="sa-chip sa-chip--down">▼ {fmt(Math.abs(it.deviation_pct), 1)}% so với {it.reference.type === "band" ? "dải" : "mức tham chiếu"}</span>
                ) : null}
              </div>
              <div className="sa-crow__dev">
                <ItemChart item={it} />
                <span className="sa-tone--down sa-crow__devtxt">{deviationText(it)}</span>
                <span className="sa-hint">{refText(it)}</span>
              </div>
              <div className="sa-crow__cause">
                <span className="sa-stages">
                  {STAGES.map((s, j) => (
                    <span className={`sa-stage ${j === stage ? "sa-stage--on" : ""}`} key={s}>
                      {s}
                    </span>
                  ))}
                </span>
                <span className="sa-hint2">{it.cause.text}</span>
              </div>
              <div className="sa-crow__stake">
                <b className="sa-tone--down">{sv(-(it.at_stake_per_day ?? 0))}/ngày</b>
                <span className="sa-hint">{sv(-(it.at_stake_per_month ?? 0))}/tháng</span>
                {it.card ? (
                  <Link className="sa-rec sa-rec--s" href={links.card(it.card.id, "phan-tich", it.id)}>
                    Xem đề xuất ›
                  </Link>
                ) : (
                  <span className="sa-hint">Chưa có đề xuất</span>
                )}
                <Link
                  className="sa-link"
                  href={links.ranking(
                    { kpi: rankKpi, src: rankSrc, focus: it.ranking_link.focus, from: "phan-tich", card: it.card?.id ?? null },
                    state,
                  )}
                >
                  Xem xếp hạng ›
                </Link>
              </div>
            </div>
          );
        })}
        {shown.length === 0 ? (
          <Empty testId="sa-critical-empty">
            {c.items.length === 0
              ? "Chưa có chỉ số nào cần chú ý trong kỳ này. Mọi chỉ số đang trong dải bình thường hoặc chưa đủ dữ liệu để so."
              : "Không có chỉ số cần chú ý ở nhóm này. Chọn “Tất cả” để xem các nhóm khác."}
          </Empty>
        ) : null}
      </section>

      <section className="sa-card sa-card--soft" data-testid="sa-in-band">
        <div className="sa-card__head">
          <h2 className="sa-h2">Trong dải bình thường</h2>
          <span className="sa-hint">{inBand.length} mục · không tính vào ₫ có nguy cơ</span>
          <button aria-expanded={okOpen} className="sa-link sa-card__aside" onClick={() => setOkOpen(!okOpen)} type="button">
            {okOpen ? "Thu gọn" : "Xem thêm"}
          </button>
        </div>
        {okOpen
          ? inBand.map((it) => (
              <div className="sa-orow" data-testid={`sa-ok-${it.id}`} key={it.id}>
                <span className="sa-crow__who">
                  <Ini text={initialsOf(it.name ?? "Cả shop")} />
                  <span>
                    <span className="sa-mname__t">{it.name ?? "Cả shop"}</span>
                    <span className="sa-hint sa-block">
                      {sourceLabel(it)} · {kpiLabel(it)}
                    </span>
                  </span>
                </span>
                <b>{valueText(it, it.current)}</b>
                <ItemChart item={it} small />
                <span className="sa-hint2">Trong mức tham chiếu; không tính vào ₫ có nguy cơ.</span>
              </div>
            ))
          : null}
        {okOpen && inBand.length === 0 ? <Empty>Chưa có mục nào trong dải.</Empty> : null}
      </section>
      <p className="sa-hint">
        Thanh xám là dải bình thường của luồng; vạch đen là mục tiêu, giá sàn, điểm hoà vốn hoặc trung vị shop; chấm là hiện
        trạng.
      </p>
    </>
  );
}
