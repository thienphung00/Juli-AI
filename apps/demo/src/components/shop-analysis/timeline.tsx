"use client";

import { useId, useState } from "react";
import { CartesianGrid, Line, LineChart, ReferenceArea, ReferenceLine, XAxis, YAxis } from "recharts";

import { CHANNEL_LABELS } from "../../lib/shop-analysis/derive";
import type { Band, ChannelKey, ChannelTimeline, ShopDiagnosisReport } from "../../lib/shop-analysis/types";
import { money, num, pct, shortDate } from "../../lib/vn-format";

/**
 * Step 3 of the report (ADR-108 decision 9): per channel, four lines —
 * Lượt hiển thị sản phẩm, CTR, CTOR, AOV — as 7-day rolling averages, with
 * flash-sale days shaded, the start of "30 ngày gần đây" as a solid line and
 * platform sale days dashed. Promotions are drawn as date bands on the same
 * 60-day axis above the charts.
 */

const METRICS = [
  { key: "impressions", title: "Lượt hiển thị sản phẩm", format: (v: number | null) => num(v) },
  { key: "ctr", title: "CTR (Tỷ lệ nhấp)", format: (v: number | null) => pct(v) },
  { key: "ctor", title: "CTOR", format: (v: number | null) => pct(v) },
  { key: "aov", title: "AOV (SKU)", format: (v: number | null) => money(v) },
] as const;

const CHART_W = 320;
const CHART_H = 150;

export function allDays(report: ShopDiagnosisReport): string[] {
  const days: string[] = [];
  const first = new Date(`${report.windows.prior_first}T00:00:00Z`);
  const last = new Date(`${report.windows.last_last}T00:00:00Z`);
  for (let d = first; d <= last; d = new Date(d.getTime() + 86_400_000)) {
    days.push(d.toISOString().slice(0, 10));
  }
  return days;
}

/** Contiguous runs of flash days (coverage ≥ 50 %, ADR-108 decision 10). */
export function flashRuns(coverage: Record<string, number>, days: string[]): Array<[string, string]> {
  const runs: Array<[string, string]> = [];
  let start: string | null = null;
  let prev: string | null = null;
  for (const day of days) {
    const isFlash = (coverage[day] ?? 0) >= 0.5;
    if (isFlash && start === null) start = day;
    if (!isFlash && start !== null && prev) {
      runs.push([start, prev]);
      start = null;
    }
    prev = day;
  }
  if (start !== null && prev) runs.push([start, prev]);
  return runs;
}

