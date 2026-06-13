"use client";

import { useEffect, useMemo, useState } from "react";
import * as navigation from "next/navigation";

import { REPORT_DOMAIN_IDS, type ReportDomainId } from "./todays-report";

import { parseHomeHighlight, type HomeMetricAnchor } from "./journey-loop";

const HIGHLIGHT_DURATION_MS = 2000;

function prefersReducedMotion(): boolean {
  if (typeof window === "undefined") {
    return false;
  }

  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function isReportDomain(domain: HomeMetricAnchor["reportDomain"]): domain is ReportDomainId {
  return (REPORT_DOMAIN_IDS as readonly string[]).includes(domain);
}

function resolveHighlightTarget(anchor: HomeMetricAnchor): HTMLElement | null {
  if (anchor.reportDomain === "shop_health") {
    return document.querySelector<HTMLElement>(`[data-testid="shop-health-${anchor.metricKey}"]`);
  }

  return document.querySelector<HTMLElement>(
    `[data-testid="report-metric-chart-${anchor.reportDomain}-${anchor.metricKey}"]`,
  );
}

export interface HomeJourneyHighlightState {
  anchor: HomeMetricAnchor | null;
  highlightedMetricKey: string | null;
  highlightDomain: ReportDomainId | null;
}

export function useHomeJourneyHighlight(): HomeJourneyHighlightState {
  const searchParams =
    typeof navigation.useSearchParams === "function" ? navigation.useSearchParams() : null;
  const anchor = useMemo(
    () => parseHomeHighlight(searchParams?.get("highlight") ?? null),
    [searchParams],
  );
  const [highlightedMetricKey, setHighlightedMetricKey] = useState<string | null>(null);

  useEffect(() => {
    if (!anchor) {
      setHighlightedMetricKey(null);
      return;
    }

    const reducedMotion = prefersReducedMotion();
    if (!reducedMotion) {
      setHighlightedMetricKey(anchor.metricKey);
    } else {
      setHighlightedMetricKey(null);
    }

    const scrollTimer = window.setTimeout(() => {
      const target = resolveHighlightTarget(anchor);
      target?.scrollIntoView({
        behavior: reducedMotion ? "auto" : "smooth",
        block: "center",
      });
    }, 0);

    const pulseTimer = reducedMotion
      ? undefined
      : window.setTimeout(() => {
          setHighlightedMetricKey(null);
        }, HIGHLIGHT_DURATION_MS);

    return () => {
      window.clearTimeout(scrollTimer);
      if (pulseTimer !== undefined) {
        window.clearTimeout(pulseTimer);
      }
    };
  }, [anchor, searchParams]);

  const highlightDomain =
    anchor && isReportDomain(anchor.reportDomain) ? anchor.reportDomain : null;

  return {
    anchor,
    highlightedMetricKey,
    highlightDomain,
  };
}
