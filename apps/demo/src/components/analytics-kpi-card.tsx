"use client";

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
import { getPreviewSnapshot } from "../lib/analytics/mock-data";
import type { AnalyticsRange } from "../lib/analytics/main-kpis";
import {
  AnalyticsPreviewChart,
  AnalyticsUnavailableChartPattern,
} from "./analytics-charts";

interface AnalyticsKpiCardProps {
  metricKey: MetricKey;
  range: AnalyticsRange;
  selected?: boolean;
  onSelect?: (metricKey: MetricKey, keyboardInitiated: boolean) => void;
}

export function AnalyticsKpiCard({
  metricKey,
  range,
  selected = false,
  onSelect,
}: AnalyticsKpiCardProps) {
  const definition = getMainKpiDefinition(metricKey);
  const preview = definition.available
    ? getPreviewSnapshot(metricKey, range)
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
        {definition.available && preview ? (
          <>
            <p className="analytics-kpi-card__value">{preview.formattedValue}</p>
            <p className="analytics-kpi-card__delta">{preview.delta}</p>
            <AnalyticsPreviewChart
              delta={preview.delta}
              label={definition.name}
              sparkline={preview.sparkline}
              trend={preview.trend}
              value={preview.formattedValue}
            />
          </>
        ) : (
          <>
            <StatusChip variant="neutral">Chưa khả dụng</StatusChip>
            <AnalyticsUnavailableChartPattern />
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

  if (!definition.available) {
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
