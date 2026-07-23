"use client";

import type { ExecutionRecord } from "@juli/contracts";
import {
  Button,
  Card,
  CardBody,
  CardHeader,
  CardTitle,
  PageHeader,
  StatusChip,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "@juli/ui";
import { formatDateTime } from "@juli/utils";
import { useParams } from "next/navigation";

import { DestinationPlaceholder } from "../../../../components/destination-placeholder";
import {
  LIFECYCLE_STATUS_LABELS,
  STEP_KIND_LABELS,
  STEP_STATUS_LABELS,
  getLifecycleChipVariant,
  getWorkflowCapability,
  getWorkflowTitle,
} from "../../../../components/in-progress-panel";
import { useDemoState } from "../../../../components/demo-state";
import { getWorkflowReviewStages } from "../../../../lib/reviews";

function getApprovedInputLabel(
  workflowKey: string,
  inputKey: string,
): string {
  const inputField = getWorkflowReviewStages(workflowKey)
    .flatMap((stage) => stage.inputFields ?? [])
    .find((field) => field.key === inputKey);

  return inputField?.label ?? inputKey;
}

function ExecutionIdentity({ record }: { record: ExecutionRecord }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{getWorkflowTitle(record.workflowKey)}</CardTitle>
      </CardHeader>
      <CardBody>
        <Table aria-label="Thông tin luồng thực hiện">
          <TableBody keyboardNav={false}>
            <TableRow focusable={false}>
              <TableCell label="Mã thực thi">{record.executionId}</TableCell>
            </TableRow>
            <TableRow focusable={false}>
              <TableCell label="workflow_key">{record.workflowKey}</TableCell>
            </TableRow>
            <TableRow focusable={false}>
              <TableCell label="Công cụ">{record.toolName}</TableCell>
            </TableRow>
            <TableRow focusable={false}>
              <TableCell label="Trạng thái vòng đời">
                <StatusChip variant={getLifecycleChipVariant(record.lifecycleStatus)}>
                  {LIFECYCLE_STATUS_LABELS[record.lifecycleStatus]}
                </StatusChip>
              </TableCell>
            </TableRow>
            <TableRow focusable={false}>
              <TableCell label="Khả năng">
                {getWorkflowCapability(record.workflowKey)}
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </CardBody>
    </Card>
  );
}

function ApprovedInputsTable({ record }: { record: ExecutionRecord }) {
  const entries = Object.entries(record.approvedInputs);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Thông tin đã phê duyệt</CardTitle>
      </CardHeader>
      <CardBody>
        <Table aria-label="Thông tin đã phê duyệt">
          <TableHead>
            <TableRow focusable={false}>
              <TableHeaderCell>Trường</TableHeaderCell>
              <TableHeaderCell>Giá trị</TableHeaderCell>
            </TableRow>
          </TableHead>
          <TableBody keyboardNav={false}>
            {entries.map(([key, value]) => (
              <TableRow key={key} focusable={false}>
                <TableCell label="Trường">
                  {getApprovedInputLabel(record.workflowKey, key)}
                </TableCell>
                <TableCell label="Giá trị">{value}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardBody>
    </Card>
  );
}

function ExecutionTimeline({
  record,
  onRefreshWait,
}: {
  record: ExecutionRecord;
  onRefreshWait: () => void;
}) {
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
                <StatusChip
                  variant={
                    step.status === "failed"
                      ? "destructive"
                      : step.status === "succeeded"
                        ? "success"
                        : step.status === "running"
                          ? "info"
                          : "neutral"
                  }
                >
                  <span aria-hidden="true">
                    {step.status === "running"
                      ? "● "
                      : step.status === "succeeded"
                        ? "✓ "
                        : step.status === "failed"
                          ? "✕ "
                          : "○ "}
                  </span>
                  {STEP_STATUS_LABELS[step.status]}
                </StatusChip>
                <p className="demo-intro">{step.description}</p>
                {step.recoveryText ? (
                  <p className="demo-notice">{step.recoveryText}</p>
                ) : null}
                {step.errorText ? (
                  <p className="demo-notice" role="alert">
                    {step.errorText}
                  </p>
                ) : null}
                {step.kind === "wait" ? (
                  <div>
                    <p className="demo-intro">
                      Sự kiện mong đợi: {step.description}
                    </p>
                    <p className="demo-intro">
                      Kiểm tra lần cuối: {formatDateTime(record.updatedAt)}
                    </p>
                    <Button
                      size="small"
                      type="button"
                      variant="secondary"
                      onClick={onRefreshWait}
                    >
                      Kiểm tra lại
                    </Button>
                  </div>
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

  const handleRefreshWait = () => {
    updateMutableState((current) => {
      const currentRecord = current.executionRecords[executionId];
      if (!currentRecord) {
        return current;
      }

      return {
        ...current,
        executionRecords: {
          ...current.executionRecords,
          [executionId]: {
            ...currentRecord,
            updatedAt: new Date().toISOString(),
          },
        },
      };
    });
  };

  return (
    <section className="demo-decisions">
      <PageHeader
        subtitle="Theo dõi từng bước hành động, chờ và kết quả sau khi bạn phê duyệt."
        title={getWorkflowTitle(record.workflowKey)}
      />
      <div className="demo-decisions__list">
        <ExecutionIdentity record={record} />
        <ApprovedInputsTable record={record} />
        <ExecutionTimeline onRefreshWait={handleRefreshWait} record={record} />
      </div>
    </section>
  );
}

export default function InProgressDetailPage() {
  const { executionId } = useParams<{ executionId: string }>();

  return <InProgressDetailView executionId={executionId} />;
}
