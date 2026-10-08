/**
 * Decision evidence mapper (AC-7.6) — the ONE place that reads the P7-B
 * Optimize Product fields of a `GET /v1/demo/decisions` item.
 *
 * Shape (backend `api/routes/demo_decisions.py`, mirrored in
 * `@juli/contracts` `DemoDecisionDiagnosis` / `DemoDecisionEvidence`):
 *
 *   item.recommendation.diagnosis = {
 *     rank, status, status_label,
 *     stage: { code, label },              // label is Vietnamese, shown as is
 *     lever: { code, label, action, detail, … },
 *     main_kpi, trigger: { code, gap, sentence },
 *     recoverable_gmv_per_day, recoverable_gmv_basis: { label, … }, …
 *   }
 *   item.recommendation.evidence = {
 *     window_days, current: { start, end, days_with_data }, previous: {…},
 *     notes: string[],
 *     metrics: [{ key, label, unit, definition, current, previous, change,
 *                 confidence, note }]
 *   }
 *   item.recommendation.expected_impact =
 *     { metric: "recoverable_gmv_per_day", value, confidence: "rule_based_estimate" }
 *
 * Ratios are fractions (0.02 = 2 %); `change` is relative. Metric labels are
 * TikTok's KPI names and are shown exactly as the backend sends them; codes
 * (`stage.code`, `lever.code`, `metric.key`) never reach the screen.
 *
 * A card WITHOUT `diagnosis` maps to `null` and keeps the old rendering.
 */

import type { DemoDecisionItem } from "@juli/contracts";

export type EvidenceConfidence = "Rõ" | "Tham khảo" | "Chưa đủ dữ liệu";

/** How a value is printed: ratio → %, vnd → ₫, count → plain number. */
export type EvidenceUnit = "ratio" | "vnd" | "count";

export interface EvidenceMetric {
  readonly key: string;
  readonly label: string;
  readonly unit: EvidenceUnit;
  readonly previous: number | null;
  readonly current: number | null;
  readonly change: number | null;
  readonly confidence: EvidenceConfidence | null;
  readonly note: string | null;
}

export interface DecisionEvidence {
  /** Diagnosed funnel stage, e.g. "Hiển thị → Nhấp (thẻ sản phẩm)". */
  readonly stage: string | null;
  /** What to do, e.g. "Viết lại tiêu đề" (lever action, else its label). */
  readonly lever: string | null;
  /** Why, e.g. "CTR thẻ sản phẩm ước tính thấp hơn 60 % …". */
  readonly trigger: string | null;
  /** D22 rule-based recoverable GMV per day, in đồng. */
  readonly recoverableGmvPerDay: number | null;
  readonly windowDays: number;
  /** Last day of the recent window (ISO date). */
  readonly asOf: string | null;
  readonly metrics: readonly EvidenceMetric[];
  readonly notes: readonly string[];
}

const CONFIDENCES: readonly EvidenceConfidence[] = ["Rõ", "Tham khảo", "Chưa đủ dữ liệu"];

function finite(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function unitOf(unit: unknown): EvidenceUnit {
  if (unit === "ratio") return "ratio";
  if (unit === "vnd" || unit === "vnd_per_day") return "vnd";
  return "count";
}

function confidenceOf(value: unknown): EvidenceConfidence | null {
  return CONFIDENCES.find((label) => label === value) ?? null;
}

export function mapDecisionEvidence(
  item: DemoDecisionItem | null | undefined,
): DecisionEvidence | null {
  const recommendation = item?.recommendation;
  const diagnosis = recommendation?.diagnosis;
  if (!recommendation || !diagnosis) return null;
  const evidence = recommendation.evidence ?? null;

  const impact = recommendation.expected_impact;
  const recoverable =
    finite(diagnosis.recoverable_gmv_per_day) ??
    (impact?.metric === "recoverable_gmv_per_day" ? finite(impact.value) : null);

  const metrics: EvidenceMetric[] = (evidence?.metrics ?? []).flatMap((metric) => {
    const label = text(metric?.label);
    if (!label) return [];
    return [
      {
        key: metric.key,
        label,
        unit: unitOf(metric.unit),
        previous: finite(metric.previous),
        current: finite(metric.current),
        change: finite(metric.change),
        confidence: confidenceOf(metric.confidence),
        note: text(metric.note),
      },
    ];
  });

  return {
    stage: text(diagnosis.stage?.label),
    lever: text(diagnosis.lever?.action) ?? text(diagnosis.lever?.label),
    trigger: text(diagnosis.trigger?.sentence),
    recoverableGmvPerDay: recoverable,
    windowDays: finite(evidence?.window_days) ?? 30,
    asOf: text(evidence?.current?.end),
    metrics,
    notes: (evidence?.notes ?? []).filter((note) => text(note) !== null),
  };
}
