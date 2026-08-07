"use client";

import { CardBody } from "@juli/ui";
import Link from "next/link";
import { useEffect } from "react";

import { useOptionalAnalyticsData } from "../lib/analytics/analytics-data-context";
import { buildImpactMetricSnapshot } from "../lib/analytics/envelope-mapper";
import {
  buildAnalyticsMetricHref,
  getMainKpiDefinition,
} from "../lib/analytics/main-kpis";
import type { PlanImpactContent } from "../lib/plan-reviews";

/**
 * Shown in place of the number when the serving envelope carries no value for
 * the tied KPI. Deliberately digit-free: a placeholder number would be a
 * fabricated reading (ADR-055 item 15).
 */
export const IMPACT_UNAVAILABLE_TEXT =
  "Chưa có số liệu cho chỉ số này trong Phân tích";

interface PlanImpactBlockProps {
  impact: PlanImpactContent;
}

/**
 * The impact block — the plan review card's centre of gravity (ADR-055
 * items 15–17, issue #771).
 *
 * Shows the tied Main KPI's **real** current value and trend, read from the
 * same serving envelope the Analytics screen reads, plus a **directional**
 * goal and a deep link to the full metric.
 *
 * Three things it deliberately never does:
 * - **No projected magnitude.** Juli does not quote an amount it cannot stand
 *   behind (PRD user story 22; ADR-055 item 16).
 * - **No placeholder value.** A missing reading renders as a missing reading.
 * - **No second state.** It does not change after approval (ADR-055 item 17):
 *   Mock-mode executions are dry-run, so any later KPI movement is the
 *   reference shop's real trading, and showing it as the seller's achievement
 *   would be a fabricated causal claim.
 */
export function PlanImpactBlock({ impact }: PlanImpactBlockProps) {
  const analytics = useOptionalAnalyticsData();
  const loadAnalytics = analytics?.loadAnalytics;
  const definition = getMainKpiDefinition(impact.metricKey);
  const href = buildAnalyticsMetricHref(impact.metricKey);

  // The decision surface is not an analytics screen, so nothing else has asked
  // for the envelope by the time the card mounts.
  useEffect(() => {
    void loadAnalytics?.();
  }, [loadAnalytics]);

  const snapshot = buildImpactMetricSnapshot(
    analytics?.envelope,
    impact.metricKey,
  );

  return (
    <CardBody className="demo-plan__impact" data-testid="plan-impact">
      <p className="demo-plan__impact-metric">{definition.name}</p>
      {snapshot ? (
        <p className="demo-plan__impact-reading">
          <span className="demo-plan__impact-value">
            {snapshot.formattedValue}
          </span>{" "}
          <span
            className={`demo-plan__impact-delta demo-plan__impact-delta--${snapshot.sentiment}`}
          >
            {snapshot.delta}
          </span>
        </p>
      ) : (
        <p className="demo-plan__impact-unavailable">
          {IMPACT_UNAVAILABLE_TEXT}
        </p>
      )}
      <p className="demo-plan__impact-goal">{impact.directionalGoal}</p>
      <p className="demo-plan__impact-link">
        <Link href={href}>Xem {definition.name} trên Phân tích</Link>
      </p>
    </CardBody>
  );
}
