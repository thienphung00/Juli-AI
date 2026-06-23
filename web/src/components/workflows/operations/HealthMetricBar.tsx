"use client";

import { formatNumber } from "@/lib/format";
import { healthBarProgressPercent } from "@/lib/metrics/shop-health-metrics";

export function HealthMetricBar({
  label,
  description,
  current,
  target,
  testId,
}: {
  label: string;
  description: string;
  current: number;
  target: number;
  testId: string;
}) {
  const percent = healthBarProgressPercent(current, target);
  const rampOpacity = 0.35 + (percent / 100) * 0.65;

  return (
    <div data-testid={testId}>
      <div className="flex items-end justify-between gap-2">
        <div>
          <p className="text-sm font-semibold" style={{ color: "var(--foreground)" }}>
            {label}
          </p>
          <p className="text-muted mt-0.5 text-xs">{description}</p>
        </div>
        <p className="text-right text-sm font-bold tabular-nums" style={{ color: "var(--brand-primary)" }}>
          {formatNumber(current)}
          <span className="text-muted font-medium"> / {formatNumber(target)}</span>
        </p>
      </div>

      <div
        className="mt-2 h-3 overflow-hidden rounded-full"
        style={{ background: "color-mix(in srgb, var(--brand-primary) 14%, transparent)" }}
        role="progressbar"
        aria-valuenow={current}
        aria-valuemin={0}
        aria-valuemax={target}
        aria-label={`${label}: ${formatNumber(current)} trên ${formatNumber(target)}`}
      >
        <div
          className="h-full rounded-full transition-all"
          style={{
            width: `${percent}%`,
            background: `color-mix(in srgb, var(--brand-primary) ${Math.round(rampOpacity * 100)}%, var(--foreground))`,
          }}
          data-testid={`${testId}-fill`}
        />
      </div>
    </div>
  );
}
