import {
  deriveLifecycleFromTimeline,
  type ExecutionRecord,
  type ExecutionTimelineStep,
} from "@juli/contracts";

import {
  buildReviewInputDefaultsForWorkflow,
  CREATE_HERO_PRODUCT_WORKFLOW_KEY,
} from "./reviews";
import {
  CREATE_ACTIVITY_TOOL_NAME,
  CREATE_ACTIVITY_WORKFLOW_KEY,
  createCreateActivityTimeline,
} from "./workflows/create-activity";
import {
  CLEAR_EXCESS_TOOL_NAME,
  CLEAR_EXCESS_WORKFLOW_KEY,
  createClearExcessTimeline,
} from "./workflows/clear-excess";
import {
  DELETE_ACTIVITY_TOOL_NAME,
  DELETE_ACTIVITY_WORKFLOW_KEY,
  createDeleteActivityTimeline,
} from "./workflows/delete-activity";
import {
  createOptimizeProductTimeline,
  OPTIMIZE_PRODUCT_TOOL_NAME,
  OPTIMIZE_PRODUCT_WORKFLOW_KEY,
} from "./workflows/optimize-product";
import {
  createProcessOrderTimeline,
  PROCESS_ORDER_TOOL_NAME,
  PROCESS_ORDER_WORKFLOW_KEY,
} from "./workflows/process-order";
import {
  createReplenishInventoryTimeline,
  REPLENISH_INVENTORY_TOOL_NAME,
  REPLENISH_INVENTORY_WORKFLOW_KEY,
} from "./workflows/replenish-inventory";
import {
  createUpdateActivityTimeline,
  UPDATE_ACTIVITY_TOOL_NAME,
  UPDATE_ACTIVITY_WORKFLOW_KEY,
} from "./workflows/update-activity";

export { CREATE_HERO_PRODUCT_WORKFLOW_KEY };
export const CREATE_HERO_PRODUCT_TOOL_NAME = "listing.create_hero_product";

const executionCounters = new Map<string, number>();

const SUPPORTED_WORKFLOWS: Record<
  string,
  {
    toolName: string;
    createTimeline: () => ExecutionTimelineStep[];
  }
> = {
  [CREATE_HERO_PRODUCT_WORKFLOW_KEY]: {
    toolName: CREATE_HERO_PRODUCT_TOOL_NAME,
    createTimeline: createHeroProductTimeline,
  },
  [OPTIMIZE_PRODUCT_WORKFLOW_KEY]: {
    toolName: OPTIMIZE_PRODUCT_TOOL_NAME,
    createTimeline: createOptimizeProductTimeline,
  },
  [REPLENISH_INVENTORY_WORKFLOW_KEY]: {
    toolName: REPLENISH_INVENTORY_TOOL_NAME,
    createTimeline: createReplenishInventoryTimeline,
  },
  [CLEAR_EXCESS_WORKFLOW_KEY]: {
    toolName: CLEAR_EXCESS_TOOL_NAME,
    createTimeline: createClearExcessTimeline,
  },
  [PROCESS_ORDER_WORKFLOW_KEY]: {
    toolName: PROCESS_ORDER_TOOL_NAME,
    createTimeline: createProcessOrderTimeline,
  },
  [CREATE_ACTIVITY_WORKFLOW_KEY]: {
    toolName: CREATE_ACTIVITY_TOOL_NAME,
    createTimeline: createCreateActivityTimeline,
  },
  [UPDATE_ACTIVITY_WORKFLOW_KEY]: {
    toolName: UPDATE_ACTIVITY_TOOL_NAME,
    createTimeline: createUpdateActivityTimeline,
  },
  [DELETE_ACTIVITY_WORKFLOW_KEY]: {
    toolName: DELETE_ACTIVITY_TOOL_NAME,
    createTimeline: createDeleteActivityTimeline,
  },
};

export function resetExecutionCountersForTests(): void {
  executionCounters.clear();
}

function nextExecutionId(workflowKey: string): string {
  const next = (executionCounters.get(workflowKey) ?? 0) + 1;
  executionCounters.set(workflowKey, next);
  return `exec-${workflowKey}-${next}`;
}

