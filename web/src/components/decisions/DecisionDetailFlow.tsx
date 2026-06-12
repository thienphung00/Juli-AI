"use client";

import { useCallback, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { TaskDismissModal } from "@/components/tasks/TaskDismissModal";
import { TaskExecutorModals } from "@/components/tasks/TaskExecutorModals";
import { TaskFeedbackBanner } from "@/components/tasks/TaskFeedbackBanner";
import { ReasoningPanel } from "@/components/workflows/operations/ReasoningPanel";
import {
  buildDecisionAnalytics,
  getDecisionPreviewRisks,
} from "@/lib/decisions/detail-content";
import {
  getNextStep,
  getPreviousStep,
  isFirstStep,
  isLastStep,
  type DecisionDetailStep,
} from "@/lib/decisions/detail-steps";
import type { RequiredInput } from "@/lib/decisions/types";
import { formatNumber } from "@/lib/format";
import type { PersonaId, SellerPersona } from "@/lib/mock-data/seller-personas/schemas";
import { useOperationsApproval } from "@/lib/operations/use-operations-approval";
import { buildWorkflowReasoning } from "@/lib/operations/reasoning";
import type { HealthCheckResults } from "@/lib/operations/health-check";
import type { WorkflowRecommendation } from "@/lib/operations/recommendations";

import { DecisionDetailStepIndicator } from "./DecisionDetailStepIndicator";

function confidenceLabel(
  confidence: WorkflowRecommendation["expected_impact"]["confidence"],
): string {
  if (confidence === "high") {
    return "Cao";
  }
  if (confidence === "medium") {
    return "Trung bình";
  }
  return "Thấp";
}

function DecisionDetailStepContent({
  step,
  recommendation,
  health,
  requiredInputs,
  inputValues,
  onInputChange,
}: {
  step: DecisionDetailStep;
  recommendation: WorkflowRecommendation;
  health: HealthCheckResults;
  requiredInputs: RequiredInput[];
  inputValues: Record<string, string>;
  onInputChange: (key: string, value: string) => void;
}) {
  const reasoning = buildWorkflowReasoning(recommendation, health);
  const analytics = buildDecisionAnalytics(recommendation, health);
  const risks = getDecisionPreviewRisks(recommendation.workflow_id);
  const { expected_impact: impact } = recommendation;

  switch (step) {
    case "why":
      return (
        <div data-testid="decision-detail-step-why">
          <h2 className="text-lg font-semibold">{recommendation.workflow_name}</h2>
          <p className="text-muted mt-1 text-sm">{recommendation.rationale}</p>
          <ReasoningPanel reasoning={reasoning} />
        </div>
      );
    case "analytics":
      return (
        <div data-testid="decision-detail-step-analytics">
          <h2 className="text-lg font-semibold">Phân tích hỗ trợ</h2>
          <p className="text-muted mt-1 text-sm">
            Số liệu từ kiểm tra sức khỏe shop (mock P1.8).
          </p>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            {analytics.map((metric) => (
              <div
                key={metric.key}
                className="rounded-xl border p-3"
                style={{ borderColor: "var(--border)" }}
                data-testid={`decision-analytics-${metric.key}`}
              >
                <p className="text-muted text-xs font-medium uppercase">{metric.label}</p>
                <p className="mt-1 text-lg font-semibold">{metric.value}</p>
                {metric.trend && (
                  <p className="text-muted mt-1 text-sm">{metric.trend}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      );
    case "inputs":
      return (
        <div data-testid="decision-detail-step-inputs">
          <h2 className="text-lg font-semibold">Thông tin cần có</h2>
          <p className="text-muted mt-1 text-sm">
            Cung cấp thông tin để Juli thực hiện đúng ý bạn.
          </p>
          <div className="mt-4 space-y-4">
            {requiredInputs.map((input) => (
              <label key={input.key} className="block">
                <span className="text-sm font-medium">
                  {input.label}
                  {!input.required ? " (tùy chọn)" : ""}
                </span>
                <input
                  type="text"
                  className="mt-1 w-full rounded-lg border px-3 py-2 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
                  style={{ borderColor: "var(--border)", outlineColor: "var(--primary)" }}
                  value={inputValues[input.key] ?? ""}
                  onChange={(event) => onInputChange(input.key, event.target.value)}
                  data-testid={`decision-input-${input.key}`}
                  placeholder="Nhập thông tin..."
                />
              </label>
            ))}
          </div>
        </div>
      );
    case "preview":
      return (
        <div data-testid="decision-detail-step-preview">
          <h2 className="text-lg font-semibold">Xem trước thực thi</h2>
          <div className="mt-4 space-y-3">
            <div
              className="rounded-xl border p-3"
              style={{ borderColor: "var(--border)" }}
              data-testid="decision-preview-impact"
            >
              <p className="text-muted text-xs font-medium uppercase">Tác động dự kiến</p>
              <p className="mt-1 text-sm">
                {impact.metric}: {formatNumber(impact.value)} điểm
              </p>
            </div>
            <div
              className="rounded-xl border p-3"
              style={{ borderColor: "var(--border)" }}
              data-testid="decision-preview-confidence"
            >
              <p className="text-muted text-xs font-medium uppercase">Độ tin cậy</p>
              <p className="mt-1 text-sm">{confidenceLabel(impact.confidence)}</p>
            </div>
            <div
              className="rounded-xl border p-3"
              style={{ borderColor: "var(--border)" }}
              data-testid="decision-preview-risks"
            >
              <p className="text-muted text-xs font-medium uppercase">Rủi ro tiềm ẩn</p>
              <ul className="mt-1 list-inside list-disc text-sm">
                {risks.map((risk) => (
                  <li key={risk}>{risk}</li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      );
    case "approve":
      return (
        <div data-testid="decision-detail-step-approve">
          <h2 className="text-lg font-semibold">Phê duyệt và thực hiện</h2>
          <p className="text-muted mt-1 text-sm">
            Xác nhận để Juli ghi nhận quyết định và mở quy trình thực thi (nếu có).
          </p>
          <div
            className="mt-4 rounded-xl border p-4"
            style={{ borderColor: "var(--border)", background: "var(--card)" }}
          >
            <p className="font-medium">{recommendation.workflow_name}</p>
            <p className="text-muted mt-1 text-sm">
              {impact.metric}: {formatNumber(impact.value)} · Độ tin cậy{" "}
              {confidenceLabel(impact.confidence).toLowerCase()}
            </p>
          </div>
        </div>
      );
    default:
      return null;
  }
}

export function DecisionDetailFlow({
  recommendation,
  health,
  persona,
  personaId,
  requiredInputs,
}: {
  recommendation: WorkflowRecommendation;
  health: HealthCheckResults;
  persona: SellerPersona;
  personaId: PersonaId;
  requiredInputs: RequiredInput[];
}) {
  const router = useRouter();
  const [currentStep, setCurrentStep] = useState<DecisionDetailStep>("why");
  const [inputValues, setInputValues] = useState<Record<string, string>>({});

  const approval = useOperationsApproval({
    persona,
    personaId,
    health,
    recommendations: [recommendation],
  });

  const {
    approveWorkflow,
    requestRejectWorkflow,
    cancelRejectWorkflow,
    confirmRejectWorkflow,
    rejectModalWorkflowId,
    feedback,
    clearFeedback,
    executor,
    getDisposition,
  } = approval;

  const disposition = getDisposition(recommendation.workflow_id);
  const isApproved = disposition === "approved";

  const handleInputChange = useCallback((key: string, value: string) => {
    setInputValues((prev) => ({ ...prev, [key]: value }));
  }, []);

  const handleNext = useCallback(() => {
    const next = getNextStep(currentStep);
    if (next) {
      setCurrentStep(next);
    }
  }, [currentStep]);

  const handleBack = useCallback(() => {
    const previous = getPreviousStep(currentStep);
    if (previous) {
      setCurrentStep(previous);
    }
  }, [currentStep]);

  const handleApprove = useCallback(() => {
    approveWorkflow(recommendation.workflow_id);
  }, [approveWorkflow, recommendation.workflow_id]);

  const handleBackToList = useCallback(() => {
    router.push("/decisions");
  }, [router]);

  const canProceedFromInputs = useMemo(() => {
    return requiredInputs
      .filter((input) => input.required)
      .every((input) => (inputValues[input.key] ?? "").trim().length > 0);
  }, [inputValues, requiredInputs]);

  const nextDisabled =
    currentStep === "inputs" && !canProceedFromInputs
      ? true
      : isLastStep(currentStep);

  return (
    <section className="space-y-4" data-testid="decision-detail-flow">
      <TaskExecutorModals
        personaId={personaId}
        leakagePersona={personaId === "leakage" ? persona : undefined}
        executor={executor}
      />

      {rejectModalWorkflowId !== null && (
        <TaskDismissModal onCancel={cancelRejectWorkflow} onConfirm={confirmRejectWorkflow} />
      )}

      {feedback && <TaskFeedbackBanner feedback={feedback} onDismiss={clearFeedback} />}

      <button
        type="button"
        className="btn-secondary text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        style={{ outlineColor: "var(--primary)" }}
        data-testid="decision-detail-back-to-list"
        onClick={handleBackToList}
      >
        ← Quay lại danh sách
      </button>

      <DecisionDetailStepIndicator currentStep={currentStep} />

      <div
        className="card p-4"
        data-testid={`decision-detail-panel-${currentStep}`}
      >
        <DecisionDetailStepContent
          step={currentStep}
          recommendation={recommendation}
          health={health}
          requiredInputs={requiredInputs}
          inputValues={inputValues}
          onInputChange={handleInputChange}
        />
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className="btn-secondary flex-1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          style={{ outlineColor: "var(--primary)" }}
          data-testid="decision-detail-back"
          disabled={isFirstStep(currentStep)}
          onClick={handleBack}
        >
          Quay lại
        </button>

        {currentStep === "approve" ? (
          isApproved ? (
            <p
              className="flex flex-1 items-center justify-center text-sm font-medium"
              style={{ color: "var(--success)" }}
              data-testid="decision-detail-approved-status"
            >
              Đã phê duyệt
            </p>
          ) : (
            <>
              <button
                type="button"
                className="btn-secondary flex-1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
                style={{ outlineColor: "var(--primary)" }}
                data-testid="decision-detail-reject"
                onClick={() => requestRejectWorkflow(recommendation.workflow_id)}
              >
                Từ chối
              </button>
              <button
                type="button"
                className="btn-primary flex-1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
                style={{ outlineColor: "var(--primary)" }}
                data-testid="decision-detail-approve"
                onClick={handleApprove}
              >
                Phê duyệt và thực hiện
              </button>
            </>
          )
        ) : (
          <button
            type="button"
            className="btn-primary flex-1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
            style={{ outlineColor: "var(--primary)" }}
            data-testid="decision-detail-next"
            disabled={nextDisabled}
            onClick={handleNext}
          >
            Tiếp theo
          </button>
        )}
      </div>
    </section>
  );
}
