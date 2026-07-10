import type {
  MockOrder,
  MockReturn,
  MockTask,
  TaskSeverity,
} from "@/lib/mock-data/seller-personas/schemas";

export const LEAKAGE_TASK_TYPES = [
  "return_spike",
  "buyer_cancellation_cluster",
  "refund_cluster",
  "return_window_policy",
] as const;

export type LeakageTaskType = (typeof LEAKAGE_TASK_TYPES)[number];

export type LeakageWorkflowStatus =
  | "new"
  | "in_review"
  | "evidence_reviewed"
  | "ready_to_execute"
  | "executing"
  | "completed"
  | "skipped";

export type LeakageCopySource = "mock" | "rules" | "ollama";

export type RootCauseClassification =
  | "seller_optimization"
  | "buyer_risk"
  | "undetermined"
  | "shop_config";

export type LeakageActionType =
  | "listing_update"
  | "investigation_package"
  | "monitoring"
  | "shop_settings";

export type LeakageSkipReason =
  | "false_positive"
  | "already_handled"
  | "not_relevant"
  | "other";

export type ReturnTypePreview = "item_swap" | "empty_return" | "other";

/** MockReturn with optional P1.7 stretch field for ML preview UI. */
export interface LeakageMockReturn extends MockReturn {
  return_type?: ReturnTypePreview;
}

export interface OrderItem {
  order_id: string;
  product_id: string;
  sku_id: string | null;
  quantity: number;
  unit_price_vnd: number;
}

export interface LeakageDetailChart {
  label_vi: string;
  value: number;
  unit: string;
}

export interface LeakageDetailBenchmark {
  label_vi: string;
  shop_value: number;
  peer_median: number;
}

export interface LeakageTaskDetail {
  summary_vi: string;
  charts: LeakageDetailChart[];
  benchmarks: LeakageDetailBenchmark[];
  affected_product_ids: string[];
  estimated_gmv_leakage_vnd: number | null;
}

export interface TimelineEvent {
  id: string;
  label_vi: string;
  occurred_at: string;
}

export interface ProfileMetric {
  key: string;
  value: string;
  label_vi: string;
}

export interface LeakageEvidenceBundle {
  orders: MockOrder[];
  returns: LeakageMockReturn[];
  order_items: OrderItem[];
  profile_metrics: ProfileMetric[];
  timeline_events: TimelineEvent[];
}

export interface LeakageRootCause {
  classification: RootCauseClassification;
  confidence: number;
  summary_vi: string;
  possible_causes: string[];
}

export interface LeakageRecommendedAction {
  action_type: LeakageActionType;
  summary_vi: string;
  checklist: string[];
}

export interface LeakageExecutionStep {
  id: string;
  title_vi: string;
  description_vi: string;
  mock_duration_ms: number | null;
}

export interface LeakageExecutionPlan {
  steps: LeakageExecutionStep[];
}

export interface LeakageSuccessPayload {
  headline_vi: string;
  metrics_vi: string[];
}

export interface LeakageWorkflowTask extends Omit<MockTask, "type" | "copy_source"> {
  type: LeakageTaskType;
  severity: TaskSeverity;
  copy_source: LeakageCopySource;
  workflow_status: LeakageWorkflowStatus;
  detail: LeakageTaskDetail;
  evidence_bundle: LeakageEvidenceBundle;
  root_cause: LeakageRootCause;
  recommended_action: LeakageRecommendedAction;
  execution_plan: LeakageExecutionPlan;
  success: LeakageSuccessPayload;
  skip_reason: LeakageSkipReason | null;
  skip_note: string | null;
}
