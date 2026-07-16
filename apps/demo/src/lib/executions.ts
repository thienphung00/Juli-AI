import {
  deriveLifecycleFromTimeline,
  type ExecutionRecord,
  type ExecutionTimelineStep,
} from "@juli/contracts";

export const CREATE_HERO_PRODUCT_WORKFLOW_KEY = "create_hero_product_1";
export const CREATE_HERO_PRODUCT_TOOL_NAME = "listing.create_hero_product";

const executionCounters = new Map<string, number>();

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

const defaultApprovedInputs: Record<string, string> = {
  category_id: "700648",
  brand_id: "BR-1024",
  warehouse_id: "WH-FBS-HCM-01",
  price: "289000",
  seo_title: "Serum dưỡng ẩm chống lão hoá cho da nhạy cảm",
  seo_description:
    "Serum dưỡng ẩm giúp cân bằng độ ẩm, hỗ trợ hàng rào da nhạy cảm.",
  main_images: "uploaded:3",
};

export function startExecution(workflowKey: string): {
  executionId: string;
  record: ExecutionRecord;
} {
  if (workflowKey !== CREATE_HERO_PRODUCT_WORKFLOW_KEY) {
    throw new Error(`Unsupported workflow key: ${workflowKey}`);
  }

  const executionId = nextExecutionId(workflowKey);
  const now = "2026-07-16T04:12:00.000Z";
  const timeline = seedInitialTimeline(createHeroProductTimeline());
  const lifecycleStatus = deriveLifecycleFromTimeline(timeline);

  const record: ExecutionRecord = {
    executionId,
    workflowKey,
    toolName: CREATE_HERO_PRODUCT_TOOL_NAME,
    lifecycleStatus,
    startedAt: now,
    updatedAt: now,
    timeline,
    approvedInputs: { ...defaultApprovedInputs },
  };

  return { executionId, record };
}

export function getWorkflowTimeline(
  workflowKey: string,
): ExecutionTimelineStep[] {
  if (workflowKey === CREATE_HERO_PRODUCT_WORKFLOW_KEY) {
    return createHeroProductTimeline();
  }

  return [];
}
