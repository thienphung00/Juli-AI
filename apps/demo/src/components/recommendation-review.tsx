"use client";

import {
  Button,
  Card,
  CardBody,
  CardFooter,
  CardHeader,
  CardTitle,
  ConfirmDialog,
  FileUploadField,
  FilterChip,
  PageHeader,
  SelectField,
  TextField,
} from "@juli/ui";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useId, useState } from "react";

import {
  buildReviewInputDefaultsForWorkflow,
  getWorkflowReviewStages,
} from "../lib/reviews";
import { getWorkflowPlanReview } from "../lib/plan-reviews";
import { SELLER_APPROVE_GATE } from "../lib/review-seller-copy";
import {
  buildDecisionsHighlightHref,
  fetchActionCardInputs,
  type ActionCardInputsData,
} from "../lib/recommendations";
import { useDemoState } from "./demo-state";
import {
  getReplenishInventoryReviewStages,
  REPLENISH_INVENTORY_WORKFLOW_KEY,
} from "../lib/workflows/replenish-inventory";
import { PlanReviewCard } from "./plan-review-card";

interface RecommendationReviewProps {
  workflowKey: string;
}

function renderBodyParagraphs(body: string) {
  return body.split("\n\n").map((paragraph) => (
    <p key={paragraph.slice(0, 48)}>{paragraph}</p>
  ));
}

export function RecommendationReview({ workflowKey }: RecommendationReviewProps) {
  // Route by workflow key (ADR-055 item 8): workflows with a plan review
  // render the Situation → Decision → Details spine; every other workflow
  // keeps the five-stage review while the spine rolls out.
  const plan = getWorkflowPlanReview(workflowKey);

  if (plan) {
    return <PlanReviewCard plan={plan} />;
  }

  return <FiveStageReview workflowKey={workflowKey} />;
}

