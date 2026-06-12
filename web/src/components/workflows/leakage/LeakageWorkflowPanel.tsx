"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { formatVND } from "@/lib/format";
import type { SellerPersona } from "@/lib/mock-data/seller-personas/schemas";
import type {
  LeakageActionType,
  LeakageEvidenceBundle,
  LeakageExecutionPlan,
  LeakageRootCause,
  LeakageTaskDetail,
  LeakageWorkflowTask,
  RootCauseClassification,
} from "@/lib/mock-data/leakage-workflow/schemas";
import {
  assertEvidenceHasNoRawPii,
  resolveEvidence,
  type ResolvedEvidence,
} from "@/lib/workflows/leakage/resolve-evidence";
import type { PersonaId } from "@/lib/mock-data/seller-personas/schemas";
import {
  LEAKAGE_WORKFLOW_STEPS,
  trackLeakageStepCompleted,
  trackLeakageWorkflowCompleted,
  trackLeakageWorkflowStarted,
  useLeakageWorkflow,
  type LeakageWorkflowStep,
} from "@/lib/workflows/leakage";

const ACTION_TYPE_LABELS: Record<LeakageActionType, string> = {
  listing_update: "Cập nhật listing",
  investigation_package: "Gói điều tra",
  monitoring: "Theo dõi watchlist",
  shop_settings: "Cài đặt shop",
};

const ROOT_CAUSE_LABELS: Record<RootCauseClassification, string> = {
  seller_optimization: "Tối ưu seller",
  buyer_risk: "Rủi ro buyer",
  undetermined: "Chưa xác định",
  shop_config: "Cấu hình shop",
};

const STEP_LABELS: Record<LeakageWorkflowStep, string> = {
  detail: "Chi tiết",
  evidence: "Bằng chứng",
  root_cause: "Nguyên nhân",
  recommended_action: "Hành động",
  execution: "Thực thi",
  success: "Hoàn tất",
};

function evidenceBundleToResolved(bundle: LeakageEvidenceBundle): ResolvedEvidence {
  return {
    orders: bundle.orders,
    returns: bundle.returns,
    affiliate_events: [],
    profile_metrics: bundle.profile_metrics.map((metric) => ({
      key: metric.key,
      value: metric.value,
    })),
  };
}

function resolveWorkflowEvidence(
  task: LeakageWorkflowTask,
  persona?: SellerPersona,
): ResolvedEvidence {
  if (persona && task.evidence_refs.length > 0) {
    return resolveEvidence(persona, task.evidence_refs);
  }
  return evidenceBundleToResolved(task.evidence_bundle);
}

