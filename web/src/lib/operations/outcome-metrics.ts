import type { ValidatedWorkflowId } from "@/lib/mock-data/operations/schemas";
import { VALIDATED_WORKFLOW_IDS } from "@/lib/mock-data/operations/schemas";

/** ADR-026 Appendix B — outcome tracking cadence slices. */
export const OUTCOME_CADENCE_IDS = [
  "realtime",
  "daily",
  "weekly",
  "monthly",
] as const;

export type OutcomeCadenceId = (typeof OUTCOME_CADENCE_IDS)[number];

export interface WorkflowOutcomeSuccessCriteria {
  metric: string;
  period: string;
  threshold: string;
}

export type OutcomeReadingStatus =
  | "on_track"
  | "preliminary"
  | "needs_attention"
  | "achieved";

export interface OutcomeMetricReading {
  label: string;
  value: string;
  status: OutcomeReadingStatus;
}

export interface OutcomeCadenceSlice {
  cadence: OutcomeCadenceId;
  title: string;
  description: string;
  execution_status?: string;
  readings: OutcomeMetricReading[];
}

/**
 * Stable P1.8 output envelope for outcome tracking (ADR-026 pipeline stage).
 * P2 swaps loaders; schema shape remains stable.
 */
export interface WorkflowOutcomeMetrics {
  workflow_id: ValidatedWorkflowId;
  workflow_name: string;
  executed_at: string;
  success_criteria: WorkflowOutcomeSuccessCriteria;
  cadences: OutcomeCadenceSlice[];
}

/** ADR-026 Appendix B — canonical success criteria per validated workflow. */
export const WORKFLOW_OUTCOME_SUCCESS_CRITERIA: Record<
  ValidatedWorkflowId,
  WorkflowOutcomeSuccessCriteria
> = {
  npl: {
    metric: "SPS change",
    period: "7d post-publish",
    threshold: "≥ +5 SPS points",
  },
  minimize_violations: {
    metric: "AHR improvement / violation count",
    period: "7d",
    threshold: "≥ +10 AHR points OR violation count ↓",
  },
  budget_optimization: {
    metric: "ROAS / revenue change",
    period: "7d",
    threshold: "ROAS +15% OR revenue +10%",
  },
  product_scaling: {
    metric: "Revenue per scaled SKU",
    period: "14d",
    threshold: "≥ +20% revenue for scaled products",
  },
  refund_spike_detection: {
    metric: "Refund rate reduction",
    period: "7d",
    threshold: "Refund rate returns to baseline",
  },
  stockout_prevention: {
    metric: "Stockouts avoided",
    period: "30d",
    threshold: "0 unplanned stockouts",
  },
};

const WORKFLOW_DISPLAY_NAMES: Record<ValidatedWorkflowId, string> = {
  npl: "Thêm sản phẩm mới",
  minimize_violations: "Giảm thiểu vi phạm",
  budget_optimization: "Tối ưu ngân sách quảng cáo",
  product_scaling: "Mở rộng sản phẩm",
  refund_spike_detection: "Phát hiện đỉnh hoàn tiền",
  stockout_prevention: "Phòng tránh hết hàng",
};

const CADENCE_LABELS: Record<OutcomeCadenceId, { title: string; description: string }> = {
  realtime: {
    title: "Thực thi thời gian thực",
    description: "Trạng thái thực thi ngay sau phê duyệt",
  },
  daily: {
    title: "Sơ bộ hàng ngày",
    description: "Đánh giá sơ bộ sau 24 giờ",
  },
  weekly: {
    title: "Đánh giá đầy đủ tuần",
    description: "Đối chiếu tiêu chí thành công theo chu kỳ",
  },
  monthly: {
    title: "Tổng hợp tháng",
    description: "Tổng hợp xu hướng và kết quả tích lũy",
  },
};

type FixtureBuilder = (criteria: WorkflowOutcomeSuccessCriteria) => OutcomeCadenceSlice[];

