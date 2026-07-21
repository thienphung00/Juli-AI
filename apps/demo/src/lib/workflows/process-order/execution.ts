import {
  deriveLifecycleFromTimeline,
  type ExecutionRecord,
  type ExecutionTimelineStep,
} from "@juli/contracts";

import {
  PROCESS_ORDER_TOOL_NAME,
  PROCESS_ORDER_WORKFLOW_KEY,
  buildProcessOrderReviewInputDefaults,
} from "./review";

const executionCounters = new Map<string, number>();

export { PROCESS_ORDER_TOOL_NAME, PROCESS_ORDER_WORKFLOW_KEY };

export function resetProcessOrderExecutionCountersForTests(): void {
  executionCounters.clear();
}

function nextExecutionId(workflowKey: string): string {
  const next = (executionCounters.get(workflowKey) ?? 0) + 1;
  executionCounters.set(workflowKey, next);
  return `exec-${workflowKey}-${next}`;
}

export function createProcessOrderTimeline(): ExecutionTimelineStep[] {
  return [
    {
      id: "get-order-list",
      stepNumber: 1,
      kind: "action",
      title: "Lấy danh sách đơn hàng",
      description: "Tải các đơn hàng ứng viên theo hàng đợi T5 đã xếp hạng.",
      status: "pending",
      recoveryText:
        "Làm mới danh sách khi trạng thái đơn có thể đã thay đổi trước khi tiếp tục.",
    },
    {
      id: "get-order-detail",
      stepNumber: 2,
      kind: "action",
      title: "Lấy chi tiết đơn hàng",
      description:
        "Tải trạng thái hiện tại, loại fulfillment/vận chuyển và địa chỉ đã che mặt.",
      status: "pending",
      recoveryText:
        "Cập nhật địa chỉ làm lỗi thời snapshot trước đó — tải lại chi tiết đơn.",
    },
    {
      id: "address-stability-wait",
      stepNumber: 3,
      kind: "wait",
      title: "Chờ ổn định địa chỉ người nhận",
      description:
        "Nếu webhook cập nhật địa chỉ (#3) kích hoạt thì quay lại bước chi tiết đơn.",
      status: "pending",
      recoveryText:
        "Địa chỉ thay đổi — quay lại chi tiết đơn trước khi tiếp tục đóng gói.",
    },
    {
      id: "awaiting-shipment-wait",
      stepNumber: 4,
      kind: "wait",
      title: "Chờ AWAITING_SHIPMENT",
      description:
        "Webhook trạng thái đơn (#1) phải chuyển ON_HOLD sang AWAITING_SHIPMENT; không tạo/giao khi còn tạm giữ.",
      status: "pending",
      recoveryText:
        "Đơn vẫn tạm giữ — làm mới trạng thái mà không bỏ qua điều kiện chờ.",
    },
    {
      id: "ready-to-pack",
      stepNumber: 5,
      kind: "outcome",
      title: "Sẵn sàng đóng gói",
      description:
        "Hiển thị line item đã xác thực và nhánh vận chuyển tương ứng từ đơn hàng.",
      status: "pending",
    },
    {
      id: "split-attributes",
      stepNumber: 6,
      kind: "action",
      title: "Lấy thuộc tính tách gói",
      description:
        "Chỉ chạy khi ràng buộc đóng gói yêu cầu — tải ràng buộc nhóm gói được phép.",
      status: "pending",
      recoveryText:
        "Bỏ qua toàn bộ luồng tách/gộp khi không cần thiết trước bước tạo gói.",
    },
    {
      id: "split-branch-outcome",
      stepNumber: 7,
      kind: "outcome",
      title: "Nhánh tách/gộp/bỏ gộp/không cần",
      description:
        "Yêu cầu shop xác nhận tách, gộp, bỏ gộp, hoặc không cần thao tác trước khi tiếp tục.",
      status: "pending",
      recoveryText:
        "Quay lại xác nhận nhánh tách/gộp khi ràng buộc đóng gói thay đổi.",
    },
    {
      id: "split-orders",
      stepNumber: 8,
      kind: "action",
      title: "Tách đơn hàng",
      description:
        "Chỉ chạy khi shop phê duyệt tách — tạo các nhóm gói đã được duyệt.",
      status: "pending",
      recoveryText: "Điều chỉnh nhóm tách rồi thử lại khi TikTok từ chối nhóm.",
    },
    {
      id: "search-combinable-packages",
      stepNumber: 9,
      kind: "action",
      title: "Tìm gói có thể gộp",
      description:
        "Chỉ liệt kê các gói khớp có thẩm quyền — bỏ qua khi không gộp.",
      status: "pending",
    },
    {
      id: "combine-package",
      stepNumber: 10,
      kind: "action",
      title: "Gộp gói",
      description:
        "Gộp các gói tương thích đã chọn — bỏ qua khi shop chọn không gộp.",
      status: "pending",
      recoveryText: "Thử lại chỉ các gói bị lỗi; giữ gói đã gộp thành công.",
    },
    {
      id: "uncombine-packages",
      stepNumber: 11,
      kind: "action",
      title: "Bỏ gộp gói",
      description:
        "Hoàn tác một tổ hợp đã chọn — bỏ qua khi không cần bỏ gộp.",
      status: "pending",
    },
    {
      id: "package-update-wait",
      stepNumber: 12,
      kind: "wait",
      title: "Chờ cập nhật gói",
      description:
        "Webhook cập nhật gói (#4) xác nhận mutation trước bước tạo gói cuối.",
      status: "pending",
      recoveryText:
        "Làm mới thủ công khi webhook quá hạn — không bỏ qua xác nhận mutation.",
    },
    {
      id: "create-packages",
      stepNumber: 13,
      kind: "action",
      title: "Tạo gói hàng",
      description:
        "Nhóm line item đã phê duyệt và giữ package_id trước khi giao.",
      status: "pending",
      recoveryText:
        "Giữ line item đã chọn và thử lại idempotent khi tạo gói thất bại.",
    },
    {
      id: "get-shipping-document",
      stepNumber: 14,
      kind: "action",
      title: "Lấy tài liệu vận chuyển gói",
      description:
        "Chỉ nhánh Ship by TikTok — tải pick list/nhãn; bỏ qua toàn bộ bước này với Ship by Seller.",
      status: "pending",
      recoveryText:
        "Thử lại tài liệu cho gói bị lỗi; không yêu cầu nhãn TikTok với Ship by Seller.",
      errorText: "Tải tài liệu vận chuyển thất bại — thử lại gói bị lỗi.",
    },
    {
      id: "own-carrier-ready",
      stepNumber: 15,
      kind: "outcome",
      title: "Sẵn sàng vận chuyển tự giao",
      description:
        "Chỉ nhánh Ship by Seller — bỏ qua tài liệu TikTok; yêu cầu mã vận đơn và mã nhà vận chuyển.",
      status: "pending",
      recoveryText:
        "Quay lại nhập mã vận đơn/nhà vận chuyển khi xác thực thất bại.",
    },
    {
      id: "ship-package-tiktok",
      stepNumber: 16,
      kind: "action",
      title: "Giao gói (Ship by TikTok)",
      description:
        "Giao một gói hoặc dùng Batch Ship Packages cho lô nhiều gói đã duyệt — loại trừ nhánh Ship by Seller.",
      status: "pending",
      recoveryText:
        "Thử lại từng gói bị lỗi trong lô; hiển thị kết quả từng phần khi batch một phần thành công.",
    },
    {
      id: "batch-ship-seller",
      stepNumber: 17,
      kind: "action",
      title: "Giao lô tự vận chuyển",
      description:
        "Chỉ nhánh Ship by Seller — gửi self_shipment với tracking và provider ID; loại trừ Ship by TikTok.",
      status: "pending",
      recoveryText:
        "Quay lại nhập tracking/provider khi xác thực thất bại; thử lại gói bị lỗi trong lô.",
    },
    {
      id: "confirm-package-shipment",
      stepNumber: 18,
      kind: "action",
      title: "Xác nhận giao gói",
      description: "Đồng bộ qua Supply Chain API sau khi giao.",
      status: "pending",
      recoveryText:
        "Không tuyên bố hoàn tác giao hàng khi xác nhận thất bại — thử lại idempotent.",
    },
    {
      id: "get-package-detail",
      stepNumber: 19,
      kind: "action",
      title: "Lấy chi tiết gói",
      description: "Đọc trạng thái gói/vận chuyển cuối cùng sau xác nhận.",
      status: "pending",
    },
    {
      id: "shipped-outcome",
      stepNumber: 20,
      kind: "outcome",
      title: "Đã giao / một phần / thất bại",
      description:
        "Hiển thị kết quả từng gói và bước khôi phục tiếp theo; không có hoàn tác gói đã giao.",
      status: "pending",
      recoveryText:
        "Một phần gói thất bại — xem kết quả từng gói và thử lại khôi phục được.",
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

export function buildProcessOrderExecution(
  approvedInputs?: Record<string, string>,
): {
  executionId: string;
  record: ExecutionRecord;
} {
  const executionId = nextExecutionId(PROCESS_ORDER_WORKFLOW_KEY);
  const now = "2026-07-21T08:30:00.000Z";
  const timeline = seedInitialTimeline(createProcessOrderTimeline());
  const lifecycleStatus = deriveLifecycleFromTimeline(timeline);

  const record: ExecutionRecord = {
    executionId,
    workflowKey: PROCESS_ORDER_WORKFLOW_KEY,
    toolName: PROCESS_ORDER_TOOL_NAME,
    lifecycleStatus,
    startedAt: now,
    updatedAt: now,
    timeline,
    approvedInputs: {
      ...buildProcessOrderReviewInputDefaults(),
      ...(approvedInputs ?? {}),
    },
  };

  return { executionId, record };
}