export function LeakageWorkflowPanel({
  taskId,
  persona,
  personaId = persona?.profile.id ?? "leakage",
  onClose,
  onComplete,
}: {
  taskId: string;
  persona?: SellerPersona;
  personaId?: PersonaId;
  onClose: () => void;
  onComplete?: () => void;
}) {
  const workflow = useLeakageWorkflow({ taskId });
  const { task, state } = workflow;
  const canAdvance = workflow.canAdvance;
  const previousStepRef = useRef<LeakageWorkflowStep | null>(null);
  const workflowStartedRef = useRef(false);

  useEffect(() => {
    if (!task || workflowStartedRef.current) return;
    workflowStartedRef.current = true;
    trackLeakageWorkflowStarted({
      personaId,
      taskType: task.type,
    });
    previousStepRef.current = state.step;
  }, [task, personaId, state.step]);

  useEffect(() => {
    if (!task || previousStepRef.current === null) return;
    if (previousStepRef.current === state.step) return;

    trackLeakageStepCompleted({
      personaId,
      taskType: task.type,
      step: previousStepRef.current,
    });
    previousStepRef.current = state.step;
  }, [state.step, task, personaId]);

  const handleWorkflowComplete = useCallback(() => {
    if (task) {
      trackLeakageWorkflowCompleted({
        personaId,
        taskType: task.type,
      });
    }
    onComplete?.();
  }, [task, personaId, onComplete]);

  const modal = (
    <div
      className="fixed inset-0 z-[100] flex items-end justify-center p-4 pb-[calc(1rem+env(safe-area-inset-bottom))] sm:items-center"
      data-testid="leakage-workflow"
      role="dialog"
      aria-modal="true"
      aria-labelledby="leakage-workflow-title"
    >
      <button
        type="button"
        className="absolute inset-0 bg-black/50"
        aria-label="Đóng quy trình rò rỉ doanh thu"
        onClick={onClose}
      />
      <div
        className="card relative z-10 flex max-h-[90vh] w-full max-w-lg flex-col overflow-hidden"
        data-testid={`leakage-step-${state.step}`}
      >
        <header className="border-b px-4 py-3" style={{ borderColor: "var(--border)" }}>
          <div className="flex items-center justify-between gap-2">
            <h2
              id="leakage-workflow-title"
              className="text-base font-bold"
              style={{ color: "var(--foreground)" }}
            >
              {task?.title ?? "Quy trình rò rỉ doanh thu"}
            </h2>
            <button
              type="button"
              className="text-sm"
              style={{ color: "var(--muted-foreground)" }}
              data-testid="leakage-close"
              onClick={onClose}
            >
              Đóng
            </button>
          </div>
          <StepIndicator currentStep={state.step} />
          <p className="text-muted mt-2 text-xs">
            Bước hiện tại: {STEP_LABELS[state.step]}
          </p>
        </header>

        <div className="flex-1 overflow-y-auto p-4">
          {!task ? (
            <p className="text-sm" style={{ color: "var(--muted-foreground)" }}>
              Không tìm thấy nhiệm vụ rò rỉ doanh thu.
            </p>
          ) : (
            <>
              {state.step === "detail" && <DetailStep detail={task.detail} />}
              {state.step === "evidence" && (
                <EvidenceStep
                  task={task}
                  persona={persona}
                  piiGuardPassed={workflow.piiGuardPassed}
                  onConfirm={workflow.reviewEvidence}
                />
              )}
              {state.step === "root_cause" && (
                <RootCauseStep rootCause={task.root_cause} />
              )}
              {state.step === "recommended_action" && (
                <RecommendedActionStep task={task} />
              )}
              {state.step === "execution" && (
                <ExecutionStep
                  plan={task.execution_plan}
                  actionType={task.recommended_action.action_type}
                  onComplete={workflow.goNext}
                />
              )}
              {state.step === "success" && (
                <SuccessStep success={task.success} onComplete={handleWorkflowComplete} />
              )}
            </>
          )}
        </div>

        <footer
          className="flex gap-2 border-t px-4 py-3 safe-area-bottom"
          style={{ borderColor: "var(--border)" }}
        >
          {workflow.canGoBack && (
            <button
              type="button"
              className="btn-secondary flex-1"
              data-testid="leakage-back"
              onClick={workflow.goBack}
            >
              Quay lại
            </button>
          )}
          {state.step !== "execution" && state.step !== "success" && (
            <button
              type="button"
              className="btn-primary flex-1"
              data-testid="leakage-next"
              disabled={!canAdvance}
              onClick={workflow.goNext}
            >
              Tiếp theo
            </button>
          )}
        </footer>
      </div>
    </div>
  );

  if (typeof document === "undefined") {
    return modal;
  }

  return createPortal(modal, document.body);
}

