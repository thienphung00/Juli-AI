"use client";

import type {
  ExecutionLifecycleStatus,
  ExecutionRecord,
  ExecutionTimelineStep,
  ExecutionTimelineStepKind,
  ExecutionTimelineStepStatus,
} from "@juli/contracts";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  CardTitle,
} from "@juli/ui";
import Link from "next/link";

import { recommendationFixtures } from "../lib/recommendations";
import { useDemoState } from "./demo-state";

export const LIFECYCLE_STATUS_LABELS: Record<ExecutionLifecycleStatus, string> =
  {
    needs_input: "Cần thêm thông tin",
    executing: "Đang thực hiện",
    completed: "Hoàn tất",
  };

export const STEP_KIND_LABELS: Record<ExecutionTimelineStepKind, string> = {
  action: "Hành động",
  wait: "Chờ",
  outcome: "Kết quả",
};

export const STEP_STATUS_LABELS: Record<ExecutionTimelineStepStatus, string> = {
  pending: "Chờ xử lý",
  running: "Đang chạy",
  succeeded: "Thành công",
  failed: "Thất bại",
};

interface InProgressPanelProps {
  panelId: string;
}

export function getWorkflowTitle(workflowKey: string): string {
  return (
    recommendationFixtures.find((fixture) => fixture.workflowKey === workflowKey)
      ?.title ?? workflowKey
  );
}

export function getWorkflowCapability(workflowKey: string): string {
  return (
    recommendationFixtures.find((fixture) => fixture.workflowKey === workflowKey)
      ?.capabilityLabel ?? "—"
  );
}

export function getActiveStep(
  timeline: ExecutionTimelineStep[],
): ExecutionTimelineStep | undefined {
  const runningStep = timeline.find((step) => step.status === "running");
  if (runningStep) {
    return runningStep;
  }

  const lastSucceededIndex = timeline.reduce(
    (lastIndex, step, index) =>
      step.status === "succeeded" ? index : lastIndex,
    -1,
  );

  return timeline
    .slice(lastSucceededIndex + 1)
    .find((step) => step.status === "pending");
}

export function getCurrentStepLabel(record: ExecutionRecord): string {
  const activeStep = getActiveStep(record.timeline);

  if (!activeStep) {
    const lastStep = record.timeline.at(-1);
    return lastStep ? `Bước ${lastStep.stepNumber}: ${lastStep.title}` : "—";
  }

  return `Bước ${activeStep.stepNumber}: ${activeStep.title}`;
}

export function getNextActionText(record: ExecutionRecord): string | undefined {
  const activeStep = getActiveStep(record.timeline);
  if (!activeStep) {
    return undefined;
  }

  return activeStep.recoveryText ?? activeStep.title;
}

export function getLifecycleChipVariant(
  status: ExecutionLifecycleStatus,
): "info" | "success" | "warning" {
  if (status === "needs_input") {
    return "warning";
  }

  if (status === "completed") {
    return "success";
  }

  return "info";
}

interface ExecutionProgressCardProps {
  record: ExecutionRecord;
  onCancel: (executionId: string) => void;
}

function ExecutionProgressCard({
  record,
  onCancel,
}: ExecutionProgressCardProps) {
  const workflowTitle = getWorkflowTitle(record.workflowKey);
  const currentStepLabel = getCurrentStepLabel(record);
  const nextAction = getNextActionText(record);
  const lifecycleChipVariant = getLifecycleChipVariant(record.lifecycleStatus);

  // Determine mode strip text
  const modeLabel =
    record.lifecycleStatus === "needs_input" ? "Xác nhận" : "Đang chạy";

  // Get badge variant for lifecycle status
  const badgeVariant: "success" | "destructive" | "warning" | "live" =
    record.lifecycleStatus === "completed"
      ? "success"
      : record.lifecycleStatus === "needs_input"
        ? "warning"
        : "live";

  return (
    <Card>
      {/* Mode strip */}
      <div className="execution-card__mode-strip">
        <span className="execution-card__mode-label">{modeLabel}</span>
      </div>

      {/* Card Header */}
      <CardHeader>
        <div className="execution-card__header-row">
          <CardTitle>
            <Link href={`/decisions/in-progress/${record.executionId}`}>
              {workflowTitle}
            </Link>
          </CardTitle>
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
            onClick={() => onCancel(record.executionId)}
            aria-label={`Hủy ${workflowTitle}`}
          >
            Hủy
          </Button>
        </div>
      </CardBody>
    </Card>
  );
}

export function InProgressPanel({ panelId }: InProgressPanelProps) {
  const { mutableState, updateMutableState } = useDemoState();

  // Sort records: executing first, then needs_input, then completed
  const executionRecords = Object.values(mutableState.executionRecords)
    .filter((record): record is ExecutionRecord => record !== undefined)
    .sort((left, right) => {
      const statusOrder: Record<ExecutionLifecycleStatus, number> = {
        executing: 0,
        needs_input: 1,
        completed: 2,
      };

      const leftOrder = statusOrder[left.lifecycleStatus];
      const rightOrder = statusOrder[right.lifecycleStatus];

      if (leftOrder !== rightOrder) {
        return leftOrder - rightOrder;
      }

      // Within same status, sort by updatedAt descending
      return (
        new Date(right.updatedAt).getTime() - new Date(left.updatedAt).getTime()
      );
    });

  const handleCancelExecution = (executionId: string) => {
    // Dry-run only: mutate local execution records
    updateMutableState((prev) => {
      const { [executionId]: _, ...restRecords } = prev.executionRecords;
      return {
        ...prev,
        executionRecords: restRecords,
        executionProgress: {
          ...prev.executionProgress,
          [executionId]: undefined,
        },
      };
    });
  };

  if (executionRecords.length === 0) {
    return (
      <div aria-label="Đang thực hiện" id={panelId}>
        <section
          aria-label="Đang thực hiện"
          className="demo-placeholder"
          role="status"
        >
          <h2>Đang thực hiện</h2>
          <p>Công việc đã phê duyệt sẽ xuất hiện ở đây.</p>
        </section>
      </div>
    );
  }

  return (
    <div aria-label="Đang thực hiện" id={panelId}>
      <div className="execution-cards-container">
        {executionRecords.map((record) => (
          <ExecutionProgressCard
            key={record.executionId}
            record={record}
            onCancel={handleCancelExecution}
          />
        ))}
      </div>
    </div>
  );
}
