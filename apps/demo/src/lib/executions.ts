import {
  deriveLifecycleFromTimeline,
  type ExecutionRecord,
  type ExecutionTimelineStep,
} from "@juli/contracts";

import {
  CREATE_HERO_PRODUCT_WORKFLOW_KEY,
  PREVENT_CANCELLATION_WORKFLOW_KEY,
  PREVENT_REFUND_WORKFLOW_KEY,
  PREVENT_RETURN_WORKFLOW_KEY,
  buildReviewInputDefaults,
  isReviewExecutableWorkflow,
} from "./reviews";

export {
  CREATE_HERO_PRODUCT_WORKFLOW_KEY,
  PREVENT_CANCELLATION_WORKFLOW_KEY,
  PREVENT_REFUND_WORKFLOW_KEY,
  PREVENT_RETURN_FBT_INTAKE_KEY,
  PREVENT_RETURN_WORKFLOW_KEY,
} from "./reviews";

export const CREATE_HERO_PRODUCT_TOOL_NAME = "listing.create_hero_product";
export const PREVENT_CANCELLATION_TOOL_NAME = "returns.prevent_cancellation";
export const PREVENT_RETURN_TOOL_NAME = "returns.prevent_return";
export const PREVENT_REFUND_TOOL_NAME = "returns.prevent_refund";

const TOOL_NAME_BY_WORKFLOW: Record<string, string> = {
  [CREATE_HERO_PRODUCT_WORKFLOW_KEY]: CREATE_HERO_PRODUCT_TOOL_NAME,
  [PREVENT_CANCELLATION_WORKFLOW_KEY]: PREVENT_CANCELLATION_TOOL_NAME,
  [PREVENT_RETURN_WORKFLOW_KEY]: PREVENT_RETURN_TOOL_NAME,
  [PREVENT_REFUND_WORKFLOW_KEY]: PREVENT_REFUND_TOOL_NAME,
};

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

export function createPreventCancellationTimeline(): ExecutionTimelineStep[] {
  return [
    {
      id: "cancel-intake",
      stepNumber: 1,
      kind: "wait",
      title: "Tiếp nhận cập nhật trạng thái đảo ngược",
      description: "Webhook #2 tạo/cập nhật bản ghi yêu cầu huỷ đơn.",
      status: "pending",
    },
    {
      id: "search-cancellations",
      stepNumber: 2,
      kind: "action",
      title: "Tìm yêu cầu huỷ đơn",
      description: "Đọc trạng thái yêu cầu chính thức từ Search Cancellations.",
      status: "pending",
      recoveryText: "Làm mới yêu cầu huỷ đơn khi dữ liệu bị cũ.",
    },
    {
      id: "get-decision-eligibility",
      stepNumber: 3,
      kind: "action",
      title: "Kiểm tra điều kiện quyết định",
      description: "Xác nhận cửa sổ quyết định của shop vẫn còn mở.",
      status: "pending",
    },
    {
      id: "eligibility-outcome",
      stepNumber: 4,
      kind: "outcome",
      title: "Đủ điều kiện / hết hạn / đã quyết định",
      description: "Chỉ yêu cầu còn đủ điều kiện mới tiếp tục; hết hạn hoặc đã quyết định là chỉ đọc.",
      status: "pending",
      recoveryText: "Vô hiệu hoá thao tác khi hết hạn hoặc đã có quyết định.",
    },
    {
      id: "get-reject-reasons",
      stepNumber: 5,
      kind: "action",
      title: "Lấy lý do từ chối",
      description: "Tải danh sách lý do SEA chính thức trước khi từ chối.",
      status: "pending",
    },
    {
      id: "seller-decision",
      stepNumber: 6,
      kind: "outcome",
      title: "Cần quyết định của shop",
      description: "Shop chọn Phê duyệt hoặc Từ chối; Từ chối bắt buộc có lý do.",
      status: "pending",
      recoveryText: "Thiếu lý do từ chối — quay lại bước lấy lý do và nhập lại.",
    },
    {
      id: "approve-cancellation",
      stepNumber: 7,
      kind: "action",
      title: "Phê duyệt huỷ đơn",
      description: "Gửi lựa chọn phê duyệt (nhánh loại trừ với từ chối).",
      status: "pending",
      recoveryText: "Thử lại ghi nhận quyết định theo cách idempotent khi lỗi tạm thời.",
    },
    {
      id: "reject-cancellation",
      stepNumber: 8,
      kind: "action",
      title: "Từ chối huỷ đơn",
      description: "Gửi từ chối kèm lý do đã chọn (nhánh loại trừ với phê duyệt).",
      status: "pending",
      recoveryText: "Thử lại ghi nhận quyết định theo cách idempotent khi lỗi tạm thời.",
    },
    {
      id: "cancellation-status-wait",
      stepNumber: 9,
      kind: "wait",
      title: "Chờ trạng thái huỷ đơn",
      description: "Webhook #11 xác nhận trạng thái cuối; timeout thì làm mới yêu cầu, không tuyên bố thành công.",
      status: "pending",
      recoveryText: "Làm mới yêu cầu huỷ đơn sau timeout webhook — không xác nhận hoàn tất sớm.",
    },
    {
      id: "cancellation-outcome",
      stepNumber: 10,
      kind: "outcome",
      title: "Đã phê duyệt / từ chối / hết hạn / thất bại",
      description:
        "Giữ hàng chờ quyết định được giải phóng tự động — không gọi Update Inventory. Không hoàn tác sau từ chối cuối.",
      status: "pending",
      recoveryText: "Không có rollback tồn kho; chỉ hiển thị trạng thái cuối từ TikTok.",
    },
  ];
}