function StepIndicator({ currentStep }: { currentStep: LeakageWorkflowStep }) {
  const currentIndex = LEAKAGE_WORKFLOW_STEPS.indexOf(currentStep);

  return (
    <>
      {/* Mobile: numbered dots */}
      <ol
        className="mt-3 flex items-center justify-between gap-1 sm:hidden"
        data-testid="leakage-step-indicator"
        aria-label="Tiến trình quy trình"
      >
        {LEAKAGE_WORKFLOW_STEPS.map((step, index) => (
          <li
            key={step}
            className="flex flex-1 flex-col items-center gap-1"
            data-testid={`leakage-step-indicator-${step}`}
            aria-current={step === currentStep ? "step" : undefined}
          >
            <span
              className="flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold"
              title={STEP_LABELS[step]}
              style={{
                background: index <= currentIndex ? "var(--primary)" : "var(--muted)",
                color: index <= currentIndex ? "#fff" : "var(--muted-foreground)",
              }}
            >
              {index + 1}
            </span>
          </li>
        ))}
      </ol>
      {/* Tablet+: labeled pills */}
      <ol
        className="mt-3 hidden gap-1 sm:flex"
        aria-label="Tiến trình quy trình"
      >
        {LEAKAGE_WORKFLOW_STEPS.map((step, index) => (
          <li
            key={`${step}-wide`}
            className="flex-1 rounded-full px-1 py-1 text-center text-xs font-semibold"
            aria-current={step === currentStep ? "step" : undefined}
            style={{
              background: index <= currentIndex ? "var(--primary)" : "var(--muted)",
              color: index <= currentIndex ? "#fff" : "var(--muted-foreground)",
            }}
          >
            {STEP_LABELS[step]}
          </li>
        ))}
      </ol>
    </>
  );
}

