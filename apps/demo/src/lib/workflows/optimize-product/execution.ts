import {
  deriveLifecycleFromTimeline,
  type ExecutionRecord,
  type ExecutionTimelineStep,
} from "@juli/contracts";

import {
  OPTIMIZE_PRODUCT_TOOL_NAME,
  OPTIMIZE_PRODUCT_WORKFLOW_KEY,
  buildOptimizeProductReviewInputDefaults,
} from "./review";

const executionCounters = new Map<string, number>();

export { OPTIMIZE_PRODUCT_TOOL_NAME, OPTIMIZE_PRODUCT_WORKFLOW_KEY };

export function resetOptimizeProductExecutionCountersForTests(): void {
  executionCounters.clear();
}

function nextExecutionId(workflowKey: string): string {
  const next = (executionCounters.get(workflowKey) ?? 0) + 1;
  executionCounters.set(workflowKey, next);
  return `exec-${workflowKey}-${next}`;
}

export function createOptimizeProductTimeline(): ExecutionTimelineStep[] {
  return [
    {
      id: "get-product",
      stepNumber: 1,
      kind: "action",
      title: "Lấy sản phẩm",
      description:
        "Tải tiêu đề, mô tả, ảnh, giá và thuộc tính hiện tại từ Get Product.",
      status: "pending",
    },
    {
      id: "editable-listing-outcome",
      stepNumber: 2,
      kind: "outcome",
      title: "Tin đăng có thể sửa",
      description:
        "Tiếp tục nếu trạng thái/danh mục cho phép sửa; nếu không thì chặn và giải thích.",
      status: "pending",
      recoveryText:
        "Quay lại chọn sản phẩm khác hoặc bổ sung điều kiện còn thiếu trước khi tiếp tục.",
    },
    {
      id: "get-seo-words",
      stepNumber: 3,
      kind: "action",
      title: "Lấy từ khoá SEO",
      description: "Đọc từ khoá được hỗ trợ cho tiêu đề/mô tả.",
      status: "pending",
    },
    {
      id: "get-title-description",
      stepNumber: 4,
      kind: "action",
      title: "Gợi ý tiêu đề và mô tả",
      description:
        "Điền sẵn nội dung đề xuất; shop vẫn có thể chỉnh trước khi gửi.",
      status: "pending",
    },
    {
      id: "upload-product-image",
      stepNumber: 5,
      kind: "action",
      title: "Tải ảnh sản phẩm",
      description:
        "Chỉ chạy khi shop phê duyệt thay thế/bổ sung ảnh — bỏ qua nếu ảnh không đổi.",
      status: "pending",
      recoveryText: "Thử lại chỉ ảnh bị lỗi; không ghi đè ảnh đã tải thành công.",
      errorText: "Tải ảnh thất bại — thử lại ảnh bị lỗi.",
    },
    {
      id: "upload-product-file",
      stepNumber: 6,
      kind: "action",
      title: "Tải tệp hỗ trợ (nếu cần)",
      description:
        "Chỉ chạy khi danh mục yêu cầu thay tài liệu — bỏ qua nếu tệp không đổi.",
      status: "pending",
      recoveryText: "Tải lại tệp bị lỗi khi danh mục yêu cầu tài liệu hỗ trợ.",
    },
    {
      id: "before-after-preview",
      stepNumber: 7,
      kind: "outcome",
      title: "Xem trước trước/sau",
      description:
        "Hiển thị trường thay đổi, chênh lệch giá, sàn lợi nhuận và rủi ro trước khi gửi.",
      status: "pending",
    },
    {
      id: "edit-product",
      stepNumber: 8,
      kind: "action",
      title: "Sửa sản phẩm (một phần)",
      description:
        "Gửi các trường đã phê duyệt qua Partial Edit Product; không dùng thay thế toàn bộ.",
      status: "pending",
      recoveryText:
        "Giữ nguyên dữ liệu đã nhập và sửa lỗi xác thực trước khi gửi lại.",
    },
    {
      id: "update-price",
      stepNumber: 9,
      kind: "action",
      title: "Cập nhật giá",
      description:
        "Chỉ gửi giá đã phê duyệt khi giá thay đổi — bỏ qua nếu giá không đổi.",
      status: "pending",
      recoveryText:
        "Điều chỉnh giá trên mức sàn lợi nhuận rồi thử lại; lỗi nội dung và giá được báo riêng.",
    },
    {
      id: "product-review-wait",
      stepNumber: 10,
      kind: "wait",
      title: "Chờ duyệt lại sản phẩm",
      description:
        "Lắng nghe webhook trạng thái sản phẩm (#5); không hiển thị ETA giả.",
      status: "pending",
    },
    {
      id: "live-outcome",
      stepNumber: 11,
      kind: "outcome",
      title: "Đã live / cần chỉnh / bị từ chối",
      description:
        "Hiển thị trạng thái cuối cùng và liên kết bước đo lường tiếp theo; không tự gửi lại khi bị từ chối.",
      status: "pending",
      recoveryText:
        "Mở lại bước xem trước để chỉnh theo lý do TikTok; không tự gửi lại.",
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

export function buildOptimizeProductExecution(
  approvedInputs?: Record<string, string>,
): {
  executionId: string;
  record: ExecutionRecord;
} {
  const executionId = nextExecutionId(OPTIMIZE_PRODUCT_WORKFLOW_KEY);
  const now = "2026-07-21T08:02:57.000Z";
  const timeline = seedInitialTimeline(createOptimizeProductTimeline());
  const lifecycleStatus = deriveLifecycleFromTimeline(timeline);

  const record: ExecutionRecord = {
    executionId,
    workflowKey: OPTIMIZE_PRODUCT_WORKFLOW_KEY,
    toolName: OPTIMIZE_PRODUCT_TOOL_NAME,
    lifecycleStatus,
    startedAt: now,
    updatedAt: now,
    timeline,
    approvedInputs: {
      ...buildOptimizeProductReviewInputDefaults(),
      ...(approvedInputs ?? {}),
    },
  };

  return { executionId, record };
}
