import {
  deriveLifecycleFromTimeline,
  type ExecutionRecord,
  type ExecutionTimelineStep,
} from "@juli/contracts";

import {
  UPDATE_ACTIVITY_TOOL_NAME,
  UPDATE_ACTIVITY_WORKFLOW_KEY,
  buildUpdateActivityReviewInputDefaults,
} from "./review";

const executionCounters = new Map<string, number>();

export { UPDATE_ACTIVITY_TOOL_NAME, UPDATE_ACTIVITY_WORKFLOW_KEY };

export function resetUpdateActivityExecutionCountersForTests(): void {
  executionCounters.clear();
}

function nextExecutionId(workflowKey: string): string {
  const next = (executionCounters.get(workflowKey) ?? 0) + 1;
  executionCounters.set(workflowKey, next);
  return `exec-${workflowKey}-${next}`;
}

export function createUpdateActivityTimeline(): ExecutionTimelineStep[] {
  return [
    {
      id: "known-activity-outcome",
      stepNumber: 1,
      kind: "outcome",
      title: "Chương trình đã biết được tải",
      description:
        "Xác định activity theo activity_id đã theo dõi — không dùng tìm kiếm.",
      status: "pending",
      recoveryText:
        "Thiếu activity_id — không thể cập nhật; quay lại chọn đề xuất có ID đã biết.",
    },
    {
      id: "update-activity",
      stepNumber: 2,
      kind: "action",
      title: "Cập nhật chương trình khuyến mãi",
      description:
        "Gửi thay đổi cấu hình/sản phẩm đã phê duyệt qua Update Activity Product.",
      status: "pending",
      recoveryText:
        "TikTok từ chối cập nhật — quay lại bước nhập liệu và chỉnh trường/SKU bị lỗi.",
    },
    {
      id: "activity-changed-wait",
      stepNumber: 3,
      kind: "wait",
      title: "Chờ thay đổi khuyến mãi",
      description:
        "Lắng nghe webhook thay đổi trạng thái (#39) và/hoặc Activity change (#63); không hiển thị ETA giả.",
      status: "pending",
    },
    {
      id: "updated-outcome",
      stepNumber: 4,
      kind: "outcome",
      title: "Đã cập nhật / một phần / bị từ chối",
      description:
        "Hiển thị trạng thái cuối cùng và liên kết bước đo lường tiếp theo; không tự gửi lại khi bị từ chối.",
      status: "pending",
      recoveryText:
        "Mở lại bước nhập liệu để chỉnh theo lý do TikTok; không tự gửi lại.",
    },
  ];
}

function seedInitialTimeline(
  timeline: ExecutionTimelineStep[],
): ExecutionTimelineStep[] {
  return timeline.map((step, index) =>
    index === 0
      ? { ...step, status: "running" }
      : { ...step, status: "pending" },
  );
}

export function buildUpdateActivityExecution(
  approvedInputs?: Record<string, string>,
): {
  executionId: string;
  record: ExecutionRecord;
} {
  const executionId = nextExecutionId(UPDATE_ACTIVITY_WORKFLOW_KEY);
  const now = "2026-07-21T09:20:00.000Z";
  const timeline = seedInitialTimeline(createUpdateActivityTimeline());
  const lifecycleStatus = deriveLifecycleFromTimeline(timeline);

  const record: ExecutionRecord = {
    executionId,
    workflowKey: UPDATE_ACTIVITY_WORKFLOW_KEY,
    toolName: UPDATE_ACTIVITY_TOOL_NAME,
    lifecycleStatus,
    startedAt: now,
    updatedAt: now,
    timeline,
    approvedInputs: {
      ...buildUpdateActivityReviewInputDefaults(),
      ...(approvedInputs ?? {}),
    },
  };

  return { executionId, record };
}