const OUTCOME_FIXTURE_BUILDERS: Record<ValidatedWorkflowId, FixtureBuilder> = {
  npl: (criteria) => [
    {
      cadence: "realtime",
      ...CADENCE_LABELS.realtime,
      execution_status: "Đã gửi bản nháp đăng sản phẩm — chờ xuất bản",
      readings: [{ label: criteria.metric, value: "—", status: "preliminary" }],
    },
    {
      cadence: "daily",
      ...CADENCE_LABELS.daily,
      readings: [{ label: criteria.metric, value: "+1.2 điểm SPS", status: "preliminary" }],
    },
    {
      cadence: "weekly",
      ...CADENCE_LABELS.weekly,
      readings: [{ label: criteria.metric, value: "+4.1 điểm SPS", status: "on_track" }],
    },
    {
      cadence: "monthly",
      ...CADENCE_LABELS.monthly,
      readings: [{ label: criteria.metric, value: "+6.0 điểm SPS", status: "achieved" }],
    },
  ],
  minimize_violations: (criteria) => [
    {
      cadence: "realtime",
      ...CADENCE_LABELS.realtime,
      execution_status: "Đã ghi nhận phê duyệt — chờ thực thi Phase 2",
      readings: [
        { label: "AHR", value: "72", status: "preliminary" },
        { label: "Vi phạm mở", value: "3", status: "needs_attention" },
      ],
    },
    {
      cadence: "daily",
      ...CADENCE_LABELS.daily,
      readings: [
        { label: "AHR", value: "74", status: "preliminary" },
        { label: "Vi phạm mở", value: "3", status: "on_track" },
      ],
    },
    {
      cadence: "weekly",
      ...CADENCE_LABELS.weekly,
      readings: [
        { label: "AHR", value: "+11 điểm", status: "achieved" },
        { label: "Vi phạm mở", value: "2", status: "achieved" },
      ],
    },
    {
      cadence: "monthly",
      ...CADENCE_LABELS.monthly,
      readings: [
        { label: criteria.metric, value: "AHR +14 · vi phạm −2", status: "achieved" },
      ],
    },
  ],
  budget_optimization: (criteria) => [
    {
      cadence: "realtime",
      ...CADENCE_LABELS.realtime,
      execution_status: "Đã ghi nhận phê duyệt — chờ thực thi Phase 2",
      readings: [{ label: "ROAS", value: "2.1×", status: "preliminary" }],
    },
    {
      cadence: "daily",
      ...CADENCE_LABELS.daily,
      readings: [
        { label: "ROAS", value: "2.3×", status: "preliminary" },
        { label: "Doanh thu", value: "+3%", status: "preliminary" },
      ],
    },
    {
      cadence: "weekly",
      ...CADENCE_LABELS.weekly,
      readings: [
        { label: "ROAS", value: "+16%", status: "achieved" },
        { label: "Doanh thu", value: "+8%", status: "on_track" },
      ],
    },
    {
      cadence: "monthly",
      ...CADENCE_LABELS.monthly,
      readings: [{ label: criteria.metric, value: "ROAS +18% · doanh thu +12%", status: "achieved" }],
    },
  ],
  product_scaling: (criteria) => [
    {
      cadence: "realtime",
      ...CADENCE_LABELS.realtime,
      execution_status: "Đã ghi nhận phê duyệt — chờ thực thi Phase 2",
      readings: [{ label: "SKU mục tiêu", value: "2", status: "preliminary" }],
    },
    {
      cadence: "daily",
      ...CADENCE_LABELS.daily,
      readings: [{ label: criteria.metric, value: "+5%", status: "preliminary" }],
    },
    {
      cadence: "weekly",
      ...CADENCE_LABELS.weekly,
      readings: [{ label: criteria.metric, value: "+14%", status: "on_track" }],
    },
    {
      cadence: "monthly",
      ...CADENCE_LABELS.monthly,
      readings: [{ label: criteria.metric, value: "+24%", status: "achieved" }],
    },
  ],
  refund_spike_detection: (criteria) => [
    {
      cadence: "realtime",
      ...CADENCE_LABELS.realtime,
      execution_status: "Quy trình rò rỉ đang chạy — thu thập bằng chứng",
      readings: [{ label: "Tỷ lệ hoàn tiền 7d", value: "8.2%", status: "needs_attention" }],
    },
    {
      cadence: "daily",
      ...CADENCE_LABELS.daily,
      readings: [{ label: criteria.metric, value: "7.6%", status: "preliminary" }],
    },
    {
      cadence: "weekly",
      ...CADENCE_LABELS.weekly,
      readings: [{ label: criteria.metric, value: "5.1% (baseline)", status: "achieved" }],
    },
    {
      cadence: "monthly",
      ...CADENCE_LABELS.monthly,
      readings: [{ label: criteria.metric, value: "Ổn định dưới baseline", status: "achieved" }],
    },
  ],
  stockout_prevention: (criteria) => [
    {
      cadence: "realtime",
      ...CADENCE_LABELS.realtime,
      execution_status: "Đã ghi nhận phê duyệt — chờ thực thi Phase 2",
      readings: [{ label: "SKU rủi ro", value: "4", status: "needs_attention" }],
    },
    {
      cadence: "daily",
      ...CADENCE_LABELS.daily,
      readings: [{ label: "Tồn kho tối thiểu", value: "2 SKU", status: "on_track" }],
    },
    {
      cadence: "weekly",
      ...CADENCE_LABELS.weekly,
      readings: [{ label: criteria.metric, value: "0 sự cố", status: "on_track" }],
    },
    {
      cadence: "monthly",
      ...CADENCE_LABELS.monthly,
      readings: [{ label: criteria.metric, value: "0 unplanned stockouts", status: "achieved" }],
    },
  ],
};

export function getWorkflowOutcomeSuccessCriteria(
  workflowId: ValidatedWorkflowId,
): WorkflowOutcomeSuccessCriteria {
  return WORKFLOW_OUTCOME_SUCCESS_CRITERIA[workflowId];
}

/**
 * Returns mock workflow_outcome_metrics for a validated workflow (P1.8-7).
 */
export function loadWorkflowOutcomeMetrics(
  workflowId: ValidatedWorkflowId,
  options?: { executedAt?: string },
): WorkflowOutcomeMetrics {
  const success_criteria = WORKFLOW_OUTCOME_SUCCESS_CRITERIA[workflowId];
  return {
    workflow_id: workflowId,
    workflow_name: WORKFLOW_DISPLAY_NAMES[workflowId],
    executed_at: options?.executedAt ?? new Date().toISOString(),
    success_criteria,
    cadences: OUTCOME_FIXTURE_BUILDERS[workflowId](success_criteria),
  };
}

export function loadAllWorkflowOutcomeMetrics(): WorkflowOutcomeMetrics[] {
  return VALIDATED_WORKFLOW_IDS.map((workflowId) => loadWorkflowOutcomeMetrics(workflowId));
}