export function createPreventReturnTimeline(): ExecutionTimelineStep[] {
  return [
    {
      id: "return-intake",
      stepNumber: 1,
      kind: "wait",
      title: "Tiếp nhận cập nhật trạng thái đảo ngược",
      description: "Webhook #2 ghi nhận yêu cầu trả hàng mới hoặc thay đổi.",
      status: "pending",
    },
    {
      id: "search-returns",
      stepNumber: 2,
      kind: "action",
      title: "Tìm yêu cầu trả hàng",
      description: "Đọc trạng thái yêu cầu chính thức từ Search Returns.",
      status: "pending",
      recoveryText: "Làm mới yêu cầu trả hàng khi dữ liệu bị cũ.",
    },
    {
      id: "get-aftersale-eligibility",
      stepNumber: 3,
      kind: "action",
      title: "Kiểm tra điều kiện hậu mãi",
      description: "Xác nhận cửa sổ và quy tắc mặt hàng còn hiệu lực.",
      status: "pending",
    },
    {
      id: "search-rma",
      stepNumber: 4,
      kind: "action",
      title: "Tìm RMA",
      description: "Theo dõi trạng thái trả hàng vật lý trước khi quyết định cuối.",
      status: "pending",
    },
    {
      id: "rma-status-wait",
      stepNumber: 5,
      kind: "wait",
      title: "Chờ cập nhật trạng thái RMA",
      description: "Webhook #65 chờ giai đoạn vật lý bắt buộc; thiếu RMA thì chờ rõ ràng.",
      status: "pending",
      recoveryText: "Giữ trạng thái chờ khi thiếu RMA — không bịa hoàn tất.",
    },
    {
      id: "review-aftersales",
      stepNumber: 6,
      kind: "action",
      title: "Xem xét hậu mãi (có điều kiện)",
      description: "Chạy khi trường hợp leo thang/mơ hồ theo quy tắc hiện có.",
      status: "pending",
    },
    {
      id: "get-reject-reasons",
      stepNumber: 7,
      kind: "action",
      title: "Lấy lý do từ chối",
      description: "Tải lý do hợp lệ trước khi từ chối trả hàng.",
      status: "pending",
    },
    {
      id: "seller-decision",
      stepNumber: 8,
      kind: "outcome",
      title: "Cần quyết định của shop",
      description: "Shop chọn Phê duyệt hoặc Từ chối; Từ chối bắt buộc có lý do.",
      status: "pending",
      recoveryText: "Thiếu lý do từ chối — chặn gửi và quay lại nhập.",
    },
    {
      id: "approve-return",
      stepNumber: 9,
      kind: "action",
      title: "Phê duyệt trả hàng",
      description: "Gửi phê duyệt (nhánh loại trừ với từ chối).",
      status: "pending",
      recoveryText: "Thử lại ghi nhận quyết định theo cách idempotent khi lỗi tạm thời.",
    },
    {
      id: "reject-return",
      stepNumber: 10,
      kind: "action",
      title: "Từ chối trả hàng",
      description: "Gửi từ chối kèm lý do (nhánh loại trừ với phê duyệt).",
      status: "pending",
      recoveryText: "Thử lại ghi nhận quyết định theo cách idempotent khi lỗi tạm thời.",
    },
    {
      id: "physical-inspection-wait",
      stepNumber: 11,
      kind: "wait",
      title: "Chờ kiểm tra thực tế",
      description: "Với trả hàng FBS đã phê duyệt, thu kết quả còn bán được trước khi nhập kho.",
      status: "pending",
      recoveryText: "Giữ kết quả kiểm tra ở trạng thái cần thêm thông tin đến khi có số lượng.",
    },
    {
      id: "update-inventory-fbs",
      stepNumber: 12,
      kind: "action",
      title: "Cập nhật tồn kho FBS (nhập lại kho)",
      description:
        "Chỉ nhập lại số lượng FBS đã kiểm tra còn bán được — không tự động nhập lại. FBT intake (prevent_return_8b_fbt) không có bước seller Update Inventory.",
      status: "pending",
      recoveryText:
        "Giữ kết quả kiểm tra khi nhập kho thất bại; quyết định trả hàng không bị rollback.",
      errorText: "Nhập lại kho thất bại — giữ số lượng đã kiểm tra.",
    },
    {
      id: "get-return-records",
      stepNumber: 13,
      kind: "action",
      title: "Lấy lịch sử trả hàng",
      description: "Đọc bản ghi quyết định/lịch sử sau khi xử lý.",
      status: "pending",
    },
    {
      id: "return-status-wait",
      stepNumber: 14,
      kind: "wait",
      title: "Chờ thay đổi trạng thái trả hàng",
      description: "Webhook #12 xác nhận trạng thái cuối; timeout thì làm mới, không bịa hoàn tất.",
      status: "pending",
      recoveryText: "Làm mới bản ghi trả hàng sau timeout — không tuyên bố hoàn tất sớm.",
    },
    {
      id: "return-outcome",
      stepNumber: 15,
      kind: "outcome",
      title: "Đã trả / từ chối / nhập lại kho / thất bại",
      description:
        "Tách quyết định trả hàng khỏi đối soát tồn kho. Thành công quyết định + lỗi nhập kho là kết quả một phần, không rollback quyết định.",
      status: "pending",
      recoveryText: "Giữ kết quả kiểm tra và hiển thị lỗi nhập kho riêng nếu có.",
    },
  ];
}

