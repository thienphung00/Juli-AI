import { CardBody } from "@juli/ui";
import Link from "next/link";

import type { ImpactMetricSnapshot } from "../lib/analytics/envelope-mapper";
import {
  buildAnalyticsMetricHref,
  getMainKpiDefinition,
} from "../lib/analytics/main-kpis";
import type { PlanImpactContent } from "../lib/plan-reviews";

/**
 * Shown in place of the number when the serving envelope carries no value for
 * the tied KPI — including the no-session case, where no envelope was ever
 * requested (issue #1772, ADR-094 decision 1). Deliberately digit-free: a
 * placeholder number would be a fabricated reading (ADR-055 item 15).
 */
export const IMPACT_UNAVAILABLE_TEXT =
  "Chưa có số liệu cho chỉ số này trong Phân tích";

export interface ImpactBlockShellProps {
  impact: PlanImpactContent;
  /**
   * `null` renders the same honest unavailable state whether the reason is
   * "no session, nothing was fetched" (the replay door) or "fetched, but the
   * envelope carries no value for this KPI" — the seller sees one missing
   * reading either way, never a different sentence per cause.
   */
  snapshot: ImpactMetricSnapshot | null;
}

/**
 * Pure presentation for the plan review card's impact block (ADR-055 items
 * 15–17, issue #771). Carries no analytics fetch capability of its own —
 * `PlanImpactBlock` (`impact-block.tsx`) is the only caller with a session
 * check, and `LiveImpactBlock` (`impact-block-live.tsx`) is the only caller
 * with fetch capability. Kept in its own module so both can render the
 * identical shell without either one owning the other's concern.
 */
export function ImpactBlockShell({ impact, snapshot }: ImpactBlockShellProps) {
  const definition = getMainKpiDefinition(impact.metricKey);
  const href = buildAnalyticsMetricHref(impact.metricKey);

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