export function createHeroProductTimeline(): ExecutionTimelineStep[] {
  return [
    {
      id: "get-category",
      stepNumber: 1,
      kind: "action",
      title: "Lấy danh mục",
      description: "Xác định category_id trước khi đọc thuộc tính.",
      status: "pending",
    },
    {
      id: "check-prerequisites",
      stepNumber: 2,
      kind: "action",
      title: "Kiểm tra điều kiện niêm yết",
      description: "Đọc điều kiện shop/danh mục trước khi gọi thuộc tính hoặc nhãn hiệu.",
      status: "pending",
    },
    {
      id: "eligibility-outcome",
      stepNumber: 3,
      kind: "outcome",
      title: "Kết quả điều kiện",
      description: "Tiếp tục nếu đủ điều kiện; nếu thiếu điều kiện thì chuyển sang cần thêm thông tin.",
      status: "pending",
      recoveryText:
        "Quay lại bước lấy danh mục hoặc bổ sung điều kiện còn thiếu trước khi tiếp tục.",
    },
    {
      id: "get-attributes",
      stepNumber: 4,
      kind: "action",
      title: "Lấy thuộc tính",
      description: "Tải trường bắt buộc/tùy chọn theo danh mục đã chọn.",
      status: "pending",
      recoveryText: "Bổ sung thuộc tính bắt buộc còn thiếu rồi thử lại.",
    },
    {
      id: "get-brands",
      stepNumber: 5,
      kind: "action",
      title: "Lấy nhãn hiệu",
      description: "Xác định brand_id hoặc chọn đường không nhãn hiệu nếu danh mục cho phép.",
      status: "pending",
      recoveryText: "Chọn nhãn hiệu phù hợp hoặc xác nhận đường không nhãn hiệu.",
    },
    {
      id: "upload-images",
      stepNumber: 6,
      kind: "action",
      title: "Tải ảnh sản phẩm",
      description: "Tải từng ảnh đã duyệt và giữ URI trả về cho main_images.",
      status: "pending",
      recoveryText: "Thử lại chỉ ảnh bị lỗi; không ghi đè ảnh đã tải thành công.",
      errorText: "Tải ảnh thất bại — thử lại ảnh bị lỗi.",
    },
    {
      id: "upload-file",
      stepNumber: 7,
      kind: "action",
      title: "Tải tệp hỗ trợ (nếu cần)",
      description: "Chỉ chạy khi danh mục yêu cầu chứng từ hoặc tài liệu bổ sung.",
      status: "pending",
      recoveryText: "Tải lại tệp bị lỗi khi danh mục yêu cầu tài liệu hỗ trợ.",
    },
    {
      id: "get-seo-words",
      stepNumber: 8,
      kind: "action",
      title: "Lấy từ khoá SEO",
      description: "Đọc từ khoá được hỗ trợ cho tiêu đề/mô tả.",
      status: "pending",
    },
    {
      id: "get-title-description",
      stepNumber: 9,
      kind: "action",
      title: "Gợi ý tiêu đề và mô tả",
      description: "Điền sẵn nội dung đề xuất; shop vẫn có thể chỉnh trước khi gửi.",
      status: "pending",
    },
    {
      id: "review-ready-outcome",
      stepNumber: 10,
      kind: "outcome",
      title: "Sẵn sàng xem lại",
      description:
        "Hiển thị tin niêm yết đầy đủ, kho FBS, giá và kết quả kiểm tra trước khi tạo sản phẩm.",
      status: "pending",
    },
    {
      id: "create-product",
      stepNumber: 11,
      kind: "action",
      title: "Tạo sản phẩm",
      description: "Gửi payload một/nhiều SKU đã được phê duyệt.",
      status: "pending",
      recoveryText: "Giữ nguyên dữ liệu đã nhập và sửa lỗi xác thực trước khi gửi lại.",
    },
    {
      id: "product-review-wait",
      stepNumber: 12,
      kind: "wait",
      title: "Chờ duyệt sản phẩm",
      description:
        "Lắng nghe webhook trạng thái sản phẩm (#5) và kiểm duyệt (#37); không hiển thị ETA giả.",
      status: "pending",
    },
    {
      id: "search-product",
      stepNumber: 13,
      kind: "action",
      title: "Tra cứu sản phẩm",
      description: "Xác nhận trạng thái niêm yết sau khi TikTok duyệt.",
      status: "pending",
    },
    {
      id: "listed-outcome",
      stepNumber: 14,
      kind: "outcome",
      title: "Đã niêm yết / cần chỉnh / bị từ chối",
      description:
        "Hiển thị trạng thái TikTok và hướng khôi phục; không tự gửi lại khi bị từ chối.",
      status: "pending",
      recoveryText:
        "Mở lại bước xem lại để chỉnh thông tin theo lý do TikTok; không tự gửi lại.",
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

export function startExecution(
  workflowKey: string,
  approvedInputs?: Record<string, string>,
): {
  executionId: string;
  record: ExecutionRecord;
} {
  const config = SUPPORTED_WORKFLOWS[workflowKey];

  if (!config) {
    throw new Error(`Unsupported workflow key: ${workflowKey}`);
  }

  const executionId = nextExecutionId(workflowKey);
  const now = "2026-07-16T04:12:00.000Z";
  const timeline = seedInitialTimeline(config.createTimeline());
  const lifecycleStatus = deriveLifecycleFromTimeline(timeline);

  const record: ExecutionRecord = {
    executionId,
    workflowKey,
    toolName: config.toolName,
    lifecycleStatus,
    startedAt: now,
    updatedAt: now,
    timeline,
    approvedInputs: {
      ...buildReviewInputDefaultsForWorkflow(workflowKey),
      ...(approvedInputs ?? {}),
    },
  };

  return { executionId, record };
}

export function getWorkflowTimeline(
  workflowKey: string,
): ExecutionTimelineStep[] {
  const config = SUPPORTED_WORKFLOWS[workflowKey];

  if (!config) {
    return [];
  }

  return config.createTimeline();
}
