import {
  deriveLifecycleFromTimeline,
  type ExecutionRecord,
  type ExecutionTimelineStep,
} from "@juli/contracts";

import {
  CREATE_ACTIVITY_TOOL_NAME,
  CREATE_ACTIVITY_WORKFLOW_KEY,
  buildCreateActivityReviewInputDefaults,
} from "./review";

const executionCounters = new Map<string, number>();

export { CREATE_ACTIVITY_TOOL_NAME, CREATE_ACTIVITY_WORKFLOW_KEY };

export function resetCreateActivityExecutionCountersForTests(): void {
  executionCounters.clear();
}

function nextExecutionId(workflowKey: string): string {
  const next = (executionCounters.get(workflowKey) ?? 0) + 1;
  executionCounters.set(workflowKey, next);
  return `exec-${workflowKey}-${next}`;
}

export function createCreateActivityTimeline(): ExecutionTimelineStep[] {
  return [
    {
      id: "create-eligibility-outcome",
      stepNumber: 1,
      kind: "outcome",
      title: "Kết quả điều kiện tạo khuyến mãi",
      description:
        "Hiển thị ràng buộc SKU, giá và cửa sổ khuyến mãi trước khi gửi.",
      status: "pending",
      recoveryText:
        "Quay lại bước nhập liệu để chỉnh SKU, loại khuyến mãi hoặc cửa sổ thời gian.",
    },
    {
      id: "create-activity",
      stepNumber: 2,
      kind: "action",
      title: "Tạo chương trình khuyến mãi",
      description: "Gửi activity đã phê duyệt qua Create Activity.",
      status: "pending",
      recoveryText:
        "Giữ nguyên dữ liệu đã nhập và sửa lỗi xác thực trước khi gửi lại.",
    },
    {
      id: "update-activity-product",
      stepNumber: 3,
      kind: "action",
      title: "Gắn sản phẩm vào khuyến mãi",
      description:
        "Đính kèm SKU và giá đã duyệt vào activity_id vừa tạo trước khi báo live.",
      status: "pending",
      recoveryText:
        "Một phần SKU không gắn được — giữ activity hiện tại và thử lại SKU bị lỗi.",
    },
    {
      id: "activity-live-wait",
      stepNumber: 4,
      kind: "wait",
      title: "Chờ khuyến mãi live",
      description:
        "Lắng nghe webhook thay đổi trạng thái khuyến mãi (#39); không hiển thị ETA giả.",
      status: "pending",
    },
    {
      id: "active-outcome",
      stepNumber: 5,
      kind: "outcome",
      title: "Đang hoạt động / một phần / bị từ chối",
      description:
        "Hiển thị trạng thái activity và kết quả từng SKU; tạo thành công nhưng gắn SKU thất bại được coi là một phần, không phải thất bại toàn bộ.",
      status: "pending",
      recoveryText:
        "Mở lại bước gắn sản phẩm để thử lại SKU bị lỗi; không tự gửi lại activity khi bị từ chối.",
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

export function buildCreateActivityExecution(
  approvedInputs?: Record<string, string>,
): {
  executionId: string;
  record: ExecutionRecord;
} {
  const executionId = nextExecutionId(CREATE_ACTIVITY_WORKFLOW_KEY);
  const now = "2026-07-21T09:15:00.000Z";
  const timeline = seedInitialTimeline(createCreateActivityTimeline());
  const lifecycleStatus = deriveLifecycleFromTimeline(timeline);

  const record: ExecutionRecord = {
    executionId,
    workflowKey: CREATE_ACTIVITY_WORKFLOW_KEY,
    toolName: CREATE_ACTIVITY_TOOL_NAME,
    lifecycleStatus,
    startedAt: now,
    updatedAt: now,
    timeline,
    approvedInputs: {
      ...buildCreateActivityReviewInputDefaults(),
      ...(approvedInputs ?? {}),
    },
  };

  return { executionId, record };
}
