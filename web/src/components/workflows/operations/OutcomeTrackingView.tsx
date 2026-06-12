"use client";

import { useState } from "react";

import type { ValidatedWorkflowId } from "@/lib/mock-data/operations/schemas";
import {
  loadWorkflowOutcomeMetrics,
  OUTCOME_CADENCE_IDS,
  type OutcomeCadenceId,
  type OutcomeReadingStatus,
} from "@/lib/operations/outcome-metrics";

const CADENCE_TAB_LABELS: Record<OutcomeCadenceId, string> = {
  realtime: "Thời gian thực",
  daily: "Hàng ngày",
  weekly: "Hàng tuần",
  monthly: "Hàng tháng",
};

function statusLabel(status: OutcomeReadingStatus): string {
  switch (status) {
    case "achieved":
      return "Đạt mục tiêu";
    case "on_track":
      return "Đúng hướng";
    case "needs_attention":
      return "Cần theo dõi";
    default:
      return "Sơ bộ";
  }
}

function statusStyle(status: OutcomeReadingStatus): { background: string; color: string } {
  if (status === "achieved") {
    return {
      background: "color-mix(in srgb, var(--success) 12%, transparent)",
      color: "var(--success)",
    };
  }
  if (status === "on_track") {
    return {
      background: "color-mix(in srgb, var(--info) 12%, transparent)",
      color: "var(--info)",
    };
  }
  if (status === "needs_attention") {
    return {
      background: "color-mix(in srgb, var(--warning) 12%, transparent)",
      color: "var(--warning)",
    };
  }
  return {
    background: "color-mix(in srgb, var(--muted-foreground) 12%, transparent)",
    color: "var(--muted-foreground)",
  };
}

export function OutcomeTrackingView({
  workflowId,
  onBack,
}: {
  workflowId: ValidatedWorkflowId;
  onBack: () => void;
}) {
  const metrics = loadWorkflowOutcomeMetrics(workflowId);
  const [activeCadence, setActiveCadence] = useState<OutcomeCadenceId>("realtime");
  const activeSlice = metrics.cadences.find((slice) => slice.cadence === activeCadence);

  return (
    <section className="space-y-4" data-testid="outcome-tracking-view" data-workflow-id={workflowId}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-muted text-xs font-medium uppercase tracking-wide">
            Theo dõi kết quả
          </p>
          <h2 className="mt-1 text-lg font-bold" style={{ color: "var(--foreground)" }}>
            {metrics.workflow_name}
          </h2>
        </div>
        <button
          type="button"
          className="btn-secondary"
          data-testid="outcome-tracking-back"
          onClick={onBack}
        >
          Quay lại gợi ý
        </button>
      </div>

      <div
        className="card p-4"
        data-testid="outcome-success-criteria"
      >
        <h3 className="text-sm font-semibold">Tiêu chí thành công</h3>
        <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-muted">Chỉ số</dt>
            <dd data-testid="outcome-criteria-metric">{metrics.success_criteria.metric}</dd>
          </div>
          <div>
            <dt className="text-muted">Chu kỳ</dt>
            <dd data-testid="outcome-criteria-period">{metrics.success_criteria.period}</dd>
          </div>
          <div>
            <dt className="text-muted">Ngưỡng</dt>
            <dd data-testid="outcome-criteria-threshold">{metrics.success_criteria.threshold}</dd>
          </div>
        </dl>
      </div>

      <div
        className="flex flex-wrap gap-2"
        role="tablist"
        aria-label="Chu kỳ theo dõi kết quả"
        data-testid="outcome-cadence-tabs"
      >
        {OUTCOME_CADENCE_IDS.map((cadence) => (
          <button
            key={cadence}
            type="button"
            role="tab"
            aria-selected={activeCadence === cadence}
            className={activeCadence === cadence ? "btn-primary" : "btn-secondary"}
            data-testid={`outcome-cadence-tab-${cadence}`}
            onClick={() => setActiveCadence(cadence)}
          >
            {CADENCE_TAB_LABELS[cadence]}
          </button>
        ))}
      </div>

      {activeSlice && (
        <div
          className="card space-y-3 p-4"
          role="tabpanel"
          data-testid={`outcome-cadence-panel-${activeCadence}`}
        >
          <div>
            <h3 className="text-base font-semibold">{activeSlice.title}</h3>
            <p className="text-muted mt-1 text-sm">{activeSlice.description}</p>
          </div>

          {activeSlice.execution_status && (
            <p
              className="rounded-lg border px-3 py-2 text-sm"
              style={{ borderColor: "var(--border)" }}
              data-testid="outcome-execution-status"
            >
              {activeSlice.execution_status}
            </p>
          )}

          <ul className="space-y-2" data-testid="outcome-metric-readings">
            {activeSlice.readings.map((reading) => (
              <li
                key={`${reading.label}-${reading.value}`}
                className="flex flex-wrap items-center justify-between gap-2 rounded-lg border px-3 py-2"
                style={{ borderColor: "var(--border)" }}
              >
                <div>
                  <p className="text-sm font-medium">{reading.label}</p>
                  <p className="text-muted text-sm">{reading.value}</p>
                </div>
                <span className="badge text-xs" style={statusStyle(reading.status)}>
                  {statusLabel(reading.status)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
