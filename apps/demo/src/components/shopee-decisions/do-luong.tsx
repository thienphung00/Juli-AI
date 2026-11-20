"use client";

import { useEffect } from "react";

import { DASH, fmt } from "../../lib/shopee-analytics/format";
import { useResource } from "../../lib/shopee-analytics/use-resource";
import { METRIC_NAME, type MetricKey } from "../../lib/metrics";
import { useReco } from "../../lib/shopee-decisions/context";
import type { MeasureVerdict, MeasurementCard } from "../../lib/shopee-decisions/types";
import { useSampleShopReviewer } from "../../lib/reviewer/mode";
import { MetricChip, Shift } from "../metrics/metric-chip";
import { TextChip } from "../shopee-analytics/ui";
import { finalVerdict } from "../../lib/shopee-decisions/forecast-display";
import { ActualLines } from "./forecast-lines";
import { NavLink, RecoState } from "./ui";

/**
 * Quyết định › Đo lường: per measuring / finished card the days measured, Thực tế against hiện tại per
 * metric (one amount, no range), the metric change and the final verdict, "đo chung với …" for a group; a finished card also gets the
 * Tối ưu row. Data comes through the host's RecoApi (seller, Ops, reviewer sample shop read-only).
 */

const VERDICT_LABEL: Record<MeasureVerdict, string> = { dang_do: "Đang đo", trong_khoang: "Trong khoảng", duoi_khoang: "Dưới khoảng", vuot_khoang: "Vượt khoảng", chua_ket_luan: "Chưa kết luận" };
const VERDICT_TONE: Record<MeasureVerdict, "flat" | "up" | "down" | "info"> = { dang_do: "flat", trong_khoang: "up", duoi_khoang: "down", vuot_khoang: "info", chua_ket_luan: "flat" };
const METRICS = new Set<string>(["views", "ctr", "ctor", "aov", "orders", "gmv", "margin"]);

function dm(iso: string | null): string {
  const m = iso ? /^(\d{4})-(\d{2})-(\d{2})/.exec(iso) : null;
  return m ? `${m[3]}/${m[2]}` : DASH;
}

function withQuery(href: string, extra: Record<string, string>): string {
  const [path, qs = ""] = href.split("?");
  const p = new URLSearchParams(qs);
  for (const [k, v] of Object.entries(extra)) p.set(k, v);
  return `${path}?${p.toString()}`;
}

function Row({ c, name, readOnly }: { readonly c: MeasurementCard; readonly name: string | null; readonly readOnly: boolean }) {
  const host = useReco();
  const final = finalVerdict(c.actual);
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
          <TextChip tone={VERDICT_TONE[c.verdict]}>{final ?? VERDICT_LABEL[c.verdict]}</TextChip>
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
        <div className="sd-dl-range" data-testid={`sd-dl-actual-${c.card_id}`}>
          <ActualLines actual={c.actual} showVerdict={false} measurement={{ label: c.label, measured_with: c.measured_with }} testId={`sd-dl-ac-${c.card_id}`} />
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
