"use client";

import type { ExecutionRecord } from "@juli/contracts";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  CardTitle,
  PageHeader,
} from "@juli/ui";
import { useParams } from "next/navigation";

import { DestinationPlaceholder } from "../../../../components/destination-placeholder";
import {
  LIFECYCLE_STATUS_LABELS,
  STEP_KIND_LABELS,
  STEP_STATUS_LABELS,
  getLifecycleChipVariant,
  getWorkflowTitle,
  getCurrentStepLabel,
  getNextActionText,
} from "../../../../components/in-progress-panel";
import { useDemoState } from "../../../../components/demo-state";
import { getWorkflowReviewStages } from "../../../../lib/reviews";
import { sanitizeSellerReviewText } from "../../../../lib/review-seller-copy";

function getApprovedInputLabel(
  workflowKey: string,
  inputKey: string,
): string {
  const inputField = getWorkflowReviewStages(workflowKey)
    .flatMap((stage) => stage.inputFields ?? [])
    .find((field) => field.key === inputKey);

  return inputField?.label ?? inputKey;
}

function ApprovedInputsSummary({ record }: { record: ExecutionRecord }) {
  const entries = Object.entries(record.approvedInputs);

  if (entries.length === 0) {
    return null;
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Thông tin đã phê duyệt</CardTitle>
      </CardHeader>
      <CardBody>
        <div className="execution-detail__summary">
          {entries.map(([key, value]) => (
            <div key={key} className="execution-detail__summary-item">
              <span className="execution-detail__label">
                {getApprovedInputLabel(record.workflowKey, key)}
              </span>
              <span className="execution-detail__value">{value}</span>
            </div>
          ))}
        </div>
      </CardBody>
    </Card>
  );
}

function ExecutionStepsList({ record }: { record: ExecutionRecord }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Tiến trình thực hiện</CardTitle>
      </CardHeader>
      <CardBody>
        <ol aria-label="Tiến trình thực hiện" className="demo-decisions__list">
          {record.timeline.map((step) => (
            <li key={step.id} data-step-kind={step.kind} data-step-status={step.status}>
              <article>
                <p className="demo-kicker">
                  Bước {step.stepNumber} · {STEP_KIND_LABELS[step.kind]}
                </p>
                <h3>{step.title}</h3>
                <p className="demo-intro">
                  {sanitizeSellerReviewText(step.description)}
                </p>
                {step.recoveryText ? (
                  <p className="demo-notice">
                    {sanitizeSellerReviewText(step.recoveryText)}
                  </p>
                ) : null}
                {step.errorText ? (
                  <p className="demo-notice" role="alert">
                    {sanitizeSellerReviewText(step.errorText)}
                  </p>
                ) : null}
              </article>
            </li>
          ))}
        </ol>
      </CardBody>
    </Card>
  );
}

export function InProgressDetailView({ executionId }: { executionId: string }) {
  const { mutableState, updateMutableState } = useDemoState();
  const record = mutableState.executionRecords[executionId];

  if (!record) {
    return (
      <DestinationPlaceholder
        description="Luồng thực hiện này không còn trong Demo hoặc chưa được tạo. Hãy quay lại Quyết định để xem các luồng đang chạy."
        recoveryHref="/decisions"
        recoveryLabel="Về Quyết định"
        state="empty"
        title="Không tìm thấy luồng thực hiện"
      />
    );
  }

  const workflowTitle = getWorkflowTitle(record.workflowKey);
  const currentStepLabel = getCurrentStepLabel(record);
  const nextAction = getNextActionText(record);
  const modeLabel =
    record.lifecycleStatus === "needs_input" ? "Xác nhận" : "Đang chạy";
  const badgeVariant: "success" | "destructive" | "warning" | "live" =
    record.lifecycleStatus === "completed"
      ? "success"
      : record.lifecycleStatus === "needs_input"
        ? "warning"
        : "live";

  const handleCancel = () => {
    updateMutableState((prev) => {
      const { [executionId]: _, ...restRecords } = prev.executionRecords;
      const { [executionId]: __, ...restProgress } = prev.executionProgress;
      return {
        ...prev,
        executionRecords: restRecords,
        executionProgress: restProgress,
      };
    });
  };

  return (
    <section className="demo-decisions">
      <PageHeader
        subtitle="Theo dõi từng bước hành động, chờ và kết quả sau khi bạn phê duyệt."
        title={workflowTitle}
      />
      <div className="demo-decisions__list">
        {/* Main execution progress card */}
        <Card>
          {/* Mode strip */}
          <div className="execution-card__mode-strip">
            <span className="execution-card__mode-label">{modeLabel}</span>
          </div>

          {/* Card Header */}
          <CardHeader>
            <div className="execution-card__header-row">
              <CardTitle>{workflowTitle}</CardTitle>
              <Badge variant={badgeVariant}>
                {LIFECYCLE_STATUS_LABELS[record.lifecycleStatus]}
              </Badge>
            </div>
          </CardHeader>

          {/* Card Body */}
          <CardBody>
            {/* Narrative step line */}
            <div className="execution-card__step-line">
              <p>{currentStepLabel}</p>
              {record.lifecycleStatus === "executing" && (
                <span className="execution-card__duration">5–10 phút</span>
              )}
            </div>

            {/* Next action / recovery text */}
            {nextAction && (
              <div className="execution-card__next-action">
                <p>{nextAction}</p>
              </div>
            )}

            {/* Policy line */}
            <div className="execution-card__policy-line">
              <p>Đã kiểm tra chính sách TikTok Shop</p>
            </div>

            {/* Cancel/Rollback button */}
            <div className="execution-card__actions">
              <Button
                variant="secondary"
                size="small"
                onClick={handleCancel}
                aria-label={`Hủy ${workflowTitle}`}
              >
                Hủy
              </Button>
            </div>
          </CardBody>
        </Card>

        {/* Approved inputs summary */}
        <ApprovedInputsSummary record={record} />

        {/* Timeline/steps */}
        <ExecutionStepsList record={record} />
      </div>
    </section>
  );
}

export default function InProgressDetailPage() {
  const { executionId } = useParams<{ executionId: string }>();

  return <InProgressDetailView executionId={executionId} />;
}
