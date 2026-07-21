"use client";

import {
  Button,
  Card,
  CardBody,
  CardFooter,
  CardHeader,
  CardTitle,
  FilterChip,
  PageHeader,
  TextField,
} from "@juli/ui";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useId, useState } from "react";

import {
  buildReviewInputDefaultsForWorkflow,
  getWorkflowReviewStages,
} from "../lib/reviews";
import { useDemoState } from "./demo-state";

interface RecommendationReviewProps {
  workflowKey: string;
}

function renderBodyParagraphs(body: string) {
  return body.split("\n\n").map((paragraph) => (
    <p key={paragraph.slice(0, 48)}>{paragraph}</p>
  ));
}

export function RecommendationReview({ workflowKey }: RecommendationReviewProps) {
  const router = useRouter();
  const { mutableState, startExecution, updateMutableState } = useDemoState();
  const stages = getWorkflowReviewStages(workflowKey);
  const [currentIndex, setCurrentIndex] = useState(0);
  const progressId = useId();
  const announcementId = useId();

  const previewDraftValues = {
    ...buildReviewInputDefaultsForWorkflow(workflowKey),
    ...(mutableState.workflowReviewDrafts[workflowKey] ?? {}),
  };

  const handleInputChange = useCallback(
    (fieldKey: string, value: string) => {
      updateMutableState((current) => ({
        ...current,
        workflowReviewDrafts: {
          ...current.workflowReviewDrafts,
          [workflowKey]: {
            ...buildReviewInputDefaultsForWorkflow(workflowKey),
            ...(current.workflowReviewDrafts[workflowKey] ?? {}),
            [fieldKey]: value,
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

  const handleApprove = () => {
    const executionId = startExecution(workflowKey);
    router.push(`/decisions/in-progress/${executionId}`);
  };

  return (
    <section className="demo-review">
      <PageHeader
        subtitle="Xem lý do, bằng chứng và thông tin cần xác nhận trước khi phê duyệt."
        title="Xem xét đề xuất"
      />

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
                {currentStage.inputFields?.map((field) => (
                  <TextField
                    disabled={field.editable === false}
                    key={field.key}
                    label={field.label}
                    onChange={(event) =>
                      handleInputChange(field.key, event.target.value)
                    }
                    readOnly={field.editable === false}
                    required={field.required}
                    value={
                      mutableState.workflowReviewDrafts[workflowKey]?.[
                        field.key
                      ] ?? field.prefillValue
                    }
                  />
                ))}
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
            <Button onClick={handleApprove} type="button">
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
    </section>
  );
}
