"use client";

import { useEffect } from "react";

import { DASH, fmt, sv } from "../../lib/shopee-analytics/format";
import { useResource } from "../../lib/shopee-analytics/use-resource";
import { METRIC_NAME, type MetricKey } from "../../lib/metrics";
import { useReco } from "../../lib/shopee-decisions/context";
import type { MeasureVerdict, MeasurementCard } from "../../lib/shopee-decisions/types";
import { useSampleShopReviewer } from "../../lib/reviewer/mode";
import { MetricChip, Shift } from "../metrics/metric-chip";
import { TextChip } from "../shopee-analytics/ui";
import { NavLink, RecoState } from "./ui";

/**
 * Quyết định › Đo lường: per measuring / finished card the days measured, Δ lợi nhuận over the whole
 * period against the card's range, the metric change and the verdict; a finished card also gets the
 * Tối ưu row. Data comes through the host's RecoApi (seller, Ops, reviewer sample shop read-only).
 */

const VERDICT_LABEL: Record<MeasureVerdict, string> = { dang_do: "Đang đo", trong_khoang: "Trong khoảng", duoi_khoang: "Dưới khoảng", vuot_khoang: "Vượt khoảng", chua_ket_luan: "Chưa kết luận" };
const VERDICT_TONE: Record<MeasureVerdict, "flat" | "up" | "down" | "info"> = { dang_do: "flat", trong_khoang: "up", duoi_khoang: "down", vuot_khoang: "info", chua_ket_luan: "flat" };
const METRICS = new Set<string>(["views", "ctr", "ctor", "aov", "orders", "gmv", "margin"]);

function dm(iso: string | null): string {
  const m = iso ? /^(\d{4})-(\d{2})-(\d{2})/.exec(iso) : null;
  return m ? `${m[3]}/${m[2]}` : DASH;
}

/** Positions (0..100) of the band and the dot on one shared scale that always includes 0. */
export function scaleOf(c: Pick<MeasurementCard, "band" | "actual">): { readonly from: number; readonly to: number; readonly dot: number | null } | null {
  const { p10, p90 } = c.band;
  if (p10 === null || p90 === null) return null;
  const lo = Math.min(0, p10, p90, c.actual ?? 0);
  const hi = Math.max(0, p10, p90, c.actual ?? 0);
  const span = hi - lo || 1;
  const at = (v: number) => ((v - lo) / span) * 100;
  return { from: at(Math.min(p10, p90)), to: at(Math.max(p10, p90)), dot: c.actual === null ? null : at(c.actual) };
}

function withQuery(href: string, extra: Record<string, string>): string {
  const [path, qs = ""] = href.split("?");
  const p = new URLSearchParams(qs);
  for (const [k, v] of Object.entries(extra)) p.set(k, v);
  return `${path}?${p.toString()}`;
}

function Row({ c, name, readOnly }: { readonly c: MeasurementCard; readonly name: string | null; readonly readOnly: boolean }) {
  const host = useReco();
  const sc = scaleOf(c);
  const pct = c.days ? Math.min(100, Math.round((c.days_measured / c.days) * 100)) : 0;
  const builder = host.href({ builder: true, productId: c.product_id });
  return (
    <li className="sd-dl-row" data-testid={`sd-dl-${c.card_id}`}>
      <div className="sd-dl-row__head">
        <div className="sd-dl-row__main">
          <span className="sd-th-row__group">{c.family_label}</span>
          <NavLink className="sd-th-row__title" href={host.href({ the: c.card_id })}>
            {c.title}
          </NavLink>
          <span className="sd-th-row__product">
            {name ? `${name} · ` : ""}
            {dm(c.started)} – {dm(c.ends)}
          </span>
        </div>
        <span data-testid={`sd-dl-verdict-${c.card_id}`}>
          <TextChip tone={VERDICT_TONE[c.verdict]}>{VERDICT_LABEL[c.verdict]}</TextChip>
        </span>
      </div>
      <div className="sd-dl-row__grid">
        <div className="sd-dl-days">
          <span>Ngày đo</span>
          <b data-testid={`sd-dl-days-${c.card_id}`}>{c.days ? `${fmt(c.days_measured, 0)}/${fmt(c.days, 0)}` : fmt(c.days_measured, 0)}</b>
          <div className="sd-dl-bar">
            <div className="sd-dl-bar__fill" style={{ width: `${pct}%` }} />
          </div>
        </div>
        <div className="sd-dl-range">
          <span>Δ lợi nhuận cả kỳ</span>
          <div className="sd-dl-track" data-testid={`sd-dl-track-${c.card_id}`}>
            {sc ? <div className="sd-dl-band" style={{ left: `${sc.from}%`, width: `${sc.to - sc.from}%` }} /> : null}
            {sc && sc.dot !== null ? <div className={`sd-dl-dot sd-dl-dot--${c.verdict}`} style={{ left: `calc(${sc.dot}% - 8px)` }} /> : null}
          </div>
          <div className="sd-dl-range__foot">
            <span>
              Khoảng {sv(c.band.p10)} – {sv(c.band.p90)}
            </span>
            <b>Thực tế {sv(c.actual)}</b>
          </div>
        </div>
        <div className="sd-dl-metrics">
          {c.metrics
            .filter((m) => METRICS.has(m.metric))
            .map((m) => (
              <span className="sd-dl-metric" key={m.metric}>
                <MetricChip metric={m.metric as MetricKey}>{METRIC_NAME[m.metric as MetricKey]}</MetricChip>
                <Shift pct={m.change_pct} />
              </span>
            ))}
        </div>
      </div>
      {c.done ? (
        <div aria-label="Tối ưu" className="sd-dl-opt" data-testid={`sd-dl-opt-${c.card_id}`} role="group">
          <button className="sa-btn" disabled type="button">
            Giữ
          </button>
          <button className="sa-btn" disabled type="button">
            Tăng
          </button>
          <button className="sa-btn" disabled type="button">
            Quay lại
          </button>
          {readOnly ? (
            <button className="sa-btn sa-btn--primary" disabled type="button">
              Thử phiên bản mới
            </button>
          ) : (
            <NavLink className="sa-btn sa-btn--primary" href={withQuery(builder, { kind: c.change_kind })}>
              Thử phiên bản mới
            </NavLink>
          )}
        </div>
      ) : null}
    </li>
  );
}

export function DoLuongView({ onCount }: { readonly onCount?: (n: number) => void }) {
  const host = useReco();
  const sample = useSampleShopReviewer();
  const readOnly = !!host.readOnly || sample;
  const res = useResource(() => host.reco.measurements(), `${host.shopKey}|do-luong`);
  const names = useResource(async () => new Map((await (host.products?.() ?? Promise.resolve([]))).map((p) => [p.id, p.name])), `${host.shopKey}|products`);
  const count = res.status === "ready" ? res.data.cards.length : null;
  useEffect(() => {
    if (count !== null) onCount?.(count);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [count]);
  return (
    <RecoState resource={res}>
      {(data) => (
        <ul className="sd-dl-list" data-testid="sd-do-luong">
          {data.cards.map((c) => (
            <Row c={c} key={c.card_id} name={(names.status === "ready" && c.product_id ? names.data.get(c.product_id) : null) ?? null} readOnly={readOnly} />
          ))}
        </ul>
      )}
    </RecoState>
  );
}
