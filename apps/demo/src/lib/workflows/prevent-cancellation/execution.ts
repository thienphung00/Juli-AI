import type { ExecutionTimelineStep } from "@juli/contracts";

import {
  PREVENT_CANCELLATION_TOOL_NAME,
  PREVENT_CANCELLATION_WORKFLOW_KEY,
} from "./review";

export { PREVENT_CANCELLATION_TOOL_NAME, PREVENT_CANCELLATION_WORKFLOW_KEY };

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
      description:
        "Chỉ yêu cầu còn đủ điều kiện mới tiếp tục; hết hạn hoặc đã quyết định là chỉ đọc.",
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
      description:
        "Shop chọn Phê duyệt hoặc Từ chối; Từ chối bắt buộc có lý do.",
      status: "pending",
      recoveryText:
        "Thiếu lý do từ chối — quay lại bước lấy lý do và nhập lại.",
    },
    {
      id: "approve-cancellation",
      stepNumber: 7,
      kind: "action",
      title: "Phê duyệt huỷ đơn",
      description: "Gửi lựa chọn phê duyệt (nhánh loại trừ với từ chối).",
      status: "pending",
      recoveryText:
        "Thử lại ghi nhận quyết định theo cách idempotent khi lỗi tạm thời.",
    },
    {
      id: "reject-cancellation",
      stepNumber: 8,
      kind: "action",
      title: "Từ chối huỷ đơn",
      description:
        "Gửi từ chối kèm lý do đã chọn (nhánh loại trừ với phê duyệt).",
      status: "pending",
      recoveryText:
        "Thử lại ghi nhận quyết định theo cách idempotent khi lỗi tạm thời.",
    },
    {
      id: "cancellation-status-wait",
      stepNumber: 9,
      kind: "wait",
      title: "Chờ trạng thái huỷ đơn",
      description:
        "Webhook #11 xác nhận trạng thái cuối; timeout thì làm mới yêu cầu, không tuyên bố thành công.",
      status: "pending",
      recoveryText:
        "Làm mới yêu cầu huỷ đơn sau timeout webhook — không xác nhận hoàn tất sớm.",
    },
    {
      id: "cancellation-outcome",
      stepNumber: 10,
      kind: "outcome",
      title: "Đã phê duyệt / từ chối / hết hạn / thất bại",
      description:
        "Giữ hàng chờ quyết định được giải phóng tự động — không gọi Update Inventory. Không hoàn tác sau từ chối cuối.",
      status: "pending",
      recoveryText:
        "Không có rollback tồn kho; chỉ hiển thị trạng thái cuối từ TikTok.",
    },
  ];
}
