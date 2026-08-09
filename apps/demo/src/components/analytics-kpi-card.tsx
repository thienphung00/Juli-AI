"use client";

import type { DemoAnalyticsEnvelope } from "@juli/contracts";
import {
  Card,
  CardBody,
  CardHeader,
  CardMeta,
  CardTitle,
  InteractiveCard,
  StatusChip,
  UnavailableKpiPopover,
} from "@juli/ui";
import { useState } from "react";

import {
  type MetricKey,
  getMainKpiDefinition,
} from "../lib/analytics/main-kpis";
import type { AnalyticsRange } from "../lib/analytics/main-kpis";
import {
  buildLiveKpiSnapshot,
  isSelectableMetricKey,
} from "../lib/analytics/envelope-mapper";
import { analyticsDeltaClass } from "../lib/analytics/visual-polish";
import {
  AnalyticsPreviewChart,
  AnalyticsUnavailableChartPattern,
} from "./analytics-charts";

interface AnalyticsKpiCardProps {
  metricKey: MetricKey;
  range: AnalyticsRange;
  envelope: DemoAnalyticsEnvelope | null;
  selected?: boolean;
  onSelect?: (metricKey: MetricKey, keyboardInitiated: boolean) => void;
}

export function AnalyticsKpiCard({
  metricKey,
  range,
  envelope,
  selected = false,
  onSelect,
}: AnalyticsKpiCardProps) {
  const definition = getMainKpiDefinition(metricKey);
  const isAvailable = isSelectableMetricKey(metricKey, envelope);
  const liveSnapshot =
    envelope && isAvailable
      ? buildLiveKpiSnapshot(envelope, metricKey, range)
      : null;
  const [popoverOpen, setPopoverOpen] = useState(false);

  const cardContent = (
    <>
      <CardHeader>
        <CardMeta>
          <span aria-hidden="true">{definition.icon}</span> {definition.category}
        </CardMeta>
        <CardTitle id={`analytics-kpi-${metricKey}-title`}>
          {definition.name}
        </CardTitle>
      </CardHeader>
      <CardBody>
        <p className="analytics-kpi-card__description">{definition.description}</p>
        {isAvailable && liveSnapshot ? (
          <>
            <p className="analytics-kpi-card__value">{liveSnapshot.formattedValue}</p>
            <p className={analyticsDeltaClass(liveSnapshot.trend)}>
              {liveSnapshot.delta}
            </p>
            <AnalyticsPreviewChart
              delta={liveSnapshot.delta}
              label={definition.name}
              movement={liveSnapshot.movement}
              sparkline={liveSnapshot.sparkline}
              value={liveSnapshot.formattedValue}
            />
          </>
        ) : (
          <>
            <StatusChip variant="neutral">Chưa khả dụng</StatusChip>
            <AnalyticsUnavailableChartPattern label={definition.name} />
            <UnavailableKpiPopover
              activationRequirement={
                definition.unavailableReason?.activationRequirement ?? ""
              }
              dataSource={definition.unavailableReason?.dataSource ?? ""}
              kpiName={definition.name}
              onOpenChange={setPopoverOpen}
              open={popoverOpen}
            />
          </>
        )}
      </CardBody>
    </>
  );

  if (!isAvailable) {
    return (
      <Card
        aria-labelledby={`analytics-kpi-${metricKey}-title`}
        className="analytics-kpi-card analytics-kpi-card--unavailable"
        data-testid={`analytics-kpi-card-${metricKey}`}
      >
        {cardContent}
      </Card>
    );
  }

  return (
    <InteractiveCard
      aria-labelledby={`analytics-kpi-${metricKey}-title`}
      aria-pressed={selected}
      className="analytics-kpi-card analytics-kpi-card--available"
      data-testid={`analytics-kpi-card-${metricKey}`}
      onClick={(event) => {
        onSelect?.(metricKey, event.detail === 0);
      }}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelect?.(metricKey, true);
        }
      }}
      type="button"
    >
      {cardContent}
    </InteractiveCard>
  );
}
