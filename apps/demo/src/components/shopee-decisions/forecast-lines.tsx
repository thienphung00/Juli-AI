"use client";

import {
  METRIC_KEYS,
  actualText,
  dataThroughText,
  finalVerdict,
  measuredLabel,
  measuredWithText,
  metricView,
  type ActualBlock,
  type ForecastBlock,
  type MeasurementBlock,
  type MetricKey,
  isNoisy,
} from "../../lib/shopee-decisions/forecast-display";

/** F7.8: one amount per metric — headline "… dự kiến: X đ", grey "hiện tại: Y đ · −Z (−p %)". No range, no caption. */

export function MetricLines({ forecast, keys = METRIC_KEYS, days, testId = "fc", fallbackWhy }: { readonly forecast: ForecastBlock | null | undefined; readonly keys?: readonly MetricKey[]; readonly days?: number | null; readonly testId?: string; readonly fallbackWhy?: string | null }) {
  const why = forecast?.reason_text ?? fallbackWhy ?? null;
  return (
    <div className="fc" data-testid={testId}>
      {keys.map((k) => {
        const v = metricView(k, forecast?.metrics?.[k], { days: days ?? forecast?.days ?? null, why, noise: isNoisy(forecast, k) });
        return (
          <div className={`fc__row${k === "profit" ? " fc__row--main" : ""}`} data-testid={`${testId}-${k}`} key={k}>
            <div className="fc__head">
              <span className="fc__label">{v.label}</span>
              {": "}
              <b className={`fc__value${v.loss ? " sa-tone--down" : ""}`} data-testid={`${testId}-${k}-value`} title={v.why}>
                {v.value}
              </b>
            </div>
            {v.sub ? (
              <div className="fc__sub" data-testid={`${testId}-${k}-sub`}>
                {v.sub}
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

/** "Số liệu đến dd/mm", once per list header or card detail. */
export function DataThrough({ iso, testId = "fc-through" }: { readonly iso: string | null | undefined; readonly testId?: string }) {
  const t = dataThroughText(iso);
  return t ? (
    <span className="fc__through" data-testid={testId}>
      {t}
    </span>
  ) : null;
}

/** Đo lường / Thực hiện: Thực tế per metric, "Đã đo k/N ngày", the final verdict and "đo chung với …". */
export function ActualLines({ actual, measurement, keys = METRIC_KEYS, testId = "ac", showVerdict = true }: { readonly actual?: ActualBlock | null; readonly measurement?: MeasurementBlock | null; readonly keys?: readonly MetricKey[]; readonly testId?: string; readonly showVerdict?: boolean }) {
  const a = actual ?? measurement?.actual ?? null;
  const label = measuredLabel(a, measurement?.label);
  const verdict = showVerdict ? finalVerdict(a) : null;
  const with_ = measuredWithText(measurement?.measured_with);
  return (
    <div className="fc fc--actual" data-testid={testId}>
      {keys.map((k) => (
        <div className="fc__row" data-testid={`${testId}-${k}`} key={k}>
          {actualText(k, a?.metrics?.[k])}
        </div>
      ))}
      {label ? (
        <div className="fc__sub" data-testid={`${testId}-label`}>
          {label}
          {verdict ? (
            <>
              {" · "}
              <b data-testid={`${testId}-verdict`}>{verdict}</b>
            </>
          ) : null}
          {with_ ? <span data-testid={`${testId}-with`}>{` · ${with_}`}</span> : null}
        </div>
      ) : null}
    </div>
  );
}

/** One metric as a table cell: the amount, then the grey "hiện tại: … · ±Δ (±%)" line. */
export function MetricCell({ forecast, metric, testId, fallbackWhy }: { readonly forecast: ForecastBlock | null | undefined; readonly metric: MetricKey; readonly testId?: string; readonly fallbackWhy?: string | null }) {
  const v = metricView(metric, forecast?.metrics?.[metric], { days: forecast?.days ?? null, why: forecast?.reason_text ?? fallbackWhy ?? null, noise: isNoisy(forecast, metric) });
  return (
    <>
      <b className={v.loss ? "sa-tone--down" : undefined} data-testid={testId} title={v.why}>
        {v.value}
      </b>
      {v.sub ? (
        <div className="fc__sub" data-testid={testId ? `${testId}-sub` : undefined}>
          {v.sub}
        </div>
      ) : null}
    </>
  );
}
