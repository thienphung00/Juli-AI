import {
  deriveLifecycleFromTimeline,
  type ExecutionRecord,
  type ExecutionTimelineStep,
} from "@juli/contracts";

import {
  DELETE_ACTIVITY_TOOL_NAME,
  DELETE_ACTIVITY_WORKFLOW_KEY,
  buildDeleteActivityReviewInputDefaults,
} from "./review";

const executionCounters = new Map<string, number>();

export { DELETE_ACTIVITY_TOOL_NAME, DELETE_ACTIVITY_WORKFLOW_KEY };

export function resetDeleteActivityExecutionCountersForTests(): void {
  executionCounters.clear();
}

function nextExecutionId(workflowKey: string): string {
  const next = (executionCounters.get(workflowKey) ?? 0) + 1;
  executionCounters.set(workflowKey, next);
  return `exec-${workflowKey}-${next}`;
}

export function createDeleteActivityTimeline(): ExecutionTimelineStep[] {
  return [
    {
      id: "get-activity",
      stepNumber: 1,
      kind: "action",
      title: "Lấy chương trình khuyến mãi",
      description:
        "Làm mới activity theo activity_id đã biết trước khi kiểm tra điều kiện kết thúc.",
      status: "pending",
    },
    {
      id: "end-eligibility-outcome",
      stepNumber: 2,
      kind: "outcome",
      title: "Kết quả điều kiện kết thúc",
      description:
        "Nếu activity đã inactive thì kết thúc như no-op; nếu còn active thì tiếp tục deactivate.",
      status: "pending",
      recoveryText:
        "Activity đã inactive — không cần thao tác thêm; quay lại danh sách đề xuất.",
    },
    {
      id: "deactivate-activity",
      stepNumber: 3,
      kind: "action",
      title: "Vô hiệu hoá chương trình khuyến mãi",
      description:
        "Gửi yêu cầu deactivate sau khi shop phê duyệt rõ ràng.",
      status: "pending",
      recoveryText:
        "Deactivate thất bại — activity vẫn hiển thị active; thử lại sau khi xác nhận.",
    },
    {
      id: "deactivation-wait",
      stepNumber: 4,
      kind: "wait",
      title: "Chờ vô hiệu hoá",
      description:
        "Lắng nghe webhook thay đổi trạng thái khuyến mãi (#39); không hiển thị ETA giả.",
      status: "pending",
    },
    {
      id: "inactive-outcome",
      stepNumber: 5,
      kind: "outcome",
      title: "Đã inactive / vẫn active / thất bại",
      description:
        "Hiển thị trạng thái cuối cùng; nếu vẫn active thì cho phép thử lại deactivate.",
      status: "pending",
      recoveryText:
        "Activity vẫn active — thử lại deactivate hoặc làm mới qua Get Activity.",
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

export function buildDeleteActivityExecution(
  approvedInputs?: Record<string, string>,
): {
  executionId: string;
  record: ExecutionRecord;
} {
  const executionId = nextExecutionId(DELETE_ACTIVITY_WORKFLOW_KEY);
  const now = "2026-07-21T09:25:00.000Z";
  const timeline = seedInitialTimeline(createDeleteActivityTimeline());
  const lifecycleStatus = deriveLifecycleFromTimeline(timeline);

  const record: ExecutionRecord = {
    executionId,
    workflowKey: DELETE_ACTIVITY_WORKFLOW_KEY,
    toolName: DELETE_ACTIVITY_TOOL_NAME,
    lifecycleStatus,
    startedAt: now,
    updatedAt: now,
    timeline,
    approvedInputs: {
      ...buildDeleteActivityReviewInputDefaults(),
      ...(approvedInputs ?? {}),
    },
  };

  return { executionId, record };
}
