import type { ExecutionTimelineStep } from "@juli/contracts";

import {
  PREVENT_REFUND_TOOL_NAME,
  PREVENT_REFUND_WORKFLOW_KEY,
} from "./review";

export { PREVENT_REFUND_TOOL_NAME, PREVENT_REFUND_WORKFLOW_KEY };

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
      description:
        "Lấy bản xem trước số tiền một phần/toàn bộ — không ước lượng.",
      status: "pending",
      recoveryText:
        "Thử lại tính toán khi thất bại; chặn phê duyệt đến khi có kết quả hợp lệ.",
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
      description:
        "Shop chọn Phê duyệt hoặc Từ chối; Từ chối bắt buộc có lý do.",
      status: "pending",
      recoveryText: "Thiếu lý do từ chối — quay lại bước nhập.",
    },
    {
      id: "approve-refund",
      stepNumber: 7,
      kind: "action",
      title: "Phê duyệt hoàn tiền",
      description:
        "Gửi hoàn tiền theo số tiền đã tính (nhánh loại trừ với từ chối).",
      status: "pending",
      recoveryText:
        "Thử lại ghi nhận quyết định theo cách idempotent khi lỗi tạm thời.",
    },
    {
      id: "reject-refund",
      stepNumber: 8,
      kind: "action",
      title: "Từ chối hoàn tiền",
      description: "Gửi từ chối kèm lý do (nhánh loại trừ với phê duyệt).",
      status: "pending",
      recoveryText:
        "Thử lại ghi nhận quyết định theo cách idempotent khi lỗi tạm thời.",
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
      recoveryText:
        "Hiển thị lý do nghiệp vụ TikTok khi lỗi cuối; không bịa số tiền đã chuyển.",
    },
  ];
}