export function createPreventRefundTimeline(): ExecutionTimelineStep[] {
  return [
    {
      id: "refund-intake",
      stepNumber: 1,
      kind: "wait",
      title: "Tiếp nhận cập nhật trạng thái yêu cầu hậu mãi",
      description: "Webhook #64 tạo/cập nhật yêu cầu hoàn tiền.",
      status: "pending",
    },
    {
      id: "search-aftersales",
      stepNumber: 2,
      kind: "action",
      title: "Tìm yêu cầu hậu mãi",
      description: "Đọc trạng thái yêu cầu chính thức từ Search Aftersales.",
      status: "pending",
      recoveryText: "Làm mới yêu cầu khi dữ liệu bị cũ.",
    },
    {
      id: "calculate-refund",
      stepNumber: 3,
      kind: "action",
      title: "Tính toán hoàn tiền",
      description: "Lấy bản xem trước số tiền một phần/toàn bộ — không ước lượng.",
      status: "pending",
      recoveryText: "Thử lại tính toán khi thất bại; chặn phê duyệt đến khi có kết quả hợp lệ.",
    },
    {
      id: "calculation-outcome",
      stepNumber: 4,
      kind: "outcome",
      title: "Tính toán sẵn sàng / không khả dụng",
      description: "Chỉ tiếp tục khi có kết quả tính toán hợp lệ.",
      status: "pending",
      recoveryText: "Giữ phê duyệt tắt khi thiếu số tiền tính toán.",
    },
    {
      id: "get-reject-reasons",
      stepNumber: 5,
      kind: "action",
      title: "Lấy lý do từ chối",
      description: "Tải lý do chính thức trước khi từ chối hoàn tiền.",
      status: "pending",
    },
    {
      id: "seller-decision",
      stepNumber: 6,
      kind: "outcome",
      title: "Cần quyết định của shop",
      description: "Shop chọn Phê duyệt hoặc Từ chối; Từ chối bắt buộc có lý do.",
      status: "pending",
      recoveryText: "Thiếu lý do từ chối — quay lại bước nhập.",
    },
    {
      id: "approve-refund",
      stepNumber: 7,
      kind: "action",
      title: "Phê duyệt hoàn tiền",
      description: "Gửi hoàn tiền theo số tiền đã tính (nhánh loại trừ với từ chối).",
      status: "pending",
      recoveryText: "Thử lại ghi nhận quyết định theo cách idempotent khi lỗi tạm thời.",
    },
    {
      id: "reject-refund",
      stepNumber: 8,
      kind: "action",
      title: "Từ chối hoàn tiền",
      description: "Gửi từ chối kèm lý do (nhánh loại trừ với phê duyệt).",
      status: "pending",
      recoveryText: "Thử lại ghi nhận quyết định theo cách idempotent khi lỗi tạm thời.",
    },
    {
      id: "refund-success-wait",
      stepNumber: 9,
      kind: "wait",
      title: "Chờ hoàn tiền thành công",
      description:
        "Webhook #67 xác nhận hoàn tất sau phê duyệt; từ chối chờ trạng thái yêu cầu chính thức.",
      status: "pending",
      recoveryText:
        "Không xác nhận tiền đã chuyển trước khi webhook xác nhận — làm mới yêu cầu nếu timeout.",
    },
    {
      id: "refund-outcome",
      stepNumber: 10,
      kind: "outcome",
      title: "Đã hoàn tiền / từ chối / thất bại",
      description:
        "Hiển thị đúng số tiền và trạng thái. Không hành động tồn kho; không hứa rollback sau hoàn tiền thành công.",
      status: "pending",
      recoveryText: "Hiển thị lý do nghiệp vụ TikTok khi lỗi cuối; không bịa số tiền đã chuyển.",
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

export function getWorkflowTimeline(
  workflowKey: string,
): ExecutionTimelineStep[] {
  switch (workflowKey) {
    case CREATE_HERO_PRODUCT_WORKFLOW_KEY:
      return createHeroProductTimeline();
    case PREVENT_CANCELLATION_WORKFLOW_KEY:
      return createPreventCancellationTimeline();
    case PREVENT_RETURN_WORKFLOW_KEY:
      return createPreventReturnTimeline();
    case PREVENT_REFUND_WORKFLOW_KEY:
      return createPreventRefundTimeline();
    default:
      return [];
  }
}

export function startExecution(
  workflowKey: string,
  approvedInputs?: Record<string, string>,
): {
  executionId: string;
  record: ExecutionRecord;
} {
  if (!isReviewExecutableWorkflow(workflowKey)) {
    throw new Error(`Unsupported workflow key: ${workflowKey}`);
  }

  const timelineTemplate = getWorkflowTimeline(workflowKey);
  if (timelineTemplate.length === 0) {
    throw new Error(`Unsupported workflow key: ${workflowKey}`);
  }

  const executionId = nextExecutionId(workflowKey);
  const now = "2026-07-16T04:12:00.000Z";
  const timeline = seedInitialTimeline(timelineTemplate);
  const lifecycleStatus = deriveLifecycleFromTimeline(timeline);

  const record: ExecutionRecord = {
    executionId,
    workflowKey,
    toolName: TOOL_NAME_BY_WORKFLOW[workflowKey],
    lifecycleStatus,
    startedAt: now,
    updatedAt: now,
    timeline,
    approvedInputs: {
      ...buildReviewInputDefaults(workflowKey),
      ...(approvedInputs ?? {}),
    },
  };

  return { executionId, record };
}
