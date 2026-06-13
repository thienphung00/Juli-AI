"use client";

import Link from "next/link";
import { useState } from "react";

const ESTIMATED_OPACITY = 0.4;

export function RealEstimatedBar({
  realValue,
  estimatedValue,
  scaleMax,
  colorForValue,
  href,
  testIdPrefix,
  estimatedGainLabel,
  ariaLabel,
  thresholdTicks = [],
  trackClassName = "h-3",
}: {
  realValue: number;
  estimatedValue: number;
  scaleMax: number;
  colorForValue: (value: number) => string;
  href: string;
  testIdPrefix: string;
  estimatedGainLabel?: string;
  ariaLabel: string;
  thresholdTicks?: readonly number[];
  trackClassName?: string;
}) {
  const [hovered, setHovered] = useState(false);
  const safeMax = scaleMax > 0 ? scaleMax : 1;
  const realPct = Math.min(100, (realValue / safeMax) * 100);
  const estimatedPct = Math.min(100, (estimatedValue / safeMax) * 100);
  const extensionStartPct = Math.min(realPct, estimatedPct);
  const extensionEndPct = Math.max(realPct, estimatedPct);
  const extensionPct = Math.max(0, extensionEndPct - extensionStartPct);
  const realColor = colorForValue(realValue);
  const estimatedColor = colorForValue(estimatedValue);

  return (
    <div className="relative">
      <div
        className={`relative overflow-hidden rounded-full ${trackClassName}`}
        style={{ background: "color-mix(in srgb, var(--brand-primary) 14%, transparent)" }}
        role="group"
        aria-label={ariaLabel}
      >
        {thresholdTicks.map((tick) => {
          const leftPct = Math.min(100, (tick / safeMax) * 100);
          return (
            <span
              key={tick}
              className="pointer-events-none absolute top-0 z-10 h-full w-px"
              style={{
                left: `${leftPct}%`,
                background: "color-mix(in srgb, var(--foreground) 35%, transparent)",
              }}
              data-testid={`${testIdPrefix}-tick-${String(tick).replace(".", "_")}`}
              aria-hidden="true"
            />
          );
        })}

        <div
          className="absolute inset-y-0 left-0 rounded-full"
          style={{
            width: `${realPct}%`,
            background: realColor,
          }}
          data-testid={`${testIdPrefix}-real`}
        />

        {extensionPct > 0 ? (
          <Link
            href={href}
            className="absolute inset-y-0 rounded-r-full outline-none transition-opacity focus-visible:ring-2 focus-visible:ring-offset-2"
            style={{
              left: `${extensionStartPct}%`,
              width: `${extensionPct}%`,
              background: estimatedColor,
              opacity: hovered ? 1 : ESTIMATED_OPACITY,
            }}
            data-testid={`${testIdPrefix}-estimated`}
            aria-label={estimatedGainLabel ?? ariaLabel}
            title={estimatedGainLabel}
            onMouseEnter={() => setHovered(true)}
            onMouseLeave={() => setHovered(false)}
            onFocus={() => setHovered(true)}
            onBlur={() => setHovered(false)}
          />
        ) : null}
      </div>
    </div>
  );
}