function MetricChart({
  title,
  data,
  dataKey,
  format,
  flash,
  boundary,
  saleDays,
}: {
  readonly title: string;
  readonly data: Array<Record<string, number | string | null>>;
  readonly dataKey: string;
  readonly format: (v: number | null) => string;
  readonly flash: Array<[string, string]>;
  readonly boundary: string;
  readonly saleDays: string[];
}) {
  const values = data
    .map((row) => row[dataKey])
    .filter((v): v is number => typeof v === "number");
  const lo = values.length ? Math.min(...values) : null;
  const hi = values.length ? Math.max(...values) : null;
  return (
    <figure className="timeline-chart">
      <figcaption className="timeline-chart__title">{title}</figcaption>
      {values.length === 0 ? (
        <p className="analysis-note">Không có số liệu</p>
      ) : (
        <>
          <div className="timeline-chart__plot" aria-hidden="true">
            <LineChart width={CHART_W} height={CHART_H} data={data} margin={{ top: 6, right: 6, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="var(--border)" vertical={false} />
              <XAxis
                dataKey="day"
                tickFormatter={shortDate}
                interval={13}
                tick={{ fill: "var(--muted-foreground)", fontSize: 10 }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis hide domain={["auto", "auto"]} />
              {flash.map(([from, to]) => (
                <ReferenceArea key={from} x1={from} x2={to} fill="var(--warning)" fillOpacity={0.15} strokeOpacity={0} />
              ))}
              {saleDays.map((day) => (
                <ReferenceLine key={day} x={day} stroke="var(--destructive)" strokeDasharray="2 2" />
              ))}
              <ReferenceLine x={boundary} stroke="var(--muted-foreground)" />
              <Line
                type="monotone"
                dataKey={dataKey}
                stroke="var(--chart-neutral)"
                strokeWidth={1.8}
                dot={false}
                connectNulls={false}
                isAnimationActive={false}
              />
            </LineChart>
          </div>
          <p className="timeline-chart__range">
            thấp nhất {format(lo)} · cao nhất {format(hi)}
          </p>
        </>
      )}
    </figure>
  );
}

const LANES: ReadonlyArray<{ kind: string; className: string }> = [
  { kind: "Flash sale", className: "band-lane__fill--flash" },
  { kind: "Giảm giá sản phẩm", className: "band-lane__fill--discount" },
  { kind: "Voucher", className: "band-lane__fill--voucher" },
];

/** Backend `render._band_strip`: three lanes over the 60 days. */
export function BandStrip({
  days,
  bands,
  coverage,
}: {
  readonly days: string[];
  readonly bands: Band[];
  readonly coverage: Record<string, number>;
}) {
  const index = new Map(days.map((d, i) => [d, i]));
  const n = Math.max(days.length, 1);
  return (
    <div className="band-strip" role="img" aria-label="Lịch khuyến mãi trong 60 ngày">
      {LANES.map((lane) => (
        <div key={lane.kind} className="band-lane">
          <span className="band-lane__label">{lane.kind}</span>
          <span className="band-lane__track">
            {lane.kind === "Flash sale"
              ? days.map((day, i) =>
                  (coverage[day] ?? 0) > 0 ? (
                    <span
                      key={day}
                      className={`band-lane__fill ${lane.className}`}
                      style={{
                        left: `${(i / n) * 100}%`,
                        width: `${100 / n}%`,
                        opacity: 0.25 + 0.75 * (coverage[day] ?? 0),
                      }}
                      title={`${shortDate(day)}: ${pct(coverage[day], 0)} thời gian có flash sale`}
                    />
                  ) : null,
                )
              : bands
                  .filter((b) => b.kind === lane.kind && index.has(b.first) && index.has(b.last))
                  .map((b) => {
                    const from = index.get(b.first) ?? 0;
                    const to = index.get(b.last) ?? 0;
                    return (
                      <span
                        key={`${b.title}-${b.first}`}
                        className={`band-lane__fill ${lane.className}`}
                        style={{ left: `${(from / n) * 100}%`, width: `${((to - from + 1) / n) * 100}%` }}
                        title={`${b.title}: ${shortDate(b.first)}–${shortDate(b.last)}`}
                      />
                    );
                  })}
          </span>
        </div>
      ))}
      <div className="band-lane band-lane--axis" aria-hidden="true">
        <span className="band-lane__label" />
        <span className="band-lane__track band-lane__track--axis">
          {days.map((day, i) =>
            i % 14 === 0 || i === days.length - 1 ? (
              <span key={day} className="band-lane__tick" style={{ left: `${(i / n) * 100}%` }}>
                {shortDate(day)}
              </span>
            ) : null,
          )}
        </span>
      </div>
    </div>
  );
}

export function TimelineSection({ report }: { readonly report: ShopDiagnosisReport }) {
  const timelines = report.timelines ?? [];
  const [selected, setSelected] = useState<ChannelKey>(timelines[0]?.channel ?? "total");
  const panelId = useId();
  const days = allDays(report);
  const flash = flashRuns(report.shop_flash?.coverage ?? {}, days);
  const timeline: ChannelTimeline | undefined =
    timelines.find((t) => t.channel === selected) ?? timelines[0];
  const byDay = new Map((timeline?.points ?? []).map((p) => [p.day, p]));
  const data = days.map((day) => {
    const point = byDay.get(day);
    return {
      day,
      impressions: point?.impressions ?? null,
      ctr: point?.ctr ?? null,
      ctor: point?.ctor ?? null,
      aov: point?.aov ?? null,
    };
  });

  return (
    <>
      <div className="band-legend">
        <span>
          <i className="band-legend__swatch band-lane__fill--flash" />
          Flash sale (đậm hơn = chạy lâu hơn trong ngày)
        </span>
        <span>
          <i className="band-legend__swatch band-lane__fill--discount" />
          Giảm giá sản phẩm
        </span>
        <span>
          <i className="band-legend__swatch band-lane__fill--voucher" />
          Voucher
        </span>
      </div>
      <BandStrip days={days} bands={report.shop_bands ?? []} coverage={report.shop_flash?.coverage ?? {}} />
      {timelines.length > 0 && (
        <>
          <div className="analysis-segmented" role="group" aria-label="Chọn kênh">
            {timelines.map((t) => (
              <button
                key={t.channel}
                type="button"
                aria-controls={panelId}
                aria-pressed={t.channel === timeline?.channel}
                onClick={() => setSelected(t.channel)}
              >
                {CHANNEL_LABELS[t.channel] ?? t.channel}
              </button>
            ))}
          </div>
          <div className="timeline-grid" id={panelId}>
            {METRICS.map((metric) => (
              <MetricChart
                key={metric.key}
                title={metric.title}
                data={data}
                dataKey={metric.key}
                format={metric.format}
                flash={flash}
                boundary={report.windows.last_first}
                saleDays={(report.sale_days ?? []).filter((d) => days.includes(d))}
              />
            ))}
          </div>
        </>
      )}
    </>
  );
}