function DetailStep({ detail }: { detail: LeakageTaskDetail }) {
  return (
    <div className="space-y-4" data-testid="leakage-detail-step">
      <p className="text-sm" data-testid="leakage-detail-summary">
        {detail.summary_vi}
      </p>

      {detail.charts.length > 0 && (
        <section>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">
            Chỉ số
          </h3>
          <ul className="mt-2 space-y-2">
            {detail.charts.map((chart, index) => (
              <li
                key={chart.label_vi}
                className="flex justify-between text-sm"
                data-testid={`leakage-detail-chart-${index}`}
              >
                <span style={{ color: "var(--muted-foreground)" }}>
                  {chart.label_vi}
                </span>
                <span className="font-medium">
                  {chart.unit === "VND"
                    ? formatVND(chart.value)
                    : `${chart.value}${chart.unit === "%" ? "%" : ` ${chart.unit}`}`}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {detail.benchmarks.length > 0 && (
        <section data-testid="leakage-detail-benchmarks">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">
            So sánh ngành
          </h3>
          <ul className="mt-2 space-y-2">
            {detail.benchmarks.map((benchmark) => (
              <li key={benchmark.label_vi} className="text-sm">
                <p className="font-medium">{benchmark.label_vi}</p>
                <p className="text-muted text-xs">
                  Shop: {benchmark.shop_value} · Trung vị: {benchmark.peer_median}
                </p>
              </li>
            ))}
          </ul>
        </section>
      )}

      {detail.estimated_gmv_leakage_vnd != null && (
        <p className="text-sm font-semibold" data-testid="leakage-detail-gmv">
          GMV rò rỉ ước tính: {formatVND(detail.estimated_gmv_leakage_vnd)}
        </p>
      )}
    </div>
  );
}

function EvidenceStep({
  task,
  persona,
  piiGuardPassed,
  onConfirm,
}: {
  task: LeakageWorkflowTask;
  persona?: SellerPersona;
  piiGuardPassed: boolean;
  onConfirm: () => void;
}) {
  const evidence = useMemo(
    () => resolveWorkflowEvidence(task, persona),
    [task, persona],
  );

  if (!piiGuardPassed) {
    return (
      <div className="space-y-4" data-testid="leakage-pii-guard-blocked">
        <p className="text-sm font-medium" style={{ color: "var(--destructive, #ef4444)" }}>
          Không thể tiếp tục — bằng chứng chứa dữ liệu nhạy cảm chưa được ẩn danh hóa.
        </p>
        <p className="text-muted text-xs">
          Liên hệ hỗ trợ nếu bạn thấy thông tin buyer hoặc PII chưa được che.
        </p>
      </div>
    );
  }

  assertEvidenceHasNoRawPii(evidence);

  return (
    <div className="space-y-4" data-testid="leakage-evidence-step">
      <p className="text-sm" style={{ color: "var(--muted-foreground)" }}>
        Xem lại bằng chứng đã được ẩn danh hóa trước khi tiếp tục.
      </p>
      <EvidenceRows evidence={evidence} bundle={task.evidence_bundle} />
      <button
        type="button"
        className="btn-primary w-full"
        data-testid="leakage-evidence-confirm"
        onClick={onConfirm}
      >
        Đã xem bằng chứng
      </button>
    </div>
  );
}

function EvidenceRows({
  evidence,
  bundle,
}: {
  evidence: ResolvedEvidence;
  bundle: LeakageEvidenceBundle;
}) {
  return (
    <div className="space-y-4">
      {evidence.returns.length > 0 && (
        <section data-testid="leakage-evidence-section-returns">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-muted">
            Đơn trả hàng
          </h4>
          <ul className="mt-2 space-y-2">
            {evidence.returns.map((ret) => (
              <li
                key={ret.id}
                className="rounded-lg border px-3 py-2 text-sm"
                style={{ borderColor: "var(--border)" }}
                data-testid="leakage-evidence-return-row"
              >
                <p className="font-medium">{ret.product_title}</p>
                <p className="text-muted text-xs">Mã người mua: {ret.buyer_id}</p>
                <p className="mt-1">{ret.reason}</p>
              </li>
            ))}
          </ul>
        </section>
      )}

      {evidence.orders.length > 0 && (
        <section data-testid="leakage-evidence-section-orders">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-muted">
            Đơn hàng liên quan
          </h4>
          <ul className="mt-2 space-y-2">
            {evidence.orders.map((order) => (
              <li
                key={order.id}
                className="rounded-lg border px-3 py-2 text-sm"
                style={{ borderColor: "var(--border)" }}
                data-testid="leakage-evidence-order-row"
              >
                <p className="font-medium">{order.product_title}</p>
                <p className="text-muted text-xs">Mã người mua: {order.buyer_id}</p>
              </li>
            ))}
          </ul>
        </section>
      )}

      {bundle.timeline_events.length > 0 && (
        <section data-testid="leakage-evidence-section-timeline">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-muted">
            Dòng thời gian
          </h4>
          <ul className="mt-2 space-y-1">
            {bundle.timeline_events.map((event) => (
              <li key={event.id} className="text-sm">
                {event.label_vi}
              </li>
            ))}
          </ul>
        </section>
      )}

      {evidence.profile_metrics.length > 0 && (
        <section data-testid="leakage-evidence-section-profile">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-muted">
            Chỉ số shop
          </h4>
          <ul className="mt-2 space-y-1">
            {bundle.profile_metrics.map((metric) => (
              <li key={metric.key} className="text-sm">
                <span className="font-medium">{metric.label_vi}</span>: {metric.value}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function RootCauseStep({ rootCause }: { rootCause: LeakageRootCause }) {
  return (
    <div className="space-y-4" data-testid="leakage-root-cause-step">
      <p
        className="inline-block rounded-full px-2 py-0.5 text-xs font-semibold"
        data-testid="leakage-root-cause-classification"
        style={{ background: "var(--muted)", color: "var(--foreground)" }}
      >
        {ROOT_CAUSE_LABELS[rootCause.classification]}
      </p>
      <p className="text-sm" data-testid="leakage-root-cause-summary">
        {rootCause.summary_vi}
      </p>
      <p className="text-muted text-xs">
        Độ tin cậy: {(rootCause.confidence * 100).toFixed(0)}%
      </p>
      {rootCause.possible_causes.length > 0 && (
        <ul className="list-disc space-y-1 pl-5 text-sm">
          {rootCause.possible_causes.map((cause) => (
            <li key={cause}>{cause}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function RecommendedActionStep({ task }: { task: LeakageWorkflowTask }) {
  const { recommended_action: action } = task;

  return (
    <div className="space-y-4" data-testid="leakage-recommended-action-step">
      <p
        className="text-xs font-semibold uppercase tracking-wide text-muted"
        data-testid={`leakage-action-type-${action.action_type}`}
      >
        {ACTION_TYPE_LABELS[action.action_type]}
      </p>
      <p className="text-sm">{action.summary_vi}</p>
      <ul className="list-disc space-y-1 pl-5 text-sm">
        {action.checklist.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function ExecutionStep({
  plan,
  actionType,
  onComplete,
}: {
  plan: LeakageExecutionPlan;
  actionType: LeakageActionType;
  onComplete: () => void;
}) {
  const [activeIndex, setActiveIndex] = useState(0);
  const [completedIds, setCompletedIds] = useState<string[]>([]);

  const advance = useCallback(() => {
    setActiveIndex((index) => index + 1);
  }, []);

  useEffect(() => {
    if (activeIndex >= plan.steps.length) {
      onComplete();
      return;
    }

    const step = plan.steps[activeIndex]!;
    const duration = step.mock_duration_ms ?? 0;
    const timer = window.setTimeout(() => {
      setCompletedIds((prev) => [...prev, step.id]);
      advance();
    }, duration);

    return () => window.clearTimeout(timer);
  }, [activeIndex, advance, onComplete, plan.steps]);

  return (
    <div className="space-y-4" data-testid="leakage-execution-step">
      <p
        className="text-xs font-semibold uppercase tracking-wide"
        data-testid={`leakage-execution-mock-${actionType}`}
        style={{ color: "var(--primary)" }}
      >
        {ACTION_TYPE_LABELS[actionType]} (mock)
      </p>
      <ol className="space-y-3" data-testid="leakage-execution-stepper">
        {plan.steps.map((step, index) => {
          const isComplete = completedIds.includes(step.id);
          const isActive = index === activeIndex && !isComplete;

          return (
            <li
              key={step.id}
              className="rounded-lg border px-3 py-2 text-sm"
              data-testid={`leakage-execution-substep-${step.id}`}
              style={{
                borderColor: "var(--border)",
                opacity: index > activeIndex && !isComplete ? 0.5 : 1,
              }}
            >
              <div className="flex items-center gap-2">
                <span
                  className="flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-bold"
                  style={{
                    background: isComplete ? "var(--primary)" : "var(--muted)",
                    color: isComplete ? "var(--primary-foreground)" : "var(--muted-foreground)",
                  }}
                  aria-hidden
                >
                  {isComplete ? (
                    <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                      <path
                        d="M2.5 6L5 8.5L9.5 3.5"
                        stroke="currentColor"
                        strokeWidth="1.5"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                  ) : (
                    index + 1
                  )}
                </span>
                <p className="font-medium">{step.title_vi}</p>
              </div>
              <p className="text-muted mt-1 text-xs">{step.description_vi}</p>
              {isActive && (
                <p
                  className="mt-2 text-xs font-medium"
                  data-testid="leakage-execution-active"
                  style={{ color: "var(--primary)" }}
                >
                  Đang thực hiện…
                </p>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function SuccessStep({
  success,
  onComplete,
}: {
  success: LeakageWorkflowTask["success"];
  onComplete?: () => void;
}) {
  return (
    <div className="space-y-4" data-testid="leakage-success-step">
      <p className="text-sm font-medium" data-testid="leakage-success-headline">
        {success.headline_vi}
      </p>
      <ul className="space-y-2" data-testid="leakage-success-metrics">
        {success.metrics_vi.map((metric) => (
          <li
            key={metric}
            className="rounded-lg border px-3 py-2 text-sm"
            style={{ borderColor: "var(--border)" }}
          >
            {metric}
          </li>
        ))}
      </ul>
      {onComplete && (
        <button
          type="button"
          className="btn-primary w-full"
          data-testid="leakage-workflow-complete"
          onClick={onComplete}
        >
          Hoàn tất
        </button>
      )}
    </div>
  );
}