function FiveStageReview({ workflowKey }: RecommendationReviewProps) {
  const router = useRouter();
  const { mutableState, startExecution, updateMutableState } = useDemoState();
  const [currentIndex, setCurrentIndex] = useState(0);
  const [approveGateOpen, setApproveGateOpen] = useState(false);
  const [actionCardInputs, setActionCardInputs] = useState<ActionCardInputsData | null>(null);
  const progressId = useId();
  const announcementId = useId();

  // Fetch action card inputs for workflows that support computed values
  useEffect(() => {
    if (workflowKey === REPLENISH_INVENTORY_WORKFLOW_KEY) {
      fetchActionCardInputs(workflowKey).then((inputs) => {
        setActionCardInputs(inputs);
      });
    }
  }, [workflowKey]);

  // Use computed reorder_quantity for replenish_inventory, otherwise use base stages
  const stages =
    workflowKey === REPLENISH_INVENTORY_WORKFLOW_KEY && actionCardInputs
      ? getReplenishInventoryReviewStages(
          "cancellation-rate",
          actionCardInputs.reorder_quantity,
        )
      : getWorkflowReviewStages(workflowKey);

  const previewDraftValues = {
    ...buildReviewInputDefaultsForWorkflow(workflowKey, actionCardInputs?.reorder_quantity),
    ...(mutableState.workflowReviewDrafts[workflowKey] ?? {}),
  };

  const handleInputChange = useCallback(
    (fieldKey: string, value: string | File | null) => {
      // Store file name for uploaded files, empty string for null
      const storedValue = value instanceof File ? value.name : (value ?? "");

      updateMutableState((current) => ({
        ...current,
        workflowReviewDrafts: {
          ...current.workflowReviewDrafts,
          [workflowKey]: {
            ...buildReviewInputDefaultsForWorkflow(workflowKey),
            ...(current.workflowReviewDrafts[workflowKey] ?? {}),
            [fieldKey]: storedValue,
          },
        },
      }));
    },
    [updateMutableState, workflowKey],
  );

  if (stages.length === 0) {
    return (
      <section
        aria-label="Không tìm thấy quy trình"
        className="demo-placeholder"
        role="status"
      >
        <p className="demo-kicker">Không tìm thấy</p>
        <h1>Quy trình không được hỗ trợ</h1>
        <p>
          Đề xuất hoặc quy trình này chưa có trong Demo. Hãy quay lại Quyết định
          để chọn đề xuất khác.
        </p>
        <Link className="demo-placeholder__recovery" href="/decisions">
          Về Quyết định
        </Link>
      </section>
    );
  }

  const currentStage = stages[currentIndex];
  const isFirstStage = currentIndex === 0;
  const isApproveStage = currentStage.stage === "approve";

  const goToStage = (nextIndex: number) => {
    setCurrentIndex(nextIndex);
  };

  const handleApproveConfirm = () => {
    const executionId = startExecution(workflowKey);
    router.push(`/decisions/in-progress/${executionId}`);
  };

  return (
    <section className="demo-review">
      <PageHeader
        subtitle="Xem lý do, bằng chứng và thông tin cần xác nhận trước khi phê duyệt."
        title="Xem xét đề xuất"
      />

      <p className="demo-review__back">
        <Link href={buildDecisionsHighlightHref(workflowKey)}>
          Về danh sách đề xuất
        </Link>
      </p>

      <nav
        aria-label="Tiến trình xem xét"
        className="demo-review__progress"
        id={progressId}
      >
        <div aria-orientation="horizontal" role="tablist">
          {stages.map((stage, index) => {
            const isCurrent = index === currentIndex;
            const isComplete = index < currentIndex;

            return (
              <FilterChip
                aria-controls={announcementId}
                aria-current={isCurrent ? "step" : undefined}
                aria-label={`${stage.title}${isCurrent ? " (hiện tại)" : isComplete ? " (đã xem)" : ""}`}
                aria-selected={isCurrent}
                className="demo-review__progress-chip"
                disabled
                key={stage.stage}
                selected={isCurrent}
                tabIndex={isCurrent ? 0 : -1}
              >
                {stage.title}
              </FilterChip>
            );
          })}
        </div>
      </nav>

      <p aria-live="polite" className="demo-review__announcement" id={announcementId}>
        {`Đang ở bước ${currentIndex + 1} trên ${stages.length}: ${currentStage.title}`}
      </p>

      <Card aria-labelledby={`${announcementId}-title`}>
        <CardHeader>
          <CardTitle id={`${announcementId}-title`}>{currentStage.title}</CardTitle>
        </CardHeader>
        <CardBody data-testid="review-stage-body">
          {currentStage.stage === "why" ? renderBodyParagraphs(currentStage.body) : null}

          {currentStage.stage === "analytics" ? (
            <>
              <p>{currentStage.body}</p>
              {currentStage.analyticsMetricHref ? (
                <p>
                  <Link href={currentStage.analyticsMetricHref}>
                    Xem trên Phân tích
                  </Link>
                </p>
              ) : null}
            </>
          ) : null}

          {currentStage.stage === "inputs" ? (
            <>
              <p>{currentStage.body}</p>
              <form
                className="demo-review__inputs"
                onSubmit={(event) => event.preventDefault()}
              >
                {currentStage.inputFields?.map((field) => {
                  const currentValue =
                    mutableState.workflowReviewDrafts[workflowKey]?.[
                      field.key
                    ] ?? field.prefillValue;
                  const isSuggestion =
                    field.editable !== false &&
                    field.prefillValue !== "" &&
                    currentValue === field.prefillValue;

                  if (field.kind === "option-list" && field.options) {
                    return (
                      <SelectField
                        disabled={field.editable === false}
                        key={field.key}
                        label={field.label}
                        onChange={(event) =>
                          handleInputChange(field.key, event.target.value)
                        }
                        options={field.options}
                        prefillValue={field.prefillValue}
                        required={field.required}
                        suggestion={isSuggestion}
                        value={currentValue}
                      />
                    );
                  }

                  if (field.kind === "upload") {
                    return (
                      <FileUploadField
                        key={field.key}
                        label={field.label}
                        onChange={(file) =>
                          handleInputChange(field.key, file)
                        }
                        required={field.required}
                      />
                    );
                  }

                  return (
                    <TextField
                      disabled={field.editable === false}
                      key={field.key}
                      label={field.label}
                      onChange={(event) =>
                        handleInputChange(field.key, event.target.value)
                      }
                      readOnly={field.editable === false}
                      required={field.required}
                      suggestion={isSuggestion}
                      value={currentValue as string}
                    />
                  );
                })}
              </form>
            </>
          ) : null}

          {currentStage.stage === "preview" ? (
            <>
              {renderBodyParagraphs(currentStage.body)}
              <dl className="demo-review__draft-summary" data-testid="review-draft-summary">
                <dt>Tóm tắt thông tin sẽ gửi</dt>
                {stages
                  .find((stage) => stage.stage === "inputs")
                  ?.inputFields?.map((field) => (
                    <div className="demo-review__draft-row" key={field.key}>
                      <dt>{field.label}</dt>
                      <dd>
                        {(previewDraftValues[field.key] ?? field.prefillValue) ||
                          "—"}
                      </dd>
                    </div>
                  ))}
              </dl>
            </>
          ) : null}

          {currentStage.stage === "approve" ? <p>{currentStage.body}</p> : null}
        </CardBody>
        <CardFooter className="demo-review__actions">
          <Button
            disabled={isFirstStage}
            onClick={() => goToStage(currentIndex - 1)}
            type="button"
            variant="secondary"
          >
            Quay lại
          </Button>
          {isApproveStage ? (
            <Button onClick={() => setApproveGateOpen(true)} type="button">
              Phê duyệt
            </Button>
          ) : (
            <Button
              onClick={() => goToStage(currentIndex + 1)}
              type="button"
            >
              Tiếp theo
            </Button>
          )}
        </CardFooter>
      </Card>

      <ConfirmDialog
        cancelLabel={SELLER_APPROVE_GATE.cancelLabel}
        confirmLabel={SELLER_APPROVE_GATE.confirmLabel}
        description={SELLER_APPROVE_GATE.description}
        onConfirm={handleApproveConfirm}
        onOpenChange={setApproveGateOpen}
        open={approveGateOpen}
        title={SELLER_APPROVE_GATE.title}
      />
    </section>
  );
}
