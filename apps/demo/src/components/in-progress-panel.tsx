"use client";

import type {
  ExecutionLifecycleStatus,
  ExecutionRecord,
  ExecutionTimelineStep,
  ExecutionTimelineStepKind,
  ExecutionTimelineStepStatus,
} from "@juli/contracts";
import {
  StatusChip,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "@juli/ui";
import { formatDateTime } from "@juli/utils";
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

export function InProgressPanel({ panelId }: InProgressPanelProps) {
  const { mutableState } = useDemoState();
  const executionRecords = Object.values(mutableState.executionRecords).sort(
    (left, right) =>
      new Date(right.updatedAt).getTime() - new Date(left.updatedAt).getTime(),
  );

  if (executionRecords.length === 0) {
    return (
      <div aria-label="Đang thực hiện" id={panelId}>
        <section
          aria-label="Đang thực hiện"
          className="demo-placeholder"
          role="status"
        >
          <p className="demo-kicker">Sắp ra mắt</p>
          <h2>Đang thực hiện</h2>
          <p>
            Công việc đã phê duyệt sẽ xuất hiện ở đây trong một bản cập nhật
            tiếp theo.
          </p>
        </section>
      </div>
    );
  }

  return (
    <div aria-label="Đang thực hiện" id={panelId}>
      <Table aria-label="Danh sách luồng đang thực hiện">
        <TableCaption>
          Các luồng đã phê duyệt đang chạy hoặc chờ phản hồi từ TikTok Shop.
        </TableCaption>
        <TableHead>
          <TableRow focusable={false}>
            <TableHeaderCell>Quy trình</TableHeaderCell>
            <TableHeaderCell>Trạng thái</TableHeaderCell>
            <TableHeaderCell>Bước hiện tại</TableHeaderCell>
            <TableHeaderCell>Bắt đầu</TableHeaderCell>
            <TableHeaderCell>Cập nhật</TableHeaderCell>
            <TableHeaderCell>Khả năng</TableHeaderCell>
            <TableHeaderCell>Việc tiếp theo</TableHeaderCell>
          </TableRow>
        </TableHead>
        <TableBody keyboardNav={false}>
          {executionRecords.map((record) => {
            const workflowTitle = getWorkflowTitle(record.workflowKey);
            const nextAction = getNextActionText(record);

            return (
              <TableRow
                key={record.executionId}
                data-execution-id={record.executionId}
                focusable={false}
              >
                <TableCell label="Quy trình">
                  <Link href={`/decisions/in-progress/${record.executionId}`}>
                    {workflowTitle}
                  </Link>
                </TableCell>
                <TableCell label="Trạng thái">
                  <StatusChip variant={getLifecycleChipVariant(record.lifecycleStatus)}>
                    {LIFECYCLE_STATUS_LABELS[record.lifecycleStatus]}
                  </StatusChip>
                </TableCell>
                <TableCell label="Bước hiện tại">
                  {getCurrentStepLabel(record)}
                </TableCell>
                <TableCell label="Bắt đầu">
                  {formatDateTime(record.startedAt)}
                </TableCell>
                <TableCell label="Cập nhật">
                  {formatDateTime(record.updatedAt)}
                </TableCell>
                <TableCell label="Khả năng">
                  {getWorkflowCapability(record.workflowKey)}
                </TableCell>
                <TableCell label="Việc tiếp theo">
                  {nextAction ?? "—"}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
