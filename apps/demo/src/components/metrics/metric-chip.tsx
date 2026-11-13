import type { ReactNode } from "react";
import { METRIC_NAME, shift, type MetricKey } from "../../lib/metrics";

/** One colour per metric, the same on every screen (P100). */
export function MetricChip({ metric, on = false, children }: { readonly metric: MetricKey; readonly on?: boolean; readonly children?: ReactNode }) {
  return <span className={`jm-chip jm-chip--${metric}${on ? " jm-chip--on" : ""}`}>{children ?? METRIC_NAME[metric]}</span>;
}

/** "▲ 12 %" coloured by whether the change is good. Renders nothing without a value. */
export function Shift({ pct, good = 1, testId }: { readonly pct: number | null | undefined; readonly good?: 1 | -1; readonly testId?: string }) {
  const s = shift(pct, good);
  if (!s) return null;
  return (
    <span className={`jm-shift jm-shift--${s.tone}`} data-testid={testId}>
      {s.text}
    </span>
  );
}
