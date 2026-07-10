"use client";

import Link from "next/link";
import { useState } from "react";

import { usePrefersReducedMotion } from "@/hooks/use-prefers-reduced-motion";
import { computeEstimatedExtensionPct } from "@/lib/operations/estimated-extension";

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
  noExtensionCopy,
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
  noExtensionCopy?: string;
  thresholdTicks?: readonly number[];
  trackClassName?: string;
}) {
  const [hovered, setHovered] = useState(false);
  const prefersReducedMotion = usePrefersReducedMotion();
  const safeMax = scaleMax > 0 ? scaleMax : 1;
  const realPct = Math.min(100, (realValue / safeMax) * 100);
  const estimatedPct = Math.min(100, (estimatedValue / safeMax) * 100);
  const extensionStartPct = Math.min(realPct, estimatedPct);
  const extensionPct = computeEstimatedExtensionPct(realValue, estimatedValue, scaleMax);
  const realColor = colorForValue(realValue);
  const estimatedColor = colorForValue(estimatedValue);
  const showGlow = extensionPct > 0 && !prefersReducedMotion;

  if (extensionPct === 0) {
    return (
      <div
        className="relative flex min-h-11 flex-col justify-center gap-2"
        data-testid={`${testIdPrefix}-touch-target`}
      >
        <div
          className={`relative w-full rounded-full ${trackClassName}`}
          style={{ background: "color-mix(in srgb, var(--brand-primary) 14%, transparent)" }}
          role="group"
          aria-label={ariaLabel}
        >
          <div
            className="absolute inset-y-0 left-0 overflow-hidden rounded-full"
            style={{
              width: `${realPct}%`,
              background: realColor,
            }}
            data-testid={`${testIdPrefix}-real`}
          />
        </div>
        {noExtensionCopy ? (
          <p
            className="text-xs"
            style={{ color: "var(--muted-foreground)" }}
            data-testid={`${testIdPrefix}-no-extension`}
            aria-disabled="true"
          >
            {noExtensionCopy}
          </p>
        ) : null}
      </div>
    );
  }

  return (
    <div
      className="relative flex min-h-11 items-center"
      data-testid={`${testIdPrefix}-touch-target`}
    >
      <div
        className={`relative w-full rounded-full ${trackClassName}`}
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
          className="absolute inset-y-0 left-0 overflow-hidden rounded-full"
          style={{
            width: `${realPct}%`,
            background: realColor,
          }}
          data-testid={`${testIdPrefix}-real`}
        />

        <Link
          href={href}
          className={`absolute inset-y-0 rounded-r-full outline-none transition-opacity focus-visible:ring-2 focus-visible:ring-offset-2${
            showGlow ? " estimated-segment-glow" : ""
          }`}
          style={{
            left: `${extensionStartPct}%`,
            width: `${extensionPct}%`,
            background: estimatedColor,
            opacity: hovered ? 1 : ESTIMATED_OPACITY,
          }}
          data-testid={`${testIdPrefix}-estimated`}
          data-estimated-glow={showGlow ? "on" : "off"}
          aria-label={estimatedGainLabel ?? ariaLabel}
          title={estimatedGainLabel}
          onMouseEnter={() => setHovered(true)}
          onMouseLeave={() => setHovered(false)}
          onFocus={() => setHovered(true)}
          onBlur={() => setHovered(false)}
        />
      </div>
    </div>
  );
}
